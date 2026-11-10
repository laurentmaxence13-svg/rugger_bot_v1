"""Evaluation of plan V3-P0-EXPLO-1 from the trial bundles (no replay, no data file is read).

Everything reported is EXPLORATORY research on P0 visible pools. The verdict of each hypothesis is
computed from the criteria written in ``plan.HYPOTHESES`` before any replay; nothing here can
promote a policy. Definitions:

* ``r``: net return of a closed cycle, ``pnl_lamports / (spent + tx_costs + failed_attempt_costs)``
  (the frozen formula); ``-1`` for an entered position that is not a closed cycle (pessimistic).
* ``cost0``: instant round-trip cost of the entry (buy then sell at once on the state our own buy
  left, both transaction costs included), as a return on the same denominator; ``drift = r - cost0``
  is what the market did during the hold. Closed cycles only.
* CVaR 5 %: mean of the ``ceil(5 % n)`` worst ``r``.
* Intervals: creator-cluster percentile bootstrap, the algorithm of the frozen ``bootstrap_mean_ci``.
* Deflated Sharpe ratio: PSR against the expected maximum Sharpe of N unskilled trials, with
  N = 25 (P0 registry) + EVERY entry of the V3 registry, whatever its pack (R02 F-1: a second pack
  never resets the count); the spread is that of the trial Sharpe ratios available (V3 trials of
  this pack on the exploration segment, plus P0 ones when supplied). Descriptive (R02 B-6).
* ``global_holm_descriptive``: Holm over the five decisions (H1, the three H2 candidates, H3). It
  does not change a verdict, which follows the pre-registered criteria only.
"""
from collections import Counter, OrderedDict
import json
import math
from pathlib import Path
import random
import statistics

from bot.master_v2 import registry
from bot.master_v2.challengers import veto_partition
from bot.master_v2.validation import EULER_GAMMA, probabilistic_sharpe_ratio, sharpe_ratio
from bot.p4 import historical_research_replay as hrr

from v3lab import plan

SCHEMA = 'rugger-master-v3-evaluation-v1'
# Biases every report of this plan must carry (RUGGER 02, audit 548b2716).
BIASES = (
    'B-1: the hypotheses were formed after 25 trials and deliverable G on the same pools: p-values are '
    'nominal and optimistic',
    'B-2: up to about 23 % risk of at least one false PASS over the five decisions',
    'B-3: H1 is confounded by the launch type correlated with the fee tier',
    'B-4: an exit chosen from the probe is legitimate only on a fresh window (W2)',
    'B-5: non-closed positions are counted -1 (a convention, not a measurement)',
    'B-6: the deflated Sharpe ratio is descriptive',
    'B-7: low power (a few hundred pools, 12.85 h)',
    'B-8: cycles cluster by creator; intervals resample creators, the permutation test of H1 does not',
)
HORIZONS_S = (10, 25, 60, 120, 300, 600, 900)
MFE_LEVELS = (0.0, 0.10, 0.25, 0.50, 1.00)
_NORMAL = statistics.NormalDist()


def _cost(trade):
    return trade['spent'] + trade['tx_costs'] + trade['failed_attempt_costs']


def _entered(bundle, pools):
    return {row['pool']: row for row in bundle['pools']
            if row['pool'] in pools and row['trade']['entry_index'] is not None}


def _r(row):
    trade = row['trade']
    return trade['pnl_lamports'] / _cost(trade) if trade['outcome'] == 'closed' else -1.0


def cluster_bootstrap_means(values, groups, *, n_boot, seed):
    """Sorted bootstrap means; same resampling as the frozen ``bootstrap_mean_ci`` (whole creators)."""
    by_group = OrderedDict()
    for value, group in zip(values, groups):
        by_group.setdefault(group, []).append(value)
    clusters = list(by_group.values())
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [value for _k in range(len(clusters)) for value in clusters[rng.randrange(len(clusters))]]
        means.append(sum(sample) / len(sample))
    return sorted(means)


def _interval(means, alpha):
    n = len(means)
    return [means[int(math.floor(alpha / 2 * (n - 1)))], means[int(math.ceil((1 - alpha / 2) * (n - 1)))]]


def cvar(values, share=0.05):
    if not values:
        return None
    worst = sorted(values)[:max(1, math.ceil(share * len(values)))]
    return sum(worst) / len(worst)


def holm(pvalues):
    """Holm-adjusted p-values, in the input order (None stays None and is not counted)."""
    order = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    adjusted, running = [None] * len(pvalues), 0.0
    for rank, (p, i) in enumerate(order):
        running = max(running, min(1.0, (len(order) - rank) * p))
        adjusted[i] = running
    return adjusted


def expected_max_sharpe_n(spread, n):
    """Expected maximum Sharpe of ``n`` unskilled trials with that spread (Bailey and Lopez de Prado, 2014)."""
    if n < 2:
        raise ValueError('at_least_two_trials_required')
    return spread * ((1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / n) + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (n * math.e)))


def arm_metrics(bundle, pools, *, n_boot=plan.N_BOOT, seed=plan.SEED, alpha=plan.ALPHA):
    entered = _entered(bundle, pools)
    rows = [entered[pool] for pool in sorted(entered)]
    closed = [row for row in rows if row['trade']['outcome'] == 'closed']
    returns = [_r(row) for row in closed]
    pessimistic = [_r(row) for row in rows]
    cost0 = [row['v3'].get('round_trip_cost_return') for row in closed]
    known = [(r, c) for r, c in zip(returns, cost0) if c is not None]
    metrics = dict(
        pools=len(pools), entered=len(rows), closed=len(closed),
        non_closed=dict(sorted(Counter(row['trade']['outcome'] for row in rows
                                       if row['trade']['outcome'] != 'closed').items())),
        independent_creators=len({row['creator'] for row in rows}),
        mean_return=statistics.fmean(returns) if returns else None,
        median_return=statistics.median(returns) if returns else None,
        pessimistic_mean=statistics.fmean(pessimistic) if pessimistic else None,
        win_rate=sum(r > 0 for r in returns) / len(returns) if returns else None,
        cvar_5pct=cvar(pessimistic), best_return=max(returns) if returns else None,
        worst_return=min(returns) if returns else None,
        total_pnl_sol=sum(row['trade']['pnl_lamports'] for row in closed) / 1e9,
        mean_cost0=statistics.fmean(c for _r0, c in known) if known else None,
        mean_drift=statistics.fmean(r - c for r, c in known) if known else None,
        fee_rate_ppm=dict(sorted(Counter(str(row['trade']['fee_rate_ppm']) for row in rows).items())),
        exit_triggers=dict(sorted(Counter((row['trade'].get('exit_trigger') or {}).get('reason', 'none')
                                          for row in closed).items())),
        sharpe=sharpe_ratio(returns), ci95_creator_cluster=None, p_one_sided_vs_zero=None)
    if len(pessimistic) >= 2:
        means = cluster_bootstrap_means(pessimistic, [row['creator'] for row in rows], n_boot=n_boot, seed=seed)
        metrics['ci95_creator_cluster'] = _interval(means, alpha)
        metrics['p_one_sided_vs_zero'] = (sum(m <= 0 for m in means) + 1) / (n_boot + 1)
    return metrics


def by_fee_tier(bundle, pools):
    """Closed cycles of one arm by the fee rate applied to our fills: count, mean r, cost0 and drift (R02 B-3)."""
    tiers = {}
    for row in _entered(bundle, pools).values():
        if row['trade']['outcome'] == 'closed' and row['v3'].get('round_trip_cost_return') is not None:
            tiers.setdefault(row['trade']['fee_rate_ppm'], []).append((_r(row), row['v3']['round_trip_cost_return']))
    return {str(rate): dict(closed=len(values), mean_return=statistics.fmean(r for r, _c in values),
                            mean_cost0=statistics.fmean(c for _r0, c in values),
                            mean_drift=statistics.fmean(r - c for r, c in values))
            for rate, values in sorted(tiers.items())}


def paired(base, candidate, pools, *, n_boot=plan.N_BOOT, seed=plan.SEED, alpha=plan.ALPHA):
    """H2: per-pool difference of ``r`` between two exit rules on the same entries."""
    b, c = _entered(base, pools), _entered(candidate, pools)
    both = sorted(set(b) & set(c))
    moved = [pool for pool in both if (b[pool]['trade']['entry_index'], b[pool]['trade']['entry_slot'])
             != (c[pool]['trade']['entry_index'], c[pool]['trade']['entry_slot'])]
    if moved:
        raise ValueError('paired_arms_do_not_share_their_entries:%d' % len(moved))
    diffs = [_r(c[pool]) - _r(b[pool]) for pool in both]
    out = dict(paired=len(both), only_base=len(set(b) - set(c)), only_candidate=len(set(c) - set(b)),
               mean_diff=statistics.fmean(diffs) if diffs else None, ci95_creator_cluster=None, p_one_sided=None,
               cvar_5pct_base=cvar([_r(b[pool]) for pool in both]),
               cvar_5pct_candidate=cvar([_r(c[pool]) for pool in both]))
    if len(diffs) >= 2:
        means = cluster_bootstrap_means(diffs, [b[pool]['creator'] for pool in both], n_boot=n_boot, seed=seed)
        out['ci95_creator_cluster'] = _interval(means, alpha)
        out['p_one_sided'] = (sum(m <= 0 for m in means) + 1) / (n_boot + 1)
    return out


def probe(bundle, pools):
    """V3-06 (descriptive): best and worst exact liquidation value after entry, and the horizon curve.

    The values at a horizon ignore the sale latency (a few slots): they describe the path, they are
    not the result of an exit rule and never a candidate.
    """
    rows = [row for row in _entered(bundle, pools).values() if row['v3'].get('immediate_mark') is not None]
    if not rows:
        return dict(entered=0)
    mfe, mae, peak_age, horizon = [], [], [], {h: [] for h in HORIZONS_S}
    for row in rows:
        block = row['v3']
        cost = block['cost_lamports']                    # amount spent plus both transaction costs
        points = [(0, block['immediate_mark'])] + [tuple(p) for p in block.get('path', [])]
        value = lambda mark: (mark - cost) / cost        # noqa: E731
        best = max(points, key=lambda p: (p[1], -p[0]))
        mfe.append(value(best[1]))
        peak_age.append(best[0])
        mae.append(value(min(p[1] for p in points)))
        for h in HORIZONS_S:
            seen = [mark for age, mark in points if age <= h]
            horizon[h].append(value(seen[-1]))
    return dict(
        entered=len(rows), mfe_mean=statistics.fmean(mfe), mfe_median=statistics.median(mfe),
        mae_mean=statistics.fmean(mae), mae_median=statistics.median(mae),
        peak_age_s_median=statistics.median(peak_age),
        share_mfe_above={str(level): sum(v > level for v in mfe) / len(mfe) for level in MFE_LEVELS},
        horizon_curve={str(h): dict(mean=statistics.fmean(v), median=statistics.median(v),
                                    share_positive=sum(x > 0 for x in v) / len(v)) for h, v in horizon.items()},
        note='descriptive: liquidation value read on the recorded path, sale latency ignored')


def _sign(value):
    return value is not None and value > 0


def evaluate(bundles, *, registry_entries, p0_trial_sharpes=(), n_boot=plan.N_BOOT):
    """Report of the plan: arms, H1, H2, H3, probe and the verdicts (EXPLORATORY)."""
    manifests = {b['fixtures']['manifest_sha256'] for b in bundles.values()}
    if len(manifests) != 1:
        raise ValueError('runs_on_different_packs')
    manifest_sha256 = manifests.pop()
    if any('plan_sha256' not in e or 'trial' not in e for e in registry_entries):
        raise ValueError('not_a_v3_registry')
    registered = {e['preregistration_sha256']: e for e in registry_entries if e['manifest_sha256'] == manifest_sha256}
    given = {b['preregistration_sha256'] for b in bundles.values()}
    if given - set(registered):
        raise ValueError('unregistered_runs:%d' % len(given - set(registered)))
    if set(registered) - given:
        raise ValueError('registered_trials_missing:%d' % len(set(registered) - given))   # every trial counts
    for trial_id, bundle in bundles.items():
        entry = registered[bundle['preregistration_sha256']]
        if (bundle['trial'], entry['trial']) != (trial_id, trial_id) or bundle['plan_sha256'] != plan.plan_sha256():
            raise ValueError('bundle_is_not_this_plan_trial:%s' % trial_id)
        if (entry['code_sha256'], entry['v3lab_sha256']) != (bundle['code_sha256'], bundle['v3lab_sha256']):
            raise ValueError('code_sha256_mismatch:%s' % trial_id)
    if len({(b['code_sha256'], b['v3lab_sha256']) for b in bundles.values()}) != 1:
        raise ValueError('trials_run_on_different_code')
    segments = {}
    for bundle in bundles.values():
        for row in bundle['pools']:
            if segments.setdefault(row['pool'], row['segment']) != row['segment']:
                raise ValueError('segment_changed_between_trials')
    if set(segments.values()) - set(plan.SEGMENTS):
        raise ValueError('non_visible_segment_in_bundle')
    pools = {name: {pool for pool, segment in segments.items() if segment == name} for name in plan.SEGMENTS}
    decision = plan.DECISION_SEGMENT
    arms = {trial_id: {name: arm_metrics(bundle, pools[name], n_boot=n_boot) for name in plan.SEGMENTS}
            for trial_id, bundle in sorted(bundles.items())}
    n_cumulative = plan.P0_REGISTERED_TRIALS + len(registry_entries)     # every V3 entry, every pack (R02 F-1)
    sharpes = [arms[t]['exploration']['sharpe'] for t in arms] + list(p0_trial_sharpes)
    sharpes = [s for s in sharpes if s is not None]
    spread = statistics.pstdev(sharpes) if len(sharpes) >= 2 else None
    benchmark = expected_max_sharpe_n(spread, n_cumulative) if spread is not None else None
    for trial_id, bundle in bundles.items():
        for name in plan.SEGMENTS:
            returns = [_r(row) for row in _entered(bundle, pools[name]).values() if row['trade']['outcome'] == 'closed']
            arms[trial_id][name]['dsr_cumulative_n'] = (
                probabilistic_sharpe_ratio(returns, benchmark) if benchmark is not None and len(returns) >= 3 else None)
    report = dict(schema=SCHEMA, plan=plan.PLAN['plan'], plan_sha256=plan.plan_sha256(), status='EXPLORATORY',
                  manifest_sha256=manifest_sha256, registry_head=registry_entries[-1]['entry_sha256'],
                  v3_trials=len(registered), v3_trials_all_packs=len(registry_entries),
                  n_cumulative=n_cumulative, biases=list(BIASES),
                  dsr_benchmark=dict(spread=spread, expected_max_sharpe=benchmark, sharpes_used=len(sharpes),
                                     p0_sharpes_supplied=len(list(p0_trial_sharpes))),
                  segments={name: len(pools[name]) for name in plan.SEGMENTS}, arms=arms, hypotheses={})
    verdicts, decisions_p = {}, {}
    # --- H1: exact ablation of the reference by the fee veto -------------------------------------
    if {'V3-01', 'V3-07'} <= set(bundles):
        h1 = {name: veto_partition(bundles['V3-01'], bundles['V3-07'], pools[name], n_perm=n_boot, seed=plan.SEED)
              for name in plan.SEGMENTS}
        for name in plan.SEGMENTS:
            h1[name]['by_fee_tier'] = by_fee_tier(bundles['V3-01'], pools[name])
        d = h1[decision]
        decisions_p['H1'] = d['random_abstention_p']
        if d['kept_closed'] < plan.MIN_GROUP or d['removed_closed'] < plan.MIN_GROUP:
            verdict = 'NOT_EVALUABLE'
        else:
            ok = (_sign(d['kept_minus_removed']) and d['random_abstention_p'] < plan.ALPHA
                  and all(_sign(h1[name]['kept_minus_removed']) for name in plan.SEGMENTS if name != decision))
            verdict = 'PASS_EXPLORATORY' if ok else 'REJECTED_ON_P0'
        report['hypotheses']['H1'], verdicts['H1'] = h1, verdict
    # --- H2: exit rules on the same entries, Holm over the candidates ----------------------------
    candidates = [row['id'] for row in plan.TRIALS if row.get('hypothesis') == 'H2' and row['role'] == 'candidate'
                  and row['id'] in bundles]
    if 'V3-01' in bundles and candidates:
        h2 = {c: {name: paired(bundles['V3-01'], bundles[c], pools[name], n_boot=n_boot) for name in plan.SEGMENTS}
              for c in candidates}
        adjusted = holm([h2[c][decision]['p_one_sided'] for c in candidates])
        outcome = {}
        for c, p_holm in zip(candidates, adjusted):
            d = h2[c][decision]
            d['p_holm'] = p_holm
            decisions_p['H2:' + c] = d['p_one_sided']
            if d['paired'] < plan.MIN_GROUP or p_holm is None:
                outcome[c] = 'NOT_EVALUABLE'
                continue
            ok = (_sign(d['mean_diff']) and p_holm < plan.ALPHA
                  and d['cvar_5pct_candidate'] >= d['cvar_5pct_base'] - 0.10
                  and all(_sign(h2[c][name]['mean_diff']) for name in plan.SEGMENTS if name != decision))
            outcome[c] = 'PASS_EXPLORATORY' if ok else 'REJECTED_ON_P0'
        report['hypotheses']['H2'] = dict(candidates=h2, by_candidate=outcome)
        verdicts['H2'] = ('PASS_EXPLORATORY' if 'PASS_EXPLORATORY' in outcome.values() else
                          'NOT_EVALUABLE' if set(outcome.values()) == {'NOT_EVALUABLE'} else 'REJECTED_ON_P0')
    if 'V3-06' in bundles:
        report['probe'] = {name: probe(bundles['V3-06'], pools[name]) for name in plan.SEGMENTS}
    # --- H3: the selection arm alone, against zero and against the two references -----------------
    if 'V3-08' in bundles:
        d = arms['V3-08'][decision]
        if d['entered'] < plan.MIN_GROUP:
            verdict = 'NOT_EVALUABLE'
        else:
            references = [arms[t][decision]['pessimistic_mean'] for t in ('V3-01', 'V3-02') if t in arms]
            ok = (_sign(d['pessimistic_mean']) and d['ci95_creator_cluster'] is not None
                  and d['ci95_creator_cluster'][0] > 0
                  and all(ref is None or d['pessimistic_mean'] > ref for ref in references))
            verdict = 'PASS_EXPLORATORY' if ok else 'REJECTED_ON_P0'
        decisions_p['H3'] = arms['V3-08'][decision]['p_one_sided_vs_zero']
        report['hypotheses']['H3'] = {name: dict(entered=arms['V3-08'][name]['entered'],
                                                 pessimistic_mean=arms['V3-08'][name]['pessimistic_mean'],
                                                 ci95_creator_cluster=arms['V3-08'][name]['ci95_creator_cluster'])
                                      for name in plan.SEGMENTS}
        verdicts['H3'] = verdict
    names = sorted(decisions_p)
    report['global_holm_descriptive'] = dict(
        decisions=len(names), p=dict(zip(names, (decisions_p[n] for n in names))),
        p_holm=dict(zip(names, holm([decisions_p[n] for n in names]))),
        note='descriptive: Holm over all decisions of the plan; verdicts follow the pre-registered criteria only')
    report['verdicts'] = verdicts
    report['flags'] = dict(exploratory=True, promotion_allowed=False, master_operational_trade=False,
                           counted_in_master_gate=False, profitability_demonstrated=False,
                           holdout_read=False, w1_data_read=False)
    return report


def load_bundles(directory):
    bundles = {}
    for path in sorted(Path(directory).glob('V3-*.json')):
        bundle = json.loads(path.read_text(encoding='utf-8'))
        body = {k: v for k, v in bundle.items() if k != 'bundle_sha256'}
        if hrr._sha(body) != bundle.get('bundle_sha256'):
            raise ValueError('bundle_sha256_mismatch:%s' % path.name)
        bundles[bundle['trial']] = bundle
    return bundles


def evaluate_directory(directory, registry_path, *, p0_trial_sharpes=(), n_boot=plan.N_BOOT):
    return evaluate(load_bundles(directory), registry_entries=registry.load(registry_path),
                    p0_trial_sharpes=p0_trial_sharpes, n_boot=n_boot)
