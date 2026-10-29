"""P3-011: one prospective, indicative exact-size experiment, without a ledger.

STRICT remains unchanged. A single historical platform-admin UNKNOWN can admit
observational research only. Both position sizes have their own provider quotes.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import aiohttp

from bot.analyser.artifacts import atomic_write_json
from bot.p3 import campaign as cp,prospective_campaign as prospective
from bot.p3.active_cohort_campaign import _prefix
from bot.p3.cohort import CRITERIA,classify_snapshot
from bot.p3.collect import CANONICAL_RPC_URL,_rpc,now_ms
from bot.p3.inventory_provider import NativeInventoryQuoteProvider
from bot.p3.launchlab import addresses_from_pool
from bot.p3.research_gate import select_research_cohort
from bot.p3.store import CaptureStore,_safe_json
from bot.p3.transport import PhaseRecorder,connector,managed_proxy_routes,disable_retries


FIXED=dict(schema='p3-research-prospective-011-v1',control_id='P3-011',
    index_sort='lastTrade',index_source=cp.INDEX_URL,rpc_source=CANONICAL_RPC_URL,
    quote_source=CRITERIA['sources']['quotes'],max_requests=20,max_elapsed_ms=60000,
    process_child_deadline_seconds=58,process_termination_reserve_seconds=2,
    maximum_universe_rows=100,screen_prefix=6,maximum_candidates=2,
    primary_model_input_lamports=100000000,
    position_sizes_lamports=['100000000','1000000000'],followup_delay_ms=15000,
    selection='first_two_strict_or_research_only_admissible_in_first_six_unique_native_SOL_rows',
    historical_unknown_allowed='platform_pda:original_platform_admin_seed_not_retained',
    safety_FAIL_policy='reject; no_override',
    size_policy='own_separate_exact_quotes; size_model_and_current_full_exit_capacity_required',
    horizon_anchor='after_all_initial_full_exit_receipts; followed_by_newer_same_bank_RPC_snapshot',
    request_budget=dict(discovery=1,pool_roots=1,initial_bank_and_time=2,
        four_exact_buys_and_initial_full_sells=8,followup_bank_and_time=2,
        four_exact_followup_full_sells=4,fee_reference_page_and_body=2),
    projected_inventory='expected_output_of_validated_exact_input_quote; never_acquired',
    missing_actual_input='UNKNOWN; permitted_for_research_projection_only',
    missing_source_clocks='UNKNOWN; local_causality_is_not_source_freshness',
    additional_costs_lamports_hypotheses=['0','5000','100000','1000000'],
    fees_policy='route_fees_already_in_quoted_output; no_double_count',
    stop_policy='first_blocking_HTTP_transport_malformed_error_after_receipt; no_retry_no_fallback',
    logical_HTTP200_quote_refusals='retain_all; continue_only_fixed_schedule',
    market_orders_enabled=False,ledger_mutation=False,active_policy_changed=False,
    AB_policy='only_independently_admissible_causal_inputs; no_forced_trades_or_policy_promotion',
    independent_trials='new_clocked_capture; repeated_tokens_and_creator_links_not_independent_trials')


def make_plan(*,registered_at_ms,source_revision):
    from bot.p3.cohort import make_acquisition_plan
    make_acquisition_plan(registered_at_ms=registered_at_ms,source_revision=source_revision)
    return dict(deepcopy(FIXED),registered_at_ms=registered_at_ms,source_revision=source_revision)


def validate_plan(plan,*,first_observation_at_ms=None):
    if type(plan) is not dict or plan!=make_plan(registered_at_ms=plan.get('registered_at_ms'),source_revision=plan.get('source_revision')):
        raise ValueError('Exact independently preregistered011 plan required')
    if first_observation_at_ms is not None and first_observation_at_ms<=plan['registered_at_ms']:
        raise ValueError('Observation must follow preregistration')
    return hashlib.sha256(cp.canonical(plan)).hexdigest()


async def collect_research_cohort(store,session,plan,*,provenance='live'):
    from bot.p3.research_cycles import projected_research_inventory
    started=now_ms();digest=validate_plan(plan,first_observation_at_ms=started)
    if (not isinstance(session,cp.CampaignSession) or session.rpc_url!=CANONICAL_RPC_URL
            or session.max_requests!=20 or session.requests_used or store.events()
            or session._deadline_ns is not None or not session.bounded_phases
            or session.discovery_sort!='lastTrade'
            or getattr(session.session,'_retry_connection',None) is not False
            or provenance not in ('live','synthetic')):
        raise ValueError('New bounded anonymous journal/session and explicit provenance required')
    mono=time.monotonic_ns();session._deadline_ns=mono+60000000000
    stop=None;selection=None;retained=[];inventories=[]
    def append(kind,**event):
        identity=store.append(kind,provenance=provenance,**event)
        status=event.get('payload',{}).get('http_status')
        logical=(kind=='quote_attempt' and status==200 and event.get('outcome')=='unavailable'
            and event.get('reason') in ('provider_rejected','route_unavailable'))
        if ((type(status) is int and not 200<=status<300)
                or (kind in ('request','quote_attempt') and event.get('outcome') in ('error','cancelled'))
                or (kind=='quote_attempt' and event.get('payload',{}).get('provider')=='raydium_trade_api'
                    and event.get('outcome')!='quoted' and not logical)):
            raise cp.CampaignSourceStopped('source_error_after_persisted_receipt')
        return identity
    append('checkpoint',received_at_ms=started,outcome='research_plan_registered',payload=dict(plan=plan,plan_sha256=digest))

    async def run():
        nonlocal retained,selection
        payload,received=await cp._discover(session,append)
        retained,_,total=cp.select_rows(payload)
        for row in retained:row['provisional_index_reason']=row.pop('selection_reason')
        discovery=dict(rows=retained,received_row_count=total,response_representation_sha256=cp.digest(payload))
        try:
            _safe_json(payload)
            if len(cp.canonical(payload))>2000000:raise ValueError('Discovery retention bound')
        except (ValueError,TypeError):
            discovery.update(raw_response_retained=False,raw_response_retention_reason='unsafe_or_oversized_body; all_selection_fields_and_digest_retained')
        else:discovery.update(raw_response_retained=True,raw_response=payload)
        append('discovery',received_at_ms=received,outcome='observed',payload=discovery)
        rows=_prefix(retained)
        if not rows:return
        roots,receipt,request,_=await _rpc(session,append,'getMultipleAccounts',
            [[row['pool'] for row in rows],{'encoding':'base64','commitment':'confirmed'}])
        slot,values=cp._bank(roots,len(rows))
        append('pool_snapshot',received_at_ms=receipt,source_slot=slot,request_id=request,
            outcome='observed' if values is not None else 'missing',payload=dict(purpose='research_pool_roots',raw_rpc_result=roots,rows=rows))
        if values is None:raise cp.CampaignSourceStopped('malformed_root_bank')
        graphs={}
        for row,raw in zip(rows,values):
            try:graphs[row['mint']]=addresses_from_pool(raw,row['mint'],row['pool'])
            except (ValueError,KeyError,TypeError):cp._gap(append,'research_pool_graph_unusable',mint=row['mint'])
        initial_slot,initial=await prospective._grouped_snapshot(store,session,append,rows,graphs,slot,'initial',input_lamports=100000000)
        by_id={e['id']:e for e in store.events()}
        for row in retained:
            snapshot=initial.get(row.get('mint'))
            if snapshot:
                row['snapshot']=snapshot['analysis']
                row['snapshot_available_at_ms']=by_id[snapshot['snapshot_observation_id']]['available_at_ms']
        selection=select_research_cohort(retained,decision_at_ms=now_ms())
        append('checkpoint',received_at_ms=now_ms(),outcome='strict_cohort_fixed',payload=selection['strict_selection'])
        append('checkpoint',received_at_ms=now_ms(),outcome='research_cohort_fixed',payload={k:v for k,v in selection.items() if k!='strict_selection'})
        if not selection['selected']:return
        intents=[]
        for row in selection['selected']:
            source=next(r for r in retained if r.get('mint')==row['mint'])
            for budget in plan['position_sizes_lamports']:
                size_screen=classify_snapshot(source['snapshot'],size_lamports=int(budget),
                    available_at_ms=source['snapshot_available_at_ms'],decision_at_ms=selection['decision_at_ms'],
                    expected_mint=row['mint'],expected_pool=row['pool'])
                model=size_screen.get('own_entry_projection')
                admissible=model is not None and size_screen.get('observed_full_exit_capacity') is True
                append('checkpoint',received_at_ms=now_ms(),mint=row['mint'],outcome='research_size_admission',
                    payload=dict(budget_lamports=budget,admissible=admissible,screen=size_screen,trade_allowed=False))
                if not admissible:continue
                intents.append(dict(row=row,budget=budget))
        append('checkpoint',received_at_ms=now_ms(),outcome='research_quote_intents_fixed',
            payload=dict(intents=intents,trade_allowed=False,selection_before_economic_quotes=True))
        provider=NativeInventoryQuoteProvider(session.session,store,shared_session=session,append=append,max_requests=20,stop_on_provider_rejection=False)
        for intent in intents:
            row,budget=intent['row'],intent['budget']
            context=await provider(None,row['mint'],side='buy',amount_atomic=budget,inventory=None,
                decision_at_ms=now_ms(),observation_metadata=dict(probe_phase='initial',prospective_ordinal=row['ordinal']))
            if context is None:continue
            buy=context['buy_observation']
            inv=projected_research_inventory(buy,decision_at_ms=max(now_ms(),buy['available_at_ms']))
            append('checkpoint',received_at_ms=now_ms(),mint=row['mint'],outcome='research_inventory_fixed' if inv['accepted'] else 'research_inventory_refused',payload=dict(inventory=inv))
            if not inv['accepted']:continue
            inventories.append(dict(row=row,inventory=inv))
            await provider(None,row['mint'],side='sell',amount_atomic=inv['acquired_atomic'],
                inventory=dict(mint=row['mint'],remaining_atomic=inv['acquired_atomic']),decision_at_ms=now_ms(),
                observation_metadata=dict(probe_phase='initial',exit_scope='full_expected',
                    inventory_buy_observation_id=inv['buy_observation_id'],prospective_ordinal=row['ordinal']))
        if not inventories:return
        # A fresh full interval after every initial quote/persistence ensures a
        # followup cannot precede the known projected lot or its first exit.
        anchor=time.monotonic_ns()
        await asyncio.sleep(plan['followup_delay_ms']/1000)
        waited=(time.monotonic_ns()-anchor)//1000000
        if waited<plan['followup_delay_ms']:raise ValueError('Followup horizon not elapsed')
        append('checkpoint',received_at_ms=now_ms(),outcome='research_followup_horizon',payload=dict(elapsed_ms=waited))
        following,_=await prospective._grouped_snapshot(store,session,append,selection['selected'],graphs,initial_slot+1,'followup',input_lamports=100000000)
        if following is None or following<=initial_slot:raise cp.CampaignSourceStopped('followup_slot_not_advanced')
        for item in inventories:
            row,inv=item['row'],item['inventory']
            await provider(None,row['mint'],side='sell',amount_atomic=inv['acquired_atomic'],
                inventory=dict(mint=row['mint'],remaining_atomic=inv['acquired_atomic']),decision_at_ms=now_ms(),
                observation_metadata=dict(probe_phase='followup',exit_scope='full_expected',
                    inventory_buy_observation_id=inv['buy_observation_id'],prospective_ordinal=row['ordinal']))
        await prospective._fee_reference(store,session,append,selection['selected'][0])

    try:await asyncio.wait_for(run(),timeout=60)
    except cp.CampaignSourceStopped as error:stop=str(error)
    except (ValueError,TypeError,KeyError,asyncio.TimeoutError,cp.ReadOnlyPolicyError):stop='incomplete_source_evidence_or_budget'
    if selection is None:
        selection=select_research_cohort(retained,decision_at_ms=now_ms())
        store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),outcome='strict_cohort_fixed',payload=selection['strict_selection'])
        store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),outcome='research_cohort_fixed',payload={k:v for k,v in selection.items() if k!='strict_selection'})
    store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),outcome='research_capture_closed',
        payload=dict(requests_used=session.requests_used,elapsed_ms=(time.monotonic_ns()-mono)//1000000,stop_reason=stop,position_acquired=False))
    return build_report(store,plan)


def build_report(store,plan):
    from bot.p3.research_cycles import evaluate_research_cycles
    digest=validate_plan(plan);events=store.events();tail=store.verify_integrity()
    if (not events or events[-1]['outcome']!='research_capture_closed'
            or events[0]['payload']!={'plan':plan,'plan_sha256':digest}):
        raise ValueError('Closed matching011 journal required')
    state=events[-1]['payload'];discovery=next((e for e in events if e['kind']=='discovery'),None)
    selection=next(e['payload'] for e in events if e['outcome']=='research_cohort_fixed')
    strict=next(e['payload'] for e in events if e['outcome']=='strict_cohort_fixed')
    return dict(schema='p3-research-prospective-011-result-v1',plan_sha256=digest,
        source_revision=plan['source_revision'],records=len(events),tail_hash=tail,**state,
        discovery_universe_known=discovery is not None,selection=selection,strict_selection=strict,
        economics=evaluate_research_cycles(events,expected_tail=tail),
        provider_route_vs_screened_bank='UNPROVEN; route_pool_ids_retained_in_quotes_not_assumed_equal',
        net_market_pnl_sol=None,qualified_economic_cycles=0,AB_comparable_decisions=0,
        active_policy_changed=False,execution_verified=False)


async def capture(plan,database,*,output):
    routes=managed_proxy_routes((cp.INDEX_URL,CANONICAL_RPC_URL,CRITERIA['sources']['quotes']))
    with CaptureStore(database) as store:
        recording=True
        def retain(event):
            if recording:store.append('checkpoint',provenance='live',received_at_ms=now_ms(),outcome='transport_phase',payload=event)
        recorder=PhaseRecorder(retain)
        async with aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),
                connector=connector(recorder,proxy_host=urlsplit(routes[cp.INDEX_URL]).hostname),
                trace_configs=[recorder.trace_config()]) as transport:
            disable_retries(transport)
            session=cp.CampaignSession(transport,20,proxy_resolver=routes.__getitem__,rpc_url=CANONICAL_RPC_URL,bounded_phases=True,discovery_sort=plan['index_sort'])
            try:report=await collect_research_cohort(store,session,plan)
            finally:recording=False
            atomic_write_json(output,report,indent=2,sort_keys=True,allow_nan=False)
            return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','db','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--network',action='store_true');args=parser.parse_args(argv)
    if (not args.network or args.plan.is_symlink() or args.plan.name.startswith('.env') or args.plan.suffix!='.json'
            or args.db.exists() or args.db.is_symlink() or args.output.exists() or args.output.is_symlink()
            or args.output.suffix!='.json'
            or len({p.resolve() for p in (args.plan,args.db,args.output)})!=3):
        parser.error('Published011 plan, network opt-in and new separate outputs required')
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    report=asyncio.run(capture(plan,args.db,output=args.output))
    print(json.dumps({k:report[k] for k in ('requests_used','stop_reason','qualified_economic_cycles')}))


if __name__=='__main__':main()
