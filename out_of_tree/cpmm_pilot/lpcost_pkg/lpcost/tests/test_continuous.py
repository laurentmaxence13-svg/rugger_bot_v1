"""lpcost 0.2 continuous position on synthetic CPMM pools only (cpmmx simulator via the cpmmgen3 test pools): stake read
on the decision state, the exact identity, daily values summing to the gap, the marks at day boundaries, others' LP
events, guard, failures, inputs."""
from fractions import Fraction

import pytest

from closedacct import model as CA
from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A, POOL_A, calm, line_of
from cpmmx import curve
from lpcost import continuous as K, model as M

DAY = 86_400
SOL = 10 ** 9


def balanced(days=2, every=120, quote=200 * SOL):
    return line_of(POOL_A, calm(0, 300 + days * DAY + 600, every=every), quote=quote)


def trend(days=2, every=120):
    return line_of(POOL_A, [(t, 'sell', 3 * 10 ** 11) for t in range(0, 300 + days * DAY + 600, every)])


def pos(line, days=2, **kw):
    return K.continuous_position(line, CONFIG_A, start_time=300, end_time=300 + days * DAY, **kw)


def test_stake_is_0_5_percent_of_the_decision_reserve():
    for quote in (200 * SOL, 400 * SOL):
        line = balanced(quote=quote, every=600)
        fees = CC.fees_from_amm_config(CONFIG_A)
        _b, q = CC._state(line, fees, time_limit=300)
        p = pos(line)
        assert p['stake_lamports'] == q * 5_000 // 1_000_000 and p['stake_ppm'] == K.STAKE_PPM == 5_000
        assert abs(p['stake_lamports'] - quote // 200) < quote // 2_000             # ~ 0.5 % of the reserve
    small = pos(balanced(every=600), stake_ppm=1_000)
    assert small['stake_lamports'] * 5 == pytest.approx(pos(balanced(every=600))['stake_lamports'], abs=5)


def test_identity_daily_sum_and_decomposition_are_exact():
    p = pos(balanced(days=3), days=3)
    d = p['decomposition_lamports']
    assert len(p['days']) == 3 and sum(x['gap_lamports'] for x in p['days']) == p['gap_lamports']
    assert p['gap_lamports'] == d['mark_change'] + d['entry'] + d['exit'] + d['transactions'] + d['rent_lost']
    assert p['net_lamports'] == p['gap_lamports'] + d['deposit_rounding'] + d['hold_price_move']
    assert p['net_lamports'] == p['received'] - p['stake_lamports'] - 6 * CC.TX_FEE_LAMPORTS
    assert d['transactions'] == -6 * CC.TX_FEE_LAMPORTS and d['rent_lost'] == 0
    assert d['entry'] < 0 and d['exit'] < 0 and -1 <= d['deposit_rounding'] <= 0      # rounding up on the deposit
    costs = -(d['entry'] + d['exit'] + d['transactions'] + d['rent_lost'])
    assert all(x['cost_share_lamports'] == -costs / 3 for x in p['days'])              # C2: costs split equally
    assert all(x['gap_lamports'] == x['mark_change_lamports'] + x['cost_share_lamports'] for x in p['days'])
    assert [x['day_start'] for x in p['days']] == [300, 300 + DAY, 300 + 2 * DAY]
    assert p['counts_for_operational_master'] is False and 'LP_SIDE_RESEARCH' in p['labels']


def test_a_busy_balanced_pool_pays_and_a_trend_costs_inventory():
    # 2 SOL each way every 60 s on 200 SOL: a daily rotation of about 7 -> the LP part of the fees beats the costs
    heavy = [(t, 'buy' if (t // 60) % 2 else 'sell', 2 * SOL if (t // 60) % 2 else 10 ** 13)
             for t in range(0, 300 + 2 * DAY + 600, 60)]
    busy = pos(line_of(POOL_A, heavy))
    assert busy['gap_lamports'] > 0 and busy['decomposition_lamports']['mark_change'] > 0
    assert busy['fees_earned_estimate'] > 0
    falling = pos(trend())
    assert falling['decomposition_lamports']['mark_change'] < 0                         # inventory loss vs holding
    assert falling['decomposition_lamports']['hold_price_move'] < 0


def test_marks_use_the_first_observed_state_after_each_boundary():
    line = balanced(days=2, every=600)
    p = pos(line)
    t1 = 300 + DAY
    nxt = next(s for s in line.swaps if s.block_time > t1)
    fees = CC.fees_from_amm_config(CONFIG_A)
    land_in = M.landing_time(300)
    buys = [(curve.swap_base_input(p['stake_lamports'] // 2, s[1], s[0], fees, True).output_amount, s)
            for s in M._states(line, fees, land_in)]
    tokens, (b0, q0) = min(buys)
    share0 = min(Fraction(tokens, b0), Fraction(p['stake_lamports'] - p['stake_lamports'] // 2, q0))
    dep_b, dep_q = p['deposited']['base'], p['deposited']['quote']
    g0 = 2 * share0 * q0 - Fraction(dep_b * q0, b0) - dep_q
    g1 = 2 * share0 * nxt.quote_before - Fraction(dep_b * nxt.quote_before, nxt.base_before) - dep_q
    assert p['days'][0]['mark_change_lamports'] == g1 - g0
    assert p['decomposition_lamports']['deposit_rounding'] == g0


def test_an_lp_event_of_others_between_a_boundary_and_the_next_swap_is_never_bridged():
    t1 = 300 + DAY
    steps = calm(0, t1 - 60, every=600) + calm(t1 + 120, 300 + 2 * DAY + 600, every=600)
    quiet = pos(line_of(POOL_A, steps))
    doubled = pos(line_of(POOL_A, sorted(steps + [(t1 + 30, 'lp', (1, 1))])))
    assert doubled['share_at_exit'] == pytest.approx(quiet['share_at_exit'] / 2, rel=1e-9)
    # the value of our claim at the boundary mark is about the same: share halves, reserves double
    assert doubled['days'][0]['mark_change_lamports'] == pytest.approx(quiet['days'][0]['mark_change_lamports'],
                                                                         abs=quiet['stake_lamports'] * 1e-4)


def test_the_guard_refuses_a_bad_fill_and_charges_it_over_the_days():
    land = M.landing_time(300)
    jump = calm(0, 300, every=60) + [(land, 'buy', 30 * SOL)] + calm(land + 60, 300 + 2 * DAY + 600, every=600)
    refused = pos(line_of(POOL_A, jump))
    assert refused['status'] == 'guard_failed' and refused['entered'] is False
    assert refused['net_lamports'] == refused['gap_lamports'] == -CC.TX_FEE_LAMPORTS
    assert [x['gap_lamports'] for x in refused['days']] == [Fraction(-CC.TX_FEE_LAMPORTS, 2)] * 2
    assert pos(line_of(POOL_A, jump), buy_guard_ppm=None)['status'] == 'entered'
    one = pos(line_of(POOL_A, jump), failures=CC.SENSITIVITY_FAILURES)
    assert one['net_lamports'] == -2 * CC.TX_FEE_LAMPORTS
    # half = 0.5 SOL on 200 SOL; a 3 SOL buy at the landing second: fill ~3 % worse -> refused at 20 000 ppm only
    mid = calm(0, 300, every=60) + [(land, 'buy', 3 * SOL)] + calm(land + 60, 300 + 2 * DAY + 600, every=600)
    assert pos(line_of(POOL_A, mid))['status'] == 'guard_failed'
    assert pos(line_of(POOL_A, mid), buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM)['status'] == 'entered'
    small = calm(0, 300, every=60) + [(land, 'buy', 1 * SOL)] + calm(land + 60, 300 + 2 * DAY + 600, every=600)
    assert pos(line_of(POOL_A, small))['status'] == 'entered'


def test_failures_and_rent_change_only_the_transaction_part():
    line = balanced(every=600)
    base, one = pos(line), pos(line, failures=CC.SENSITIVITY_FAILURES)
    assert base['gap_lamports'] - one['gap_lamports'] == 3 * CC.TX_FEE_LAMPORTS
    lost = pos(line, failures=CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS))
    assert lost['decomposition_lamports']['rent_lost'] == -2 * CC.TOKEN_ACCOUNT_RENT_LAMPORTS
    assert base['gap_lamports'] - lost['gap_lamports'] == 2 * CC.TOKEN_ACCOUNT_RENT_LAMPORTS + 2 * CC.TX_FEE_LAMPORTS


def test_inputs_are_checked():
    line = balanced(every=600)
    for kw in (dict(start_time=300, end_time=300 + DAY + 1), dict(start_time=300, end_time=300),
               dict(start_time=300.0, end_time=300 + DAY)):
        with pytest.raises(M.LpCostError, match='whole_days'):
            K.continuous_position(line, CONFIG_A, **kw)
    for ppm in (0, 5_001, 5_000.0):
        with pytest.raises(M.LpCostError, match='0_5_percent'):
            pos(line, stake_ppm=ppm)
    with pytest.raises(M.LpCostError, match='guard'):
        pos(line, buy_guard_ppm=12_345)
    with pytest.raises(CC.CostError, match='u1'):
        K.continuous_position(line, dict(CONFIG_A, trade_fee_rate=10_000), start_time=300, end_time=300 + DAY)


def test_an_independent_recomputation_of_the_exit():
    lo = M.landing_time(300 + 2 * DAY)
    # a large sale exactly at the exit landing second: the two exit states differ
    line = line_of(POOL_A, [(t, 'sell', 3 * 10 ** 11) for t in range(0, lo, 600)] + [(lo, 'sell', 3 * 10 ** 13)]
                   + [(t, 'sell', 3 * 10 ** 11) for t in range(lo + 60, lo + 600, 60)])
    p = pos(line)
    fees = CC.fees_from_amm_config(CONFIG_A)
    exits = M._states(line, fees, lo)
    assert Fraction(exits[0][1], exits[0][0]) != Fraction(exits[1][1], exits[1][0])
    b1, q1 = min(exits, key=lambda st: Fraction(st[1], st[0]))
    land_in = M.landing_time(300)
    buys = [(curve.swap_base_input(p['stake_lamports'] // 2, st[1], st[0], fees, True).output_amount, st)
            for st in M._states(line, fees, land_in)]
    tokens, (b0, q0) = min(buys)
    share = min(Fraction(tokens, b0), Fraction(p['stake_lamports'] - p['stake_lamports'] // 2, q0))
    wd_b, wd_q = (share * b1).numerator // (share * b1).denominator, (share * q1).numerator // (share * q1).denominator
    assert (p['withdrawn']['base'], p['withdrawn']['quote']) == (wd_b, wd_q)                    # floors, worse state
    left_b, left_q = p['left']['base'], p['left']['quote']
    sale = min(curve.swap_base_input(wd_b + left_b, bb, qq, fees, True).output_amount
               for b, q in exits for bb, qq in ((b, q), (b - wd_b, q - wd_q)))
    assert p['received'] == wd_q + left_q + sale                                                 # worst candidate
    assert p['decomposition_lamports']['exit'] == -(2 * share * q1 + left_b * Fraction(q1, b1) + left_q - p['received'])
