"""lpcost 0.1 on synthetic CPMM pools only (cpmmx simulator through the cpmmgen3 test pools): the five steps, the exact
identity, fees against inventory loss, others' LP events, guard, transactions, inputs."""
from fractions import Fraction

import pytest

from closedacct import model as CA
from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A, POOL_A, calm, line_of
from cpmmx import events, timeline as TL
from lpcost import model as M

DAY = 86_400


def flat_day(every=60, end=DAY + 600):
    """A balanced market: alternating buys and sells, the price oscillates and comes back."""
    return line_of(POOL_A, calm(0, end, every=every))


def trend_day(end=DAY + 600, every=60):
    """A falling market: every swap is a sale of the base token."""
    return line_of(POOL_A, [(t, 'sell', 3 * 10 ** 11) for t in range(0, end, every)])


def pos(line, **kw):
    kw.setdefault('start_time', 300)
    kw.setdefault('end_time', 300 + DAY)
    return M.lp_position(line, CONFIG_A, **kw)


def test_transactions_of_a_round_trip():
    assert M.transactions() == (6 * CC.TX_FEE_LAMPORTS, 0)                 # 2 swaps, deposit, withdrawal, WSOL, cleanup
    assert M.transactions(CC.SENSITIVITY_FAILURES) == (9 * CC.TX_FEE_LAMPORTS, 0)
    left_open = CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS)
    assert M.transactions(left_open) == ((5 + 3) * CC.TX_FEE_LAMPORTS, 2 * CC.TOKEN_ACCOUNT_RENT_LAMPORTS)
    assert M.transactions(wsol_separate_close=False) == (5 * CC.TX_FEE_LAMPORTS, 0)


def test_the_identity_is_exact_and_the_parts_are_consistent():
    p = pos(flat_day())
    d = p['decomposition_lamports']
    assert p['net_lamports'] == d['hold_pnl'] + d['lp_vs_hold'] + d['transactions'] + d['rent_lost']
    assert p['net_lamports'] == p['lp_received'] - M.STAKE - 6 * CC.TX_FEE_LAMPORTS
    assert d['hold_pnl'] == p['hold_received'] - M.STAKE and d['lp_vs_hold'] == p['lp_received'] - p['hold_received']
    assert p['net_return'] == p['net_lamports'] / M.STAKE
    assert p['deposited']['base'] + p['left']['base'] == p['tokens_bought']
    assert p['deposited']['quote'] + p['left']['quote'] == M.HALF
    assert p['labels'] == list(M.LABELS) and p['counts_for_operational_master'] is False


def test_a_balanced_market_pays_the_liquidity_provider():
    p = pos(flat_day())
    assert p['fees_earned_estimate'] > 0
    assert p['decomposition_lamports']['lp_vs_hold'] > 0                     # fees > inventory loss when price comes back
    assert p['inventory_loss_estimate'] < p['fees_earned_estimate']


def test_a_trend_costs_inventory():
    p = pos(trend_day())
    assert p['inventory_loss_estimate'] > 0                                  # the LP sold the falling token on the way down
    flat = pos(flat_day())
    assert p['inventory_loss_estimate'] > flat['inventory_loss_estimate']


def test_a_day_without_swaps_earns_nothing_but_rounding():
    line = line_of(POOL_A, calm(0, 300, every=60) + calm(300 + DAY + 60, 300 + DAY + 600, every=60))
    p = pos(line)
    assert p['fees_earned_estimate'] == 0
    assert -5 <= p['decomposition_lamports']['lp_vs_hold'] <= 0              # deposit up, withdrawal down


def test_others_lp_events_rescale_our_share():
    # the same balanced swaps around the event in both lines; an LP event needs a later swap to fix the reserves
    base_steps = (calm(0, 300, every=60) + calm(360, 600, every=60) + calm(40_060, 40_600, every=60)
                  + calm(300 + DAY + 60, 300 + DAY + 600, every=60))
    quiet = pos(line_of(POOL_A, base_steps))
    doubled = pos(line_of(POOL_A, sorted(base_steps + [(40_000, 'lp', (1, 1))])))
    # another LP doubles the pool: our fraction halves, the reserves double, our claim is about the same
    assert doubled['share_at_exit'] == pytest.approx(quiet['share_at_exit'] / 2, rel=1e-9)
    # rel 5e-3: in the doubled pool the later swaps move the price less (a real effect, not rounding)
    assert doubled['withdrawn']['quote'] == pytest.approx(quiet['withdrawn']['quote'], rel=5e-3)
    halved = pos(line_of(POOL_A, sorted(base_steps + [(40_000, 'lp1', (1, 2))])))
    assert halved['share_at_exit'] == pytest.approx(quiet['share_at_exit'] * 2, rel=1e-9)
    assert halved['withdrawn']['quote'] == pytest.approx(quiet['withdrawn']['quote'], rel=5e-3)
    # an LP event after the last swap before the exit cannot be priced (cpmmcost refuses to bridge it)
    with pytest.raises(CC.CostError, match='lp_change'):
        pos(line_of(POOL_A, calm(0, 300, every=60) + calm(360, 600, every=60) + [(40_000, 'lp', (1, 1))]
                    + calm(300 + DAY + 60, 300 + DAY + 600, every=60)))


def test_share_after_others_rules_and_window():
    line = line_of(POOL_A, calm(0, 600, every=60) + [(305, 'lp', (1, 1)), (400, 'lp1', (1, 4))])
    s = Fraction(1, 1000)
    rows = line.lp_changes
    keys = [row[:3] for row in rows]
    f0 = Fraction(rows[0][3].token_0_amount, rows[0][3].token_0_vault_before)
    f1 = Fraction(rows[1][3].token_0_amount, rows[1][3].token_0_vault_before)
    assert f0 == 1 and f1 == pytest.approx(0.25, rel=1e-9)
    assert M.share_after_others(line, s, (-1, -1, -1), keys[0]) == s / (1 + f0)              # a deposit
    assert M.share_after_others(line, s, (-1, -1, -1), keys[1]) == s / (1 + f0) / (1 - f1)   # then a withdrawal
    assert M.share_after_others(line, s, keys[0], keys[1]) == s / (1 - f1)                    # low bound exclusive
    assert M.share_after_others(line, s, keys[1], (10 ** 9, 0, 0)) == s
    bad = TL.Timeline('p', 'b', TL.WSOL, (), ((1, 0, 0, events.LpChangeEvent('p', 1, 100, 100, 5, 5, 0, 0, 2)),), ())
    with pytest.raises(M.LpCostError, match='unknown'):
        M.share_after_others(bad, s, (-1, -1, -1), (5, 0, 0))
    empty = TL.Timeline('p', 'b', TL.WSOL, (), ((1, 0, 0, events.LpChangeEvent('p', 1, 0, 0, 5, 5, 0, 0, 0)),), ())
    with pytest.raises(M.LpCostError, match='empty_vault'):
        M.share_after_others(empty, s, (-1, -1, -1), (5, 0, 0))
    drained = TL.Timeline('p', 'b', TL.WSOL, (), ((1, 0, 0, events.LpChangeEvent('p', 1, 100, 100, 100, 100, 0, 0, 1)),),
                          ())
    with pytest.raises(M.LpCostError, match='emptied'):
        M.share_after_others(drained, s, (-1, -1, -1), (5, 0, 0))


def test_the_fee_estimate_is_our_share_of_the_lp_part():
    line = flat_day()
    fees = CC.fees_from_amm_config(CONFIG_A)
    land_in, land_out = M.landing_time(300), M.landing_time(300 + DAY)
    share = Fraction(1, 2_000)
    lp_part = Fraction(1_000_000 - 120_000 - 40_000, 1_000_000)
    expected = Fraction(0)
    for s in line.swaps:
        if land_in < s.block_time <= land_out:
            b, q = TL.after_swap(s, 120_000, 40_000)
            expected += share * s.event.trade_fee * lp_part * (1 if s.side == 'buy' else Fraction(q, b))
    assert M.fees_earned_estimate(line, fees, share_at_entry=share, land_in=land_in, land_out=land_out) == expected
    assert expected > 0


def test_the_buy_guard_refuses_a_bad_fill_and_charges_it():
    land = M.landing_time(300)
    jump = calm(0, 300, every=60) + [(land, 'buy', 30 * 10 ** 9)] + calm(land + 60, 300 + DAY + 600, every=60)
    refused = pos(line_of(POOL_A, jump))
    assert refused['status'] == 'guard_failed' and refused['entered'] is False
    assert refused['net_lamports'] == -CC.TX_FEE_LAMPORTS
    one = pos(line_of(POOL_A, jump), failures=CC.SENSITIVITY_FAILURES)
    assert one['net_lamports'] == -2 * CC.TX_FEE_LAMPORTS
    off = pos(line_of(POOL_A, jump), buy_guard_ppm=None)
    assert off['status'] == 'entered'
    with pytest.raises(M.LpCostError, match='guard'):
        pos(flat_day(), buy_guard_ppm=12_345)
    # a fill 2.9 % worse than the decision state: refused at 20 000 ppm, accepted at the 50 000 ppm sensitivity
    mid = calm(0, 300, every=60) + [(land, 'buy', 3 * 10 ** 9)] + calm(land + 60, 300 + DAY + 600, every=60)
    assert pos(line_of(POOL_A, mid))['status'] == 'guard_failed'
    assert pos(line_of(POOL_A, mid), buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM)['status'] == 'entered'
    small = calm(0, 300, every=60) + [(land, 'buy', 1 * 10 ** 9)] + calm(land + 60, 300 + DAY + 600, every=60)
    assert pos(line_of(POOL_A, small))['status'] == 'entered'                # 1 % worse: accepted


def test_entry_takes_the_worse_landing_state():
    land = M.landing_time(300)
    line = line_of(POOL_A, calm(0, 300, every=60) + [(land, 'buy', 3 * 10 ** 8)] + calm(land + 60, 300 + DAY + 600,
                                                                                         every=60))
    fees = CC.fees_from_amm_config(CONFIG_A)
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    from cpmmx import curve
    fills = [curve.swap_base_input(M.HALF, s[1], s[0], fees, on_input).output_amount for s in M._states(line, fees, land)]
    assert pos(line)['tokens_bought'] == min(fills) and min(fills) < max(fills)


def test_an_independent_recomputation_of_the_five_steps():
    from bot.p4 import historical_research_replay as hrr
    from cpmmx import curve
    assert M.HALF == 50_000_000 and M.landing_time(300) == 300 + hrr.clock_exit_latency_s(CC.LATENCY_SLOTS)
    lo_t = M.landing_time(300 + DAY)
    # a sale exactly at the exit landing second: the two exit states differ, the withdrawal takes the worse one
    line = line_of(POOL_A, [(t, 'sell', 3 * 10 ** 11) for t in range(0, lo_t, 60)] + [(lo_t, 'sell', 3 * 10 ** 13)]
                   + [(t, 'sell', 3 * 10 ** 11) for t in range(lo_t + 60, lo_t + 600, 60)])
    p = pos(line)
    fees = CC.fees_from_amm_config(CONFIG_A)
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    li, lo = M.landing_time(300), M.landing_time(300 + DAY)
    buys = [(curve.swap_base_input(M.HALF, s[1], s[0], fees, on_input).output_amount, s) for s in M._states(line, fees, li)]
    tokens, (b0, q0) = min(buys)
    share = min(Fraction(tokens, b0), Fraction(M.HALF, q0))
    dep_b, dep_q = -((-share * b0).numerator // (share * b0).denominator), -((-share * q0).numerator // (share * q0).denominator)
    assert (p['tokens_bought'], p['deposited']['base'], p['deposited']['quote']) == (tokens, dep_b, dep_q)   # ceilings
    exits = M._states(line, fees, lo)
    b1, q1 = min(exits, key=lambda s: Fraction(s[1], s[0]))
    assert Fraction(exits[0][1], exits[0][0]) != Fraction(exits[1][1], exits[1][0])
    wd_b, wd_q = (share * b1).numerator // (share * b1).denominator, (share * q1).numerator // (share * q1).denominator
    assert (p['withdrawn']['base'], p['withdrawn']['quote']) == (wd_b, wd_q)                                  # floors

    def sale(amount):
        return min(curve.swap_base_input(amount, bb, qq, fees, on_input).output_amount
                   for b, q in exits for bb, qq in ((b, q), (b - wd_b, q - wd_q)))
    assert p['hold_received'] == M.HALF + sale(tokens)
    assert p['lp_received'] == wd_q + (M.HALF - dep_q) + sale(wd_b + tokens - dep_b)


def test_failures_and_rent_change_only_the_transaction_part():
    line = flat_day()
    base = pos(line)
    one = pos(line, failures=CC.SENSITIVITY_FAILURES)
    assert base['net_lamports'] - one['net_lamports'] == 3 * CC.TX_FEE_LAMPORTS
    lost = pos(line, failures=CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS))
    assert lost['decomposition_lamports']['rent_lost'] == -2 * CC.TOKEN_ACCOUNT_RENT_LAMPORTS
    assert base['net_lamports'] - lost['net_lamports'] == 2 * CC.TOKEN_ACCOUNT_RENT_LAMPORTS + 2 * CC.TX_FEE_LAMPORTS


def test_inputs_are_checked():
    line = flat_day()
    for kw in (dict(start_time=10, end_time=10), dict(start_time=10.0, end_time=100), dict(start_time=10, end_time=5)):
        with pytest.raises(M.LpCostError, match='period'):
            M.lp_position(line, CONFIG_A, **kw)
    with pytest.raises(CC.CostError, match='u1'):
        M.lp_position(line, dict(CONFIG_A, trade_fee_rate=10_000), start_time=300, end_time=300 + DAY)
    with pytest.raises(M.LpCostError, match='no_swap'):
        M.lp_position(TL.build(events.b58encode(POOL_A), {}, base_mint='b'), CONFIG_A, start_time=1, end_time=2)
