"""Policy-agnostic statistics for MASTER V2 research (offline, pure Python, deterministic).

Inputs are closed research cycles only (``pnl_lamports`` set); open, migrated or
unpriced positions never enter these numbers and must be reported separately.

* ``cycle_metrics``: net P&L, expectancy, median, win rate, profit factor, maximum
  drawdown of the cumulative P&L in time order, tail means.
* ``bootstrap_mean_ci``: percentile bootstrap of the mean; with ``groups`` it is a
  cluster bootstrap (whole creators are resampled), because cycles of one creator
  are not independent.
* ``probabilistic_sharpe_ratio`` (Bailey and Lopez de Prado, 2012) and
  ``deflated_sharpe_ratio`` (Bailey and Lopez de Prado, 2014): probability that the
  true per-cycle Sharpe ratio exceeds a benchmark, correcting for skewness, kurtosis,
  sample length and, for the deflated version, the number of policies tried.
* ``chronological_split``: exploration / train / validation / holdout segments in
  creation order, with an embargo at each boundary and creators kept disjoint
  (a pool whose creator already appeared in an earlier segment is set aside and
  reported, never silently reused).
* ``preregistration``: canonical SHA-256 of a policy and its evaluation design,
  fixed before any holdout result is read.
"""
from collections import OrderedDict
import hashlib
import json
import math
import random
import statistics

EULER_GAMMA = 0.5772156649015329
SEGMENTS = ('exploration', 'train', 'validation', 'holdout')
_NORMAL = statistics.NormalDist()


def _require_cycles(cycles):
    for row in cycles:
        if type(row.get('pnl_lamports')) is not int:
            raise ValueError('closed_cycle_pnl_required')
        if type(row.get('cost_lamports')) is not int or row['cost_lamports'] <= 0:
            raise ValueError('positive_cost_required')


def cycle_metrics(cycles):
    """Summary of closed cycles, ordered by ``order_key`` (e.g. (exit_slot, index))."""
    _require_cycles(cycles)
    ordered = sorted(cycles, key=lambda row: row['order_key'])
    pnl = [row['pnl_lamports'] for row in ordered]
    returns = [row['pnl_lamports'] / row['cost_lamports'] for row in ordered]
    n = len(pnl)
    if not n:
        return dict(n=0, total_pnl_lamports=0, mean_pnl_lamports=None, median_pnl_lamports=None,
                    mean_return=None, win_rate=None, profit_factor=None, max_drawdown_lamports=0,
                    worst_decile_mean_return=None, best_decile_mean_return=None)
    wins = sum(value for value in pnl if value > 0)
    losses = -sum(value for value in pnl if value < 0)
    peak = cumulative = drawdown = 0
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    tail = max(1, n // 10)
    ranked = sorted(returns)
    return dict(
        n=n, total_pnl_lamports=sum(pnl), mean_pnl_lamports=sum(pnl) / n,
        median_pnl_lamports=statistics.median(pnl), mean_return=sum(returns) / n,
        win_rate=sum(value > 0 for value in pnl) / n,
        profit_factor=None if losses == 0 else wins / losses,
        max_drawdown_lamports=drawdown,
        worst_decile_mean_return=sum(ranked[:tail]) / tail,
        best_decile_mean_return=sum(ranked[-tail:]) / tail)


def bootstrap_mean_ci(values, groups=None, *, n_boot=10_000, alpha=0.05, seed=0):
    """(low, high) percentile bootstrap interval of the mean; cluster bootstrap with ``groups``."""
    values = list(values)
    if not values:
        raise ValueError('no_values')
    if not 0 < alpha < 1 or type(n_boot) is not int or n_boot < 100:
        raise ValueError('invalid_bootstrap_parameters')
    rng = random.Random(seed)
    if groups is None:
        clusters = [[value] for value in values]
    else:
        groups = list(groups)
        if len(groups) != len(values):
            raise ValueError('groups_length_mismatch')
        by_group = OrderedDict()
        for value, group in zip(values, groups):
            by_group.setdefault(group, []).append(value)
        clusters = list(by_group.values())
    means = []
    for _ in range(n_boot):
        sample = [value for _k in range(len(clusters)) for value in clusters[rng.randrange(len(clusters))]]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int(math.floor(alpha / 2 * (n_boot - 1)))]
    high = means[int(math.ceil((1 - alpha / 2) * (n_boot - 1)))]
    return low, high


def _moments(values):
    n = len(values)
    mean = sum(values) / n
    centred = [value - mean for value in values]
    m2 = sum(c * c for c in centred) / n
    if m2 == 0:
        return mean, 0.0, None, None
    skew = (sum(c ** 3 for c in centred) / n) / m2 ** 1.5
    kurt = (sum(c ** 4 for c in centred) / n) / m2 ** 2          # Pearson (non-excess)
    return mean, math.sqrt(m2), skew, kurt


def sharpe_ratio(values):
    """Per-cycle Sharpe ratio (mean / sample standard deviation); None if undefined."""
    values = list(values)
    if len(values) < 2:
        return None
    std = statistics.stdev(values)
    return None if std == 0 else statistics.fmean(values) / std


def probabilistic_sharpe_ratio(values, benchmark=0.0):
    """P(true per-cycle Sharpe > benchmark); None when the sample cannot support it."""
    values = list(values)
    n = len(values)
    if n < 3:
        return None
    _mean, std, skew, kurt = _moments(values)
    sr = sharpe_ratio(values)
    if sr is None or std == 0:
        return None
    variance = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if variance <= 0:
        return None
    return _NORMAL.cdf((sr - benchmark) * math.sqrt(n - 1) / math.sqrt(variance))


def expected_max_sharpe(trial_sharpes):
    """Expected maximum Sharpe ratio of N unskilled trials (benchmark of the deflated ratio)."""
    trials = [value for value in trial_sharpes if value is not None]
    count = len(trials)
    if count < 2:
        raise ValueError('at_least_two_trials_required')
    spread = statistics.pstdev(trials)
    return spread * ((1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / count)
                     + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (count * math.e)))


def deflated_sharpe_ratio(values, trial_sharpes):
    """PSR against the expected maximum Sharpe of all trials (every policy tried counts)."""
    return probabilistic_sharpe_ratio(values, expected_max_sharpe(trial_sharpes))


def chronological_split(pools, *, fractions=(0.25, 0.25, 0.25, 0.25), embargo_slots=750):
    """Assign each pool to one segment, an embargo, or the creator-overlap set.

    ``pools``: dicts with ``pool``, ``creator`` and ``created_slot``. Segments are
    contiguous in creation order (ties broken by pool id). A pool created within
    ``embargo_slots`` after a segment boundary goes to ``embargoed``. A pool whose
    creator appeared in an earlier segment goes to ``creator_overlap``. Every pool
    is accounted for exactly once.
    """
    if len(fractions) != len(SEGMENTS) or any(f <= 0 for f in fractions) or abs(sum(fractions) - 1) > 1e-9:
        raise ValueError('invalid_fractions')
    if type(embargo_slots) is not int or embargo_slots < 0:
        raise ValueError('invalid_embargo_slots')
    rows = sorted(pools, key=lambda row: (row['created_slot'], row['pool']))
    if len({row['pool'] for row in rows}) != len(rows):
        raise ValueError('duplicate_pool')
    n = len(rows)
    bounds, acc = [], 0.0
    for fraction in fractions[:-1]:
        acc += fraction
        bounds.append(int(round(acc * n)))
    result = {name: [] for name in SEGMENTS}
    result.update(embargoed=[], creator_overlap=[])
    starts = {}
    seen_creators = {}
    for index, row in enumerate(rows):
        segment = SEGMENTS[sum(index >= bound for bound in bounds)]
        if segment not in starts:
            starts[segment] = row['created_slot']
        position = SEGMENTS.index(segment)
        if position > 0 and row['created_slot'] < starts[segment] + embargo_slots:
            result['embargoed'].append(row['pool'])
            continue
        first = seen_creators.setdefault(row['creator'], position)
        if first < position:
            result['creator_overlap'].append(row['pool'])
            continue
        result[segment].append(row['pool'])
    total = sum(len(value) for value in result.values())
    if total != n:
        raise ValueError('split_accounting_mismatch')
    return result


def preregistration(policy_name, params, design):
    """Canonical SHA-256 of a policy, its parameters and its evaluation design."""
    doc = dict(policy=policy_name, params=params, design=design)
    text = json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()
