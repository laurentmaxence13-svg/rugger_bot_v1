"""One bounded, causal S0/S1/S2 bank capture; no quotes, orders or wallet.

The fixed twelve-pool denominator precedes every reserve observation. Only S0
and S1 select candidates. All numerical results are conditional bank models,
never fills, independently executable prices or certified market returns.
"""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import aiohttp

# Collection never needs the application's user configuration or credentials,
# including when invoked directly rather than through the watchdog wrapper.
os.environ['RUGGER_NO_DOTENV']='1'

from bot.analyser.artifacts import atomic_write_json
from bot.p3 import campaign as cp, prospective_campaign as prospective
from bot.p3.asof_protocol_012 import validate_plan
from bot.p3.asof_slot_markout import evaluate_asof_slot_markout
from bot.p3.asof_wide_selection import select_twelve_prefix_asof_research
from bot.p3.collect import _rpc, now_ms, capture_transaction
from bot.p3.launchlab import addresses_from_pool, analyze_snapshot
from bot.p3.own_fee_bounds import legacy_v0_roundtrip_fee_bounds
from bot.p3.platform_admin_history import _signature, refine_snapshot_with_platform_history
from bot.p3.quotes import SOL_MINT
from bot.p3.store import CaptureStore, _safe_json
from bot.p3.transport import PhaseRecorder, connector, managed_proxy_routes, disable_retries


def fixed_prefix(retained):
    """Keep every row, including duplicates and rejected rows, in source order."""
    rows=[];mints=set();pools=set()
    for row in retained:
        row['previous_two_prefix_reason']=row.pop('selection_reason',None)
        mint,pool=row.get('mint'),row.get('pool')
        if not mint or mint==SOL_MINT or not pool or row.get('quote_mint_claim')!=SOL_MINT:
            reason='invalid_or_outside_native_SOL_scope'
        elif mint in mints or pool in pools:
            reason='duplicate_mint_or_pool'
        elif len(rows)>=12:
            reason='outside_fixed_twelve_prefix'
        else:
            reason='fixed_before_any_reserve_observation'
            row['ordinal']=len(rows);rows.append(row)
        row['selection_reason']=reason
        if mint and mint!=SOL_MINT and pool and row.get('quote_mint_claim')==SOL_MINT:
            mints.add(mint);pools.add(pool)
    return rows


def _event(store,identity):
    return next(e for e in store.events() if e['id']==identity)


async def _history(store,session,append,rows,snapshots,plan):
    seen=set()
    for row in rows:
        snapshot=snapshots.get(row['mint'])
        platform=(snapshot or {}).get('analysis',{}).get('facts',{}).get('addresses',{}).get('platform')
        if not platform or platform in seen:continue
        seen.add(platform)
        if len(seen)>plan['historical_platforms_max']:break
        page,receipt,request,_=await _rpc(session,append,'getSignaturesForAddress',
            [platform,{'limit':plan['historical_signature_page_limit'],'commitment':'confirmed'}])
        identity=append('checkpoint',received_at_ms=receipt,request_id=request,
            outcome='asof_historical_signature_page',payload=dict(platform=platform,rows=page,
                snapshot_context_slot=snapshot['context_slot'],selection='oldest_successful_in_single_page'))
        if type(page) is not list or len(page)>plan['historical_signature_page_limit']:
            raise cp.CampaignSourceStopped('malformed_historical_signature_page')
        candidates=[]
        for entry in page:
            if (type(entry) is not dict or 'err' not in entry or type(entry.get('slot')) is not int
                    or entry['slot']<0):
                raise cp.CampaignSourceStopped('malformed_historical_signature_row')
            try:signature=_signature(entry.get('signature'))
            except (ValueError,TypeError):
                raise cp.CampaignSourceStopped('malformed_historical_signature_row') from None
            if entry['err'] is None and entry['slot']<=snapshot['context_slot']:
                candidates.append((entry['slot'],signature))
        if not candidates:continue
        # Ties preserve page order; no result-dependent search or second page.
        slot,signature=min(candidates,key=lambda item:item[0])
        append('checkpoint',received_at_ms=now_ms(),outcome='asof_historical_body_intent',
            payload=dict(platform=platform,signature=signature,slot=slot,page_observation_id=identity))
        tx,receipt,request,_=await _rpc(session,append,'getTransaction',
            [signature,{'encoding':'jsonParsed','commitment':'confirmed','maxSupportedTransactionVersion':0}])
        capture_transaction(append,tx,signature=signature,slot=slot,received_at_ms=receipt,request_id=request)
        event=next((e for e in reversed(store.events(kind='transaction'))
                    if e.get('signature')==signature and e.get('request_id')==request),None)
        if tx is None:continue  # Unavailable historical body stays UNKNOWN.
        signatures=tx.get('transaction',{}).get('signatures') if type(tx) is dict else None
        if (not event or event['outcome']!='observed' or type(tx) is not dict or tx.get('slot')!=slot
                or type(signatures) is not list or not signatures or signatures[0]!=signature):
            raise cp.CampaignSourceStopped('historical_transaction_identity_or_shape_invalid')
        if event:
            append('checkpoint',received_at_ms=now_ms(),outcome='asof_historical_body_binding',
                payload=dict(platform=platform,signature=signature,slot=slot,
                    page_observation_id=identity,transaction_observation_id=event['id'],
                    source_request_id=request,cryptographic_signature_verified=False))


def _proofs(events,decision_at_ms):
    by_id={e['id']:e for e in events};proofs={}
    for event in events:
        if event.get('outcome')!='asof_historical_body_binding' or event['available_at_ms']>decision_at_ms:continue
        binding=event['payload'];txevent=by_id.get(binding['transaction_observation_id'])
        pageevent=by_id.get(binding['page_observation_id'])
        if (not txevent or not pageevent or txevent['available_at_ms']>decision_at_ms
                or txevent.get('signature')!=binding['signature']
                or txevent.get('source_slot')!=binding['slot']
                or txevent.get('request_id')!=binding['source_request_id']):
            raise ValueError('Historical transaction provenance binding invalid')
        tx=txevent['payload'].get('raw_transaction')
        if (type(tx) is not dict or tx.get('slot')!=binding['slot']
                or tx.get('transaction',{}).get('signatures',[None])[0]!=binding['signature']
                or pageevent['payload'].get('platform')!=binding['platform']
                or not any(r.get('signature')==binding['signature'] and r.get('slot')==binding['slot']
                           and r.get('err') is None for r in pageevent['payload']['rows'])):
            raise ValueError('Historical page and transaction disagree')
        proofs[binding['platform']]=(tx,binding['signature'],event['available_at_ms'])
    return proofs


def _refine(analysis,proofs,decision_at_ms):
    platform=analysis.get('facts',{}).get('addresses',{}).get('platform')
    proof=proofs.get(platform)
    return (refine_snapshot_with_platform_history(analysis,proof[0],signature=proof[1],
        proof_available_at_ms=proof[2],decision_at_ms=decision_at_ms) if proof else deepcopy(analysis))


def _selection_inputs(events,decision_at_ms):
    discovery=next((e for e in events if e['kind']=='discovery'),None)
    rows=deepcopy(discovery['payload']['rows']) if discovery else []
    proofs=_proofs(events,decision_at_ms);prior={};by_id={e['id']:e for e in events}
    for event in events:
        if event['kind']!='candidate_decision' or event['payload'].get('probe_phase') not in ('S0','S1'):continue
        if event['available_at_ms']>decision_at_ms:
            raise ValueError('Predecision analysis was not available at the decision')
        phase=event['payload']['probe_phase'];identity=event['payload']['snapshot_observation_id']
        raw=by_id[identity];analysis=_refine(event['payload']['analysis'],proofs,decision_at_ms)
        mint=analysis['mint']
        if phase=='S0':prior[mint]=dict(pool=analysis['pool_address'],snapshot=analysis,
                                       available_at_ms=raw['available_at_ms'])
        else:
            for row in rows:
                if row.get('mint')==mint and row.get('pool')==analysis['pool_address']:
                    row.update(snapshot=analysis,snapshot_available_at_ms=raw['available_at_ms'])
    return rows,prior


def cost_scenarios(plan):
    common=plan['cost_assumptions']
    return {
        'unknown_ATA':legacy_v0_roundtrip_fee_bounds(**common),
        'hypothetical_existing_ATA':legacy_v0_roundtrip_fee_bounds(**common,
            ata_rent_locked_lamports=0,ata_recovered_at_horizon=True),
        'hypothetical_new_classic_ATA':legacy_v0_roundtrip_fee_bounds(**common,
            ata_rent_locked_lamports=plan['classic_ATA_deposit_hypothesis_lamports'],
            ata_recovered_at_horizon=None)}


def _markouts(selection,events,plan):
    scenarios=cost_scenarios(plan);results=[];by_id={e['id']:e for e in events}
    for event in events:
        if event['kind']!='candidate_decision' or event['payload'].get('probe_phase')!='S2':continue
        raw=by_id[event['payload']['snapshot_observation_id']]
        at=max(event['available_at_ms'],raw['available_at_ms'])
        s2=_refine(event['payload']['analysis'],_proofs(events,selection['decision_at_ms']),selection['decision_at_ms'])
        for budget in plan['position_sizes_lamports']:
            for name,costs in scenarios.items():
                result=evaluate_asof_slot_markout(selection,s2,s2_available_at_ms=raw['available_at_ms'],
                    exit_decision_at_ms=at,budget_lamports=budget,
                    extra_cost_lower_lamports=int(costs['economic_fee_cost_lower_lamports']),
                    extra_cost_upper_lamports=int(costs['economic_fee_cost_upper_lamports']))
                result.update(cost_scenario=name,cost_bounds=costs,
                    network_fee_only_lower_lamports=result.pop('net_conditional_lower_lamports',None),
                    network_fee_only_upper_lamports=result.pop('net_conditional_upper_lamports',None),
                    full_cost_conditional_lower_lamports=None,full_cost_conditional_upper_lamports=None,
                    all_applicable_costs_known=False)
                if result['status']=='CONDITIONAL_BANK_MARKOUT':
                    gross=int(result['gross_conditional_markout_lamports'])
                    result['full_cost_conditional_upper_lamports']=str(gross-int(costs['cost_lower_lamports']))
                    if costs['cost_upper_lamports'] is not None:
                        result['full_cost_conditional_lower_lamports']=str(gross-int(costs['cost_upper_lamports']))
                results.append(result)
    return results


async def _wait_interval(append,anchor,minimum_ms,label):
    remaining=max(0,minimum_ms*1000000-(time.monotonic_ns()-anchor))
    if remaining:await asyncio.sleep(remaining/1000000000)
    elapsed=(time.monotonic_ns()-anchor)//1000000
    if elapsed<minimum_ms:raise ValueError('Published causal interval not elapsed')
    append('checkpoint',received_at_ms=now_ms(),outcome='asof_interval_completed',
        payload=dict(interval=label,elapsed_ms=elapsed,minimum_ms=minimum_ms))


async def collect_asof_012(store,session,plan,*,provenance='live'):
    started=now_ms();digest=validate_plan(plan,first_observation_at_ms=started)
    if (not isinstance(session,cp.CampaignSession) or session.rpc_url!=plan['rpc_source']
            or session.max_requests!=20 or session.requests_used or store.events()
            or session._deadline_ns is not None or not session.bounded_phases
            or session.discovery_sort!='lastTrade'
            or getattr(session.session,'_retry_connection',None) is not False
            or provenance not in ('live','synthetic')):
        raise ValueError('Fresh bounded anonymous session and dedicated journal required')
    mono=time.monotonic_ns();session._deadline_ns=mono+plan['max_elapsed_ms']*1000000
    stop=None
    def append(kind,**event):
        identity=store.append(kind,provenance=provenance,**event)
        status=event.get('payload',{}).get('http_status')
        if ((type(status) is int and not 200<=status<300)
                or (kind=='request' and event.get('outcome') in ('error','cancelled'))):
            raise cp.CampaignSourceStopped('source_error_after_persisted_receipt')
        return identity
    append('checkpoint',received_at_ms=started,outcome='asof_plan_registered',payload=dict(plan=plan,plan_sha256=digest))

    async def run():
        payload,received=await cp._discover(session,append)
        retained,_,total=cp.select_rows(payload);rows=fixed_prefix(retained)
        discovery=dict(rows=retained,received_row_count=total,retained_row_count=len(retained),
            response_representation_sha256=cp.digest(payload),universe_truncated=total>100)
        try:
            _safe_json(payload)
            if len(cp.canonical(payload))>2000000:raise ValueError('Public body retention bound')
        except (ValueError,TypeError):
            discovery.update(raw_response_retained=False,
                raw_response_retention_reason='unsafe_or_oversized_body; every_bounded_selection_row_and_digest_retained')
        else:discovery.update(raw_response_retained=True,raw_response=payload)
        append('discovery',received_at_ms=received,outcome='observed',payload=discovery)
        append('checkpoint',received_at_ms=now_ms(),outcome='asof_prefix_fixed',
            payload=dict(rows=rows,maximum=12,denominator=len(retained),selection_before_any_reserves=True))
        if total>100:raise cp.CampaignSourceStopped('discovery_exceeds_registered_universe')
        if not rows:return
        roots,receipt,request,_=await _rpc(session,append,'getMultipleAccounts',
            [[row['pool'] for row in rows],{'encoding':'base64','commitment':'confirmed'}])
        slot,values=cp._bank(roots,len(rows))
        append('pool_snapshot',received_at_ms=receipt,source_slot=slot,request_id=request,
            outcome='observed' if values is not None else 'missing',
            payload=dict(purpose='asof_pool_roots',raw_rpc_result=roots,rows=rows))
        if values is None or slot<=0:raise cp.CampaignSourceStopped('malformed_root_bank')
        graphs={}
        for row,raw in zip(rows,values):
            try:graphs[row['mint']]=addresses_from_pool(raw,row['mint'],row['pool'])
            except (ValueError,KeyError,TypeError):cp._gap(append,'asof_pool_graph_unusable',mint=row['mint'])
        initial_slot,initial=await prospective._grouped_snapshot(store,session,append,rows,graphs,slot,'S0',
            input_lamports=plan['primary_model_input_lamports'])
        if initial_slot is None:return
        first_anchor=time.monotonic_ns()
        await _history(store,session,append,rows,initial,plan)
        await _wait_interval(append,first_anchor,plan['first_interval_minimum_ms'],'S0_to_S1')
        current_slot,_=await prospective._grouped_snapshot(store,session,append,rows,graphs,initial_slot+1,'S1',
            input_lamports=plan['primary_model_input_lamports'])
        decision=now_ms();universe,prior=_selection_inputs(store.events(),decision)
        selection=select_twelve_prefix_asof_research(universe,prior,decision_at_ms=decision,
            max_prior_age_ms=plan['max_S0_receipt_age_at_decision_ms'])
        append('checkpoint',received_at_ms=decision,outcome='asof_selection_fixed',payload=selection)
        from bot.master_comparison import freeze_bank_research_decisions
        comparison=freeze_bank_research_decisions(selection,decision_at_ms=decision)
        append('checkpoint',received_at_ms=now_ms(),outcome='asof_master_reference_fixed',payload=comparison)
        append('checkpoint',received_at_ms=now_ms(),outcome='asof_cost_intents_fixed',
            payload=dict(position_sizes_lamports=plan['position_sizes_lamports'],scenarios=cost_scenarios(plan),
                trade_allowed=False,own_entry_impact_on_future_actual_bank_unmodeled=True))
        if not selection['selected']:return
        second_anchor=time.monotonic_ns()
        await _wait_interval(append,second_anchor,plan['second_interval_minimum_ms'],'decision_to_S2')
        await prospective._grouped_snapshot(store,session,append,selection['selected'],graphs,current_slot+1,'S2',
            input_lamports=plan['primary_model_input_lamports'])

    try:await asyncio.wait_for(run(),timeout=plan['max_elapsed_ms']/1000)
    except cp.CampaignSourceStopped as error:stop=str(error)
    except (ValueError,TypeError,KeyError,IndexError,asyncio.TimeoutError,cp.ReadOnlyPolicyError):
        stop='incomplete_source_evidence_or_budget'
    except asyncio.CancelledError:
        stop='capture_cancelled_no_resume'
    store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),outcome='asof_capture_closed',
        payload=dict(requests_used=session.requests_used,elapsed_ms=(time.monotonic_ns()-mono)//1000000,
            stop_reason=stop,position_acquired=False))
    return build_report(store,plan)


def build_report(store,plan,*,allow_interrupted=False):
    """Replay raw account bytes, selection and markouts, including a crash prefix.

    Interrupted evidence is reportable; it is never resumable as an acquisition.
    A hash chain alone does not establish external source authenticity.
    """
    digest=validate_plan(plan);events=store.events();tail=store.verify_integrity()
    if not events or events[0]['payload']!={'plan':plan,'plan_sha256':digest}:
        raise ValueError('Matching012 preregistration journal required')
    closed=events[-1]['outcome']=='asof_capture_closed'
    if not closed and not allow_interrupted:raise ValueError('Capture is interrupted; explicit prefix replay required')
    by_id={e['id']:e for e in events};decoded=0
    requests=[e for e in events if e['kind']=='request']
    maxima={'getMultipleAccounts':4,'getBlockTime':3,'getSignaturesForAddress':2,'getTransaction':2}
    if len(requests)>12:raise ValueError('Registered unspent reserve was consumed')
    for method,maximum in maxima.items():
        if sum(e['payload'].get('rpc_method')==method for e in requests)>maximum:
            raise ValueError('Registered method-specific budget exceeded')
    if sum(e['payload'].get('provider')=='raydium_launch_mint_index' for e in requests)>1:
        raise ValueError('Discovery retried')
    for index,event in enumerate(requests):
        status=event['payload'].get('http_status')
        if (event['outcome'] in ('error','cancelled') or
                (type(status) is int and not 200<=status<300)) and index!=len(requests)-1:
            raise ValueError('Requests continued after blocking source error')
    if closed and events[-1]['payload']['requests_used']!=len(requests):
        raise ValueError('Closed request budget differs from retained attempts')
    for event in events:
        if event['kind']!='candidate_decision' or event['payload'].get('probe_phase') not in ('S0','S1','S2'):continue
        raw=by_id[event['payload']['snapshot_observation_id']];p=raw['payload']
        group=by_id[p['source_group_observation_id']]['payload']
        all_accounts=dict(zip(group['requested_addresses'],group['raw_rpc_result']['value']))
        subset=p['raw_rpc_result']
        if (subset['context']!=group['raw_rpc_result']['context']
                or subset['value']!=[all_accounts[a] for a in p['requested_addresses']]
                or raw['source_slot']!=subset['context']['slot']):
            raise ValueError('Subset and original grouped bank disagree')
        analysis=analyze_snapshot(all_accounts,context_slot=raw['source_slot'],expected_mint=raw['mint'],
            pool_address=p['addresses']['pool'],input_lamports=plan['primary_model_input_lamports'],
            evidence_profile='published_metadata_v1')
        if analysis!=event['payload']['analysis']:raise ValueError('Raw account decoder replay differs')
        decoded+=1
    selected=next((e for e in events if e['outcome']=='asof_selection_fixed'),None)
    comparison=next((e for e in events if e['outcome']=='asof_master_reference_fixed'),None)
    selection=selected['payload'] if selected else None
    if selected:
        universe,prior=_selection_inputs(events,selection['decision_at_ms'])
        replay=select_twelve_prefix_asof_research(universe,prior,decision_at_ms=selection['decision_at_ms'],
            max_prior_age_ms=plan['max_S0_receipt_age_at_decision_ms'])
        if replay!=selection:raise ValueError('Frozen pre-S2 selection differs on replay')
        if any(e['payload'].get('probe_phase')=='S2' and e['id']<selected['id'] for e in events):
            raise ValueError('S2 preceded selection')
    phases={phase:min((e['id'] for e in events if e['payload'].get('phase')==phase),default=None)
            for phase in ('S1','S2')}
    for phase,label,minimum in (('S1','S0_to_S1',plan['first_interval_minimum_ms']),
                                 ('S2','decision_to_S2',plan['second_interval_minimum_ms'])):
        if phases[phase] is None:continue
        waits=[e for e in events if e['outcome']=='asof_interval_completed'
               and e['payload'].get('interval')==label and e['id']<phases[phase]]
        if (len(waits)!=1 or waits[0]['payload'].get('minimum_ms')!=minimum
                or type(waits[0]['payload'].get('elapsed_ms')) is not int
                or waits[0]['payload']['elapsed_ms']<minimum):
            raise ValueError('Published causal waiting interval absent or too short')
    if comparison:
        from bot.master_comparison import freeze_bank_research_decisions
        if (not selected or comparison['payload']!=freeze_bank_research_decisions(
                selection,decision_at_ms=selection['decision_at_ms'])):
            raise ValueError('Frozen Master/reference decisions differ on replay')
        if any(e['payload'].get('probe_phase')=='S2' and e['id']<comparison['id'] for e in events):
            raise ValueError('S2 preceded Master/reference freeze')
    costs=next((e for e in events if e['outcome']=='asof_cost_intents_fixed'),None)
    expected_costs=dict(position_sizes_lamports=plan['position_sizes_lamports'],scenarios=cost_scenarios(plan),
        trade_allowed=False,own_entry_impact_on_future_actual_bank_unmodeled=True)
    if costs and (not selected or costs['id']<selected['id'] or costs['payload']!=expected_costs):
        raise ValueError('Frozen costs differ from the preregistered hypotheses')
    if phases['S2'] is not None and (not comparison or not costs or costs['id']>=phases['S2']):
        raise ValueError('S2 preceded the complete decision and cost freeze')
    discovery=next((e for e in events if e['kind']=='discovery'),None)
    state=events[-1]['payload'] if closed else dict(requests_used=sum(e['kind']=='request' for e in events),
        elapsed_ms=None,stop_reason='interrupted_committed_prefix; network_resume_prohibited',position_acquired=False)
    return dict(schema='p3-asof-bank-012-result-v1',plan_sha256=digest,source_revision=plan['source_revision'],
        records=len(events),tail_hash=tail,closed=closed,**state,
        discovery_universe_known=discovery is not None,
        universe_size=len(discovery['payload']['rows']) if discovery else None,
        selection=selection,master_reference=comparison['payload'] if comparison else None,
        replayed_raw_analyses=decoded,markouts=_markouts(selection,events,plan) if selection else [],
        cost_scenarios=cost_scenarios(plan),qualified_economic_cycles=0,net_market_pnl_sol=None,
        actual_executed_transactions=0,active_policy_changed=False,execution_verified=False,
        network_resume_permitted=False,
        missing_economic_evidence=['actual_own_entry_impact_on_future_bank','all_applicable_own_costs',
            'independent_trader_identity','current_SOL_USD_for_strategy_features','actual_fills_and_settlement'])


async def capture(plan,database,*,output):
    validate_plan(plan);routes=managed_proxy_routes((plan['index_source'],plan['rpc_source']))
    with CaptureStore(database) as store:
        recording=True
        def retain(event):
            if recording:store.append('checkpoint',provenance='live',received_at_ms=now_ms(),
                outcome='transport_phase',payload=event)
        recorder=PhaseRecorder(retain)
        async with aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),
                connector=connector(recorder,proxy_host=urlsplit(routes[plan['index_source']]).hostname),
                trace_configs=[recorder.trace_config()]) as transport:
            disable_retries(transport)
            session=cp.CampaignSession(transport,20,proxy_resolver=routes.__getitem__,rpc_url=plan['rpc_source'],
                bounded_phases=True,discovery_sort='lastTrade')
            try:report=await collect_asof_012(store,session,plan)
            finally:recording=False
            # Persist BEFORE HTTP/DNS/executor cleanup, which may block.
            atomic_write_json(output,report,indent=2,sort_keys=True,allow_nan=False)
            return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','db','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--network',action='store_true');args=parser.parse_args(argv)
    if (not args.network or args.plan.is_symlink() or args.plan.name.startswith('.env') or args.plan.suffix!='.json'
            or args.db.exists() or args.db.is_symlink() or args.output.exists() or args.output.is_symlink()
            or args.output.suffix!='.json' or len({p.resolve() for p in (args.plan,args.db,args.output)})!=3):
        parser.error('Published012 plan, network opt-in and new separate outputs required')
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    report=asyncio.run(capture(plan,args.db,output=args.output))
    print(json.dumps({k:report[k] for k in ('requests_used','stop_reason','qualified_economic_cycles')}))


if __name__=='__main__':main()
