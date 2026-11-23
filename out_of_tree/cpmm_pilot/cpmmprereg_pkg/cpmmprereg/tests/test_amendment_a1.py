"""cpmmprereg 0.2: R02 amendment A1 (a) confirmation, (b) trigger count before T0, (c) buy guard ON."""
import statistics

import pytest

from cpmmcost import model as CC
from cpmmprereg import rule as R
from cpmmprereg.tests.test_rule import CONFIG, SHEET, SOL, calm, drop_then, market
from w2arms import ce as W

DAY = 86_400


def test_the_guard_is_on_by_default_and_the_sensitivities_are_declared():
    rebound = market(drop_then([(710, 'buy', 30 * SOL)] + calm(720, 900)))
    p = R.positions(rebound, CONFIG, [35])[0]
    assert p['guard_ppm'] == CC.BUY_GUARD_PPM == 20_000 and p['latency_slots'] == 4 and p['decision_time'] == 705
    assert R.positions(rebound, CONFIG, [35], buy_guard_ppm=50_000)[0]['guard_ppm'] == 50_000
    flat = market(drop_then(calm(710, 2_600)))
    slow = R.positions(flat, CONFIG, [35], latency_slots=10)[0]
    assert slow['latency_slots'] == 10 and slow['buy_landing_slot'] == flat.swaps[35].slot + 10
    one = R.positions(flat, CONFIG, [35], failures=CC.Failures(buy=1, sell=1))[0]
    assert one['failures'] == dict(buy=1, sell=1, cleanup=0) and one['buy_landing_slot'] == flat.swaps[35].slot + 8
    assert R.positions(flat, CONFIG, [35])[0]['net_return'] > one['net_return']
    # a big real buy inside the landing slot: R-CP1 decides, the guard refuses, the attempt is charged and listed
    jumped = market(drop_then([(707, 'buy', 40 * SOL)] + calm(720, 900)))
    refused = R.positions(jumped, CONFIG, [35])[0]
    assert refused['status'] == 'guard_failed' and refused['net_lamports'] == -CC.TX_FEE_LAMPORTS
    assert R.positions(jumped, CONFIG, [35], buy_guard_ppm=None)[0]['status'] == 'entered'
    with pytest.raises(R.PreregError, match='latency_not_a_declared_value'):
        R.exit_point(rebound, 35, CONFIG, latency_slots=6)


def test_the_10_slot_exit_moves_with_the_latency():
    rebound = market(drop_then([(715, 'buy', 30 * SOL)] + calm(720, 900)))          # slot 1430, after both landings
    assert R.exit_point(rebound, 35, CONFIG) == (rebound.swaps[36].slot + 4, None)
    assert R.exit_point(rebound, 35, CONFIG, latency_slots=10) == (rebound.swaps[36].slot + 10, None)
    early = market(drop_then([(710, 'buy', 30 * SOL)] + calm(720, 900)))            # slot 1420: inside the 10-slot landing
    assert R.exit_point(early, 35, CONFIG)[0] == early.swaps[36].slot + 4
    assert R.exit_point(early, 35, CONFIG, latency_slots=10)[0] != early.swaps[36].slot + 10
    flat = market(drop_then(calm(710, 2_600)))
    assert R.exit_point(flat, 35, CONFIG, latency_slots=10) == (
        None, 705 + R.CLOCK_S + R.hrr.clock_exit_latency_s(10))
    assert R.hrr.clock_exit_latency_s(10) > R.CLOCK_LATENCY_S


def test_the_trigger_count_reads_only_the_7_days_before_t0_and_no_outcome():
    t0 = 2 * DAY
    steps = drop_then(calm(710, 1_400))                                      # one decision at t = 705
    shifted = [(t + t0 - 3 * 3_600, side, amount) for t, side, amount in steps]  # three hours before T0
    old = [(t + 1_000, side, amount) for t, side, amount in steps]            # a decision before T0 - 7 d? no: day 0
    line_in = market(shifted)
    count = R.trigger_count([line_in], CONFIG, t0)
    assert count['triggers'] == 1 and count['outcomes_computed'] is False and count['window'] == [t0 - 7 * DAY, t0]
    assert 'net_return' not in str(count)
    # a decision older than T0 - 7 d is not counted
    far = 9 * DAY
    assert R.trigger_count([market(old)], CONFIG, far)['triggers'] == 0
    assert R.trigger_count([market(old)], CONFIG, 7 * DAY + 1_000 + 705)['triggers'] == 1        # exactly at the start
    assert R.trigger_count([market(old)], CONFIG, 7 * DAY + 1_000 + 706)['triggers'] == 0
    # any swap at or after T0 is refused, never filtered
    with pytest.raises(R.PreregError, match='data_at_or_after_t0_refused'):
        R.trigger_count([line_in], CONFIG, shifted[-1][0])
    with pytest.raises(R.PreregError, match='pool_given_twice'):
        R.trigger_count([line_in, line_in], CONFIG, t0)
    with pytest.raises(R.PreregError, match='t0_must_be_an_integer_block_time'):
        R.trigger_count([line_in], CONFIG, float(t0))


def test_expected_entries_and_the_power_stop():
    count = dict(triggers=40, outcomes_computed=False, days=7)
    assert R.expected_entries(count, 7) == 40 and R.expected_entries(count, 14) == 80 and R.expected_entries(count, 3) == 17
    assert R.power_stop(R.expected_entries(count, 3)) == 'UNDERPOWERED_DECLARED_OWNER_DECIDES'
    assert R.power_stop(R.expected_entries(count, 7)) == 'BELOW_POWER_TARGET_PUBLISHED_AS_SUCH'
    assert R.power_stop(R.expected_entries(dict(count, triggers=160), 7)) == 'POWERED'
    for bad in (dict(count, outcomes_computed=True), dict(count, days=14), dict(triggers=40)):
        with pytest.raises(R.PreregError, match='not_a_trigger_count'):
            R.expected_entries(bad, 7)
    with pytest.raises(R.PreregError, match='pilot_days_must_be_a_positive_integer'):
        R.expected_entries(count, 0)


def test_sigma_c_is_the_larger_of_the_pilot_and_2_5_percent():
    low = R.confirmation_n(0.01)
    assert low['sigma_c'] == 0.025 and low['n'] == R.n_required(sigma=0.025, alpha=0.05 / 3) == 221
    high = R.confirmation_n(0.04)
    assert high['sigma_c'] == 0.04 and high['n'] == R.n_required(sigma=0.04, alpha=0.05 / 3) > 221
    assert high['alpha'] == 0.05 / 3 and high['delta'] == 0.005 and high['power'] == 0.8
    for bad in (-0.1, float('nan'), float('inf'), '0.03', None):
        with pytest.raises(R.PreregError, match='invalid_sigma'):
            R.confirmation_n(bad)
    rows = [dict(net_return=v) for v in (0.01, -0.02, 0.03)] + [dict(unpriced='x')]
    assert R.sigma_of_pilot(rows) == statistics.stdev([0.01, -0.02, 0.03])
    with pytest.raises(R.PreregError, match='sigma_needs_two_priced_positions'):
        R.sigma_of_pilot([dict(net_return=0.01)])


def arms(n, pools, value, placebo_value, *, t=lambda i: i, **extra):
    primary = [dict(pool='p%d' % (i % pools), decision_index=i, net_return=value(i), decision_time=t(i),
                    entered=True, status='entered') for i in range(n)]
    placebo = [dict(pool='p%d' % (i % pools), decision_index=10_000 + i, net_return=placebo_value(i),
                    decision_time=t(i)) for i in range(n)]
    return primary, placebo


def run(primary, placebo, *, one=None, slow=None, cut=None, sigma=0.01, draws=300):
    one = [dict(p, net_return=p['net_return'] - 0.002) for p in primary] if one is None else one
    slow = [dict(p, net_return=p['net_return'] - 0.003) for p in primary] if slow is None else slow
    cut = len(primary) // 2 if cut is None else cut
    return R.confirmation_verdict(primary, placebo_=placebo, one_failure=one, ten_slots=slow, cut_time=cut,
                                  sigma_pilot=sigma, freeze_sheet_sha256=SHEET, draws=draws)


def test_confirmed_needs_every_condition_and_enough_entries():
    good_p, good_pl = arms(240, 24, lambda i: 0.02 + (i % 5) * 0.002, lambda i: -0.004)
    out = run(good_p, good_pl)
    assert out['decision'] == 'CONFIRMÉ' and all(out['conditions'].values()) and out['n_entered'] == 240
    assert out['counts_for_operational_master'] is False and out['n_required']['n'] == 221
    # below n (sigma of the pilot larger: n grows) -> INCONCLUSIF
    assert run(good_p, good_pl, sigma=0.05)['decision'] == 'INCONCLUSIF'
    assert run(good_p[:220], good_pl)['decision'] == 'INCONCLUSIF'
    # guard-failed rows are not entries
    refused = [dict(p, entered=False, status='guard_failed', net_return=-0.00105) for p in good_p[:30]]
    mixed = run(refused + good_p[30:], good_pl)
    assert mixed['n_entered'] == 210 and mixed['guard_failed'] == 30 and mixed['decision'] == 'INCONCLUSIF'
    # each A1 condition alone
    neg_one = run(good_p, good_pl, one=[dict(p, net_return=-0.001) for p in good_p])
    assert neg_one['decision'] == 'NON CONFIRMÉ' and neg_one['conditions']['a1_net_above_zero_with_1_failure'] is False
    neg_slow = run(good_p, good_pl, slow=[dict(p, net_return=-0.001) for p in good_p])
    assert (neg_slow['decision'], neg_slow['conditions']['c5_net_above_zero_at_10_slots_and_without_the_best_5']) == (
        'NON CONFIRMÉ', False)
    same_p, same_pl = arms(240, 24, lambda i: 0.02 + (i % 5) * 0.002, lambda i: 0.02 + (i % 5) * 0.002)
    tied = run(same_p, same_pl)
    assert tied['difference_to_placebo'] == 0 and tied['decision'] == 'NON CONFIRMÉ'
    assert tied['conditions']['a1_difference_to_the_placebo_above_zero'] is False


def test_halves_unpriced_and_the_bootstrap_are_those_declared():
    p, pl = arms(240, 24, lambda i: 0.03 if i >= 120 else -0.001, lambda i: -0.01)
    out = run(p, pl)
    assert out['conditions']['c3_both_halves_positive'] is False and out['decision'] == 'NON CONFIRMÉ'
    good_p, good_pl = arms(240, 24, lambda i: 0.02, lambda i: -0.004)
    holed = good_p[:-1] + [dict(pool=good_p[-1]['pool'], decision_index=good_p[-1]['decision_index'],
                                unpriced='data_ends', decision_time=239)]
    out = run(holed, good_pl, one=[dict(x, net_return=0.01) for x in good_p], slow=[dict(x, net_return=0.01) for x in good_p])
    assert out['unpriced'] == 1 and out['conditions']['c4_every_position_priced_with_a_zero_residual'] is False
    assert out['decision'] == 'NON CONFIRMÉ'
    # the bound is the audited cluster bootstrap by pool, alpha 0.05 / 3, seed = sheet[:8]
    mixed_p, mixed_pl = arms(240, 24, lambda i: (0.02 if i % 3 else -0.01), lambda i: -0.004)
    out = run(mixed_p, mixed_pl, draws=400)
    groups = {}
    for r in [dict(x, arm='rcp1') for x in mixed_p] + [dict(x, arm='placebo') for x in mixed_pl]:
        groups.setdefault(r['pool'], []).append(r)
    mean = lambda rows: R._mean([r['net_return'] for r in rows if r['arm'] == 'rcp1'])    # noqa: E731
    assert out['lower_bound'] == W.lower_bound(groups, mean, seed=int(SHEET[:8], 16), draws=400, alpha=0.05 / 3)
    assert out['seed'] == int(SHEET[:8], 16)


def test_the_confirmation_inputs_are_checked():
    p, pl = arms(240, 24, lambda i: 0.02, lambda i: -0.004)
    with pytest.raises(R.PreregError, match='sensitivities_are_not_the_same_decisions'):
        run(p, pl, one=p[1:])
    with pytest.raises(R.PreregError, match='sensitivities_are_not_the_same_decisions'):
        run(p, pl, slow=p[1:])
    with pytest.raises(R.PreregError, match='placebo_outside_the_pools'):
        run(p, pl + [dict(pool='zz', decision_index=1, net_return=0.0, decision_time=1)])
    with pytest.raises(R.PreregError, match='freeze_sheet_sha256_required'):
        R.confirmation_verdict(p, placebo_=pl, one_failure=p, ten_slots=p, cut_time=1, sigma_pilot=0.01,
                               freeze_sheet_sha256='x')
    with pytest.raises(R.PreregError, match='cut_time_must_be_anchored'):
        R.confirmation_verdict(p, placebo_=pl, one_failure=p, ten_slots=p, cut_time=None, sigma_pilot=0.01,
                               freeze_sheet_sha256=SHEET)
    assert set(R.CONFIRMATION_VERDICTS) == {'CONFIRMÉ', 'NON CONFIRMÉ', 'INCONCLUSIF'}


def test_a_failed_buy_moves_the_first_swap_checked_by_the_exit():
    line = market(drop_then([(708, 'buy', 30 * SOL)] + calm(720, 900)))              # slot 1416: between 1414 and 1418
    assert R.exit_point(line, 35, CONFIG) == (line.swaps[36].slot + 4, None)
    assert R.exit_point(line, 35, CONFIG, buy_failures=1) != (line.swaps[36].slot + 4, None)


def test_c2_is_a_bound_on_the_difference_not_on_the_mean():
    noise = lambda i: 0.01 if (i % 24) % 2 else -0.01                                 # noqa: E731
    p, pl = arms(240, 24, lambda i: 0.02 + noise(i), lambda i: 0.0195 - noise(i))
    out = run(p, pl)
    assert out['conditions']['c1_lower_bound_of_the_mean_above_zero'] is True
    assert out['difference_to_placebo'] > 0 and out['lower_bound_minus_placebo'] < 0
    assert out['conditions']['c2_lower_bound_over_the_paired_placebo_above_zero'] is False
    assert out['decision'] == 'NON CONFIRMÉ'


def test_the_seed_is_the_prefix_of_the_freeze_sheet():
    sheet = '1234abcd' + 'ef' * 28
    p, pl = arms(240, 24, lambda i: (0.02 if i % 3 else -0.01), lambda i: -0.004)
    out = R.confirmation_verdict(p, placebo_=pl, one_failure=p, ten_slots=p, cut_time=120, sigma_pilot=0.01,
                                 freeze_sheet_sha256=sheet, draws=300)
    assert out['seed'] == 0x1234abcd
    groups = {}
    for r in [dict(x, arm='rcp1') for x in p] + [dict(x, arm='placebo') for x in pl]:
        groups.setdefault(r['pool'], []).append(r)
    mean = lambda rows: R._mean([r['net_return'] for r in rows if r['arm'] == 'rcp1'])    # noqa: E731
    assert out['lower_bound'] == W.lower_bound(groups, mean, seed=0x1234abcd, draws=300, alpha=0.05 / 3)
