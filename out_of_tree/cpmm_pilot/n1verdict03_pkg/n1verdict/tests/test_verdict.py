"""n1verdict 0.3 (R04-6, K-1, alpha): one continuous position per pool (real lpcost 0.2 on synthetic CPMM pools), the total-loss
rule for an unpriced position, and the word of g23five 0.2 with 2-day blocks on controlled gaps (lpcost replaced by a
stub in those tests only)."""
from fractions import Fraction
from types import SimpleNamespace

import pytest

from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A, CONFIG_B, POOL_A, calm, line_of
from g23five import verdict as G
from lpcost import continuous as K, model as LP
from n1verdict import verdict as N

DAY = 86_400
T0 = 10 * DAY
SHEET = '13579bdf' + '02468ace' * 7
DRAWS = 300
POOLS = ['pA', 'pB', 'pC', 'pD']
D = 12


def test_total_loss_per_day_is_the_stake_and_the_round_trip_over_d():
    assert N.total_loss_per_day(10 ** 9, 12) == -(1 + Fraction(630_000, 10 ** 9)) / 12
    tx, rent = LP.transactions(CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS))
    assert N.total_loss_per_day(10 ** 9, 12, CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)) == \
        -(1 + Fraction(tx + rent, 10 ** 9)) / 12


# -- real lpcost 0.2 on a synthetic pool -------------------------------------------------------------------------------
def real_line(extra=(), days=8):
    return line_of(POOL_A, sorted(calm(T0 - 600, T0 + days * DAY + 600, every=1_800) + list(extra)))


def test_the_pool_days_are_the_daily_values_of_one_position():
    line = real_line()
    rows, pos = N.pool_days(line, CONFIG_A, t0=T0, d_days=8)
    direct = K.continuous_position(line, CONFIG_A, start_time=T0, end_time=T0 + 8 * DAY)
    assert [r['day'] for r in rows] == list(range(8)) and [r['decision_time'] for r in rows] == [T0 + k * DAY
                                                                                                 for k in range(8)]
    assert [r['net_return'] for r in rows] == [float(d['gap_lamports'] / direct['stake_lamports'])
                                               for d in direct['days']]
    assert pos['gap_lamports'] == direct['gap_lamports'] and all(r['status'] == 'entered' for r in rows)


def test_an_unpriced_position_is_a_total_loss_and_other_errors_stop():
    rows, pos = N.pool_days(real_line([(T0 + 100, 'lp', (1, 10))]), CONFIG_A, t0=T0, d_days=8)
    assert pos is None and len(rows) == 8
    assert all(r['status'] == 'unpriced_total_loss' and r['unpriced'] == 'lp_change_at_the_landing_point'
               and r['entered'] is True for r in rows)
    line = real_line()
    stake0 = [s for s in line.swaps if s.block_time < T0][-1].quote_before * 5_000 // 1_000_000
    assert N.unpriced_stake(line, T0) == stake0
    assert rows[0]['net_return'] == float(N.total_loss_per_day(stake0, 8)) and rows[0]['stake_lamports'] == stake0
    sens, _p = N.pool_days(real_line([(T0 + 100, 'lp', (1, 10))]), CONFIG_A, t0=T0, d_days=8,
                           failures=CC.SENSITIVITY_FAILURES)
    assert sens[0]['net_return'] == float(N.total_loss_per_day(stake0, 8, CC.SENSITIVITY_FAILURES)) != rows[0]['net_return']
    # the stake of an unpriced position is read before the LAST pre-T0 swap
    early = line_of(POOL_A, [(t, 'buy', 5 * 10 ** 9) for t in range(T0 - 5_400, T0, 1_800)]
                    + calm(T0 + 60, T0 + 9 * DAY, every=1_800))
    pre = [s for s in early.swaps if s.block_time < T0]
    assert pre[0].quote_before != pre[-1].quote_before
    assert N.unpriced_stake(early, T0) == pre[-1].quote_before * 5_000 // 1_000_000
    with pytest.raises(CC.CostError, match='outside_universe'):
        N.pool_days(real_line(), CONFIG_B, t0=T0, d_days=8)
    with pytest.raises(N.N1Error, match='pre_t0'):
        N.pool_days(line_of(POOL_A, calm(T0 + 60, T0 + 9 * DAY, every=1_800)), CONFIG_A, t0=T0, d_days=8)
    assert N._unpriced(LP.LpCostError('exit_state_empty')) and not N._unpriced(LP.LpCostError('period_must_be_whole_days'))
    assert not N._unpriced(CC.CostError('exit_state_empty'))


# -- the word on controlled gaps ---------------------------------------------------------------------------------------
def fake_lines(pools=POOLS):
    return [SimpleNamespace(pool=p, swaps=[SimpleNamespace(block_time=T0 - 5, quote_before=200 * 10 ** 9)])
            for p in pools]


@pytest.fixture
def stub(monkeypatch):
    calls = []

    def install(value, unpriced=(), refused=()):
        def continuous_position(line, config, *, start_time, end_time, failures=CC.FROZEN_FAILURES,
                                buy_guard_ppm=CC.BUY_GUARD_PPM):
            calls.append((line.pool, failures, buy_guard_ppm))
            if line.pool in unpriced:
                raise CC.CostError('lp_change_at_the_landing_point')
            n, stake = (end_time - start_time) // DAY, 10 ** 9
            shift = Fraction(-3, 1000) if failures != CC.FROZEN_FAILURES else 0
            days = [dict(day=k, gap_lamports=Fraction(value(line.pool, k)) * stake + shift * stake) for k in range(n)]
            status = 'guard_failed' if line.pool in refused else 'entered'
            gap = sum(d['gap_lamports'] for d in days)
            return dict(pool=line.pool, status=status, entered=status == 'entered', stake_lamports=stake, days=days,
                        gap_lamports=gap, net_lamports=int(gap) + 7, fees_earned_estimate=1_000.0,
                        decomposition_lamports=dict(hold_price_move=Fraction(5), mark_change=gap + 9, entry=-3, exit=-2,
                                                    transactions=-3, rent_lost=-1))
        monkeypatch.setattr(K, 'continuous_position', continuous_position)
        return calls
    return install


def run(**kw):
    kw.setdefault('pools', POOLS)
    kw.setdefault('g0_passed', True)
    kw.setdefault('freeze_sheet_sha256', SHEET)
    kw.setdefault('t0', T0)
    kw.setdefault('d_days', D)
    kw.setdefault('draws', DRAWS)
    lines = kw.pop('lines', None) or fake_lines(kw['pools'])
    return N.report(lines, CONFIG_A, **kw)


def test_go_uses_two_day_blocks_and_the_sheet_seed(stub):
    stub(lambda p, d: Fraction(1, 100) + Fraction(2, 1000) * (d % 3))
    out = run()
    assert out['decision'] == 'GO_PILOTE' and out['n'] == 48 and out['block_days'] == 2
    rows, _w = N.positions(fake_lines(), CONFIG_A, pools=POOLS, t0=T0, d_days=D)
    seed = int(SHEET[:8], 16)
    assert out['seed'] == seed
    assert (out['lower_bound_95'], out['upper_bound_95']) == G.stratified_bounds(G.blocks(rows, T0, D, 2), seed=seed,
                                                                                  draws=DRAWS)
    assert out['lower_bound_95'] != G.stratified_bounds(G.blocks(rows, T0, D, 1), seed=seed, draws=DRAWS)[0]
    rest = [r for r in rows if r['pool'] != out['without_top_pool']['pool']]
    assert out['without_top_pool']['lower_bound_95'] == G.stratified_bounds(G.blocks(rest, T0, D, 2), seed=seed,
                                                                             draws=DRAWS)[0]
    assert out['power']['flag'] == G.G1.UNDER_TARGET and out['stake_ppm'] == 5_000
    pa = out['per_pool']['pA']
    assert pa['gap_return'] == pytest.approx(sum(0.01 + 0.002 * (d % 3) for d in range(D)))
    assert pa['net_return_absolute'] == pytest.approx(pa['gap_return'] + 7e-9, abs=1e-9) and pa['verdict'] is None
    assert pa['costs_return'] == pytest.approx(9e-9) and pa['entries'] == 12
    assert out['limits'] == N.LIMITS and out['scope'] == N.SCOPE and out['counts_for_operational_master'] is False


def test_leave_top_out_no_go_floors_refusals_and_unpriced(stub):
    stub(lambda p, d: (Fraction(1, 2) if p == 'pA' else Fraction(-4, 1000)) + Fraction(1, 1000) * (d % 3),
         unpriced={'pB'})
    c = run()
    assert c['lower_bound_95'] > 0 and c['without_top_pool']['pool'] == 'pA'
    assert c['without_top_pool']['lower_bound_95'] <= 0 and c['decision'] == 'INCONCLUSIF'
    assert c['unpriced'] == dict(pools=['pB'], reasons=['lp_change_at_the_landing_point'])
    loss = float(N.total_loss_per_day(200 * 10 ** 9 * 5_000 // 1_000_000, D))
    assert c['per_pool']['pB']['mean_gap_return'] == pytest.approx(loss) and c['per_pool']['pB']['entries'] == 12
    stub(lambda p, d: Fraction(-2, 100) + Fraction(2, 1000) * (d % 3))
    assert run()['decision'] == 'NO-GO'
    stub(lambda p, d: Fraction(-5, 100), refused={'pD'})
    refused = run(d_days=8)                                                   # 3 pools x 8 = 24 pool-days < 30
    assert refused['decision'] == 'INCONCLUSIF' and refused['upper_bound_95'] < 0
    assert refused['per_pool']['pD']['entries'] == 0 and refused['per_pool']['pD']['status'] == 'guard_failed'
    stub(lambda p, d: Fraction(1, 100) * ((d + POOLS.index(p)) % 3 - 1))
    assert run()['decision'] == 'INCONCLUSIF'


def test_sensitivities_are_descriptive_and_use_the_declared_variants(stub):
    calls = stub(lambda p, d: Fraction(1, 100))
    out = run()
    s = out['sensitivities']
    assert set(s) == {'one_failure_per_tx', 'guard_50000', 'rent_lost'}
    assert s['one_failure_per_tx']['mean_gap_return'] == pytest.approx(0.007) and s['guard_50000']['verdict'] is None
    assert s['guard_50000']['mean_gap_return'] == pytest.approx(0.01)
    assert {(f, g) for _p, f, g in calls} == {
        (CC.FROZEN_FAILURES, CC.BUY_GUARD_PPM), (CC.SENSITIVITY_FAILURES, CC.BUY_GUARD_PPM),
        (CC.FROZEN_FAILURES, CC.BUY_GUARD_SENSITIVITY_PPM),
        (CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS), CC.BUY_GUARD_PPM)}
    assert out['decision'] == 'GO_PILOTE'


def test_stop_and_inputs(stub):
    stub(lambda p, d: Fraction(1, 100))
    stop = run(g0_passed=False)
    assert stop['decision'] == 'STOP' and stop['published_numbers'] is False and 'floors' not in stop
    assert run(g0_passed=1)['decision'] == 'STOP'
    with pytest.raises(N.N1Error, match='sheet_order'):
        run(lines=fake_lines(list(reversed(POOLS))))
    for d in (6, 9, 31, 12.0):
        with pytest.raises(N.N1Error, match='d_days'):
            run(d_days=d)
    with pytest.raises(N.N1Error, match='t0'):
        run(t0=float(T0))
    for pools in (['pA', 'pB'], ['pA', 'pA', 'pB']):
        with pytest.raises(N.N1Error, match='3_distinct'):
            run(pools=pools)
    with pytest.raises(G.VerdictError, match='sheet'):
        run(freeze_sheet_sha256='A' * 64)
    out = run()
    assert out['meaning'] == N.MEANING and 'Holm' in out['multiplicity']
    with pytest.raises(G.G1.ReportError, match='forbidden'):
        run(pools=['pA', 'pB', 'pC', 'pool ' + G.G1.FORBIDDEN_WORDS[1]])


# -- 0.2.1: K-1, the guard removes the pool that carries the result ---------------------------------------------------
def test_k1_the_guard_removes_the_pool_with_the_largest_sum_of_gaps(stub):
    # pC carries the whole gain; all pools have 12 pool-days: "most entries" would pick pA (by id) and say GO
    stub(lambda p, d: (Fraction(1, 2) if p == 'pC' else Fraction(-4, 1000)) + Fraction(1, 1000) * (d % 3))
    out = run()
    assert out['lower_bound_95'] > 0 and out['without_top_pool']['pool'] == 'pC'
    assert out['without_top_pool']['lower_bound_95'] <= 0 and out['decision'] == 'INCONCLUSIF'
    assert 'K-1' in out['without_top_pool']['rule']
    rows, _w = N.positions(fake_lines(), CONFIG_A, pools=POOLS, t0=T0, d_days=D)
    assert G.top_pool(rows) == 'pA' and N.top_gap_pool(rows) == 'pC'
    rest = [r for r in rows if r['pool'] != 'pA']
    assert G.stratified_bounds(G.blocks(rest, T0, D, 2), seed=int(SHEET[:8], 16), draws=DRAWS)[0] > 0   # old rule: GO
    # ties by id; empty
    tie = [dict(pool=p, net_return=0.1) for p in ('pB', 'pA')]
    assert N.top_gap_pool(tie) == 'pA' and N.top_gap_pool([]) is None
    assert N.top_gap_pool([dict(pool='pA', net_return=0.2), dict(pool='pB', net_return=0.3),
                           dict(pool='pA', net_return=0.2)]) == 'pA'                      # sums, not the best day


# -- 0.3: alpha, p-value, halves ----------------------------------------------------------------------------------------
def _v021():
    import hashlib
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / 'n1verdict_pkg' / 'n1verdict' / 'verdict.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        'e6db8985b24e8eb4f7246428041a3f9d8a22d7ea580a9ef05c7d1d2631a199f8')          # verdict.py of 0.2.1 / 0.2.2
    spec = importlib.util.spec_from_file_location('n1verdict_v021', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_alpha_is_identical_to_0_2_1(stub):
    old = _v021()
    for value in (lambda p, d: Fraction(1, 100) + Fraction(2, 1000) * (d % 3),
                  lambda p, d: Fraction(1, 100) * ((d + POOLS.index(p)) % 3 - 1)):
        stub(value)
        new_doc = run()
        old_doc = old.report(fake_lines(), CONFIG_A, pools=POOLS, g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                             d_days=D, draws=DRAWS)
        assert new_doc.pop('schema') == 'n1verdict-v0.3' and new_doc.pop('alpha') == 0.05
        new_doc.pop('p_value'), new_doc.pop('halves'), old_doc.pop('schema')
        assert new_doc == old_doc


def test_alpha_p_value_and_halves(stub):
    stub(lambda p, d: Fraction(1, 100) * ((d + POOLS.index(p)) % 4 - 1) - Fraction(3, 1000))
    rows, _w = N.positions(fake_lines(), CONFIG_A, pools=POOLS, t0=T0, d_days=D)
    seed = int(SHEET[:8], 16)
    for alpha in (0.025, 0.0125):
        out = run(alpha=alpha)
        assert (out['lower_bound_95'], out['upper_bound_95']) == G.stratified_bounds(
            G.blocks(rows, T0, D, 2), seed=seed, draws=DRAWS, alpha=alpha) and out['alpha'] == alpha
        rest = [r for r in rows if r['pool'] != out['without_top_pool']['pool']]
        assert out['without_top_pool']['lower_bound_95'] == G.stratified_bounds(
            G.blocks(rest, T0, D, 2), seed=seed, draws=DRAWS, alpha=alpha)[0]
        s = out['sensitivities']['one_failure_per_tx']
        alt, _w = N.positions(fake_lines(), CONFIG_A, pools=POOLS, t0=T0, d_days=D, failures=CC.SENSITIVITY_FAILURES)
        assert (s['lower_bound_95'], s['upper_bound_95']) == G.stratified_bounds(
            G.blocks(alt, T0, D, 2), seed=seed, draws=DRAWS, alpha=alpha)
    assert run(alpha=0.0125)['lower_bound_95'] < run()['lower_bound_95']
    out = run()
    assert 0.05 < out['p_value'] < 0.95
    assert out['p_value'] == G.bootstrap_p(G.blocks(rows, T0, D, 2), seed=seed, draws=DRAWS)
    assert out['p_value'] != G.bootstrap_p(G.blocks(rows, T0, D, 1), seed=seed, draws=DRAWS)
    assert out['halves'] == G.halves(rows, T0, D) and out['halves']['cut_time'] == T0 + 6 * DAY
    stub(lambda p, d: Fraction(1, 100) if d < 6 else Fraction(-1, 100))
    assert run()['halves']['both_positive'] is False
    stub(lambda p, d: Fraction(1, 100))
    assert run()['halves']['both_positive'] is True
    with pytest.raises(G.VerdictError, match='alpha'):
        run(alpha=0.1)
    with pytest.raises(G.VerdictError, match='alpha'):
        run(alpha=0.1, g0_passed=False)                                     # refused even before a STOP
