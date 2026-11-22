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
    assert frozen['net_lamports'] - one['net_lamports'] == 3 * 105_000
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
    calm = M.position(quiet, 0, CONFIG, exit_slot=2000)
    hit = M.position(busy, 0, CONFIG, exit_slot=2000)
    assert hit['tokens'] < calm['tokens']
    line_before = M._state(busy, FEES, slot_limit=1003)
    assert hit['tokens'] == M._buy_on(M._state(busy, FEES, slot_limit=1004), FEES, True).output_amount
    assert hit['tokens'] < M._buy_on(line_before, FEES, True).output_amount
    # a big real sale inside the exit slot (2000): the value after it is kept
    dump, _ = market([(1000, 'buy', 10 ** 6), (2000, 'sell', 2 * 10 ** 14)])
    low = M.position(dump, 0, CONFIG, exit_slot=2000)
    high = M.position(dump, 0, CONFIG, exit_slot=1999)
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
    out = M.position(line, 0, dict(CONFIG, creator_fee_rate=1_000), exit_slot=2000)
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
    assert M.pilot_verdict(rows(40, 24, 0.05), g0_passed=False, freeze_anchor_sha256=ANCHOR)['decision'] == 'STOP'
    assert M.pilot_verdict(rows(40, 24, 0.05), g0_passed=None, freeze_anchor_sha256=ANCHOR)['published_numbers'] is False
    assert M.pilot_verdict(rows(29, 24, 0.05), g0_passed=True, freeze_anchor_sha256=ANCHOR)['decision'] == 'INCONCLUSIF'
    assert M.pilot_verdict(rows(40, 19, 0.05), g0_passed=True, freeze_anchor_sha256=ANCHOR)['decision'] == 'INCONCLUSIF'
    nogo = M.pilot_verdict(rows(40, 20, -0.01), g0_passed=True, freeze_anchor_sha256=ANCHOR, draws=500)
    same = rows(20, 20, -0.002) + rows(20, 20, 0.001)                          # every pool at -0.05 %: no spread
    assert M.pilot_verdict(same, g0_passed=True, freeze_anchor_sha256=ANCHOR, draws=500)['decision'] == 'NO-GO'
    assert nogo['decision'] == 'NO-GO' and nogo['upper_bound_95_one_sided'] == pytest.approx(-0.01)
    mixed = [dict(pool='p%02d' % (i % 20), net_return=0.01 if i % 20 < 10 else -0.012) for i in range(40)]
    out = M.pilot_verdict(mixed, g0_passed=True, freeze_anchor_sha256=ANCHOR, draws=500)
    assert out['decision'] == 'GO_PILOTE' and out['upper_bound_95_one_sided'] >= 0 > out['mean_net_return']
    assert out['counts_for_operational_master'] is False and 'never means profitable' in out['meaning']
    assert M.pilot_verdict(rows(40, 24, 0.05), g0_passed=True, freeze_anchor_sha256=ANCHOR, draws=500)['draws'] == 500
    assert M.DRAWS == 10_000 and (M.MIN_ENTRIES, M.MIN_POOLS, M.ALPHA_UPPER) == (30, 20, 0.05)
    with pytest.raises(M.CostError, match='freeze_anchor_sha256_required'):
        M.pilot_verdict(rows(40, 24, 0.05), g0_passed=True, freeze_anchor_sha256='x')


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
