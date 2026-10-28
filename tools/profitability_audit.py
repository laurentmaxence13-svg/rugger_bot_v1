"""Read-only profitability readiness audit of retained Rugger PAPER evidence.

This tool reports the evidentiary state; it never promotes a strategy, mutates
positions, opens a wallet or contacts an endpoint. In particular, synthetic
fixtures and conditional model proceeds cannot establish market profitability.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path


def _nonnegative_int(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f'{field} must be a nonnegative integer')
    return value


def _read_json(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def audit(positions, market_eval, ab_summary, p3_009, *, p3_010_evidence_present=False):
    """Derive exact arithmetic and fail-closed profitability gates from sources."""
    if any(type(x) is not dict for x in (positions, market_eval, ab_summary, p3_009)):
        raise ValueError('four JSON evidence objects are required')
    if positions.get('schema') != 'p3-archived-position-size-study-v1':
        raise ValueError('unknown position evidence schema')
    if market_eval.get('schema') != 'rugger-atomic-market-evaluation-v1':
        raise ValueError('unknown economic evidence schema')
    if ab_summary.get('schema') != 'master-v2-fixture-measurements-v1':
        raise ValueError('unknown A/B evidence schema')
    if p3_009.get('schema') != 'p3-active-cohort-result-v1':
        raise ValueError('unknown P3-009 evidence schema')
    if type(p3_010_evidence_present) is not bool:
        raise ValueError('P3-010 evidence presence must be explicitly verified')
    rows = positions.get('initial_bank_rows')
    if type(rows) is not list or not rows:
        raise ValueError('initial retained model rows must be present')
    evaluated = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise ValueError('malformed position row')
        try:
            spent = int(row['entry_lamports'])
            received = int(row['immediate_sell_net_of_curve_lamports'])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f'malformed position amounts at index {index}') from None
        if spent <= 0 or received < 0 or spent >= 2**64 or received >= 2**64:
            raise ValueError('position amounts outside supported domain')
        if str(spent) != row['entry_lamports'] or str(received) != row['immediate_sell_net_of_curve_lamports']:
            raise ValueError('position amount is not a canonical integer string')
        # No floats: atomic lamports remain exact and original source rows untouched.
        evaluated.append((spent, received, received - spent))
    strict = _nonnegative_int(positions.get('strict_economic_cycles'), 'position strict cycles')
    if strict != _nonnegative_int(market_eval.get('qualified_economic_cycles'), 'market eval cycles'):
        raise ValueError('strict cycle count disagrees across retained source artifacts')
    if type(ab_summary.get('market_advantage_verified')) is not bool or type(ab_summary.get('promotion_allowed')) is not bool:
        raise ValueError('explicit A/B proof flags required')
    ab_market = ab_summary.get('data_kind') == 'market_observation' and ab_summary['market_advantage_verified']
    # This is deliberately not an activation decision; further independent
    # verification of holdout provenance, costs, and confidence is required.
    pnl = positions.get('net_market_pnl_sol')
    verified_pnl = pnl is not None and strict > 0
    if pnl is not None:
        try:
            if not Decimal(str(pnl)).is_finite():
                raise ValueError('nonfinite market P&L')
        except Exception:
            raise ValueError('invalid market P&L') from None
    model_nets = [x[2] for x in evaluated]
    request_count = _nonnegative_int(p3_009.get('requests_used'), 'P3-009 request count')
    market_009_quotes = _nonnegative_int(p3_009.get('provider_quotes'), 'P3-009 quotes')
    result = {
        'schema': 'rugger-profitability-evidence-audit-v1',
        'scope': 'read_only_snapshot_of_published_evidence_no_trading_authorization',
        'economic_conclusion': 'NOT_DEMONSTRATED' if not (verified_pnl and ab_market) else 'REQUIRES_INDEPENDENT_REVIEW',
        'real_trading_authorized': False,
        'active_policy_promoted': False,
        'p3_strict_market_cycles': strict,
        'market_net_pnl_sol': str(pnl) if verified_pnl else None,
        'master_market_advantage_verified': ab_market,
        'ab_source_kind': ab_summary.get('data_kind'),
        'model': {
            'retained_initial_rows': len(rows),
            'archived_size_cases_reported': _nonnegative_int(positions.get('admissible_model_cases'), 'model cases'),
            'distinct_mints_reported': _nonnegative_int(positions.get('distinct_mints'), 'mints'),
            'sessions_reported': _nonnegative_int(positions.get('capture_sessions'), 'sessions'),
            'negative_initial_rows': sum(x < 0 for x in model_nets),
            'nonnegative_initial_rows': sum(x >= 0 for x in model_nets),
            'minimum_conditional_roundtrip_net_sol': str(Decimal(min(model_nets)) / Decimal(1_000_000_000)),
            'maximum_conditional_roundtrip_net_sol': str(Decimal(max(model_nets)) / Decimal(1_000_000_000)),
            'cost_scope': 'curve_only_additional_execution_costs_unknown',
            'realized_pnl': False,
        },
        'p3_009': {
            'requests': request_count,
            'provider_quotes': market_009_quotes,
            'discovery_universe_known': p3_009.get('discovery_universe_known') is True,
        },
        'p3_010_manifest_exists_unverified': p3_010_evidence_present,
        'blockers': [
            *(['P3_010_EVIDENCE_NOT_PUBLISHED'] if not p3_010_evidence_present else []),
            *(['NO_STRICT_QUALIFIED_MARKET_CYCLE'] if strict == 0 else []),
            *(['MARKET_NET_PNL_UNKNOWN'] if not verified_pnl else []),
            *(['NO_INDEPENDENT_MASTER_HOLDOUT_ADVANTAGE'] if not ab_market else []),
        ],
        'next_required_evidence': 'independent_prospective_exact_size_buy_sell_quotes_costs_and_causal_decisions',
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--positions', default='validation/P3_POSITION_SIZE_SUMMARY.json')
    parser.add_argument('--market-eval', default='validation/P3_ATOMIC_MARKET_EVALUATION.json')
    parser.add_argument('--ab-summary', default='validation/master_v2/COMPARISON_SUMMARY.json')
    parser.add_argument('--p3-009', default='validation/p3_active_cohort_009/RESULT.json')
    parser.add_argument('--p3-010-manifest', default='evidence/p3/active_cohort_010/manifest.json')
    parser.add_argument('--output', help='Optional report file (otherwise stdout)')
    args = parser.parse_args()
    report = audit(*(_read_json(path) for path in
        (args.positions, args.market_eval, args.ab_summary, args.p3_009)),
        p3_010_evidence_present=Path(args.p3_010_manifest).is_file())
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + '\n'
    if args.output:
        Path(args.output).write_text(rendered, encoding='utf-8')
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
