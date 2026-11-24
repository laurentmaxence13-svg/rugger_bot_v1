"""n1verdict 0.1: pool-days on synthetic CPMM pools (real lpcost), the total-loss rule for unpriced pool-days, and the
word of g23five on controlled nets (lpcost replaced by a stub in those tests only)."""
from types import SimpleNamespace

import pytest

from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A, CONFIG_B, POOL_A, calm, line_of
from g23five import verdict as G
from lpcost import model as LP
from n1verdict import verdict as N

DAY = 86_400
T0 = 10 * DAY
SHEET = '13579bdf' + '02468ace' * 7                 # head and tail differ
DRAWS = 300
POOLS = ['pA', 'pB', 'pC', 'pD']


def test_total_loss_is_the_stake_and_the_round_trip():
    assert N.total_loss_lamports() == -100_630_000                           # 0.1 SOL + 6 x 105 000
    for f in (CC.SENSITIVITY_FAILURES, CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)):
        tx, rent = LP.transactions(f)
        assert N.total_loss_lamports(f) == -(LP.STAKE + tx + rent)
    assert N.total_loss_lamports(CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)) < -100_630_000 - 2 * LP.RENT + 1


# -- real lpcost on a synthetic pool -----------------------------------------------------------------------------------
def real_line(extra=(), days=7):
    return line_of(POOL_A, sorted(calm(T0 - 600, T0 + days * DAY + 600, every=1_800) + list(extra)))


def test_pool_days_are_aligned_on_t0_and_priced_by_lpcost():
    line = real_line()
    rows = N.pool_days(line, CONFIG_A, t0=T0, d_days=7)
    assert [r['day'] for r in rows] == list(range(7))
    assert [r['decision_time'] for r in rows] == [T0 + k * DAY for k in range(7)]
    for k, r in enumerate(rows):
        direct = LP.lp_position(line, CONFIG_A, start_time=T0 + k * DAY, end_time=T0 + (k + 1) * DAY)
        assert r['status'] == 'entered' and r['net_lamports'] == direct['net_lamports']
        assert r['end_time'] == T0 + (k + 1) * DAY


def test_an_unpriced_pool_day_is_a_total_loss_and_other_errors_stop():
    lp_at = T0 + 2 * DAY + 100                                    # between the last swap before day 2 and the next
    rows = N.pool_days(real_line([(lp_at, 'lp', (1, 10))]), CONFIG_A, t0=T0, d_days=7)
    lost = [r for r in rows if r['status'] == 'unpriced_total_loss']
    assert [r['day'] for r in lost] == [1, 2]                                # day 1 exit and day 2 entry
    assert all(r['unpriced'] == 'lp_change_at_the_landing_point' for r in lost)
    assert all(r['net_lamports'] == -100_630_000 and r['entered'] is True for r in lost)
    assert all(r['counts_for_operational_master'] is False for r in lost)
    sens = N.pool_days(real_line([(lp_at, 'lp', (1, 10))]), CONFIG_A, t0=T0, d_days=7,
                       failures=CC.SENSITIVITY_FAILURES)
    assert {r['net_lamports'] for r in sens if r['status'] == 'unpriced_total_loss'} == {
        N.total_loss_lamports(CC.SENSITIVITY_FAILURES)} != {-100_630_000}
    with pytest.raises(CC.CostError, match='outside_universe'):
        N.pool_days(real_line(), CONFIG_B, t0=T0, d_days=7)                 # a code / input defect, never a loss
    with pytest.raises(N.N1Error, match='pre_t0'):
        N.pool_days(line_of(POOL_A, calm(T0 + 60, T0 + 8 * DAY, every=1_800)), CONFIG_A, t0=T0, d_days=7)
    assert N._unpriced(LP.LpCostError('exit_state_empty')) and not N._unpriced(LP.LpCostError('invalid_period'))
    assert N._unpriced(N.TL.TimelineError('no_pool_state_at_the_landing_point'))
    assert not N._unpriced(CC.CostError('exit_state_empty'))                # the kind must match too


# -- the word on controlled nets ---------------------------------------------------------------------------------------
def fake_lines(pools=POOLS):
    return [SimpleNamespace(pool=p, swaps=[SimpleNamespace(block_time=T0 - 5)]) for p in pools]


@pytest.fixture
def stub(monkeypatch):
    calls = []

    def install(value, unpriced=()):
        def lp_position(line, config, *, start_time, end_time, failures=CC.FROZEN_FAILURES,
                        buy_guard_ppm=CC.BUY_GUARD_PPM):
            day = (start_time - T0) // DAY
            calls.append((line.pool, day, failures, buy_guard_ppm))
            if (line.pool, day) in unpriced:
                raise CC.CostError('lp_change_at_the_landing_point')
            v = value(line.pool, day)
            if failures != CC.FROZEN_FAILURES:
                v -= 0.003
            return dict(pool=line.pool, start_time=start_time, end_time=end_time, status='entered', entered=True,
                        net_return=v, net_lamports=round(v * LP.STAKE),
                        decomposition_lamports=dict(hold_pnl=round(0.5 * v * LP.STAKE), lp_vs_hold=round(0.002 * LP.STAKE)),
                        fees_earned_estimate=1_000.0, inventory_loss_estimate=400.0)
        monkeypatch.setattr(LP, 'lp_position', lp_position)
        return calls
    return install


def run(**kw):
    kw.setdefault('pools', POOLS)
    kw.setdefault('g0_passed', True)
    kw.setdefault('freeze_sheet_sha256', SHEET)
    kw.setdefault('t0', T0)
    kw.setdefault('d_days', 12)
    kw.setdefault('draws', DRAWS)
    lines = kw.pop('lines', None) or fake_lines(kw['pools'])
    return N.report(lines, CONFIG_A, **kw)


def test_go_needs_both_bounds_and_the_seed_is_the_sheet(stub):
    stub(lambda p, d: 0.01 + 0.002 * (d % 3))
    out = run()
    assert out['decision'] == 'GO_PILOTE' and out['n'] == 48 and out['seed'] == int(SHEET[:8], 16)
    rows = N.positions(fake_lines(), CONFIG_A, pools=POOLS, t0=T0, d_days=12)
    assert (out['lower_bound_95'], out['upper_bound_95']) == G.stratified_bounds(G.blocks(rows, T0, 12),
                                                                                  seed=int(SHEET[:8], 16), draws=DRAWS)
    assert out['floors']['passed'] is True and out['power']['flag'] == G.G1.UNDER_TARGET   # 48 < 155
    d = out['descriptive']
    assert d['lp_vs_hold']['mean'] == pytest.approx(0.002) and d['verdict'] is None
    assert d['hold_pnl']['mean'] == pytest.approx(0.5 * out['mean_net_return'], rel=1e-6)
    assert d['fees_earned_estimate_lamports'] == 1_000.0 and d['inventory_loss_estimate_lamports'] == 400.0
    assert out['limits'] == N.LIMITS and set(out['limits']) == {'L1', 'L2', 'L3'}
    assert out['labels'] == list(LP.LABELS) and out['counts_for_operational_master'] is False


def test_leave_top_out_no_go_and_floors(stub):
    # pool pA carries the gain; an unpriced day is still an entry: 12 entries everywhere, tie -> pA by id
    stub(lambda p, d: (0.5 if p == 'pA' else -0.004) + 0.001 * (d % 3), unpriced={('pB', 0)})
    c = run()
    assert c['lower_bound_95'] > 0 and c['without_top_pool']['pool'] == 'pA'
    assert c['without_top_pool']['lower_bound_95'] <= 0 and c['decision'] == 'INCONCLUSIF'
    assert c['unpriced'] == dict(count=1, value_lamports=-100_630_000, reasons=['lp_change_at_the_landing_point'])
    assert c['per_pool']['pB']['unpriced_total_loss'] == 1 and c['per_pool']['pB']['entries'] == 12
    stub(lambda p, d: -0.02 + 0.002 * (d % 3))
    assert run()['decision'] == 'NO-GO'
    stub(lambda p, d: -0.05)
    short = run(d_days=7)                                                     # 28 pool-days < 30: before NO-GO
    assert short['decision'] == 'INCONCLUSIF' and short['upper_bound_95'] < 0
    stub(lambda p, d: 0.01 * ((d + POOLS.index(p)) % 3 - 1))
    assert run()['decision'] == 'INCONCLUSIF'


def test_sensitivities_are_descriptive_and_use_the_declared_variants(stub):
    calls = stub(lambda p, d: 0.01)
    out = run()
    s = out['sensitivities']
    assert set(s) == {'one_failure_per_tx', 'guard_50000', 'rent_lost'}
    assert s['one_failure_per_tx']['mean_net_return'] == pytest.approx(0.007) and s['guard_50000']['verdict'] is None
    assert s['guard_50000']['mean_net_return'] == pytest.approx(0.01)
    assert {(f, g) for _p, _d, f, g in calls} == {
        (CC.FROZEN_FAILURES, CC.BUY_GUARD_PPM), (CC.SENSITIVITY_FAILURES, CC.BUY_GUARD_PPM),
        (CC.FROZEN_FAILURES, CC.BUY_GUARD_SENSITIVITY_PPM),
        (CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS), CC.BUY_GUARD_PPM)}
    assert out['decision'] == 'GO_PILOTE'                                      # the word is the frozen run's only


def test_stop_and_inputs(stub):
    stub(lambda p, d: 0.01)
    stop = run(g0_passed=False)
    assert stop['decision'] == 'STOP' and stop['published_numbers'] is False and 'floors' not in stop
    assert run(g0_passed=1)['decision'] == 'STOP'
    with pytest.raises(N.N1Error, match='sheet_order'):
        run(lines=fake_lines(list(reversed(POOLS))))
    with pytest.raises(N.N1Error, match='sheet_order'):
        run(lines=fake_lines(POOLS[:3]))
    for d in (6, 31, 12.0):
        with pytest.raises(N.N1Error, match='d_days'):
            run(d_days=d)
    with pytest.raises(N.N1Error, match='t0'):
        run(t0=float(T0))
    with pytest.raises(N.N1Error, match='3_distinct'):
        run(pools=['pA', 'pB'])
    with pytest.raises(N.N1Error, match='3_distinct'):
        run(pools=['pA', 'pA', 'pB'])
    with pytest.raises(G.VerdictError, match='sheet'):
        run(freeze_sheet_sha256='A' * 64)
    out = run()
    assert out['meaning'] == N.MEANING and 'Holm' in out['multiplicity']
    G.G1.check_vocabulary(out)
    leaked = ['pA', 'pB', 'pC', 'pool ' + G.G1.FORBIDDEN_WORDS[1]]
    with pytest.raises(G.G1.ReportError, match='forbidden'):
        run(pools=leaked)                                                      # the whole document is checked
