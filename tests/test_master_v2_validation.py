"""Statistics of the MASTER V2 research harness: exact on small cases, deterministic."""
import math
import statistics

import pytest

from bot.master_v2 import validation as v


def _cycles(pnls, costs=None, creators=None):
    costs = costs or [100_000_000] * len(pnls)
    creators = creators or ['c%d' % i for i in range(len(pnls))]
    return [dict(pnl_lamports=p, cost_lamports=c, creator=k, order_key=(i,))
            for i, (p, c, k) in enumerate(zip(pnls, costs, creators))]


def test_cycle_metrics_on_a_hand_checked_example():
    m = v.cycle_metrics(_cycles([10, -30, 20, -5, 40]))
    assert (m['n'], m['total_pnl_lamports'], m['mean_pnl_lamports'], m['median_pnl_lamports']) == (5, 35, 7, 10)
    assert m['win_rate'] == 3 / 5 and m['profit_factor'] == 70 / 35
    assert m['max_drawdown_lamports'] == 30              # 10 -> -20
    assert m['worst_decile_mean_return'] == -30 / 100_000_000
    assert v.cycle_metrics(_cycles([5, 5]))['profit_factor'] is None
    assert v.cycle_metrics([])['n'] == 0


def test_drawdown_follows_time_order_not_list_order():
    rows = _cycles([-50, 100, -60])
    rows[0]['order_key'], rows[1]['order_key'] = (1,), (0,)   # +100 happened first
    assert v.cycle_metrics(rows)['max_drawdown_lamports'] == 110


@pytest.mark.parametrize('row', [dict(pnl_lamports=None, cost_lamports=1, order_key=(0,)),
                                 dict(pnl_lamports=1, cost_lamports=0, order_key=(0,))])
def test_open_or_costless_cycles_are_refused(row):
    with pytest.raises(ValueError):
        v.cycle_metrics([row])


def test_bootstrap_is_deterministic_and_covers_the_mean():
    values = [((i * 7919) % 101) - 50 for i in range(400)]
    a = v.bootstrap_mean_ci(values, n_boot=2000, seed=3)
    assert a == v.bootstrap_mean_ci(values, n_boot=2000, seed=3)
    assert a[0] < statistics.fmean(values) < a[1]


def test_cluster_bootstrap_is_wider_for_correlated_creators():
    values, groups = [], []
    for creator in range(20):
        level = 100 if creator % 2 else -100              # every cycle of a creator moves together
        values += [level + j for j in range(10)]
        groups += [creator] * 10
    iid = v.bootstrap_mean_ci(values, n_boot=3000, seed=1)
    cluster = v.bootstrap_mean_ci(values, groups, n_boot=3000, seed=1)
    assert cluster[1] - cluster[0] > 2 * (iid[1] - iid[0])
    with pytest.raises(ValueError):
        v.bootstrap_mean_ci(values, groups[:-1])


def _reference_psr(values, benchmark):
    n = len(values)
    mean = sum(values) / n
    m2 = sum((x - mean) ** 2 for x in values) / n
    skew = sum((x - mean) ** 3 for x in values) / n / m2 ** 1.5
    kurt = sum((x - mean) ** 4 for x in values) / n / m2 ** 2
    sr = mean / statistics.stdev(values)
    z = (sr - benchmark) * math.sqrt(n - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def test_probabilistic_sharpe_matches_the_formula_and_its_limits():
    values = [0.4, -0.2, 0.1, 0.9, -0.5, 0.3, 0.05, -0.1, 0.6, -0.35, 1.8, -0.4]
    assert v.probabilistic_sharpe_ratio(values) == pytest.approx(_reference_psr(values, 0.0), rel=1e-12)
    assert v.probabilistic_sharpe_ratio(values, 0.2) == pytest.approx(_reference_psr(values, 0.2), rel=1e-12)
    assert v.probabilistic_sharpe_ratio([1, -1, 1, -1]) == pytest.approx(0.5)
    assert v.probabilistic_sharpe_ratio([1, 1, 1]) is None and v.probabilistic_sharpe_ratio([1, 2]) is None


def test_deflated_sharpe_penalises_more_trials_and_wider_trials():
    values = [0.3, -0.1, 0.25, 0.4, -0.2, 0.35, 0.1, 0.05, -0.05, 0.3] * 3
    psr = v.probabilistic_sharpe_ratio(values)
    few = v.deflated_sharpe_ratio(values, [0.1, 0.2, 0.0])
    many = v.deflated_sharpe_ratio(values, [0.1, 0.2, 0.0] * 30)
    wide = v.deflated_sharpe_ratio(values, [0.5, -0.5, 0.0])
    assert psr > few > many and few > wide
    count, spread = 3, statistics.pstdev([0.1, 0.2, 0.0])
    expected = spread * ((1 - v.EULER_GAMMA) * statistics.NormalDist().inv_cdf(1 - 1 / count)
                         + v.EULER_GAMMA * statistics.NormalDist().inv_cdf(1 - 1 / (count * math.e)))
    assert v.expected_max_sharpe([0.1, 0.2, 0.0]) == pytest.approx(expected)
    with pytest.raises(ValueError):
        v.expected_max_sharpe([0.1])


def _pools():
    rows = []
    for i in range(40):
        rows.append(dict(pool='p%02d' % i, creator='k%d' % (i % 13), created_slot=1000 + 100 * i))
    return rows


def test_chronological_split_accounts_for_every_pool_and_keeps_creators_disjoint():
    split = v.chronological_split(_pools(), embargo_slots=150)
    every = [pool for pools in split.values() for pool in pools]
    assert sorted(every) == sorted(row['pool'] for row in _pools())
    slot = {row['pool']: row['created_slot'] for row in _pools()}
    creator = {row['pool']: row['creator'] for row in _pools()}
    for earlier, later in zip(v.SEGMENTS, v.SEGMENTS[1:]):
        if split[earlier] and split[later]:
            assert max(slot[p] for p in split[earlier]) < min(slot[p] for p in split[later])
    owners = [{creator[p] for p in split[name]} for name in v.SEGMENTS]
    for i in range(len(owners)):
        for j in range(i + 1, len(owners)):
            assert not owners[i] & owners[j]
    assert split['embargoed'] and split['creator_overlap']
    for pool in split['creator_overlap']:
        assert any(creator[pool] in owners[i] for i in range(len(owners)))


def test_split_refuses_invalid_designs():
    for kwargs in (dict(fractions=(0.5, 0.5)), dict(fractions=(0.5, 0.5, 0.0, 0.0)),
                   dict(fractions=(0.3, 0.3, 0.3, 0.3)), dict(embargo_slots=-1)):
        with pytest.raises(ValueError):
            v.chronological_split(_pools(), **kwargs)
    with pytest.raises(ValueError, match='duplicate_pool'):
        v.chronological_split(_pools() + _pools()[:1])


def test_preregistration_is_canonical_and_sensitive():
    a = v.preregistration('challenger-x', dict(b=1, a=2), dict(split='chronological'))
    assert a == v.preregistration('challenger-x', dict(a=2, b=1), dict(split='chronological'))
    assert a != v.preregistration('challenger-x', dict(a=2, b=2), dict(split='chronological'))


def test_bootstrap_interval_is_two_sided():
    values = list(range(-500, 501))
    low, high = v.bootstrap_mean_ci(values, n_boot=4000, seed=11)
    assert low < 0 < high and abs(low + high) < 0.05 * (high - low)
