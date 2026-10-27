"""Offline qualification of active-exit control007; no ledger or network access.

The small fixed diagnostic sale is not the liquidation of the independent
1 SOL buy quote. Matching arithmetic never establishes a fill or future exit.
"""
import argparse
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys


def analyze(repo, result_path, bundle_path):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo))
    from bot.p3.evidence import verify_bundle
    from bot.p3.launchlab import analyze_snapshot, _pool, observed_sell_projection
    from bot.p3.quotes import RaydiumQuoteClient, SOL_MINT
    result = json.loads(result_path.read_text())
    if result['plan_sha256'] != '6639407545df5accb89f80d48fdfa91a7dcd651ab54c154138743c6c57f680e9':
        raise ValueError('Result does not belong to fixed active-exit control007')
    anchor = '2d2bf40400d62903995ad9ae0d746d5775a12decbd29819b37ea09fd505c2e0b'
    if result['tail_hash'] != anchor:
        raise ValueError('Result differs from the separately retained control007 anchor')
    bundle = verify_bundle(bundle_path, expected_tail=anchor)
    assert bundle['records'] == result['records'] == 1030
    assert bundle['plan_sha256'] == result['plan_sha256']
    events = bundle['events']
    by_id = {e['id']:e for e in events}
    checkpoint = by_id[result['fixed_quantity_checkpoint_id']]
    quantity = int(result['fixed_sell_quantity_atomic'])
    assert int(checkpoint['payload']['input_token_atomic']) == quantity
    assert checkpoint['payload']['position_acquired'] is False
    quotes = [e for e in events if e['kind'] == 'quote_attempt'
              and e['payload'].get('provider') == 'raydium_trade_api']
    assert len(quotes) == 4
    normalization_checks = []
    for e in quotes:
        p = e['payload']; body = p['retained_sanitized_response']
        serialized = json.dumps(body, sort_keys=True, allow_nan=False).encode()
        assert hashlib.sha256(serialized).hexdigest() == p['sanitized_response_sha256']
        replay = {'input_mint':p['input_mint'], 'output_mint':p['output_mint'],
            'input_amount_atomic':p['input_amount_atomic'], 'slippage_bps':p['slippage_bps'],
            'outcome':'error', 'reason':None, 'output_amount_atomic':None,
            'actual_input_amount_atomic':None, 'min_output_amount_atomic':None,
            'route':[], 'fee_details':{'route_fees':[]}, 'price_impact_pct':None,
            'quality_flags':[], 'source_slot':None, 'source_time_ms':None}
        RaydiumQuoteClient._parse(deepcopy(body), replay)
        fields = ('outcome','reason','output_amount_atomic','actual_input_amount_atomic',
                  'min_output_amount_atomic','route','price_impact_pct','source_slot','source_time_ms')
        assert all(replay[key] == p[key] for key in fields)
        assert replay['fee_details']['route_fees'] == p['fee_details']['route_fees']
        assert checkpoint['available_at_ms'] <= p['requested_at_ms']
        normalization_checks.append({'observation_id':e['id'], 'phase':p['probe_phase'],
            'side':p['quote_side'], 'http_status':p['http_status'], 'outcome':p['outcome'],
            'retained_body_digest_verified':True, 'normalization_reproduced':True,
            'source_slot':p['source_slot'], 'source_time_ms':p['source_time_ms']})
    analyses = {e['payload']['snapshot_observation_id']:e['payload']['analysis']
                for e in events if e['kind'] == 'candidate_decision' and 'analysis' in e['payload']}
    phases = []
    for state in result['snapshots']:
        e = by_id[state['snapshot_observation_id']]; p = e['payload']; raw = p['raw_rpc_result']
        accounts = dict(zip(p['requested_addresses'], raw['value']))
        replay = analyze_snapshot(accounts, context_slot=raw['context']['slot'],
            expected_mint=result['selected_mint'], pool_address=p['addresses']['pool'],
            input_lamports=1_000_000_000, evidence_profile=p['evidence_profile'])
        assert replay == analyses[e['id']]
        facts = replay['facts']; pool, _ = _pool(accounts[p['addresses']['pool']])
        rates = tuple(int(value) for value in (facts['config']['trade_fee_rate_ppm'],
            facts['platform']['platform_fee_rate_ppm'], facts['platform']['creator_fee_rate_ppm']))
        estimate = observed_sell_projection(pool, input_token_atomic=quantity,
            fee_rates_ppm=rates, quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
            curve_type=int(facts['config']['curve_type']))
        phase_quotes = {q['payload']['quote_side']:q for q in quotes if q['payload']['probe_phase'] == state['phase']}
        buy, sell = phase_quotes['buy']['payload'], phase_quotes['sell']['payload']
        assert (buy['input_mint'], buy['output_mint']) == (SOL_MINT, result['selected_mint'])
        assert (sell['input_mint'], sell['output_mint']) == (result['selected_mint'], SOL_MINT)
        assert all(len(q['route']) == 1 and q['route'][0]['poolId'] == p['addresses']['pool']
                   for q in (buy, sell))
        assert int(sell['actual_input_amount_atomic']) == int(sell['input_amount_atomic']) == quantity
        assert buy['actual_input_amount_atomic'] == buy['input_amount_atomic'] == '1000000000'
        assert estimate['output_lamports'] == sell['output_amount_atomic']
        retained_check = next(x for x in result['sell_prechecks'] if x['phase'] == state['phase'])
        assert estimate == retained_check['projection']
        # Independent invariant-residual calculation: reserve left after a sale.
        x, y = pool['virtual_a']-pool['real_a'], pool['virtual_b']+pool['real_b']
        gross = y-math.ceil(Fraction(x*y, x+quantity))
        fee = math.ceil(Fraction(gross*sum(rates), 1_000_000))
        assert gross == int(estimate['gross_output_lamports'])
        assert fee == int(estimate['curve_fee_lamports'])
        assert gross-fee == int(sell['output_amount_atomic'])
        expected, minimum = int(buy['output_amount_atomic']), int(buy['min_output_amount_atomic'])
        with localcontext() as context:
            context.prec = 30
            expected_percent = str(Decimal(quantity)*100/Decimal(expected))
            minimum_percent = str(Decimal(quantity)*100/Decimal(minimum))
        phases.append({'phase':state['phase'], 'snapshot_id':e['id'], 'slot':raw['context']['slot'],
            'snapshot_analysis_reproduced':True,
            'supply_consistency':facts['supply_consistency'],
            'all_public_PDA_checks_pass':facts['identity_certification']['program_derived_addresses_verified'],
            'observed_net_curve_tokens_sold_atomic':str(pool['real_a']),
            'spendable_quote_vault_lamports':estimate['spendable_quote_vault_lamports'],
            'diagnostic_sell_input_atomic':str(quantity), 'diagnostic_sell_output_lamports':sell['output_amount_atomic'],
            'independent_gross_sell_lamports':str(gross), 'independent_curve_fee_lamports':str(fee),
            'independent_curve_calculation_matches_provider':True,
            'both_provider_routes_use_observed_pool':True,
            'buy_expected_output_atomic':str(expected), 'buy_minimum_output_atomic':str(minimum),
            'diagnostic_sale_vs_buy_expected_percent':expected_percent,
            'diagnostic_sale_vs_buy_minimum_percent':minimum_percent,
            'diagnostic_sale_covers_whole_independent_buy':quantity >= expected,
            'uncovered_buy_expected_quantity_atomic':str(expected-quantity),
            'quantity_fixed_before_snapshot':checkpoint['available_at_ms'] <= e['received_at_ms'],
            'blocking_reasons':replay['blocking_reasons']})
    assert len(phases) == 2 and phases[1]['slot'] > phases[0]['slot']
    assert result['position_acquired'] is result['execution_verified'] is result['strict_exit_qualified'] is False
    assert result['net_pnl_lamports'] is None
    return {'schema':'p3-active-exit-007-offline-analysis-v1', 'data_kind':'market_observation',
        'bundle_records':bundle['records'], 'tail_hash':bundle['tail_hash'],
        'mint':result['selected_mint'], 'requests_in_control':result['requests_used'],
        'analysis_network_requests':0, 'provider_quote_bodies_replayed':len(quotes),
        'normalization_checks':normalization_checks, 'phase_checks':phases,
        'indicative_sell_quotes_available':2, 'full_buy_quantity_exit_quotes':0,
        'qualified_economic_cycles':0, 'positions_acquired':0, 'net_pnl_lamports':None,
        'creation_verified':result['creation_verified'], 'strict_exit_qualified':False,
        'economic_verdict':'INSUFFICIENT DATA',
        'interpretation':'Two small fixed-size current-state sale estimates are available and match retained curve arithmetic. Their quantity is a small fraction of the independent 1 SOL buy estimate; no full-position liquidation, future exit or net return is established.',
        'remaining_limits':['quote source timestamps and slots absent', 'creation transaction not verified in control',
            'network/priority/ATA/failure costs unknown', 'no inventory acquired',
            'one selected market case is not strategy expectancy evidence']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--result', type=Path)
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args(); repo = args.repo.resolve()
    report = analyze(repo, args.result or repo/'validation/P3_ACTIVE_EXIT_007.json',
                     args.bundle or repo/'evidence/p3/active_exit_007')
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))

if __name__ == '__main__':
    main()
