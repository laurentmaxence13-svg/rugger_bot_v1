"""RUGGER 03 offline MASTER vs reference harness (SYNTHETIC journals only).

Thin audit layer over ``bot.master_comparison.evaluate_comparison``: no network,
no trade, no secret, no change to any decision rule. It adds
  * a refusal of anything that is not an explicitly synthetic journal,
  * a pre-result freeze fingerprint (plan + journal + policy hashes),
  * a lookahead audit: decisions are recomputed after corrupting every frame
    that was not yet available and must be identical,
  * a compact SOL net P&L summary with failure traces,
  * a hard refusal to declare real profitability.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from collections import Counter

from bot import master_comparison as mc
from bot import p4_experiment as p4

SCHEMA = 'rugger03-offline-harness-v1'
LAMPORTS = 10 ** 9
ARMS = ('reference', 'master')


def _sol(value):
    return None if value is None else float(value)


def _decisions(pair):
    """Decision traces per arm: frame id -> (hash of snapshot, action)."""
    out = {}
    for arm in ARMS:
        out[arm] = [(t['frame_id'], t['decision_at_ms'], p4._hash(t['decision_snapshot']))
                    for t in pair[arm]['trace']]
    return out


def _corrupt_future(journal, cutoff_ms):
    """Mutate every observation that becomes available strictly after cutoff."""
    value = deepcopy(journal)
    for frame in value['frames']:
        if frame['available_at_ms'] > cutoff_ms:
            features = frame.get('features')
            if type(features) is dict:
                if type(features.get('price_usd')) in (int, float):
                    features['price_usd'] = features['price_usd'] * 7 + 0.123
                if type(features.get('momentum_60s')) in (int, float):
                    features['momentum_60s'] = -features['momentum_60s'] - 50
            for context in frame.get('sell_contexts', []):
                payload = context.get('sell_observation', {}).get('payload', {})
                if str(payload.get('output_amount_atomic', '')).isdecimal():
                    payload['output_amount_atomic'] = str(int(payload['output_amount_atomic']) * 3 + 1)
    return value


def lookahead_audit(journal, plan):
    """Decisions at time t must not depend on observations available after t."""
    base = mc.evaluate_comparison(journal, plan)
    cutoffs = sorted({f['available_at_ms'] for f in journal['frames']})[:-1]
    violations = []
    for cutoff in cutoffs:
        other = mc.evaluate_comparison(_corrupt_future(journal, cutoff), plan)
        for left, right in zip(base['pairs'], other['pairs']):
            a, b = _decisions(left), _decisions(right)
            for arm in ARMS:
                early_a = [x for x in a[arm] if x[1] <= cutoff]
                early_b = [x for x in b[arm] if x[1] <= cutoff]
                if early_a != early_b:
                    violations.append(dict(arm=arm, cutoff_ms=cutoff, split=left['split'],
                                           fee_multiplier=left['fee_multiplier'],
                                           decision_delay_ms=left['decision_delay_ms']))
    return dict(checked_cutoffs=len(cutoffs), violations=violations, passed=not violations,
                method='recompute with all later-available prices/quotes corrupted; earlier decisions must be identical')


def _arm_summary(run):
    return dict(entered=run['entered_positions'], closed=run['closed_positions'],
                realized_pnl_sol=_sol(run['realized_pnl_sol']),
                portfolio_pnl_sol=_sol(run['portfolio_pnl_sol']),
                pnl_known=run['portfolio_pnl_sol'] is not None,
                all_liquidated=run['all_entered_positions_liquidated'],
                exit_attempts=run['exit_attempts'],
                qualification_failures=run['qualification_failures'],
                modeled_extra_costs_sol=int(run['known_modeled_extra_costs_lamports']) / LAMPORTS,
                max_realized_drawdown=run['max_realized_drawdown'])


def _failure_traces(pair):
    traces = []
    for arm in ARMS:
        for t in pair[arm]['trace']:
            snap = t['decision_snapshot']
            action = snap.get('action')
            if action in ('WAIT', 'NO_TRADE', 'WAIT_FOR_DATA') or 'refus' in str(t.get('message', '')).lower():
                traces.append(dict(arm=arm, frame_id=t['frame_id'], at_ms=t['decision_at_ms'],
                                   action=action, reason=t['decision_reason'],
                                   message=str(t.get('message', ''))[:200]))
        if pair[arm]['qualification_failures']:
            traces.append(dict(arm=arm, frame_id=None, at_ms=None, action='EXIT_QUOTE_REFUSED',
                               reason='qualification_failures=%d' % pair[arm]['qualification_failures'],
                               message='inventory kept; P&L unknown, not zero'))
    return traces


def run_harness(journal, plan):
    if type(journal) is not dict or journal.get('data_kind') != 'synthetic':
        raise ValueError('Only an explicitly synthetic journal (data_kind="synthetic") is accepted')
    if not journal.get('frames'):
        raise ValueError('Journal has no frames')
    freeze = dict(plan_sha256=p4._hash(plan), journal_sha256=p4._hash(journal),
                  master_policy_sha256=plan['master_policy_sha256'],
                  base_policy_sha256=plan['base_policy_sha256'])
    freeze['freeze_sha256'] = p4._hash(freeze)
    report = mc.evaluate_comparison(journal, plan)
    audit = lookahead_audit(journal, plan)
    scenarios = []
    for pair in report['pairs']:
        ref, mas = _arm_summary(pair['reference']), _arm_summary(pair['master'])
        both = ref['pnl_known'] and mas['pnl_known']
        wait_reasons = Counter()
        for t in pair['master']['trace']:
            if t['decision_snapshot'].get('action') == 'WAIT':
                for reason in t['decision_snapshot'].get('reasons', []):
                    wait_reasons[reason] += 1
        scenarios.append(dict(
            split=pair['split'], fee_multiplier=pair['fee_multiplier'],
            decision_delay_ms=pair['decision_delay_ms'],
            reference=ref, master=mas,
            master_minus_reference_net_sol=(mas['portfolio_pnl_sol'] - ref['portfolio_pnl_sol']) if both else None,
            known_opportunity_deltas=pair['known_opportunity_deltas'],
            unknown_opportunity_deltas=pair['unknown_opportunity_deltas'],
            master_wait_reason_counts=dict(wait_reasons),
            failure_traces=_failure_traces(pair)))
    return dict(
        schema=SCHEMA, data_kind='SYNTHETIC', synthetic_label='SYNTHETIC JOURNAL - NOT MARKET DATA',
        frozen_before_results=freeze, causality_lookahead_audit=audit,
        cost_model='identical for both arms: journal quotes, fee_multiplier and decision delay from the registered plan',
        currency='SOL', initial_capital_each_sol=10.0, scenarios=scenarios,
        real_profitability_claim='REFUSED',
        profitability_verdict='NOT_DEMONSTRATED: synthetic input cannot establish a market edge',
        network_requests=0, trades_executed=0, promotion_allowed=False,
        underlying_report_sha256=p4._hash(report))


def main(argv=None):
    os.environ['RUGGER_NO_DOTENV'] = '1'
    from bot.__main__ import _offline_policy
    sys.addaudithook(_offline_policy)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.input.is_symlink() or args.input.name.startswith('.env') or args.input.suffix != '.json'
            or args.output.exists() or args.output.suffix != '.json'):
        parser.error('Retained JSON input and new .json output required')
    data = json.loads(args.input.read_text())
    result = run_harness(data['corpus'], data['plan'])
    from bot.analyser.artifacts import atomic_write_json
    atomic_write_json(args.output, result, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps(dict(report=str(args.output), real_profitability_claim='REFUSED', network_requests=0)))


if __name__ == '__main__':
    main()
