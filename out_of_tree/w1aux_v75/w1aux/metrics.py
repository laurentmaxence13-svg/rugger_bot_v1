"""W1 descriptive metrics, defined BEFORE the data (note J_METRIQUES_DESCRIPTIVES_W1, anchored by R02).

DESCRIPTIVE ONLY: the W1 decision is evaluate_w1's (WAIT_* = NOT CONCLUSIVE, NO_GO = NEGATIVE,
CHALLENGER_FOR_W2 = POSITIVE TO CONFIRM on W2, never a LIVE authorisation). This module reads only
the anchored outputs of dayj (bundles checked against SHA256SUMS, w1_report.json, ledger.json),
rewrites nothing, and applies the frozen formulas: net return r = pnl / (spent + tx_costs +
failed_attempt_costs) on closed cycles, pessimistic mean with non-valued cycles at -100 %,
bootstrap CI by creator (validation.bootstrap_mean_ci, B = 10 000, seed 20261108). Population: the
evaluation pools of w1_eval.w1_split on the M1 pools (the decision's population), for every arm.
A metric that cannot be computed is published as None with its reason. Offline, no network.
"""
import argparse
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

LAMPORTS_PER_SOL = 1_000_000_000
SEED = 20261108
N_BOOT = 10_000
QUANTILES = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
V2_ARMS = ('P1', 'P2', 'S1', 'S2', 'S3')
L1_ARMS = (('M1', 'L1', 'master'), ('P1b', 'L1', 'placebo_random'), ('L1_reference', 'L1', 'reference'))
SENSITIVITIES = (('M1_latency10', 'M1_latency10', 'master'), ('M1_failed_fee_105000', 'L1_failed_fee_105000', 'master'),
                 ('M1_event_horizon', 'L1_event_horizon', 'master'),
                 ('P1b_event_horizon', 'L1_event_horizon', 'placebo_random'))


class MetricsError(RuntimeError):
    pass


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _bundle(bundles_dir, trial_id, sums):
    data = (Path(bundles_dir) / f'{trial_id}.json.gz').read_bytes()
    if _sha_bytes(data) != sums.get(trial_id):
        raise MetricsError(f'bundle_file_changed:{trial_id}')
    return json.loads(gzip.decompress(data))


def _rows(bundle, arm=None):
    """(pool, created_slot, creator, signed, trade row) of every pool of a bundle."""
    out = []
    for p in bundle['pools']:
        if arm is None:                                   # V2 bundle
            out.append((p['pool'], p['created_slot'], p['creator'], p['signed_creator_verified'], p['trade']))
        else:                                             # L1 bundle
            out.append((p['pool'], p['creation_slot'], p['creator'], p['signed_creator_verified'], p['arms'][arm]))
    return out


def _quantile(sorted_values, q):
    """Linear interpolation between closest ranks (numpy 'linear' definition)."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def arm_metrics(rows, population, fees_by_pool, n_boot=N_BOOT):
    from bot.master_v2.validation import bootstrap_mean_ci
    wanted = set(population)
    rows = [r for r in rows if r[0] in wanted]
    entered = [r for r in rows if r[4]['entry_index'] is not None]
    closed = [r for r in entered if r[4]['outcome'] == 'closed']
    non_valued = {}
    for r in entered:
        if r[4]['outcome'] != 'closed':
            non_valued[r[4]['outcome']] = non_valued.get(r[4]['outcome'], 0) + 1
    cost = lambda t: t['spent'] + t['tx_costs'] + t['failed_attempt_costs']          # noqa: E731
    returns = [r[4]['pnl_lamports'] / cost(r[4]) for r in closed]
    pnl = [r[4]['pnl_lamports'] for r in closed]
    gross, gross_missing = 0, 0
    for r in closed:
        fees = fees_by_pool.get(r[0])
        if fees is None:
            gross_missing += 1
        else:
            gross += r[4]['pnl_lamports'] + fees + r[4]['tx_costs'] + r[4]['failed_attempt_costs']
    ordered = sorted(returns)
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    worst = ordered[:math.ceil(0.05 * len(ordered))] if ordered else []
    cumulative, peak, drawdown = 0, 0, 0
    for r in sorted(closed, key=lambda r: (r[4]['exit_slot'] if r[4]['exit_slot'] is not None else -1, r[0])):
        cumulative += r[4]['pnl_lamports']
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    positive = sorted((x for x in pnl if x > 0), reverse=True)
    by_pool = sorted(((r[4]['pnl_lamports'], r[0]) for r in closed), reverse=True)
    creators = sorted({r[2] for r in closed if r[3] and r[2]})
    return dict(
        entered=len(entered), closed=len(closed), non_valued=dict(sorted(non_valued.items())),
        independent_creators=len(creators),
        pnl_net_sol=sum(pnl) / LAMPORTS_PER_SOL if closed else None,
        pnl_gross_sol=(gross / LAMPORTS_PER_SOL) if closed and not gross_missing else None,
        pnl_gross_missing_decomposition=gross_missing,
        mean_return=(sum(returns) / len(returns)) if returns else None,
        pessimistic_mean=((sum(returns) - (len(entered) - len(closed))) / len(entered)) if entered else None,
        win_rate=(len(wins) / len(returns)) if returns else None,
        mean_gain=(sum(wins) / len(wins)) if wins else None,
        mean_loss=(sum(losses) / len(losses)) if losses else None,
        quantiles={f'q{int(q * 100):02d}': _quantile(ordered, q) for q in QUANTILES} if ordered else None,
        min_return=ordered[0] if ordered else None, max_return=ordered[-1] if ordered else None,
        losses_le_minus_50pct=sum(1 for x in returns if x <= -0.5),
        losses_le_minus_90pct=sum(1 for x in returns if x <= -0.9),
        cvar_5pct=(sum(worst) / len(worst)) if worst else None,
        max_drawdown_sol=drawdown / LAMPORTS_PER_SOL if closed else None,
        drawdown_note='fixed 0.1 SOL per cycle, no simultaneous exposure modelled: not a portfolio drawdown',
        concentration=dict(
            positive_pnl_share_top1=(sum(positive[:1]) / sum(positive)) if positive else None,
            positive_pnl_share_top5=(sum(positive[:5]) / sum(positive)) if positive else None,
            positive_pnl_share_top10=(sum(positive[:10]) / sum(positive)) if positive else None,
            pnl_net_sol_without_top5_pools=(sum(x for x, _p in by_pool[5:]) / LAMPORTS_PER_SOL) if closed else None),
        ci95_creator=(list(bootstrap_mean_ci(returns, [r[2] for r in closed], n_boot=n_boot, seed=SEED))
                      if len(returns) >= 2 else None),
        returns_by_pool={r[0]: ret for r, ret in zip(closed, returns)})


def compute(out_dir, s0, *, n_boot=N_BOOT):
    from bot.master_v2 import w1_eval
    from bot.master_v2 import w1_run
    out_dir = Path(out_dir)
    bundles_dir = out_dir / 'run' / 'bundles'
    raw_sums = (bundles_dir / 'SHA256SUMS.json').read_bytes()
    sums = json.loads(raw_sums)
    report_raw = (out_dir / 'run' / 'w1_report.json').read_bytes()
    ledger_raw = (out_dir / 'ledger' / 'ledger.json').read_bytes()
    report, ledger = json.loads(report_raw), json.loads(ledger_raw)
    if ledger.get('verdict') != 'PASS':
        raise MetricsError('ledger_verdict_not_pass')
    plan = w1_run.plan(s0)
    l1 = _bundle(bundles_dir, 'L1', sums)
    m1_rows = _rows(l1, 'master')
    split = w1_eval.w1_split([dict(pool=r[0], created_slot=r[1]) for r in m1_rows],
                             start=plan['evaluation'][0], end=plan['evaluation'][1], embargo_slots=w1_run.EMBARGO_SLOTS)
    fees = {}
    for e in ledger['entries']:
        d = e.get('decomposition')
        if d:
            fees[(e['trial'], e['arm'], e['pool'])] = d['launchlab_buy_fee'] + d['launchlab_sell_fee']

    def fees_for(trial_id, arm):
        return {pool: f for (t, a, pool), f in fees.items() if t == trial_id and a == arm}
    arms, populations = {}, {'all': split['all'], 'A': split['A'], 'B': split['B']}
    for name, trial_id, arm in L1_ARMS:
        rows = _rows(l1, arm)
        arms[name] = {period: arm_metrics(rows, pools, fees_for(trial_id, arm), n_boot)
                      for period, pools in populations.items()}
    for trial_id in V2_ARMS:
        bundle = _bundle(bundles_dir, trial_id, sums)
        rows = _rows(bundle)
        arms[trial_id] = {period: arm_metrics(rows, pools, fees_for(trial_id, bundle['policy']), n_boot)
                          for period, pools in populations.items()}
        del bundle
    sensitivities = {}
    for name, trial_id, arm in SENSITIVITIES:
        bundle = _bundle(bundles_dir, trial_id, sums)
        sensitivities[name] = arm_metrics(_rows(bundle, arm), split['all'], fees_for(trial_id, arm), n_boot)
        del bundle
    m1, s2 = arms['M1']['all'], arms['S2']['all']
    common = sorted(set(m1['returns_by_pool']) & set(s2['returns_by_pool']))
    diffs = [m1['returns_by_pool'][p] - s2['returns_by_pool'][p] for p in common]
    comparisons = {other: dict(
        mean_return_difference=(m1['mean_return'] - arms[other]['all']['mean_return'])
        if m1['mean_return'] is not None and arms[other]['all']['mean_return'] is not None else None,
        pnl_net_sol_difference=(m1['pnl_net_sol'] - arms[other]['all']['pnl_net_sol'])
        if m1['pnl_net_sol'] is not None and arms[other]['all']['pnl_net_sol'] is not None else None)
        for other in ('S2', 'S1', 'P1b', 'P1', 'P2', 'S3', 'L1_reference')}
    comparisons['M1_vs_S2_common_pools'] = dict(pools=len(common),
                                                 mean_difference=(sum(diffs) / len(diffs)) if diffs else None)
    for period in arms.values():
        for metrics in period.values():
            metrics.pop('returns_by_pool')
    for metrics in sensitivities.values():
        metrics.pop('returns_by_pool')
    return dict(schema='rugger-w1-descriptive-metrics-v1', category='HISTORICAL_REPLAY', status='DESCRIPTIVE_ONLY',
                w1_decision=report['decision'], w1_decision_reasons=report.get('decision_reasons'),
                economic_verdict={'WAIT': 'NOT_CONCLUSIVE', 'NO_GO': 'NEGATIVE',
                                  'CHALLENGER_FOR_W2': 'POSITIVE_TO_CONFIRM_ON_W2'}.get(
                                      report['decision'].split('_')[0] if report['decision'].startswith('WAIT')
                                      else report['decision']),
                population=dict(rule='w1_eval.w1_split(M1 pools, evaluation range, embargo 4513)',
                                all=len(split['all']), A=len(split['A']), B=len(split['B'])),
                arms=arms, sensitivities=sensitivities, comparisons=comparisons,
                inputs_sha256=dict(sha256sums=_sha_bytes(raw_sums), w1_report=_sha_bytes(report_raw),
                                   ledger=_sha_bytes(ledger_raw)),
                flags=dict(master_operational_trade=False, live_authorisation=False, decision_changed=False),
                note='descriptive metrics never change the frozen W1 decision; a positive result is not a guarantee '
                     'of future profitability')


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    p = argparse.ArgumentParser(description='W1 descriptive metrics (offline, read-only)')
    p.add_argument('--w1-dir', type=Path, required=True, help='the dayj output directory')
    p.add_argument('--s0', type=int, required=True)
    a = p.parse_args(argv)
    target = a.w1_dir / 'metrics' / 'metrics.json'
    if target.exists():
        raise MetricsError('output_exists:metrics.json')
    doc = compute(a.w1_dir, a.s0)
    target.parent.mkdir()
    data = json.dumps(doc, indent=1, sort_keys=True, allow_nan=False).encode() + b'\n'
    target.write_bytes(data)
    out.write(json.dumps(dict(metrics_sha256=_sha_bytes(data), w1_decision=doc['w1_decision'],
                              economic_verdict=doc['economic_verdict']), sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
