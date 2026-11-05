"""Replay prospective008 from portable evidence, without DB or network access.

Curve-only counterfactual cash differences exclude unknown execution costs and
never become market P&L. A current bank without our buy cannot liquidate tokens
which that hypothetical buy would first introduce into its circulating supply.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys


ANCHOR = '02fcae70a4e391a493890eb29e3bd71c19a25ce26202fb9209d42cfc934f15f6'
PLAN = '33f5085fe3bd43714bec7372cd1be6848fb458e3401a70a9358553dde8128a17'
REVISION = '39fe7fd072b7076da49c88b4550cc08dcdbb57dc'


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def _subset_accounts(event, by_id):
    """Check every candidate byte against its retained shared bank context."""
    payload=event['payload']; group=by_id[payload['source_group_observation_id']]
    gp=group['payload']; bank=gp['raw_rpc_result']; subset=payload['raw_rpc_result']
    _require(group['kind']=='pool_snapshot' and gp['purpose']=='prospective_grouped_bank',
             'Candidate subset does not reference a grouped bank')
    _require(group['id']<event['id'] and group['available_at_ms']<=event['available_at_ms'],
             'Grouped bank was unavailable before its candidate subset')
    _require(event['source_slot']==group['source_slot']==bank['context']['slot']
             and subset['context']==bank['context'], 'Candidate subset context changed')
    _require(len(gp['requested_addresses'])==len(bank['value'])
             and len(set(gp['requested_addresses']))==len(bank['value']),
             'Grouped bank account alignment differs')
    accounts=dict(zip(gp['requested_addresses'],bank['value']))
    keys=payload['requested_addresses']
    _require(set(payload['addresses'].values())==set(keys)
             and len(set(keys))==len(keys)
             and subset['value']==[accounts[key] for key in keys],
             'Candidate subset bytes or account order changed')
    return {key:accounts[key] for key in keys}


def _replay_quote(event):
    from bot.p3.quotes import RaydiumQuoteClient
    p=event['payload']; body=p['retained_sanitized_response']
    _require(_digest(body)==p['sanitized_response_sha256'],'Retained quote digest differs')
    replay={key:p[key] for key in ('input_mint','output_mint','input_amount_atomic','slippage_bps')}
    replay.update(outcome='error',reason=None,output_amount_atomic=None,
        actual_input_amount_atomic=None,min_output_amount_atomic=None,route=[],
        fee_details={'route_fees':[]},price_impact_pct=None,quality_flags=[],
        source_slot=None,source_time_ms=None)
    RaydiumQuoteClient._parse(deepcopy(body),replay)
    fields=('outcome','reason','output_amount_atomic','actual_input_amount_atomic',
            'min_output_amount_atomic','route','price_impact_pct','source_slot','source_time_ms')
    _require(all(replay[key]==p[key] for key in fields)
             and replay['fee_details']['route_fees']==p['fee_details']['route_fees'],
             'Retained quote normalization differs')
    return dict(observation_id=event['id'],phase=p['probe_phase'],side=p['quote_side'],
        input_atomic=p['input_amount_atomic'],outcome=p['outcome'],reason=p['reason'],
        normalized_body_reproduced=True,source_time_ms=p['source_time_ms'],source_slot=p['source_slot'])


def analyze(repo, *, bundle_path=None, result_path=None, plan_path=None):
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(repo))
    from bot.p3.evidence import verify_bundle
    from bot.p3.prospective_report import build_prospective_report
    from bot.p3.launchlab import analyze_snapshot, _pool, observed_sell_projection, SnapshotEvidenceError
    from bot.p3.cost_evidence import classify_reference_transaction
    from bot.p3.quotes import SOL_MINT
    plan=json.loads((plan_path or repo/'benchmarks/p3_prospective_inventory_v1/plan.json').read_text())
    result=json.loads((result_path or repo/'validation/P3_PROSPECTIVE_008_REPORT.json').read_text())
    bundle=verify_bundle(bundle_path or repo/'evidence/p3/prospective_008',expected_tail=ANCHOR)
    _require(bundle['plan_sha256']==PLAN and bundle['source_revision']==REVISION
             and bundle['records']==55,'Bundle differs from retained control008 identity')
    events=bundle['events']; by_id={e['id']:e for e in events}
    replay=build_prospective_report(plan,events,integrity_verified=True,expected_tail=ANCHOR)
    _require(replay==result and replay['plan_sha256']==PLAN,'Prospective numerical report differs on replay')
    index=json.loads((repo/'evidence/p3/index.json').read_text())
    indexed=[row for row in index['bundles'] if row['run_id']=='prospective_008']
    _require(len(indexed)==1 and all(indexed[0].get(key)==bundle[key] for key in
        ('tail_hash','plan_sha256','source_revision','records','compressed_sha256','uncompressed_sha256')),
        'Evidence index does not retain the control008 anchor')
    quotes=[e for e in events if e['kind']=='quote_attempt' and e['payload'].get('provider')=='raydium_trade_api']
    quote_checks=[_replay_quote(e) for e in quotes]
    buys={e['mint']:e for e in quotes if e['payload']['quote_side']=='buy'}
    inventory={e['mint']:e for e in events if e['outcome']=='projected_inventory_fixed'}
    _require(len(buys)==len(inventory)==3 and max(e['id'] for e in buys.values())
             <min(e['id'] for e in quotes if e['payload']['quote_side']=='sell'),
             'All projected buys were not fixed before exit observations')
    analyses={e['payload']['snapshot_observation_id']:e['payload']['analysis'] for e in events
              if e['kind']=='candidate_decision' and 'analysis' in e['payload']}
    snapshots=[e for e in events if e['kind']=='pool_snapshot' and 'source_group_observation_id' in e['payload']]
    phase_checks=[]
    for event in snapshots:
        p=event['payload']; mint=event['mint']; accounts=_subset_accounts(event,by_id)
        analysis=analyze_snapshot(accounts,context_slot=event['source_slot'],expected_mint=mint,
            pool_address=p['addresses']['pool'],input_lamports=plan['input_lamports'],
            evidence_profile=p['evidence_profile'])
        _require(analysis==analyses[event['id']],'Pinned snapshot analysis differs on replay')
        pool,_=_pool(accounts[p['addresses']['pool']]); facts=analysis['facts']
        rates=tuple(int(facts[role][key]) for role,key in
            (('config','trade_fee_rate_ppm'),('platform','platform_fee_rate_ppm'),('platform','creator_fee_rate_ppm')))
        buy=buys[mint]; projected=inventory[mint]; quantity=int(projected['payload']['acquired_atomic'])
        quarter=int(projected['payload']['partial_diagnostic_atomic'])
        _require(quantity==int(buy['payload']['output_amount_atomic']) and quarter==quantity//4,
                 'Prospective full/partial quantity differs from the buy fixation')
        _require(buy['payload']['actual_input_amount_atomic']==str(plan['input_lamports'])
                 and len(buy['payload']['route'])==1
                 and buy['payload']['route'][0]['poolId']==p['addresses']['pool'],
                 'Provider buy budget or route differs from the retained pool model')
        sell_checks=[]
        for scope,amount in (('full_expected',quantity),('partial_diagnostic',quarter)):
            try:
                estimate=observed_sell_projection(pool,input_token_atomic=amount,fee_rates_ppm=rates,
                    quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
                    curve_type=int(facts['config']['curve_type']))
                refusal=None
            except SnapshotEvidenceError as error:
                estimate=None;refusal=str(error)
            matching=[e for e in quotes if e['mint']==mint and e['payload']['quote_side']=='sell'
                      and e['payload'].get('probe_phase')==p['period'] and e['payload'].get('exit_scope')==scope]
            for sell in matching:
                _require(sell['payload']['inventory_buy_observation_id']==buy['id']
                    and int(sell['payload']['input_amount_atomic'])==amount
                    and projected['id']<sell['id']
                    and projected['available_at_ms']<=sell['payload']['requested_at_ms'],
                    'Exit quantity/link was not fixed before its request')
            sell_checks.append(dict(scope=scope,input_atomic=str(amount),observed_bank_estimate=estimate,
                observed_bank_refusal=refusal,provider_observation_ids=[e['id'] for e in matching],
                hypothetical_entry_impact_applied=False))
        own=analysis['conditional_projection']; curve_difference=None
        if own is not None:
            _require(int(own['buy_output_atomic'])==quantity,'Provider buy differs from pinned curve quantity')
            curve_difference=int(own['sell_output_lamports'])-int(own['buy_input_lamports'])
        certificate=facts['identity_certification']
        phase_checks.append(dict(mint=mint,phase=p['period'],snapshot_id=event['id'],
            grouped_snapshot_id=p['source_group_observation_id'],slot=event['source_slot'],
            grouped_account_subset_reproduced=True,snapshot_analysis_reproduced=True,
            observed_outstanding_curve_tokens_atomic=str(pool['real_a']),
            observed_real_quote_reserves_lamports=str(pool['real_b']),
            observed_quote_vault_lamports=facts['quote_vault']['amount_atomic'],
            fee_rate_total_ppm=str(sum(rates)),supply_matches=facts['supply_consistency']['matches'],
            public_PDA_checks_qualified=certificate['program_derived_addresses_verified'],
            identity_unknown_reasons=certificate['blocking_reasons'],
            buy_quote_matches_pinned_local_quantity=own is not None,
            observed_state_sell_checks=sell_checks,counterfactual_own_entry=own,
            curve_only_round_trip_cash_difference_lamports=str(curve_difference) if curve_difference is not None else None,
            curve_only_round_trip_cash_difference_sol=str(Decimal(curve_difference)/Decimal(10**9)) if curve_difference is not None else None,
            additional_proceeds_needed_before_extra_costs_lamports=str(max(0,-curve_difference)) if curve_difference is not None else None,
            extra_execution_costs_unknown=True,net_economic_pnl_sol=None,
            interpretation='Counterfactual buy adds circulating tokens and reserves; the observed bank does not contain that buy.'))
    slots={phase:{x['slot'] for x in phase_checks if x['phase']==phase} for phase in ('initial','followup')}
    _require(len(phase_checks)==6 and all(len(value)==1 for value in slots.values())
             and next(iter(slots['followup']))>next(iter(slots['initial'])),'Followup bank is not strictly newer')
    wait=next(e['payload'] for e in events if e['outcome']=='followup_wait_completed')
    _require(wait['elapsed_since_initial_bank_ms']>=plan['followup_delay_ms'],'Followup horizon was too early')
    references=[]
    for event in events:
        if event['outcome']=='additional_fee_reference':
            reference=event['payload']; classification=classify_reference_transaction(by_id[reference['source_observation_id']])
            _require(classification==reference['classification'],'Reference transaction fee classification differs')
            references.append(classification)
    _require(all(e['payload']['input_mint']==SOL_MINT for e in buys.values()),'Buy was not denominated in SOL')
    sells=[e for e in quotes if e['payload']['quote_side']=='sell']
    _require(len(sells)==9 and all(e['outcome']=='unavailable' and e['reason']=='provider_rejected'
             and e['payload']['retained_sanitized_response'].get('msg')=='INSUFFICIENT_LIQUIDITY'
             for e in sells),'Control008 refusal counts differ')
    _require(all(check['observed_bank_refusal']=='sell_exceeds_observed_outstanding_curve_tokens'
             for phase in phase_checks for check in phase['observed_state_sell_checks']),
             'Not every observed bank has the same circulating-token constraint')
    return dict(schema='p3-prospective-008-offline-replay-v1',data_kind='market_observation',
        bundle_records=bundle['records'],tail_hash=ANCHOR,plan_sha256=PLAN,source_revision=REVISION,
        analysis_network_requests=0,sqlite_connections=0,report_identical_on_replay=True,
        provider_quote_bodies_replayed=len(quote_checks),quote_checks=quote_checks,
        selected_candidates=replay['selected_corpus_size'],projected_buys=len(buys),
        full_sell_refusals=replay['full_sell_observation_attempts'],
        partial_sell_refusals=replay['partial_sell_observation_attempts'],
        grouped_snapshots_verified=2,candidate_snapshot_analyses_replayed=len(phase_checks),
        measured_followup_wait_ms=wait['elapsed_since_initial_bank_ms'],phase_checks=phase_checks,
        fee_reference_classifications=references,qualified_economic_cycles=0,positions_acquired=0,
        net_economic_pnl_sol=None,execution_verified=False,economic_verdict='INSUFFICIENT DATA',
        measured_rejection='All nine provider sells were unavailable; every requested amount also exceeds observed outstanding curve tokens.',
        statistical_interpretation='Three development candidates in one session; creator claims do not establish independent trials.')


def _offline_audit(event,args):
    if event.startswith('socket.') or event=='sqlite3.connect':
        raise RuntimeError('Network and SQLite access are forbidden during portable replay')
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        path=Path(args[0].decode() if isinstance(args[0],bytes) else args[0])
        if path.name.startswith('.env') or path.suffix in ('.db','.sqlite','.sqlite3'):
            raise RuntimeError('Private configuration and database files are forbidden during portable replay')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--bundle',type=Path);parser.add_argument('--result',type=Path);parser.add_argument('--plan',type=Path)
    args=parser.parse_args();sys.addaudithook(_offline_audit)
    print(json.dumps(analyze(args.repo.resolve(),bundle_path=args.bundle,result_path=args.result,
        plan_path=args.plan),indent=2,sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
