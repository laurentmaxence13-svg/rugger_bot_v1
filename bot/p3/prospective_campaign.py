"""One preregistered multi-launch observation, sharing every source budget.

No wallet, transaction construction, orders or ledger settlement. RPC bank
models and their estimated block times never replace provider quote clocks.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import time

import aiohttp

from bot.analyser.artifacts import atomic_write_json
from bot.p3 import campaign as cp
from bot.p3.collect import (RPC_URL, _rpc, _environment_proxy, now_ms,
                            _record_quote, _quote_with_cancellation_receipt, capture_transaction,
                            ReadOnlyPolicyError)
from bot.p3.inventory_provider import NativeInventoryQuoteProvider
from bot.p3.launchlab import addresses_from_pool, analyze_snapshot
from bot.p3.exit_qualification import inventory_from_buy
from bot.p3.quotes import RaydiumQuoteClient, SOL_MINT
from bot.p3.store import CaptureStore


FIXED = dict(schema='p3-prospective-inventory-v1', plan_id='prospective-inventory-008',
    sample_size=3, max_requests=20, max_elapsed_ms=60000, followup_delay_ms=15000,
    input_lamports=1000000000, slippage_bps=100, index_sort='new', max_index_rows=100,
    rpc_endpoint=RPC_URL, evidence_profile='published_metadata_v1', partial_divisor=4,
    selection='first_three_unique_mints_and_pools_native_SOL_before_market_outcomes',
    partial_rule='prefixed_quarter_after_initial_full_logical_refusal_only',
    fee_reference='latest_successful_transaction_in_one_row_page_of_first_selected_pool',
    creation_lookup=False, stop_on_provider_rejection=False, reference_cash_lamports=10000000000,
    logical_unavailability_continuation=['provider_rejected','route_unavailable'],
    source_error_policy='stop_after_persisting_first_http_transport_or_malformed_error',
    p4_scope='instrumental_development_only',
    p4_holdout_policy='future_preregistered_after_model_freeze_excluding_development_creators')


def validate_plan(plan):
    if type(plan) is not dict or set(plan) != set(FIXED)|{'registered_at_ms','source_revision'}:
        raise ValueError('Unsupported prospective plan fields')
    if any(type(plan[k]) is not type(v) or plan[k] != v for k,v in FIXED.items()):
        raise ValueError('Unsupported prospective protocol')
    if (type(plan['registered_at_ms']) is not int or not 0 < plan['registered_at_ms'] < now_ms()
            or type(plan['source_revision']) is not str
            or re.fullmatch('[0-9a-f]{40}',plan['source_revision']) is None):
        raise ValueError('Prospective plan must be registered with an exact source revision')
    return hashlib.sha256(cp.canonical(plan)).hexdigest()


def select_prefix(payload):
    retained, _, total = cp.select_rows(payload)
    rows, mints, pools = [],set(),set()
    for row in retained:
        if not row['mint'] or row['mint']==SOL_MINT or not row['pool'] or row['quote_mint_claim']!=SOL_MINT:
            row['selection_reason']='invalid_or_outside_native_SOL_scope'
        elif row['mint'] in mints or row['pool'] in pools:
            row['selection_reason']='duplicate_mint_or_pool'
        elif len(rows)>=3:
            row['selection_reason']='outside_fixed_prefix'
        else:
            row['selection_reason']='selected_before_market_outcomes'
            row['ordinal']=len(rows)
            row['creator']=row['creator_claim']
            rows.append(row)
        if (row['mint'] and row['mint']!=SOL_MINT and row['pool']
                and row['quote_mint_claim']==SOL_MINT):
            mints.add(row['mint']);pools.add(row['pool'])
    return retained,rows,total


async def _grouped_snapshot(store,session,append,rows,graphs,minimum_slot,phase):
    ordered=list(dict.fromkeys(address for row in rows if row['mint'] in graphs
                               for address in graphs[row['mint']].values()))
    if not ordered:
        return None,{}
    if len(ordered)>100:
        raise ValueError('Grouped snapshot exceeds RPC account limit')
    raw,received,request,_=await _rpc(session,append,'getMultipleAccounts',
        [ordered,{'encoding':'base64','commitment':'confirmed','minContextSlot':minimum_slot}])
    slot,values=cp._bank(raw,len(ordered))
    if slot is not None and slot<minimum_slot:
        slot,values=None,None
    group_id=append('pool_snapshot',received_at_ms=received,source_slot=slot,request_id=request,
        outcome='observed' if values is not None else 'missing',
        payload={'purpose':'prospective_grouped_bank','phase':phase,'requested_addresses':ordered,
                 'raw_rpc_result':raw,'minimum_context_slot':minimum_slot})
    if values is None:
        cp._gap(append,'prospective_group_bank_unavailable')
        raise cp.CampaignSourceStopped('malformed_or_out_of_order_group_bank')
    block_time,time_received,time_request,_=await _rpc(session,append,'getBlockTime',[slot])
    append('checkpoint',received_at_ms=time_received,source_slot=slot,request_id=time_request,
        outcome='onchain_bank_time',payload={'context_slot':slot,'phase':phase,
            'group_observation_id':group_id,
            'block_time_seconds':block_time if type(block_time) is int and block_time>0 else None,
            'time_basis':'estimated_block_production_time_not_provider_quote_time'})
    all_accounts=dict(zip(ordered,values));snapshots={}
    for row in rows:
        mint=row['mint']
        if mint not in graphs:
            continue
        addresses=graphs[mint];keys=list(addresses.values())
        subset={'context':raw['context'],'value':[all_accounts[a] for a in keys]}
        identity=append('pool_snapshot',received_at_ms=received,source_slot=slot,mint=mint,
            request_id=request,outcome='observed',payload={'period':phase,'addresses':addresses,
                'requested_addresses':keys,'raw_rpc_result':subset,'evidence_profile':'published_metadata_v1',
                'source_group_observation_id':group_id,
                'response_representation':'ordered_subset_of_retained_group_bank'})
        analysis=analyze_snapshot(all_accounts,context_slot=slot,expected_mint=mint,
            pool_address=row['pool'],input_lamports=1000000000,evidence_profile='published_metadata_v1')
        append('candidate_decision',received_at_ms=now_ms(),source_slot=slot,mint=mint,
            outcome='not_admitted',reason='prospective_instrumentation_not_strategy_entry',
            payload={'snapshot_observation_id':identity,'analysis':analysis,'probe_phase':phase,
                     'entry_permitted':False,'creation_verified':False})
        append('quote_attempt',received_at_ms=now_ms(),source_slot=slot,mint=mint,
            outcome='conditional' if analysis['conditional_projection'] else 'unavailable',
            reason='counterfactual_own_entry_model_not_provider_bank',
            payload={'provider':'local_pinned_sdk_arithmetic','quote_side':'buy_then_sell',
                     'probe_phase':phase,'snapshot_observation_id':identity,
                     'projection':analysis['conditional_projection'],'execution_verified':False,
                     'bank_time_does_not_timestamp_provider_quotes':True})
        snapshots[mint]={'context_slot':slot,'snapshot_observation_id':identity,'analysis':analysis}
    return slot,snapshots


async def _fee_reference(store,session,append,row):
    page,received,request,_=await _rpc(session,append,'getSignaturesForAddress',
        [row['pool'],{'limit':1,'commitment':'confirmed'}])
    append('checkpoint',received_at_ms=received,mint=row['mint'],request_id=request,
        outcome='fee_reference_signature_page',payload={'rows':page if type(page) is list else None,
            'purpose':'other_transaction_cost_reference_not_our_cost'})
    if type(page) is not list or not page:
        return
    item=page[0]
    if (type(item) is not dict or item.get('err') is not None or type(item.get('slot')) is not int
            or type(item.get('signature')) is not str
            or not re.fullmatch('[1-9A-HJ-NP-Za-km-z]{64,90}',item['signature'])):
        return
    tx,receipt,reference,_=await _rpc(session,append,'getTransaction',
        [item['signature'],{'encoding':'jsonParsed','commitment':'confirmed','maxSupportedTransactionVersion':1}])
    signatures=(tx.get('transaction') or {}).get('signatures') if type(tx) is dict and type(tx.get('transaction')) is dict else None
    if (type(tx) is not dict or tx.get('slot')!=item['slot']
            or type(signatures) is not list or not signatures or signatures[0]!=item['signature']):
        cp._gap(append,'fee_reference_transaction_identity_unverified',mint=row['mint'])
        return
    capture_transaction(append,tx,signature=item['signature'],slot=item['slot'],received_at_ms=receipt,
                        request_id=reference)
    from bot.p3.cost_evidence import classify_reference_transaction
    # Classify the actual committed envelope, not a reconstructed availability.
    evidence=next((event for event in reversed(store.events(kind='transaction'))
                   if event.get('signature')==item['signature'] and event.get('request_id')==reference),None)
    classification=classify_reference_transaction(evidence or {})
    append('checkpoint',received_at_ms=now_ms(),mint=row['mint'],outcome='additional_fee_reference',
        payload={'signature':item['signature'],'source_request_id':reference,
                 'source_observation_id':evidence['id'] if evidence else None,
                 'reference_fee_lamports':tx['meta'].get('fee') if type(tx.get('meta')) is dict else None,
                 'classification':classification,
                 'applicability_to_our_scenario':'UNPROVEN','our_additional_costs_known':False})


async def collect_prospective(store,session,plan,*,provenance='live'):
    plan_hash=validate_plan(plan)
    if session.rpc_url != plan['rpc_endpoint']:
        raise ValueError('Shared session endpoint differs from the preregistered source')
    if store.events() or session.requests_used or session.max_requests!=20:
        raise ValueError('New dedicated journal and one fresh global budget required')
    start=time.monotonic_ns();session._deadline_ns=start+60000000000
    stop_reason=None
    def append(kind,**event):
        identity=store.append(kind,provenance=provenance,**event)
        status=event.get('payload',{}).get('http_status')
        logical = (kind=='quote_attempt' and status==200 and event.get('outcome')=='unavailable'
                   and event.get('reason') in ('provider_rejected','route_unavailable'))
        if ((type(status) is int and not 200<=status<300)
                or (kind in ('request','quote_attempt') and event.get('outcome') in ('error','cancelled'))
                or (kind=='quote_attempt' and event.get('payload',{}).get('provider')=='raydium_trade_api'
                    and event.get('outcome')!='quoted' and not logical)):
            raise cp.CampaignSourceStopped('source_error_after_persisted_receipt')
        return identity
    append('checkpoint',received_at_ms=now_ms(),outcome='prospective_plan_registered',
           payload={'plan':plan,'plan_sha256':plan_hash})
    async def run():
        payload,received=await cp._discover(session,append)
        retained,rows,total=select_prefix(payload)
        append('discovery',received_at_ms=received,outcome='observed',
               payload={'rows':retained,'received_row_count':total,'selection_scope':'instrumental_prefix_not_independent_trades'})
        from bot.p3.prospective_report import prospective_assignment
        assignment=prospective_assignment(plan,rows)
        append('checkpoint',received_at_ms=now_ms(),outcome='prospective_prefix_fixed',
               payload={'candidates':rows,'p4_assignment_sha256':assignment['sha256'],
                        'p4_assignment':assignment})
        if not rows:
            return
        roots,receipt,request,_=await _rpc(session,append,'getMultipleAccounts',
            [[r['pool'] for r in rows],{'encoding':'base64','commitment':'confirmed'}])
        slot,values=cp._bank(roots,len(rows))
        append('pool_snapshot',received_at_ms=receipt,source_slot=slot,request_id=request,
               outcome='roots_observed' if values is not None else 'missing',
               payload={'requested_pool_rows':rows,'raw_rpc_result':roots})
        if values is None:
            cp._gap(append,'prospective_root_bank_malformed')
            raise cp.CampaignSourceStopped('malformed_root_bank')
        graphs={}
        for row,raw in zip(rows,values):
            try:
                graphs[row['mint']]=addresses_from_pool(raw,row['mint'],row['pool'])
            except (ValueError,KeyError,TypeError):
                cp._gap(append,'prospective_pool_graph_unusable',mint=row['mint'])
        initial_slot,initial=await _grouped_snapshot(store,session,append,rows,graphs,slot,'initial')
        snapshot_completed=time.monotonic_ns()
        provider=NativeInventoryQuoteProvider(session.session,store,shared_session=session,append=append,
            stop_on_provider_rejection=False,max_requests=20)
        inventories={}
        for row in rows:
            mint=row['mint']
            if mint not in initial:
                continue
            context=await provider(None,mint,side='buy',amount_atomic='1000000000',inventory=None,
                decision_at_ms=now_ms(),observation_metadata={'probe_phase':'initial',
                    'prospective_ordinal':row['ordinal']})
            if context is None:
                continue
            event=context['buy_observation']
            decimals=initial[mint]['analysis'].get('facts',{}).get('base_mint',{}).get('decimals')
            decimals=int(decimals) if type(decimals) is str and decimals.isdecimal() else decimals
            inventory=inventory_from_buy(event,basis='expected_buy_output',token_decimals=decimals,
                entry_decision_at_ms=max(now_ms(),event['available_at_ms']),max_source_age_ms=5000)
            if inventory['accepted']:
                inventory['buy_observation_id']=event['id']
                inventory['partial_diagnostic_atomic']=str(int(inventory['acquired_atomic'])//4)
                inventories[mint]=inventory
                append('checkpoint',received_at_ms=now_ms(),mint=mint,outcome='projected_inventory_fixed',
                    payload={'acquired_atomic':inventory['acquired_atomic'],'minimum_atomic':inventory['minimum_atomic'],
                             'partial_diagnostic_atomic':inventory['partial_diagnostic_atomic'],
                             'buy_observation_id':event['id'],'acquisition_verified':False})
            else:
                cp._gap(append,'prospective_buy_inventory_unusable',mint=mint)
        for row in rows:
            mint=row['mint']
            if mint not in inventories:
                continue
            inv=inventories[mint]
            context=await provider(None,mint,side='sell',amount_atomic=inv['acquired_atomic'],
                inventory={'mint':mint,'remaining_atomic':inv['acquired_atomic']},decision_at_ms=now_ms(),
                observation_metadata={'probe_phase':'initial','exit_scope':'full_expected',
                    'inventory_buy_observation_id':inv['buy_observation_id'],'prospective_ordinal':row['ordinal']})
            event=context['sell_observation'] if context else None
            if (event and event['outcome']=='unavailable' and event.get('reason')=='provider_rejected'
                    and int(inv['partial_diagnostic_atomic'])>0):
                # Fixed BEFORE the full response; no inventory is resized or settled.
                request_id='prospective-partial-'+str(row['ordinal'])
                client=RaydiumQuoteClient(session)
                quote=await _quote_with_cancellation_receipt(client,append,mint,SOL_MINT,
                    inv['partial_diagnostic_atomic'],'sell',request_id)
                quote.update(probe_phase='initial',exit_scope='partial_diagnostic',
                    inventory_buy_observation_id=inv['buy_observation_id'],prospective_ordinal=row['ordinal'],
                    diagnostic_only=True)
                _record_quote(append,quote,'sell',request_id)
        if initial_slot is not None and inventories:
            delay=max(0,15000000000-(time.monotonic_ns()-snapshot_completed))/1e9
            await asyncio.sleep(delay)
            waited_ms=(time.monotonic_ns()-snapshot_completed)//1000000
            if waited_ms < plan['followup_delay_ms']:
                raise ValueError('Followup horizon has not elapsed')
            append('checkpoint',received_at_ms=now_ms(),outcome='followup_wait_completed',
                payload={'elapsed_since_initial_bank_ms':waited_ms,
                         'minimum_elapsed_ms':plan['followup_delay_ms']})
            following_slot,_=await _grouped_snapshot(store,session,append,rows,graphs,initial_slot+1,'followup')
            if following_slot is not None and following_slot>initial_slot:
                for row in rows:
                    mint=row['mint']
                    if mint in inventories:
                        inv=inventories[mint]
                        await provider(None,mint,side='sell',amount_atomic=inv['acquired_atomic'],
                            inventory={'mint':mint,'remaining_atomic':inv['acquired_atomic']},decision_at_ms=now_ms(),
                            observation_metadata={'probe_phase':'followup','exit_scope':'full_expected',
                                'inventory_buy_observation_id':inv['buy_observation_id'],
                                'prospective_ordinal':row['ordinal']})
        await _fee_reference(store,session,append,rows[0])
    try:
        await asyncio.wait_for(run(),timeout=60)
    except cp.CampaignSourceStopped:
        stop_reason='source_error_after_persisted_receipt'
    except (ValueError,KeyError,TypeError,asyncio.TimeoutError,ReadOnlyPolicyError):
        stop_reason='incomplete_source_evidence_or_budget'
    store.append('checkpoint',provenance=provenance,received_at_ms=now_ms(),outcome='prospective_closed',
        payload={'requests_used':session.requests_used,'stop_reason':stop_reason,
                 'elapsed_ms':(time.monotonic_ns()-start)//1000000,'position_acquired':False})
    from bot.p3.prospective_report import build_prospective_report
    tail=store.verify_integrity()
    return build_prospective_report(plan,store.events(),integrity_verified=True,expected_tail=tail)


async def _capture(plan,database):
    with CaptureStore(database) as store:
        async with aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport,'_retry_connection',None)) is not bool:
                raise ReadOnlyPolicyError('Unsupported transport retry policy')
            transport._retry_connection=False
            session=cp.CampaignSession(transport,20,proxy_resolver=_environment_proxy)
            return await collect_prospective(store,session,plan)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--network',action='store_true')
    args=parser.parse_args()
    if not args.network:
        parser.error('Explicit --network required')
    if (args.plan.suffix!='.json' or args.plan.name.startswith('.env') or args.plan.is_symlink()
            or len({p.resolve() for p in (args.plan,args.db,args.output)})!=3
            or args.db.exists() or args.db.is_symlink() or args.output.exists() or args.output.is_symlink()
            or args.output.suffix!='.json' or args.plan.stat().st_size>65536):
        parser.error('Separate registered JSON plan and new dedicated capture/report required')
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    result=asyncio.run(_capture(plan,args.db))
    atomic_write_json(args.output,result,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps({'economic_verdict':result['economic_verdict'],'report':str(args.output)}))


if __name__=='__main__':main()
