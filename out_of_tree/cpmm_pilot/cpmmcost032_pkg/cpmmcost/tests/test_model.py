"""cpmmcost: full cost model of one CPMM pilot position, on raw synthetic transactions decoded by cpmmx (no real data)."""
import base64
import struct
from fractions import Fraction

import pytest

from closedacct import model as CA
from cpmmcost import model as M
from cpmmx import curve, events, timeline as TL
from cpmmx.tests.test_cpmmx import BASE, BASE_B58, POOL, POOL_B58, QUOTE, Sim, logs, swap_payload, tx

FEES = curve.Fees(2_500, 0, 120_000, 40_000)
CONFIG = dict(trade_fee_rate=2_500, creator_fee_rate=0, protocol_fee_rate=120_000, fund_fee_rate=40_000,
              sha256='ab' * 32, slot=1)
SOL = 10 ** 9
ANCHOR = 'cd' * 32


def market(steps, *, quote=100 * SOL, base=10 ** 15, fees=FEES, on_input=True):
    """Raw transactions of a pool from (slot, side, amount) real swaps; block time = slot (one swap per slot or more)."""
    sim = Sim(base, quote, fees, on_input)
    txs = {}
    for i, (slot, side, amount) in enumerate(steps):
        payload, _ = sim.swap(side, amount)
        txs['sig%03d' % i] = tx(slot, i, logs(payload), when=slot)
    return TL.build(POOL_B58, txs, base_mint=BASE_B58), txs


def test_the_declared_threshold_and_the_cp1_table():
    assert M.fixed_cost_share() == Fraction(815, 100_000)                       # 0.815 %
    assert M.CLOSED_THRESHOLD == Fraction(82, 10_000) and -(-M.fixed_cost_share() * 10_000 // 1) == 82
    assert M.bar(20, wsol_separate_close=False) == Fraction(1815, 100_000)       # CP-1: 1.815 / 1.015 / 0.915 %
    assert M.bar(100, wsol_separate_close=False) == Fraction(1015, 100_000)
    assert M.bar(200, wsol_separate_close=False) == Fraction(915, 100_000)
    assert M.bar(100) == Fraction(112, 10_000)                                   # working bar 1.12 %
    assert M.TX_FEE_LAMPORTS == CA.CLEANUP_FEE_LAMPORTS == 105_000 and M.LATENCY_SLOTS == 4


def test_a_flat_round_trip_at_100_sol_costs_the_working_bar():
    line, _ = market([(1000, 'buy', 10 ** 6)])
    out = M.position(line, 0, CONFIG, exit_slot=2000)
    assert out['sale_state'] == 'real_reserves'                                  # lower than with our buy left
    # CP-1 sizes the bar with 2 x stake / reserve; the exact curve gives slightly less impact
    assert -float(M.bar(100)) <= out['net_return'] <= -float(M.bar(100)) + 5e-5
    parts = out['decomposition_share_of_stake']
    assert sum(parts.values()) == pytest.approx(out['net_return'], abs=1e-15)
    assert parts['trade_and_creator_fees'] == pytest.approx(-0.005, abs=2e-5)
    assert parts['price_impact'] == pytest.approx(-0.002, abs=2e-5) and parts['price_impact'] < 0
    assert parts['transactions'] == -0.0021 and parts['wsol_close'] == -0.00105 and parts['cleanup'] == -0.00105
    assert parts['rent_lost'] == 0 and out['labels'] == ['MASTER_RESEARCH_PAPER', 'HISTORICAL_REPLAY']
    assert out['counts_for_operational_master'] is False and out['amm_config_sha256'] == CONFIG['sha256']


def test_the_net_matches_closedacct_and_failures_and_closings_are_charged():
    line, _ = market([(1000, 'buy', 10 ** 6)])
    frozen = M.position(line, 0, CONFIG, exit_slot=2000)
    one = M.position(line, 0, CONFIG, exit_slot=2000, failures=M.SENSITIVITY_FAILURES)
    assert frozen['net_lamports'] - one['net_lamports'] == 3 * 105_000          # quiet pool: the delay moves no price
    assert one['buy_landing_slot'] == 1008 and one['exit']['state_kept']['slot_limit'] in (2003, 2004)
    left_open = M.position(line, 0, CONFIG, exit_slot=2000, failures=M.Failures(cleanup=3))
    assert frozen['net_lamports'] - left_open['net_lamports'] == CA.SPL_RENT_LAMPORTS + 2 * 105_000
    assert left_open['decomposition_share_of_stake']['rent_lost'] == -CA.SPL_RENT_LAMPORTS / M.STAKE_LAMPORTS
    in_sale = M.position(line, 0, CONFIG, exit_slot=2000, wsol_separate_close=False)
    assert in_sale['net_lamports'] - frozen['net_lamports'] == 105_000
    for bad in (dict(buy=-1), dict(cleanup=4), dict(sell=1.0)):
        with pytest.raises(M.CostError, match='failures'):
            M.Failures(**bad)


def test_h1_keeps_the_fewer_tokens_at_the_buy_and_the_lower_value_at_the_sale():
    quiet, _ = market([(1000, 'buy', 10 ** 6), (1100, 'buy', 10 ** 6)])
    # a big real buy inside the buy landing slot (1004) raises the price before or after our buy: the worse is kept
    busy, _ = market([(1000, 'buy', 10 ** 6), (1004, 'buy', 20 * SOL), (1100, 'buy', 10 ** 6)])
    calm = M.position(quiet, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)
    hit = M.position(busy, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)
    assert hit['tokens'] < calm['tokens']
    line_before = M._state(busy, FEES, slot_limit=1003)
    assert hit['tokens'] == M._buy_on(M._state(busy, FEES, slot_limit=1004), FEES, True).output_amount
    assert hit['tokens'] < M._buy_on(line_before, FEES, True).output_amount
    # a big real sale inside the exit slot (2000): the value after it is kept
    dump, _ = market([(1000, 'buy', 10 ** 6), (2000, 'sell', 2 * 10 ** 14)])
    low = M.position(dump, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)
    high = M.position(dump, 0, CONFIG, exit_slot=1999, buy_guard_ppm=None)
    assert low['received'] < high['received'] and low['exit']['state_kept'] == dict(slot_limit=2000)
    assert low['decomposition_share_of_stake']['price_move'] < 0


def test_a_price_rise_shows_as_price_move_and_the_identity_holds_exactly():
    line, _ = market([(1000, 'buy', 10 ** 6), (1500, 'buy', 30 * SOL)])
    out = M.position(line, 0, CONFIG, exit_slot=2000)
    parts = out['decomposition_share_of_stake']
    assert parts['price_move'] > 0.4 and out['net_return'] > 0
    assert sum(parts.values()) == pytest.approx(out['net_return'], abs=1e-15)


def test_the_clock_exit_and_the_exit_guards():
    line, _ = market([(1000, 'buy', 10 ** 6), (1003, 'buy', 10 ** 6), (1500, 'sell', 10 ** 12)])
    clock = M.position(line, 0, CONFIG, exit_time=1000 + 1800)
    assert clock['exit']['rule'] == 'clock' and clock['exit']['declared'] == 2800
    assert clock['exit']['state_kept'] in (dict(time_limit=2799), dict(time_limit=2800))
    with pytest.raises(M.CostError, match='exactly_one_exit_point'):
        M.position(line, 0, CONFIG)
    with pytest.raises(M.CostError, match='exactly_one_exit_point'):
        M.position(line, 0, CONFIG, exit_slot=2000, exit_time=2000)
    for slot in (1004, 1003):
        with pytest.raises(M.CostError, match='exit_before_the_buy_landed'):
            M.position(line, 0, CONFIG, exit_slot=slot)
    with pytest.raises(M.CostError, match='exit_before_the_buy_landed'):
        M.position(line, 0, CONFIG, exit_time=1003)                              # the swap of slot 1003 not yet seen
    with pytest.raises(M.CostError, match='invalid_decision_index'):
        M.position(line, 3, CONFIG, exit_slot=2000)


def test_the_amm_config_is_read_never_assumed_and_must_be_in_u1():
    line, _ = market([(1000, 'buy', 10 ** 6)])
    with pytest.raises(M.CostError, match='outside_universe_u1_trade_fee'):
        M.position(line, 0, dict(CONFIG, trade_fee_rate=10_000), exit_slot=2000)
    for over in (dict(sha256='x'), dict(slot=None), dict(sha256='AB' * 32)):
        with pytest.raises(M.CostError, match='amm_config_not_read_and_hashed'):
            M.position(line, 0, dict(CONFIG, **over), exit_slot=2000)
    with pytest.raises(KeyError):
        M.fees_from_amm_config({k: v for k, v in CONFIG.items() if k != 'protocol_fee_rate'})


def test_creator_fee_on_the_output_side_is_valued_and_the_identity_holds():
    fees = curve.Fees(2_500, 1_000, 120_000, 40_000)
    line, _ = market([(1000, 'buy', 10 ** 6), (1500, 'sell', 10 ** 12)], fees=fees, on_input=False)
    out = M.position(line, 0, dict(CONFIG, creator_fee_rate=1_000, pool_creator_fee_enabled=True), exit_slot=2000)
    parts = out['decomposition_share_of_stake']
    assert sum(parts.values()) == pytest.approx(out['net_return'], abs=1e-15)
    assert parts['trade_and_creator_fees'] == pytest.approx(-0.007, abs=1e-4)    # 2 x (0.25 % + 0.1 %)


def test_the_pool_gate_admits_a_clean_pool_and_names_each_exclusion():
    steps = [(1000 + 3 * i, 'buy' if i % 2 else 'sell', (10 ** 8) if i % 2 else (10 ** 12)) for i in range(40)]
    line, txs = market(steps)
    ok = M.pool_gate(line, CONFIG)
    assert ok == dict(admitted=True, reasons=[], swaps=40, exact=40, lp_changes=0, continuity_breaks=0)
    # a wrong protocol share in the AmmConfig: the reserves do not chain (C-2)
    assert M.pool_gate(line, dict(CONFIG, protocol_fee_rate=0))['reasons'] == ['reserves_chain_broken']
    # a pool whose real rate is not the AmmConfig's: swaps not reproduced (C-1 / C-3)
    other, _ = market(steps, fees=curve.Fees(2_400, 0, 120_000, 40_000))
    assert 'swaps_not_reproduced_with_the_amm_config' in M.pool_gate(other, CONFIG)['reasons']
    # a missing swap in the collection: chain broken
    gap = dict(txs)
    del gap['sig010']
    assert M.pool_gate(TL.build(POOL_B58, gap, base_mint=BASE_B58), CONFIG)['reasons'] == ['reserves_chain_broken']
    # an undecodable transaction
    bad = dict(txs, sigbad=tx(5000, 99, ['Program %s invoke [1]' % events.CPMM_PROGRAM, 'Program data: !!!',
                                         'Program %s success' % events.CPMM_PROGRAM], when=5000))
    assert 'undecoded_transactions' in M.pool_gate(TL.build(POOL_B58, bad, base_mint=BASE_B58), CONFIG)['reasons']
    # a token transfer fee (Token-2022)
    head = events.SWAP_DISCRIMINATOR + struct.pack('<32s6Q?', POOL, 10 ** 15, 100 * SOL, 10 ** 9, 99_000, 7, 0, True)
    payload = head + struct.pack('<32s32s2Q?', BASE, QUOTE, 2_500_000, 0, True)
    fee_line = TL.build(POOL_B58, {'t': tx(10, 0, logs(payload), when=10)}, base_mint=BASE_B58)
    assert 'token_transfer_fee' in M.pool_gate(fee_line, CONFIG)['reasons']
    assert M.pool_gate(TL.build(POOL_B58, {}, base_mint=BASE_B58), CONFIG) == dict(admitted=False, reasons=['no_swap'])


def test_the_pilot_verdict_follows_section_2_5_in_order():
    def rows(n, pools, value):
        return [dict(pool='p%02d' % (i % pools), net_return=value) for i in range(n)]
    assert M.pilot_verdict(rows(40, 24, 0.05), g0_passed=False, freeze_sheet_sha256=ANCHOR)['decision'] == 'STOP'
    assert M.pilot_verdict(rows(40, 24, 0.05), g0_passed=None, freeze_sheet_sha256=ANCHOR)['published_numbers'] is False
    assert M.pilot_verdict(rows(29, 24, 0.05), g0_passed=True, freeze_sheet_sha256=ANCHOR)['decision'] == 'INCONCLUSIF'
    assert M.pilot_verdict(rows(40, 19, 0.05), g0_passed=True, freeze_sheet_sha256=ANCHOR)['decision'] == 'INCONCLUSIF'
    nogo = M.pilot_verdict(rows(40, 20, -0.01), g0_passed=True, freeze_sheet_sha256=ANCHOR, draws=500)
    same = rows(20, 20, -0.002) + rows(20, 20, 0.001)                          # every pool at -0.05 %: no spread
    assert M.pilot_verdict(same, g0_passed=True, freeze_sheet_sha256=ANCHOR, draws=500)['decision'] == 'NO-GO'
    assert nogo['decision'] == 'NO-GO' and nogo['upper_bound_95_one_sided'] == pytest.approx(-0.01)
    mixed = [dict(pool='p%02d' % (i % 20), net_return=0.01 if i % 20 < 10 else -0.012) for i in range(40)]
    out = M.pilot_verdict(mixed, g0_passed=True, freeze_sheet_sha256=ANCHOR, draws=500)
    assert out['decision'] == 'GO_PILOTE' and out['upper_bound_95_one_sided'] >= 0 > out['mean_net_return']
    assert out['counts_for_operational_master'] is False and 'never means profitable' in out['meaning']
    assert M.pilot_verdict(rows(40, 24, 0.05), g0_passed=True, freeze_sheet_sha256=ANCHOR, draws=500)['draws'] == 500
    assert M.DRAWS == 10_000 and (M.MIN_ENTRIES, M.MIN_POOLS, M.ALPHA_UPPER) == (30, 20, 0.05)
    with pytest.raises(M.CostError, match='freeze_sheet_sha256_required'):
        M.pilot_verdict(rows(40, 24, 0.05), g0_passed=True, freeze_sheet_sha256='x')


def test_r_cp1_is_one_trial_under_the_cap():
    assert M.trials(168) == dict(n_before=168, n_after=169, cap_outside_hw1=170, left_after=1)
    assert M.trials(169)['left_after'] == 0
    with pytest.raises(M.CostError, match='trial_cap_exceeded'):
        M.trials(170)
    for bad in (-1, '168', 168.0):
        with pytest.raises(M.CostError, match='n_before_must_be_a_non_negative_integer'):
            M.trials(bad)


def test_end_to_end_from_raw_transactions_through_the_decoder():
    steps = [(1000 + 2 * i, 'buy' if i % 3 else 'sell', (2 * 10 ** 8) if i % 3 else (5 * 10 ** 11)) for i in range(60)]
    line, txs = market(steps)
    assert M.pool_gate(line, CONFIG)['admitted'] is True
    raw_logs = txs['sig000']['meta']['logMessages']
    assert any(line_.startswith('Program data: ') for line_ in raw_logs)
    assert base64.b64decode(raw_logs[2].split(': ', 1)[1])[:8] == events.SWAP_DISCRIMINATOR
    out = M.position(line, 10, CONFIG, exit_slot=line.swaps[40].slot)
    assert out['buy_landing_slot'] == line.swaps[10].slot + 4
    assert sum(out['decomposition_share_of_stake'].values()) == pytest.approx(out['net_return'], abs=1e-15)


def test_the_decoder_and_closedacct_are_the_audited_files(monkeypatch):
    assert M.frozen_check() == M.FROZEN_CODE
    monkeypatch.setitem(M.FROZEN_CODE, 'timeline', '0' * 64)
    with pytest.raises(M.CostError, match='frozen_code_differs:timeline'):
        M.frozen_check()
    line, _ = market([(1000, 'buy', 10 ** 6)])
    with pytest.raises(M.CostError, match='frozen_code_differs'):
        M.position(line, 0, CONFIG, exit_slot=2000)
    with pytest.raises(M.CostError, match='frozen_code_differs'):
        M.pool_gate(line, CONFIG)


def test_a_failed_attempt_lands_4_slots_later_on_another_state_with_h1():
    # a big real buy at slot 1006: after the first landing (1004), before the resent one (1008)
    line, _ = market([(1000, 'buy', 10 ** 6), (1006, 'buy', 20 * SOL)])
    first = M.position(line, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)
    late = M.position(line, 0, CONFIG, exit_slot=2000, failures=M.Failures(buy=1), buy_guard_ppm=None)
    assert first['buy_landing_slot'] == 1004 and late['buy_landing_slot'] == 1008
    assert late['tokens'] < first['tokens']
    # H-1 on the delayed slot: a real buy INSIDE slot 1008 is taken against us too
    inside, _ = market([(1000, 'buy', 10 ** 6), (1008, 'buy', 20 * SOL)])
    assert M.position(inside, 0, CONFIG, exit_slot=2000, failures=M.Failures(buy=1), buy_guard_ppm=None)['tokens'] <         M.position(inside, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)['tokens']
    # the sale: a big real sale at slot 2002, after the first sale landing (2000), before the resent one (2004)
    dump, _ = market([(1000, 'buy', 10 ** 6), (2002, 'sell', 2 * 10 ** 14)])
    sale = M.position(dump, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)
    resent = M.position(dump, 0, CONFIG, exit_slot=2000, failures=M.Failures(sell=1), buy_guard_ppm=None)
    assert resent['received'] < sale['received'] and resent['exit']['state_kept']['slot_limit'] in (2003, 2004)
    # a delayed buy that lands after the exit point is refused
    with pytest.raises(M.CostError, match='exit_before_the_buy_landed'):
        M.position(line, 0, CONFIG, exit_slot=1006, failures=M.Failures(buy=1), buy_guard_ppm=None)
    # the clock exit: a resent sale lands 4 slots after the slot of the last swap at the clock time
    clock_line, _ = market([(1000, 'buy', 10 ** 6), (2800, 'buy', 10 ** 6), (2803, 'sell', 2 * 10 ** 14)])
    on_time = M.position(clock_line, 0, CONFIG, exit_time=2800, buy_guard_ppm=None)
    resent = M.position(clock_line, 0, CONFIG, exit_time=2800, failures=M.Failures(sell=1), buy_guard_ppm=None)
    assert resent['exit']['state_kept']['slot_limit'] in (2803, 2804) and resent['received'] < on_time['received']


def test_the_g1_seed_is_the_freeze_sheet():
    rows = [dict(pool='p%02d' % (i % 24), net_return=((i * 37) % 23 - 11) / 1000) for i in range(60)]
    a = M.pilot_verdict(rows, g0_passed=True, freeze_sheet_sha256='0000002a' + 'f' * 56, draws=300)
    assert a['seed'] == 42
    assert a == M.pilot_verdict(rows, g0_passed=True, freeze_sheet_sha256='0000002a' + 'e' * 56, draws=300)
    groups = {}
    for r in rows:
        groups.setdefault(r['pool'], []).append(r)
    neg = lambda rs: -sum(r['net_return'] for r in rs) / len(rs)                 # noqa: E731
    from w2arms import ce as W
    assert a['upper_bound_95_one_sided'] == -W.lower_bound(groups, neg, seed=42, draws=300, alpha=0.05)
    other = M.pilot_verdict(rows, g0_passed=True, freeze_sheet_sha256='0000002b' + 'f' * 56, draws=300)
    assert other['upper_bound_95_one_sided'] == -W.lower_bound(groups, neg, seed=43, draws=300, alpha=0.05)


def test_the_cpmm_buy_guard_of_amendment_a1():
    assert (M.BUY_GUARD_PPM, M.BUY_GUARD_SENSITIVITY_PPM) == (20_000, 50_000)
    # a 20 SOL real buy inside the landing slot: the fill is far below the decision quote
    busy, _ = market([(1000, 'buy', 10 ** 6), (1004, 'buy', 20 * SOL)])
    refused = M.position(busy, 0, CONFIG, exit_slot=2000)
    assert refused['status'] == 'guard_failed' and refused['entered'] is False and refused['received'] == 0
    assert refused['net_lamports'] == -105_000 and refused['fill_tokens'] < refused['expected_tokens']
    assert refused['counts_for_operational_master'] is False
    twice = M.position(busy, 0, CONFIG, exit_slot=2000, failures=M.Failures(buy=1))
    assert twice['status'] == 'guard_failed' and twice['net_lamports'] == -210_000
    assert twice['net_return'] == -210_000 / M.STAKE_LAMPORTS
    # the same pool without the guard enters (the frozen 0.2 behaviour)
    assert M.position(busy, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)['status'] == 'entered'
    # a small move inside the band: entered under the guard
    calm, _ = market([(1000, 'buy', 10 ** 6), (1004, 'buy', SOL // 10)])
    assert M.position(calm, 0, CONFIG, exit_slot=2000)['status'] == 'entered'
    # a move between 2 % and 5 %: refused at 20 000 ppm, entered at the 50 000 ppm sensitivity
    found = None
    for lamports in range(SOL // 2, 40 * SOL, SOL // 2):
        line, _ = market([(1000, 'buy', 10 ** 6), (1004, 'buy', lamports)])
        primary = M.position(line, 0, CONFIG, exit_slot=2000)
        wide = M.position(line, 0, CONFIG, exit_slot=2000, buy_guard_ppm=M.BUY_GUARD_SENSITIVITY_PPM)
        if primary['status'] == 'guard_failed' and wide['status'] == 'entered':
            found = lamports
            break
    assert found is not None
    with pytest.raises(M.CostError, match='buy_guard_not_a_declared_threshold'):
        M.position(calm, 0, CONFIG, exit_slot=2000, buy_guard_ppm=10_000)


def test_the_guard_compares_with_the_state_right_after_the_decision_swap():
    line, _ = market([(1000, 'buy', 10 ** 6), (1001, 'buy', 20 * SOL)])        # a big buy BEFORE the landing slot
    out = M.position(line, 0, CONFIG, exit_slot=2000)
    fees = M.fees_from_amm_config(CONFIG)
    decision_state = TL.after_swap(line.swaps[0], fees.protocol_fee_rate, fees.fund_fee_rate)
    expected = M._buy_on(decision_state, fees, True).output_amount
    assert out['status'] == 'guard_failed' and out['expected_tokens'] == expected


def test_the_sale_keeps_no_guard():
    dump, _ = market([(1000, 'buy', 10 ** 6), (2000, 'sell', 2 * 10 ** 14)])
    out = M.position(dump, 0, CONFIG, exit_slot=2000)
    assert out['status'] == 'entered' and out['received'] > 0 and out['net_return'] < -0.05


def test_guard_failed_attempts_are_charged_in_the_mean_but_are_not_entries():
    def row(i, pools, value, entered=True):
        return dict(pool='p%d' % (i % pools), net_return=value, entered=entered,
                    status='entered' if entered else 'guard_failed')
    refused = [row(i, 24, -0.00105, entered=False) for i in range(20)]
    kept = [row(i, 24, 0.05) for i in range(29)]
    out = M.pilot_verdict(kept + refused, g0_passed=True, freeze_sheet_sha256=ANCHOR, draws=300)
    assert (out['n'], out['n_entered'], out['guard_failed']) == (49, 29, 20) and out['decision'] == 'INCONCLUSIF'
    assert abs(out['mean_net_return'] - (29 * 0.05 - 20 * 0.00105) / 49) < 1e-12
    few_pools = [row(i, 19, 0.05) for i in range(40)] + [dict(row(0, 1, -0.00105, False), pool='px%d' % i) for i in range(5)]
    out = M.pilot_verdict(few_pools, g0_passed=True, freeze_sheet_sha256=ANCHOR, draws=300)
    assert (out['pools'], out['pools_entered'], out['decision']) == (24, 19, 'INCONCLUSIF')
    enough = M.pilot_verdict([row(i, 24, 0.05) for i in range(30)] + refused, g0_passed=True,
                             freeze_sheet_sha256=ANCHOR, draws=300)
    assert enough['decision'] == 'GO_PILOTE' and enough['guard_failed'] == 20


def test_the_guard_boundary_is_exact_for_both_declared_thresholds():
    fees = M.fees_from_amm_config(CONFIG)
    seen = {20_000: set(), 50_000: set()}
    for lamports in range(SOL // 4, 12 * SOL, SOL // 4):
        line, _ = market([(1000, 'buy', 10 ** 6), (1004, 'buy', lamports)])
        free = M.position(line, 0, CONFIG, exit_slot=2000, buy_guard_ppm=None)
        expected = M._buy_on(TL.after_swap(line.swaps[0], fees.protocol_fee_rate, fees.fund_fee_rate), fees,
                             M.creator_side(line, len(line.swaps) - 1)).output_amount
        for ppm in seen:
            out = M.position(line, 0, CONFIG, exit_slot=2000, buy_guard_ppm=ppm)
            refused = free['tokens'] < expected * (1_000_000 - ppm) // 1_000_000
            assert out['status'] == ('guard_failed' if refused else 'entered')
            seen[ppm].add(out['status'])
            if refused:
                assert (out['expected_tokens'], out['fill_tokens']) == (expected, free['tokens'])
            else:
                assert out['tokens'] == free['tokens'] and out['net_lamports'] == free['net_lamports']
    assert seen == {20_000: {'entered', 'guard_failed'}, 50_000: {'entered', 'guard_failed'}}


def test_the_declared_10_slot_latency_sensitivity():
    assert (M.LATENCY_SLOTS, M.SENSITIVITY_LATENCY_SLOTS, M.ALLOWED_LATENCIES) == (4, 10, (4, 10))
    # a real buy between slot 1004 and slot 1010: the 4-slot buy is before it, the 10-slot buy after it
    line, _ = market([(1000, 'buy', 10 ** 6), (1007, 'buy', SOL // 20), (1500, 'buy', 10 ** 6)])
    fast = M.position(line, 0, CONFIG, exit_slot=2000)
    slow = M.position(line, 0, CONFIG, exit_slot=2000, latency_slots=10)
    assert fast == M.position(line, 0, CONFIG, exit_slot=2000, latency_slots=4)
    assert (fast['buy_landing_slot'], slow['buy_landing_slot']) == (1004, 1010)
    assert (fast['latency_slots'], slow['latency_slots']) == (4, 10)
    assert slow['tokens'] < fast['tokens'] and slow['status'] == fast['status'] == 'entered'
    late = M.position(line, 0, CONFIG, exit_slot=2000, latency_slots=10, failures=M.Failures(buy=1))
    assert late['buy_landing_slot'] == 1020
    # a resent sale is shifted by the declared latency too
    dump, _ = market([(1000, 'buy', 10 ** 6), (2003, 'sell', 2 * 10 ** 14)])
    assert (M.position(dump, 0, CONFIG, exit_slot=2000, latency_slots=4, failures=M.Failures(sell=1))['received'] <
            M.position(dump, 0, CONFIG, exit_slot=2000, latency_slots=4)['received'])
    assert (M.position(dump, 0, CONFIG, exit_slot=1996, latency_slots=10, failures=M.Failures(sell=1))['received'] <
            M.position(dump, 0, CONFIG, exit_slot=1996, latency_slots=4, failures=M.Failures(sell=1))['received'])
    for bad in (0, 5, 8, 4.0, None):
        with pytest.raises(M.CostError, match='latency_not_a_declared_value'):
            M.position(line, 0, CONFIG, exit_slot=2000, latency_slots=bad)


def test_a_resent_clock_sale_is_shifted_by_the_declared_latency():
    line, _ = market([(1000, 'buy', 10 ** 6), (1500, 'buy', 10 ** 6), (1507, 'sell', 2 * 10 ** 14)])
    fast = M.position(line, 0, CONFIG, exit_time=1502, failures=M.Failures(sell=1))           # resent at 1504
    slow = M.position(line, 0, CONFIG, exit_time=1502, failures=M.Failures(sell=1), latency_slots=10)   # at 1510
    assert slow['received'] < fast['received'] and slow['exit']['state_kept'] in (dict(slot_limit=1509), dict(slot_limit=1510))
    assert fast['exit']['state_kept'] in (dict(slot_limit=1503), dict(slot_limit=1504))


# -- E-CF (0.3.1): the creator fee is charged only when the POOL enables it --------------------------------------------
import hashlib
import json as _json
from pathlib import Path as _Path

from cpmmpilot.store import read_gz_page as _read

_REAL = _Path(__file__).parent / 'data_real'
# (swaps, exact with the AmmConfig creator rate charged, reasons of G-0 under 0.3.1) per real first page, frozen here
_EXPECTED = {
    'AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca': (233, 0, []),
    'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr': (100, 0, ['token_transfer_fee']),
    'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh': (91, 0, []),
    'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A': (357, 0, []),
    'GaPTvXuog95vxJii7qwvfNVNdpgAcEmjFqYdZnxxgzLV': (100, 0, []),
    '6CQSpRdGtNWEbLhKpx7DAw7FDAm3g7wvjtsvaTKWBwxo': (100, 0, []),
    '7SJ5UKJoqBUGjt1PT7AeSF7FKPgpnxeYMHHcejTiGQzc': (39, 0, ['undecoded_transactions', 'reserves_chain_broken']),
    '5zk4vhcPaFboRS16LQejvUDVbzsAjH3NCDrqvumGnTYv': (95, 0, []),
    'CXgcuECqdaBpvJWH5cwEir9Y5FY9SKTjhGutMc95bGy3': (2, 0, ['token_transfer_fee']),
    'FAn5gzoJMYriKeCoJzLTCepE9Y36oN3CidoF4dmgFNh9': (84, 0, ['undecoded_transactions', 'reserves_chain_broken']),
    'A3URwhZE2YyVNKL9CmSvU9VG1oJoZS78kX4AdK5faDud': (21, 0, ['token_transfer_fee']),
    '4D17GNQvJPMsMAiyiYvSK1GxAtduMLvyMMHVzRUniV8o': (96, 0, ['undecoded_transactions', 'reserves_chain_broken']),
}


def _real():
    meta = _json.loads((_REAL / 'META.json').read_text())
    cfg = dict(meta['amm_config'], sha256=meta['amm_config']['raw_sha256'])
    for pool, m in sorted(meta['pools'].items()):
        page = _REAL / pool / m['page']
        assert hashlib.sha256(page.read_bytes()).hexdigest() == m['page_sha256']        # the anchored page, unchanged
        txs = {t['transaction']['signatures'][0]: t for t in _read(page)['data']}
        yield pool, m, cfg, TL.build(pool, txs, base_mint=m['base_mint'])


def test_e_cf_the_amm_config_creator_rate_applies_only_to_a_pool_that_enables_it():
    cfg = dict(CONFIG, creator_fee_rate=500)
    assert M.fees_from_amm_config(cfg) == curve.Fees(2_500, 0, 120_000, 40_000)
    assert M.fees_from_amm_config(dict(cfg, pool_creator_fee_enabled=True)) == curve.Fees(2_500, 500, 120_000, 40_000)
    for flag in (False, 1, 'true', None):
        assert M.fees_from_amm_config(dict(cfg, pool_creator_fee_enabled=flag)).creator_fee_rate == 0
    assert M.fees_from_amm_config(dict(CONFIG, pool_creator_fee_enabled=True)).creator_fee_rate == 0   # no rate read


def test_e_cf_real_pre_t0_pages_are_reproduced_only_without_the_unpaid_creator_fee():
    """R02's reproduction (11:51:11Z) on the anchored first pages: 0 exact with the AmmConfig creator rate charged,
    every swap exact under 0.3.1; the 4 pilot pools and the 8 livesim pools."""
    seen = set()
    for pool, m, cfg, line in _real():
        swaps, exact_charged, reasons = _EXPECTED[pool]
        assert m['config'] == 'D4FPEruKEHrG5TenZ2mpDGEfu1iUvTiqBxvpU8HLBvC2' and cfg['creator_fee_rate'] == 500
        assert len(line.swaps) == swaps and not any(s.event.creator_fee for s in line.swaps)
        side = M.creator_side(line, len(line.swaps) - 1)
        charged = TL.reproduce(line, {k: (M.fees_from_amm_config(dict(cfg, pool_creator_fee_enabled=True)), side)
                                      for k in ('buy', 'sell')})
        effective = TL.reproduce(line, {k: (M.fees_from_amm_config(cfg), side) for k in ('buy', 'sell')})
        assert (charged['exact'], effective['exact']) == (exact_charged, swaps)
        gate = M.pool_gate(line, cfg)
        assert gate['reasons'] == reasons and gate['exact'] == swaps
        assert 'swaps_not_reproduced_with_the_amm_config' in M.pool_gate(
            line, dict(cfg, pool_creator_fee_enabled=True))['reasons']
        seen.add(m['group'])
    assert seen == {'pilot', 'livesim'} and len(_EXPECTED) == 12


def test_e_cf_a_pool_that_charges_the_creator_fee_is_never_mispriced():
    """No pool of our anchored data charges it (0 swap logs a creator fee), so this case is synthetic: with the pool's
    flag the fee is valued; without it, G-0 refuses the pool instead of pricing it without the fee."""
    fees = curve.Fees(2_500, 1_000, 120_000, 40_000)
    steps = [(1000 + 3 * i, 'buy' if i % 2 else 'sell', (10 ** 8) if i % 2 else (10 ** 12)) for i in range(40)]
    line, _ = market(steps, fees=fees, on_input=False)
    assert all(s.event.creator_fee for s in line.swaps)
    flagged = dict(CONFIG, creator_fee_rate=1_000, pool_creator_fee_enabled=True)
    assert M.pool_gate(line, flagged)['admitted'] is True
    refused = M.pool_gate(line, dict(CONFIG, creator_fee_rate=1_000))
    assert refused['admitted'] is False and 'swaps_not_reproduced_with_the_amm_config' in refused['reasons']


# -- E-G0 (0.3.2, PROJECT, not anchored): tolerance of log-truncated transactions in G-0 -------------------------------
def _market_with_truncated(steps, truncated, broken=()):
    """Like market(); the swaps whose step index is in ``truncated`` happen in the pool but log 'Log truncated'; those
    in ``broken`` log an event of a wrong size (another cause of non-decoding)."""
    sim = Sim(10 ** 15, 100 * SOL, FEES, True)
    txs = {}
    for i, (slot, side, amount) in enumerate(steps):
        payload, _ = sim.swap(side, amount)
        lines = logs(payload)
        if i in truncated:
            lines = lines[:2] + ['Log truncated']
        if i in broken:
            lines = logs(payload[:-5])
        txs['sig%03d' % i] = tx(slot, i, lines, when=slot)
    return TL.build(POOL_B58, txs, base_mint=BASE_B58), txs


def _steps(n):
    return [(1000 + 3 * i, 'buy' if i % 2 else 'sell', (10 ** 8) if i % 2 else (10 ** 12)) for i in range(n)]


def test_e_g0_is_absent_by_default_and_the_inputs_are_checked():
    line, txs = _market_with_truncated(_steps(100), {50})
    plain = M.pool_gate(line, CONFIG)
    assert plain['reasons'] == ['undecoded_transactions', 'reserves_chain_broken'] and 'undecoded_tolerated' not in plain
    assert M.skipped_positions(line, txs) == {'sig050': (1150, 50)}
    for bad in (dict(positions={}, transactions=100), dict(positions=M.skipped_positions(line, txs), transactions=0),
                dict(positions=M.skipped_positions(line, txs), transactions='100')):
        with pytest.raises(M.CostError, match='tolerance_inputs_inconsistent'):
            M.pool_gate(line, CONFIG, tolerance=bad)
    clean, ctx = market(_steps(10))
    out = M.pool_gate(clean, CONFIG, tolerance=dict(positions={}, transactions=len(ctx)))
    assert out['admitted'] is True and out['undecoded_tolerated'] is None


def test_e_g0_tolerates_a_small_share_of_truncated_logs_with_adjacent_breaks_only():
    line, txs = _market_with_truncated(_steps(100), {50})
    tol = dict(positions=M.skipped_positions(line, txs), transactions=len(txs))
    out = M.pool_gate(line, CONFIG, tolerance=tol)
    assert out['admitted'] is True and out['reasons'] == []
    assert out['undecoded_tolerated'] == dict(undecoded=1, transactions=100, share=0.01, breaks=1, cause='log_truncated')
    # share above 2 %: 3 of 100 truncated
    many, mtx = _market_with_truncated(_steps(100), {20, 50, 80})
    assert M.pool_gate(many, CONFIG, tolerance=dict(positions=M.skipped_positions(many, mtx),
                                                    transactions=len(mtx)))['admitted'] is False
    two, ttx = _market_with_truncated(_steps(100), {20, 50})
    assert M.pool_gate(two, CONFIG, tolerance=dict(positions=M.skipped_positions(two, ttx),
                                                   transactions=len(ttx)))['admitted'] is True   # exactly 2 %
    # a break NOT adjacent to the undecoded transaction: a swap missing from the collection elsewhere
    gap = {s: t for s, t in txs.items() if s != 'sig070'}
    holed = TL.build(POOL_B58, gap, base_mint=BASE_B58)
    out = M.pool_gate(holed, CONFIG, tolerance=dict(positions=M.skipped_positions(holed, gap), transactions=len(gap)))
    assert out['admitted'] is False and 'reserves_chain_broken' in out['reasons']
    # another cause than log_truncated is never tolerated
    oline, other = _market_with_truncated(_steps(100), set(), broken={50})
    assert len(oline.skipped) == 1 and oline.skipped[0][1] != 'log_truncated'
    assert M.pool_gate(oline, CONFIG, tolerance=dict(positions=M.skipped_positions(oline, other),
                                                     transactions=len(other)))['admitted'] is False
    assert M.UNDECODED_TOLERANCE == Fraction(2, 100) and M.TOLERATED_CAUSE == 'log_truncated'


def test_e_g0_never_lifts_another_reason_than_the_undecoded_ones():
    from dataclasses import replace
    line, txs = _market_with_truncated(_steps(100), {50})
    first = line.swaps[0]
    taxed = replace(line, swaps=(replace(first, event=replace(first.event, input_transfer_fee=1)),) + line.swaps[1:])
    out = M.pool_gate(taxed, CONFIG, tolerance=dict(positions=M.skipped_positions(line, txs), transactions=len(txs)))
    assert out['undecoded_tolerated'] is not None and 'token_transfer_fee' in out['reasons'] and not out['admitted']
    assert 'undecoded_transactions' not in out['reasons'] and 'reserves_chain_broken' not in out['reasons']
