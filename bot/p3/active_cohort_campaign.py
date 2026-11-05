"""One preregistered active LaunchLab cohort, at most 20 reads in 60 seconds.

Reuse the existing anonymous transport, account decoder, quote parser and capture
journal. Selection precedes provider outcomes. No financial transaction exists.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlsplit

import aiohttp

from bot.analyser.artifacts import atomic_write_json
from bot.p3 import campaign as cp
from bot.p3 import prospective_campaign as prospective
from bot.p3.cohort import (CRITERIA, make_acquisition_plan, validate_acquisition_plan,
                           select_cohort, build_comparison_corpus)
from bot.p3.collect import (CANONICAL_RPC_URL, ReadOnlyPolicyError, _rpc,
    _environment_proxy, now_ms, _record_quote, _quote_with_cancellation_receipt)
from bot.p3.exit_qualification import inventory_from_buy
from bot.p3.inventory_provider import NativeInventoryQuoteProvider
from bot.p3.launchlab import addresses_from_pool
from bot.p3.quotes import RaydiumQuoteClient, SOL_MINT
from bot.p3.store import CaptureStore, _safe_json


def make_plan(*,registered_at_ms,source_revision):
    base=make_acquisition_plan(registered_at_ms=registered_at_ms,source_revision=source_revision)
    return dict(schema='p3-active-cohort-execution-plan-v1',acquisition=base,
        source_revision=source_revision,registered_at_ms=registered_at_ms,
        effective_rpc_endpoint=CANONICAL_RPC_URL,
        source_override=dict(original_rpc=CRITERIA['sources']['rpc'],
            effective_rpc=CANONICAL_RPC_URL,
            reason='official_public_canonical_endpoint_fixed_before_capture'),
        endpoint_policy='fixed_before_capture; no_retry_no_fallback',
        features_policy='retained_source_features_only; absent_remains_unknown',
        own_cost_policy='unknown_without_applicable_own_position_evidence',
        independent_buyers_policy='unknown_without_supported_wallet_evidence',
        market_collection_executed=False,real_orders_enabled=False)


def make_plan_010(*,registered_at_ms,source_revision):
    from bot.p3.transport import PHASE_TIMEOUTS
    plan=make_plan(registered_at_ms=registered_at_ms,source_revision=source_revision)
    plan.update(schema='p3-active-cohort-execution-plan-v2',control_id='P3-010',
        previous_control_policy='009_closed_never_resumed; independent_new_acquisition',
        transport=dict(phase_timeouts_seconds=dict(PHASE_TIMEOUTS),
            recorder='safe_phase_checkpoints_in_capture_chain',
            dns='system_threaded_resolver_AF_UNSPEC_via_configured_proxy',
            tls='default_CA_and_hostname_verification_required',
            process_watchdog_seconds=58,termination_grace_seconds=2),
        comparison=dict(research_input_lamports='100000000',
            initial_reference_input_lamports='1000000000',
            resizing_provider_quotes=False,
            admissibility='no_equal_size_AB_claim_without_separate_exact_quotes_and_causal_inputs'))
    return plan


def validate_plan(plan,*,first_observation_at_ms=None):
    factory=make_plan_010 if type(plan) is dict and plan.get('schema')=='p3-active-cohort-execution-plan-v2' else make_plan
    if type(plan) is not dict or plan!=factory(
            registered_at_ms=plan.get('registered_at_ms'),source_revision=plan.get('source_revision')):
        raise ValueError('Exact active-cohort execution plan required')
    validate_acquisition_plan(plan['acquisition'],first_observation_at_ms=first_observation_at_ms)
    return hashlib.sha256(cp.canonical(plan)).hexdigest()


def _prefix(retained):
    rows=[];mints=set();pools=set()
    for row in retained:
        if (row.get('mint') and row['mint']!=SOL_MINT and row.get('pool')
                and row.get('quote_mint_claim')==SOL_MINT
                and row['mint'] not in mints and row['pool'] not in pools):
            mints.add(row['mint']);pools.add(row['pool'])
            if len(rows)<CRITERIA['screen_prefix']:
                rows.append(dict(row,ordinal=len(rows),creator=row.get('creator_claim')))
    return rows


async def collect_active_cohort(store,session,plan,*,provenance='live'):
    """Execute once on a fresh journal and shared budget, never on a user book."""
    started=now_ms();plan_hash=validate_plan(plan,first_observation_at_ms=started)
    if (not isinstance(session,cp.CampaignSession) or session.rpc_url!=plan['effective_rpc_endpoint']
            or session.max_requests!=20 or session.requests_used or store.events()
            or session._deadline_ns is not None
            or getattr(session.session,'_retry_connection',None) is not False):
        raise ValueError('New journal and registered anonymous transport with fresh global budget required')
    if provenance not in ('live','synthetic'):raise ValueError('Explicit capture provenance required')
    mono=time.monotonic_ns();session._deadline_ns=mono+CRITERIA['max_elapsed_ms']*1000000
    stop_reason=None;selection=None;retained=[];projected={};source_total=None
    def append(kind,**event):
        identity=store.append(kind,provenance=provenance,**event)
        payload=event.get('payload',{});status=payload.get('http_status')
        logical=(kind=='quote_attempt' and status==200 and event.get('outcome')=='unavailable'
            and event.get('reason') in ('provider_rejected','route_unavailable'))
        if ((type(status) is int and not 200<=status<300)
                or (kind in ('request','quote_attempt') and event.get('outcome') in ('error','cancelled'))
                or (kind=='quote_attempt' and payload.get('provider')=='raydium_trade_api'
                    and event.get('outcome')!='quoted' and not logical)):
            raise cp.CampaignSourceStopped('source_error_after_persisted_receipt')
        return identity
    append('checkpoint',received_at_ms=started,outcome='active_cohort_plan_registered',
        payload=dict(plan=plan,plan_sha256=plan_hash))

    async def run():
        nonlocal retained,selection,source_total
        payload,received=await cp._discover(session,append)
        retained,_,source_total=cp.select_rows(payload)
        for row in retained:row['provisional_index_reason']=row.pop('selection_reason')
        discovery=dict(
            rows=retained,received_row_count=source_total,
            response_representation_sha256=cp.digest(payload),
            representation='retained_selection_fields_of_first_100_rows; JSON_response_digest_not_wire_digest')
        try:
            _safe_json(payload)
            if len(cp.canonical(payload))>2000000:raise ValueError('Discovery retention bound exceeded')
        except (ValueError,TypeError):
            discovery.update(raw_response_retained=False,
                raw_response_retention_reason='unsafe_or_oversized_body; selection_fields_and_digest_retained')
        else:discovery.update(raw_response_retained=True,raw_response=payload)
        append('discovery',received_at_ms=received,outcome='observed',payload=discovery)
        rows=_prefix(retained)
        if not rows:
            selection=select_cohort(retained,decision_at_ms=now_ms())
            append('checkpoint',received_at_ms=now_ms(),outcome='active_cohort_fixed',payload=selection)
            return
        roots,receipt,request,_=await _rpc(session,append,'getMultipleAccounts',
            [[row['pool'] for row in rows],{'encoding':'base64','commitment':'confirmed'}])
        slot,values=cp._bank(roots,len(rows))
        append('pool_snapshot',received_at_ms=receipt,source_slot=slot,request_id=request,
            outcome='roots_observed' if values is not None else 'missing',
            payload=dict(requested_pool_rows=rows,raw_rpc_result=roots))
        if values is None:raise cp.CampaignSourceStopped('malformed_root_bank')
        graphs={}
        for row,raw in zip(rows,values):
            try:graphs[row['mint']]=addresses_from_pool(raw,row['mint'],row['pool'])
            except (ValueError,KeyError,TypeError):cp._gap(append,'active_pool_graph_unusable',mint=row['mint'])
        initial_slot,initial=await prospective._grouped_snapshot(store,session,append,rows,graphs,
            slot,'initial',input_lamports=CRITERIA['research_input_lamports'])
        completed=time.monotonic_ns()
        events_by_id={event['id']:event for event in store.events()}
        for row in retained:
            observed=initial.get(row.get('mint'))
            if observed is not None:
                row['snapshot']=observed['analysis']
                row['snapshot_available_at_ms']=events_by_id[observed['snapshot_observation_id']]['available_at_ms']
        selection=select_cohort(retained,decision_at_ms=now_ms())
        append('checkpoint',received_at_ms=now_ms(),outcome='active_cohort_fixed',payload=selection)
        chosen=[dict(item,creator=item.get('creator_claim')) for item in selection['selected']]
        if not chosen:return
        provider=NativeInventoryQuoteProvider(session.session,store,shared_session=session,
            append=append,max_requests=20,stop_on_provider_rejection=False)
        for row in chosen:
            context=await provider(None,row['mint'],side='buy',
                amount_atomic=str(CRITERIA['research_input_lamports']),inventory=None,
                decision_at_ms=now_ms(),observation_metadata=dict(probe_phase='initial',prospective_ordinal=row['ordinal']))
            if context is None:continue
            buy=context['buy_observation']
            decimals=initial[row['mint']]['analysis'].get('facts',{}).get('base_mint',{}).get('decimals')
            decimals=int(decimals) if type(decimals) is str and decimals.isdecimal() else decimals
            inv=inventory_from_buy(buy,basis='expected_buy_output',token_decimals=decimals,
                entry_decision_at_ms=max(now_ms(),buy['available_at_ms']),max_source_age_ms=5000)
            if not inv['accepted']:continue
            inv['buy_observation_id']=buy['id'];inv['partial_diagnostic_atomic']=str(int(inv['acquired_atomic'])//4)
            projected[row['mint']]=inv
            append('checkpoint',received_at_ms=now_ms(),mint=row['mint'],outcome='projected_inventory_fixed',
                payload=dict(acquired_atomic=inv['acquired_atomic'],minimum_atomic=inv['minimum_atomic'],
                    partial_diagnostic_atomic=inv['partial_diagnostic_atomic'],buy_observation_id=buy['id'],
                    acquisition_verified=False,own_costs_known=False))
        for row in chosen:
            inv=projected.get(row['mint'])
            if inv is None:continue
            context=await provider(None,row['mint'],side='sell',amount_atomic=inv['acquired_atomic'],
                inventory=dict(mint=row['mint'],remaining_atomic=inv['acquired_atomic']),decision_at_ms=now_ms(),
                observation_metadata=dict(probe_phase='initial',exit_scope='full_expected',
                    inventory_buy_observation_id=inv['buy_observation_id'],prospective_ordinal=row['ordinal']))
            event=context.get('sell_observation') if context else None
            if (event is not None and event.get('outcome')=='unavailable'
                    and event.get('reason')=='provider_rejected' and int(inv['partial_diagnostic_atomic'])>0):
                request_id='active-quarter-'+str(row['ordinal'])
                quote=await _quote_with_cancellation_receipt(RaydiumQuoteClient(session),append,row['mint'],
                    SOL_MINT,inv['partial_diagnostic_atomic'],'sell',request_id)
                quote.update(probe_phase='initial',exit_scope='partial_diagnostic',diagnostic_only=True,
                    inventory_buy_observation_id=inv['buy_observation_id'],prospective_ordinal=row['ordinal'])
                _record_quote(append,quote,'sell',request_id)
        # Bounded creation lookup runs inside the already-started followup wait.
        for row in chosen:
            await cp._creation(session,append,row,signature_limit=CRITERIA['creation_signature_limit'],
                max_supported_transaction_version=1)
        if projected and initial_slot is not None:
            delay=max(0,CRITERIA['followup_delay_ms']*1000000-(time.monotonic_ns()-completed))/1e9
            await asyncio.sleep(delay)
            waited=(time.monotonic_ns()-completed)//1000000
            if waited<CRITERIA['followup_delay_ms']:raise ValueError('Followup horizon has not elapsed')
            append('checkpoint',received_at_ms=now_ms(),outcome='followup_wait_completed',
                payload=dict(elapsed_since_initial_bank_ms=waited,minimum_elapsed_ms=CRITERIA['followup_delay_ms']))
            following,_=await prospective._grouped_snapshot(store,session,append,chosen,graphs,
                initial_slot+1,'followup',input_lamports=CRITERIA['research_input_lamports'])
            if following is None or following<=initial_slot:
                raise cp.CampaignSourceStopped('followup_slot_not_advanced')
            for row in chosen:
                inv=projected.get(row['mint'])
                if inv is None:continue
                await provider(None,row['mint'],side='sell',amount_atomic=inv['acquired_atomic'],
                    inventory=dict(mint=row['mint'],remaining_atomic=inv['acquired_atomic']),decision_at_ms=now_ms(),
                    observation_metadata=dict(probe_phase='followup',exit_scope='full_expected',
                        inventory_buy_observation_id=inv['buy_observation_id'],prospective_ordinal=row['ordinal']))
        await prospective._fee_reference(store,session,append,chosen[0])

    try:await asyncio.wait_for(run(),timeout=CRITERIA['max_elapsed_ms']/1000)
    except cp.CampaignSourceStopped as error:stop_reason=str(error)
    except (ValueError,KeyError,TypeError,asyncio.TimeoutError,ReadOnlyPolicyError):
        stop_reason='incomplete_source_evidence_or_budget'
    if selection is None:
        selection=select_cohort(retained,decision_at_ms=now_ms())
        store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),
            outcome='active_cohort_fixed_after_source_stop',payload=selection)
    store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),outcome='active_cohort_closed',
        payload=dict(requests_used=session.requests_used,stop_reason=stop_reason,
            elapsed_ms=(time.monotonic_ns()-mono)//1000000,position_acquired=False))
    return build_active_cohort_report(store,plan)


def build_active_cohort_report(store,plan):
    """Recover a closed control from committed evidence without another request."""
    plan_hash=validate_plan(plan)
    events=store.events();tail=store.verify_integrity()
    if (not events or events[-1].get('outcome')!='active_cohort_closed'
            or events[0].get('payload',{}).get('plan')!=plan
            or events[0].get('payload',{}).get('plan_sha256')!=plan_hash):
        raise ValueError('A closed journal matching the published plan is required')
    close=events[-1];state=close['payload']
    selection=next((e['payload'] for e in reversed(events) if e.get('outcome') in
        ('active_cohort_fixed','active_cohort_fixed_after_source_stop')),None)
    if (selection is None or type(state.get('requests_used')) is not int
            or not 0<=state['requests_used']<=20 or type(state.get('elapsed_ms')) is not int
            or state['elapsed_ms']<0 or state.get('position_acquired') is not False):
        raise ValueError('Closed control counters and retained selection required')
    discovery=next((e for e in events if e['kind']=='discovery'),None)
    source_total=discovery['payload'].get('received_row_count') if discovery else None
    projected={e.get('mint') for e in events if e.get('outcome')=='projected_inventory_fixed'}
    acquisition=build_comparison_corpus(selection,events,as_of_ms=close['available_at_ms'],integrity_verified=True,expected_tail=tail)
    acquisition['discovery_universe_known']=discovery is not None
    quotes=[e for e in events if e.get('kind')=='quote_attempt'
            and e.get('payload',{}).get('provider')=='raydium_trade_api']
    refused=[e for e in quotes if e.get('outcome')=='unavailable'
        and e.get('reason') in ('provider_rejected','route_unavailable')
        and e.get('payload',{}).get('http_status')==200]
    models=[e for e in events if e.get('kind')=='quote_attempt'
        and e.get('payload',{}).get('provider')=='local_pinned_sdk_arithmetic']
    return dict(schema='p3-active-cohort-result-v1',plan_sha256=plan_hash,source_revision=plan['source_revision'],
        requests_used=state['requests_used'],elapsed_ms=state['elapsed_ms'],
        stop_reason=state.get('stop_reason'),selection=selection,acquisition=acquisition,records=len(events),tail_hash=tail,
        received_index_rows=source_total,provider_quote_attempts=len(quotes),
        provider_quotes=sum(e.get('outcome')=='quoted' for e in quotes),
        provider_refusals=len(refused),
        provider_unavailable_or_errors=sum(e.get('outcome')!='quoted' for e in quotes)-len(refused),
        projected_positions=len(projected),positions_acquired=0,settled_legs=0,
        observation_categories=dict(OBSERVED=dict(
                discovery_responses=sum(e.get('kind')=='discovery' for e in events),
                retained_RPC_account_responses=sum(e.get('kind')=='pool_snapshot'
                    and type(e.get('payload',{}).get('raw_rpc_result')) is dict for e in events),
                provider_quote_receipts=len(quotes),provider_quoted=sum(e.get('outcome')=='quoted' for e in quotes)),
            MODELLED=dict(curve_arithmetic_records=len(models),expected_buy_inventories=len(projected)),
            UNKNOWN=dict(applicable_own_execution_costs=True,independent_buyers=True,
                independent_strategy_edge=True,provider_quote_clock_gaps=sum(
                    e.get('source_time_ms') is None or e.get('source_slot') is None for e in quotes)),
            REFUSED=[dict(mint=e.get('mint'),reason=e.get('reason')) for e in quotes if e.get('outcome')!='quoted']),
        own_additional_costs_known=False,independent_buyers_known=False,
        net_pnl_sol=None,qualified_economic_cycles=0,execution_verified=False,
        market_collection_executed=close['provenance']=='live' and state['requests_used']>0,
        discovery_universe_known=discovery is not None,
        active_policy_changed=False,economic_verdict='INSUFFICIENT DATA')


def run_process_watchdog(command,*,timeout_seconds=58,working_directory=None):
    """Bound one child process, including executor cleanup; never restart it."""
    if (type(command) is not list or not command or any(type(x) is not str for x in command)
            or type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds)
            or not 0<timeout_seconds<=58):
        raise ValueError('One child and deadline within58 seconds plus2-second termination reserve required')
    start=time.monotonic();expired=False
    child=subprocess.Popen(command,start_new_session=True,cwd=working_directory)
    try:child.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        expired=True
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=1)
        # The direct child may exit on TERM while another member of its own
        # process group ignores it. Never leave those descendants running.
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    return dict(child_exit_code=child.returncode,process_deadline_exceeded=expired,
        deadline_ms=timeout_seconds*1000,elapsed_ms=(time.monotonic()-start)*1000,
        termination_reserve_ms=2000,child_execution_count=1,retry_performed=False)


async def _capture(plan,database,*,output=None):
    phased=plan.get('control_id')=='P3-010'
    routes=None
    if phased:
        from bot.p3.transport import managed_proxy_routes
        # Check every source before creating a journal/connector. NO_PROXY is
        # respected as a configuration refusal, never as permission to go direct.
        routes=managed_proxy_routes((cp.INDEX_URL,plan['effective_rpc_endpoint'],
            CRITERIA['sources']['quotes']))
    with CaptureStore(database) as store:
        options=dict(trust_env=False,cookie_jar=aiohttp.DummyCookieJar())
        recording=True
        if phased:
            from bot.p3.transport import PhaseRecorder,connector
            def retained_phase(event):
                if recording:
                    store.append('checkpoint',provenance='live',received_at_ms=now_ms(),
                        outcome='transport_phase',payload=event)
            recorder=PhaseRecorder(retained_phase)
            proxy=routes[cp.INDEX_URL]
            options.update(connector=connector(recorder,proxy_host=urlsplit(proxy).hostname if proxy else None),
                trace_configs=[recorder.trace_config()])
        async with aiohttp.ClientSession(**options) as transport:
            if type(getattr(transport,'_retry_connection',None)) is not bool:
                raise ReadOnlyPolicyError('Unsupported transport retry switch')
            transport._retry_connection=False
            session=cp.CampaignSession(transport,20,
                proxy_resolver=routes.__getitem__ if routes is not None else _environment_proxy,
                rpc_url=plan['effective_rpc_endpoint'],bounded_phases=phased)
            try:
                report=await collect_active_cohort(store,session,plan)
            finally:
                # The close event is the journal anchor. Late resolver/task
                # cancellation belongs to process cleanup, never after it.
                recording=False
            # Publish before HTTP/DNS/executor cleanup, which can stall after
            # the capture itself has already stopped and committed its receipt.
            if output is not None:atomic_write_json(output,report,indent=2,sort_keys=True,allow_nan=False)
            return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--network',action='store_true')
    args=parser.parse_args(argv)
    if not args.network:parser.error('Explicit network opt-in and preregistered plan required')
    if (args.plan.is_symlink() or args.plan.suffix!='.json' or args.plan.name.startswith('.env')
            or args.db.exists() or args.db.is_symlink() or args.output.exists() or args.output.is_symlink()
            or args.output.suffix!='.json' or len({p.resolve() for p in (args.plan,args.db,args.output)})!=3):
        parser.error('Retained plan and new separate capture/report required')
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    report=asyncio.run(_capture(plan,args.db,output=args.output))
    print(json.dumps({k:report[k] for k in ('requests_used','stop_reason','qualified_economic_cycles')}))


if __name__=='__main__':main()
