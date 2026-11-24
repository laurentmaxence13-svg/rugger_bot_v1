"""g23five 0.1 on fixtures only: selection before T0, stratified pool-day bootstrap, floors, leave-top-out guard,
K01 rows, vocabulary; one end-to-end run of the frozen G2-3 rule on a synthetic CPMM pool."""
import hashlib
import random

import pytest

from cpmmcost import model as CC
from cpmmgen2.tests.test_gen2 import market
from cpmmpilot import step1 as PILOT
from cpmmprereg import rule as R
from cpmmprereg.tests.test_rule import CONFIG
from g23five import verdict as V

SHEET = '0123456789abcdef' * 4
T0 = 1_000_000
D = 12
DRAWS = 400
POOLS = ['pA', 'pB', 'pC', 'pD']


def row(pool, day, net, k=0, status='entered'):
    return dict(pool=pool, decision_index=day * 100 + k, decision_time=T0 + day * 86_400 + 60 * k, status=status,
                entered=status == 'entered', net_return=net, net_lamports=round(net * CC.STAKE_LAMPORTS))


def grid(value=lambda p, d, k: 0.01, days=range(D), per_day=2, pools=POOLS):
    return [row(p, d, value(p, d, k), k) for p in pools for d in days for k in range(per_day)]


def run(primary, placebo=(), **kw):
    kw.setdefault('pools', POOLS)
    kw.setdefault('g0_passed', True)
    kw.setdefault('freeze_sheet_sha256', SHEET)
    kw.setdefault('t0', T0)
    kw.setdefault('d_days', D)
    kw.setdefault('draws', DRAWS)
    return V.report(list(primary), list(placebo), **kw)


# -- selection before T0 -----------------------------------------------------------------------------------------------
def test_selection_keeps_3_or_more_triggers_the_first_5_and_ties_by_id():
    counts = dict(AEZjoU=128, Gms3Ma=105, G8kgi7=95, GdxFyc=21, two=2, z6=21, a6=21)
    out = V.select(counts)
    assert out['pools'] == ['AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc', 'a6'] and out['evaluable'] is True
    assert out['list_sha256'] == hashlib.sha256('\n'.join(out['pools']).encode()).hexdigest()
    real = V.select(dict(AEZjoU=128, Gms3Ma=105, G8kgi7=95, GdxFyc=21, yLFom=2))
    assert real['pools'] == ['AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc']                 # R02 835d648e
    assert V.select(dict(a=3, b=3, c=3))['evaluable'] is True
    few = V.select(dict(a=3, b=3, c=2))
    assert few['evaluable'] is False and few['conduct'].startswith('NON ÉVALUABLE')
    assert few['outcomes_computed'] is False


def test_counts_before_t0_use_the_frozen_rule_and_refuse_the_window():
    t0 = 7 * 86_400
    steady = [(k * 600 + s, 'buy', 10 ** 8, False, 'B%d' % ((k + s) % 3)) for k in range(1_008) for s in (7, 300)]
    burst = [(t, 'buy', 10 ** 8, False, 'Q%d' % t) for t in range(400_010, 400_200, 20)]
    line, txs = market(sorted(steady + burst))
    counts = V.counts_before_t0([line], {line.pool: txs}, t0)
    b3 = V.G2.baseline_b3(line, txs, t0)
    assert b3 == 2                                                             # the pool's own baseline, not 1
    expected = V.G2.trigger_count(lambda ln: V.G2.decisions_g23(ln, txs, b3), [line], t0)['triggers']
    assert counts == {line.pool: expected} and expected >= 1
    with pytest.raises(V.G2.PreregError, match='after_t0'):
        V.counts_before_t0([line], {line.pool: txs}, 300_000)


# -- the stratified bootstrap ------------------------------------------------------------------------------------------
def test_the_bootstrap_resamples_days_within_each_pool_only():
    # constant net per pool, same number of days and rows per pool: a within-pool resample never changes the mean
    rows = grid(lambda p, d, k: {'pA': 0.03, 'pB': -0.01, 'pC': 0.0, 'pD': 0.02}[p])
    low, high = V.stratified_bounds(V.blocks(rows, T0, D), seed=1, draws=DRAWS)
    assert low == pytest.approx(0.01) and high == pytest.approx(0.01)
    # with variance inside the pools the bounds open up, and they depend on the seed
    noisy = grid(lambda p, d, k: 0.01 * ((d * 7 + k * 3 + POOLS.index(p)) % 5 - 2))
    a = V.stratified_bounds(V.blocks(noisy, T0, D), seed=1, draws=DRAWS)
    assert a[0] < a[1] and a == V.stratified_bounds(V.blocks(noisy, T0, D), seed=1, draws=DRAWS)
    assert a != V.stratified_bounds(V.blocks(noisy, T0, D), seed=2, draws=DRAWS)
    assert V.stratified_bounds({}, seed=1) == (None, None)


def test_the_bounds_match_a_direct_computation():
    noisy = grid(lambda p, d, k: 0.01 * ((d * 5 + k + POOLS.index(p) * 2) % 7 - 3))
    bm = V.blocks(noisy, T0, D)
    rng, means = random.Random(int(SHEET[:8], 16)), []
    for _ in range(DRAWS):
        picked = []
        for p in sorted(bm):
            days = sorted(bm[p])
            for _k in days:
                picked += bm[p][days[rng.randrange(len(days))]]
        means.append(sum(r['net_return'] for r in picked) / len(picked))
    k = int(0.05 * DRAWS) - 1
    out = run(noisy)
    assert (out['lower_bound_95'], out['upper_bound_95']) == (sorted(means)[k], sorted(means, reverse=True)[k])
    assert out['seed'] == int(SHEET[:8], 16)


# -- floors ------------------------------------------------------------------------------------------------------------
def entries_rows(counts):
    """One entry per day for each pool: counts {pool: n} -> n distinct pool-days per pool."""
    return [row(p, d, 0.01) for p, n in counts.items() for d in range(n)]


def test_the_floors_at_their_boundaries():
    assert V.floors(grid(days=range(8), per_day=1), T0, D)['passed'] is True           # 32 pool-days, 4 pools
    f29 = V.floors(grid(days=range(8), per_day=1)[:29], T0, D)
    assert f29['pool_days_with_entry'] == 29 and f29['checks']['pool_days'] is False
    f30 = V.floors(grid(days=range(10), per_day=1, pools=POOLS[:3]), T0, D)
    assert f30['pool_days_with_entry'] == 30 and f30['passed'] is True                 # 3 pools, Kish 3
    two = V.floors(grid(days=range(12), per_day=2, pools=POOLS[:2]), T0, D)
    assert two['checks']['pools'] is False
    # several entries on one day count once in the pool-days
    same_day = V.floors([row('pA', 0, 0.01, k) for k in range(40)], T0, D)
    assert same_day['pool_days_with_entry'] == 1


def test_kish_and_the_largest_share():
    # entries 12, 6, 6: Kish = 24^2 / 216 = 2.667 >= 2.5 ; share 0.5 exactly passes
    ok = V.floors(entries_rows(dict(pA=12, pB=6, pC=6)), T0, D)
    assert ok['kish'] == pytest.approx(576 / 216) and ok['max_share'] == 0.5
    assert ok['checks']['kish'] is True and ok['checks']['max_share'] is True
    # entries 12, 5, 5: share 0.545 > 0.5 fails ; Kish = 484 / 194 = 2.49 < 2.5 fails
    bad = V.floors(entries_rows(dict(pA=12, pB=5, pC=5)), T0, D)
    assert bad['checks']['max_share'] is False and bad['kish'] == pytest.approx(484 / 194)
    assert bad['checks']['kish'] is False
    # Kish exactly 2.5 (inclusive): entries (6, 1, 1, 1, 1) -> 100 / 40
    exact = V.floors(entries_rows(dict(pA=6, pB=1, pC=1, pD=1, pE=1)), T0, D)
    assert exact['kish'] == 2.5 and exact['checks']['kish'] is True and exact['checks']['max_share'] is False
    assert V.MIN_KISH == 2.5 and V.MAX_SHARE == 0.5


# -- the word ----------------------------------------------------------------------------------------------------------
def test_go_needs_the_lower_bound_above_zero_with_and_without_the_top_pool():
    good = grid(lambda p, d, k: 0.01 + 0.002 * ((d + k) % 3))
    out = run(good)
    assert out['decision'] == 'GO_PILOTE' and out['lower_bound_95'] > 0
    assert out['without_top_pool']['lower_bound_95'] > 0
    # the gain is carried by one pool: GO overall but not without it -> INCONCLUSIF
    carried = grid(lambda p, d, k: (0.08 if p == 'pA' else -0.004) + 0.001 * ((d + k) % 3), per_day=2)
    carried += [row('pA', d, 0.08, 7) for d in range(D)]                     # pA has the most entries
    c = run(carried)
    assert c['lower_bound_95'] > 0 and c['without_top_pool']['pool'] == 'pA'
    assert c['without_top_pool']['lower_bound_95'] <= 0 and c['decision'] == 'INCONCLUSIF'
    bad = grid(lambda p, d, k: -0.02 + 0.002 * ((d + k) % 3))
    assert run(bad)['decision'] == 'NO-GO'
    middle = grid(lambda p, d, k: 0.01 * ((d + k) % 3 - 1))
    assert run(middle)['decision'] == 'INCONCLUSIF'


def test_inconclusive_before_no_go_and_g0_stop():
    few = grid(lambda p, d, k: -0.05, days=range(5))                        # 20 pool-days only
    assert run(few)['decision'] == 'INCONCLUSIF' and run(few)['upper_bound_95'] < 0
    stop = run(grid(), g0_passed=False)
    assert stop['decision'] == 'STOP' and stop['published_numbers'] is False and 'floors' not in stop
    assert run(grid(), g0_passed=1)['decision'] == 'STOP'


def test_top_pool_is_the_one_with_the_most_entries_ties_by_id():
    rows = grid(per_day=1) + [row('pC', 0, 0.01, 5)]
    assert V.top_pool(rows) == 'pC'
    assert V.top_pool(grid(per_day=1)) == 'pA'
    refused = [dict(row('pD', d, -0.00105, 8), status='guard_failed', entered=False) for d in range(5)]
    assert V.top_pool(grid(per_day=1) + refused) == 'pA'                      # refusals are not entries


def test_k01_rows_window_pools_and_inputs_are_checked():
    rows = grid()
    raw = dict(pool='pA', decision_index=999, decision_time=T0 + 5, unpriced='x')
    with pytest.raises(V.G1.ReportError, match='raw_unpriced'):
        run(rows + [raw])
    with pytest.raises(V.G1.ReportError, match='raw_unpriced.*placebo'):
        run(rows, [raw])
    zero = PILOT.zero_sale(dict(raw, decision_slot=1), CC.FROZEN_FAILURES)
    out = run(rows + [zero])
    assert out['zero_sale']['count'] == 1 and out['n'] == len(rows) + 1
    with pytest.raises(V.VerdictError, match='outside_the_window'):
        run(rows + [row('pA', D, 0.01)])
    with pytest.raises(V.VerdictError, match='outside_the_window'):
        run(rows + [dict(row('pA', 0, 0.01), decision_time=T0 - 1)])
    with pytest.raises(V.VerdictError, match='named_pools'):
        run(rows + [row('pZ', 0, 0.01)])
    with pytest.raises(V.VerdictError, match='named_pools'):
        run(rows, [row('pZ', 0, 0.01)])
    for bad in (dict(freeze_sheet_sha256='x'), dict(freeze_sheet_sha256='A' * 64)):
        with pytest.raises(V.VerdictError, match='sheet'):
            run(rows, **bad)
    for d in (6, 31, 12.0):
        with pytest.raises(V.VerdictError, match='d_days'):
            run(rows, d_days=d)
    with pytest.raises(V.VerdictError, match='3_named'):
        run(rows, pools=['pA', 'pB'])
    with pytest.raises(V.VerdictError, match='t0'):
        run(rows, t0=float(T0))


def test_report_per_pool_power_placebo_and_vocabulary():
    rows = grid()
    plac = grid(lambda p, d, k: -0.003)
    out = run(rows, plac)
    assert set(out['per_pool']) == set(POOLS)
    assert out['per_pool']['pA'] == dict(positions=24, entries=24, pool_days_with_entry=12, mean_net_return=0.01)
    assert out['n_entered'] == 96
    assert out['power']['n_required'] == R.n_required() == 155
    assert out['power']['flag'] == V.G1.UNDER_TARGET                          # 96 entries < 155
    assert out['placebo']['difference'] == pytest.approx(0.013) and out['placebo']['verdict'] is None
    assert out['counts_for_operational_master'] is False and out['labels'] == list(CC.LABELS)
    assert out['meaning'] == V.SHEET_MEANING
    V.G1.check_vocabulary(out)
    leaked = PILOT.zero_sale(dict(pool='pA', decision_index=999, decision_time=T0 + 5, decision_slot=1,
                                  unpriced='note ' + V.G1.FORBIDDEN_WORDS[2]), CC.FROZEN_FAILURES)
    with pytest.raises(V.G1.ReportError, match='forbidden'):
        run(rows + [leaked])                                                 # the whole document is checked
    empty_pool = run(grid(pools=POOLS[:3], days=range(D)), pools=POOLS)
    assert empty_pool['per_pool']['pD']['mean_net_return'] == V.NM


# -- end to end on the frozen G2-3 rule --------------------------------------------------------------------------------
def test_end_to_end_frozen_rule_positions_and_verdict():
    one = [(t, 'buy', 10 ** 8, False, 'Same') for t in range(0, 600, 60)]
    burst = [(t, 'buy', 10 ** 8, False, 'Q%d' % t) for t in range(600, 800, 50)]
    line, txs = market(one + burst + [(t, 'sell', 10 ** 11, False, 'S') for t in range(800, 2_600, 20)])
    idx = V.decisions(line, txs, 1)
    assert V.decisions is V.G2.decisions_g23 and V.positions is R.positions and V.placebo is R.placebo
    primary = V.positions(line, CONFIG, idx)
    assert primary and all('net_return' in p for p in primary)
    out = V.report(primary, [], pools=[line.pool, 'x', 'y'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=0,
                   d_days=D, draws=DRAWS)
    assert out['decision'] == 'INCONCLUSIF' and out['floors']['pools_with_entry'] == 1
