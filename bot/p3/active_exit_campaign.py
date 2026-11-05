"""Bounded current-state sell-depth observation, never a PAPER position/fill.

The selected quantity is a fixed fraction of observed outstanding curve tokens,
not the output of our hypothetical 1-SOL buy. No strategy thresholds are changed.
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
from bot.p3.collect import (RPC_URL, _rpc, _environment_proxy, now_ms, _record_quote,
                            _quote_with_cancellation_receipt, ReadOnlyPolicyError)
from bot.p3.launchlab import (_pool, addresses_from_pool, SnapshotEvidenceError,
                              observed_sell_projection)
from bot.p3.certification import DISCRIMINATORS, find_program_address, _decode
from bot.p3.quotes import RaydiumQuoteClient, SOL_MINT
from bot.p3.store import CaptureStore


def validate_plan(plan):
    fixed = dict(schema='p3-active-exit-control-v1', plan_id='active-exit-007',
                 max_requests=20, max_elapsed_ms=60000, screen_pool_limit=20,
                 graph_limit=3, sample_size=1, followup_delay_ms=15000,
                 input_lamports=1000000000, slippage_bps=100,
                 observed_inventory_divisor=100, index_sort='new',
                 evidence_profile='published_metadata_v1', rpc_endpoint=RPC_URL,
                 selection='first_arithmetic_safe_active_bank_in_first_three_active_pools',
                 inventory_basis='one_percent_observed_outstanding_not_acquired_inventory')
    if type(plan) is not dict or set(plan) != set(fixed) | {'registered_at_ms','source_revision'}:
        raise ValueError('Unexpected active-exit plan schema')
    if any(type(plan[k]) is not type(v) or plan[k] != v for k,v in fixed.items()):
        raise ValueError('Unsupported active-exit protocol')
    if (type(plan['registered_at_ms']) is not int
            or not 0 < plan['registered_at_ms'] < now_ms()
            or type(plan['source_revision']) is not str
            or not re.fullmatch('[0-9a-f]{40}',plan['source_revision'])):
        raise ValueError('Pre-registration time or exact source revision missing')
    return hashlib.sha256(cp.canonical(plan)).hexdigest()


def screening_rows(payload):
    retained, _, total = cp.select_rows(payload)
    screen, seen = [], set()
    for row in retained:
        valid = (row['mint'] and row['mint'] != SOL_MINT and row['pool']
                 and row['quote_mint_claim'] == SOL_MINT)
        if not valid:
            continue
        if row['mint'] in seen:
            row['selection_reason'] = 'duplicate_mint'
        elif len(screen) < 20:
            screen.append(row)
            row['selection_reason'] = 'selected_for_pool_screening'
        else:
            row['selection_reason'] = 'outside_screening_prefix'
        seen.add(row['mint'])
    return retained, screen, total


def active_pool_rows(rows, result):
    """Screen only public account facts in response order, before any quote."""
    slot, values = cp._bank(result, len(rows))
    if values is None:
        raise ValueError('Coherent screening bank missing')
    decisions, candidates = [], []
    for row, raw in zip(rows, values):
        reason = 'not_active_native_curve'
        try:
            pool, _ = _pool(raw)
            addresses_from_pool(raw, row['mint'], row['pool'])
            derived, _ = find_program_address((b'pool',_decode(row['mint']),_decode(SOL_MINT)))
            if (pool['discriminator_hex'] != DISCRIMINATORS['pool'].hex()
                    or derived != row['pool'] or pool['mint_b'] != SOL_MINT):
                reason = 'unverified_pool_identity'
            elif pool['status'] != 0:
                reason = 'not_active_native_curve'
            elif pool['real_a'] // 100 == 0 or pool['real_b'] == 0:
                reason = 'no_positive_observed_inventory_or_quote_reserve'
            elif len(candidates) == 3:
                reason = 'outside_fixed_graph_budget'
            else:
                reason = 'selected_for_graph_observation'
                candidates.append(row)
        except (ValueError, TypeError, KeyError):
            reason = 'unusable_pool_account'
        decisions.append(dict(mint=row['mint'],pool=row['pool'],reason=reason))
    return slot, candidates, decisions


def diagnostic_bank_mode(analysis):
    """UNKNOWN platform admin permits a quote probe, never candidate admission."""
    if analysis.get('conditional_projection') is None:
        return None
    identity = analysis.get('facts',{}).get('identity_certification',{})
    checks = identity.get('checks',[])
    if identity.get('account_discriminators_verified') is not True or not checks:
        return None
    required = {'pool_discriminator','config_discriminator','platform_discriminator',
                'pool_pda','config_pda','vault_a_pda','vault_b_pda','authority_pda','platform_pda'}
    if not required <= {c.get('name') for c in checks}:
        return None
    unknown = []
    for check in checks:
        if check.get('status') == 'FAIL':
            return None
        if check.get('status') != 'PASS':
            if (check.get('name') != 'platform_pda' or check.get('status') != 'UNKNOWN'
                    or check.get('reason') != 'original_platform_admin_seed_not_retained'):
                return None
            unknown.append(check)
    if unknown:
        return 'diagnostic_unknown_platform'
    return 'public_identity_checked_execution_unverified' if identity.get('program_derived_addresses_verified') is True else None


def observed_inventory_sell(analysis, quantity):
    if diagnostic_bank_mode(analysis) is None:
        raise SnapshotEvidenceError('bank_not_qualified_for_inventory_diagnostic')
    facts = analysis['facts']
    fields = ('status','virtual_a','virtual_b','real_a','real_b',
              'protocol_fee_accrued','platform_fee_accrued')
    pool = {k:int(facts['pool'][k]) for k in fields}
    pool['mint_b'] = facts['pool']['mint_b']
    rates = [int(facts['config']['trade_fee_rate_ppm']),
             int(facts['platform']['platform_fee_rate_ppm']),
             int(facts['platform']['creator_fee_rate_ppm'])]
    return observed_sell_projection(pool,input_token_atomic=quantity,fee_rates_ppm=rates,
        quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
        curve_type=int(facts['config']['curve_type']),
        share_fee_rate_ppm=int(facts['share_fee_assumption_ppm']))


async def collect_active_exit(store, session, plan, *, provenance='live'):
    plan_hash = validate_plan(plan)
    if store.events() or session.requests_used or session.max_requests != 20:
        raise ValueError('Fresh dedicated journal/session required')
    mono = time.monotonic_ns()
    session._deadline_ns = mono+60_000_000_000
    result = dict(schema='p3-active-exit-result-v1',plan_sha256=plan_hash,
                  source_revision=plan['source_revision'],
                  source_identity_basis='pre_registered_caller_revision',
                  selected_mint=None,fixed_sell_quantity_atomic=None,quotes=[],
                  snapshots=[],sell_prechecks=[],creation_verified=False,selection_mode=None,
                  position_acquired=False,execution_verified=False,
                  strict_exit_qualified=False,net_pnl_lamports=None,
                  economic_verdict='INSUFFICIENT DATA')

    def append(kind, **event):
        identity = store.append(kind,provenance=provenance,**event)
        status = event.get('payload',{}).get('http_status')
        reason = event.get('reason') or ''
        if ((type(status) is int and not 200 <= status < 300)
                or (kind in ('request','quote_attempt') and event.get('outcome') == 'error')
                or reason in ('timeout','transport_error') or reason.startswith('unsafe_')):
            raise cp.CampaignSourceStopped('source_error_after_persisted_receipt')
        return identity

    append('checkpoint',received_at_ms=now_ms(),outcome='registered_active_exit_plan',
           payload={'plan':plan,'plan_sha256':plan_hash})
    cp._gap(append,'instrumental_sample_not_independent_universe')

    async def quote(client, row, quantity, side, phase, snapshot):
        if side == 'sell':
            try:
                projection = observed_inventory_sell(snapshot['analysis'],quantity)
            except (ValueError,TypeError,KeyError) as error:
                reason = str(error) if isinstance(error,SnapshotEvidenceError) else 'unusable_bank_facts'
                append('quote_attempt',received_at_ms=now_ms(),mint=row['mint'],
                    outcome='unavailable',reason=reason,
                    payload={'provider':'local_observed_sell_precheck','probe_phase':phase,
                             'input_token_atomic':str(quantity),'position_acquired':False,
                             'snapshot_observation_id':snapshot['snapshot_observation_id']})
                result['sell_prechecks'].append({'phase':phase,'status':'rejected','reason':reason})
                return
            result['sell_prechecks'].append({'phase':phase,'status':'conditional',
                                            'projection':projection})
        request = f'active-exit-{phase}-{side}'
        q = await _quote_with_cancellation_receipt(client,append,
                SOL_MINT if side=='buy' else row['mint'],
                row['mint'] if side=='buy' else SOL_MINT,quantity,side,request)
        q.update(probe_phase=phase,quote_side=side,inventory_basis=plan['inventory_basis'],
                 fixed_quantity_checkpoint_id=result['fixed_quantity_checkpoint_id'])
        _record_quote(append,q,side,request)
        result['quotes'].append({k:q.get(k) for k in ('probe_phase','quote_side','outcome','reason','http_status',
             'actual_input_amount_atomic',
             'input_amount_atomic','output_amount_atomic','min_output_amount_atomic',
             'source_slot','source_time_ms','requested_at_ms','received_at_ms')})

    async def run():
        payload,received = await cp._discover(session,append)
        retained,rows,total = screening_rows(payload)
        # Only selection inputs are retained; creator text/images are not copied.
        replay_rows = [{k:row.get(k) for k in ('mint','poolId','configId','creator','createAt','mintB')}
                       if type(row) is dict else row for row in payload['data']['rows'][:100]]
        for row in replay_rows:
            if type(row) is dict and type(row.get('mintB')) is dict:
                row['mintB']={'address':row['mintB'].get('address')}
        append('discovery',received_at_ms=received,outcome='observed',
               payload={'rows':retained,'received_row_count':total,
                        'replay_selection_input':{'success':True,'data':{'rows':replay_rows}}})
        if not rows:
            cp._gap(append,'no_in_scope_screening_rows')
            return
        bank,receipt,request,_ = await _rpc(session,append,'getMultipleAccounts',
            [[r['pool'] for r in rows],{'encoding':'base64','commitment':'confirmed'}])
        append('pool_snapshot',received_at_ms=receipt,request_id=request,outcome='screening',
               payload={'requested_pool_rows':rows,'raw_rpc_result':bank})
        slot,candidates,decisions = active_pool_rows(rows,bank)
        append('checkpoint',received_at_ms=now_ms(),outcome='pool_screening_decisions',
               payload={'decisions':decisions,'universe_coverage_certified':False})
        selected = initial = None
        for row in candidates:
            addresses = addresses_from_pool(bank['value'][rows.index(row)],row['mint'],row['pool'])
            snap = await cp._snapshot(store,session,append,row,addresses,slot,'initial',
                                      evidence_profile='published_metadata_v1')
            mode = diagnostic_bank_mode(snap['analysis']) if snap else None
            if mode is not None:
                q = int(snap['analysis']['facts']['pool']['real_a'])//100
                try:
                    observed_inventory_sell(snap['analysis'],q)
                except (ValueError,TypeError,KeyError):
                    append('candidate_decision',received_at_ms=now_ms(),mint=row['mint'],
                           outcome='not_admitted',reason='observed_sell_precheck_failed',
                           payload={'snapshot_observation_id':snap['snapshot_observation_id'],
                                    'entry_permitted':False,'candidate_quantity_atomic':str(q)})
                    continue
                selected,initial = row,snap
                break
        if selected is None:
            cp._gap(append,'no_arithmetic_safe_active_bank_in_fixed_prefix')
            return
        # Fix q before any buy/sell quote. It is NOT acquired position inventory.
        pool = initial['analysis']['facts']['pool']
        quantity = int(pool['real_a'])//100
        if quantity <= 0 or int(pool['real_b']) <= 0:
            cp._gap(append,'active_inventory_disappeared_before_quote')
            return
        result.update(selected_mint=selected['mint'],selection_mode=mode,
                      fixed_sell_quantity_atomic=str(quantity))
        result['fixed_quantity_checkpoint_id'] = append('checkpoint',received_at_ms=now_ms(),
            outcome='fixed_diagnostic_sell_quantity',mint=selected['mint'],
            payload={'input_token_atomic':str(quantity),'basis':plan['inventory_basis'],
                     'snapshot_observation_id':initial['snapshot_observation_id'],
                     'position_acquired':False,'selection_mode':mode})
        result['snapshots'].append({'slot':initial['context_slot'],'phase':'initial',
                                   'snapshot_observation_id':initial['snapshot_observation_id']})
        completed = time.monotonic_ns()
        result['creation_verified'] = await cp._creation(session,append,selected,
            signature_limit=1000,max_supported_transaction_version=1)
        client = RaydiumQuoteClient(session)
        await quote(client,selected,1000000000,'buy','initial',initial)
        await quote(client,selected,quantity,'sell','initial',initial)
        delay=max(0,15000-(time.monotonic_ns()-completed)/1000000)
        await asyncio.sleep(delay/1000)
        following = await cp._snapshot(store,session,append,selected,addresses,
            initial['context_slot'],'followup',evidence_profile='published_metadata_v1')
        if following is not None:
            result['snapshots'].append({'slot':following['context_slot'],'phase':'followup',
                'snapshot_observation_id':following['snapshot_observation_id'],
                'new_bank':following['context_slot']>initial['context_slot']})
            if following['context_slot']<=initial['context_slot']:
                cp._gap(append,'followup_slot_not_advanced',mint=selected['mint'])
                return
            # Same quantity, even if the later bank rejects it; no replacement.
            try:
                observed_inventory_sell(following['analysis'],quantity)
            except (ValueError,TypeError,KeyError):
                await quote(client,selected,quantity,'sell','followup',following)
                return
            await quote(client,selected,1000000000,'buy','followup',following)
            await quote(client,selected,quantity,'sell','followup',following)

    try:
        await asyncio.wait_for(run(),timeout=60)
    except cp.CampaignSourceStopped:
        cp._gap(append,'active_exit_stopped_after_source_error')
    except (ValueError,KeyError,TypeError,asyncio.TimeoutError,ReadOnlyPolicyError):
        cp._gap(append,'active_exit_incomplete_evidence_or_budget')
    append('checkpoint',received_at_ms=now_ms(),outcome='bounded_active_exit_closed',
           payload={'requests_used':session.requests_used,'position_acquired':False})
    result.update(requests_used=session.requests_used,elapsed_ms=(time.monotonic_ns()-mono)//1000000,
                  tail_hash=store.verify_integrity(),records=len(store.events()))
    return result


async def _capture(plan,database):
    with CaptureStore(database) as store:
        async with aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport,'_retry_connection',None)) is not bool:
                raise ReadOnlyPolicyError('Unsupported retry policy')
            transport._retry_connection=False
            return await collect_active_exit(store,cp.CampaignSession(transport,20,
                proxy_resolver=_environment_proxy),plan)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',required=True,type=Path);p.add_argument('--db',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--network',action='store_true')
    args=p.parse_args()
    if not args.network:p.error('Explicit --network required')
    if (args.plan.name.startswith('.env') or args.plan.suffix!='.json'
            or len({x.resolve() for x in (args.plan,args.db,args.output)})!=3
            or args.db.exists() or args.output.exists() or args.output.suffix!='.json'):
        p.error('New dedicated journal/report and separate JSON plan required')
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    report=asyncio.run(_capture(plan,args.db))
    atomic_write_json(args.output,report,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps({k:report[k] for k in ('selected_mint','requests_used','economic_verdict')}))


if __name__=='__main__':main()
