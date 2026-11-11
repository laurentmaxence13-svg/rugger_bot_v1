"""cpmmlab.probe on synthetic CPMM pools only: every value recomputed by hand from the simulated reserves."""
import struct

import pytest

from cpmmx import curve, events, timeline as ct
from cpmmx.tests.test_cpmmx import BASE, BASE_B58, POOL, POOL_B58, QUOTE, Sim, logs, swap_payload, tx

from cpmmlab import probe as lab

FEES = curve.Fees(2500, 0, 120_000, 40_000)
SHARES = dict(protocol_fee_rate=120_000, fund_fee_rate=40_000)
T0, SLOT0 = 1_790_000_000, 500_000_000
BASE0, QUOTE0 = 206_900_000 * 10**6, 85 * 10**9
STAKE, TX = lab.STAKE_LAMPORTS, lab.TX_COST_LAMPORTS


def pool(steps, *, fees=FEES, on_input=True, opened=True, exact_in=True):
    """``steps``: (seconds after the opening, side, amount). Returns (timeline, {seconds: (base, quote) after})."""
    sim = Sim(BASE0, QUOTE0, fees, on_input)
    txs, states = {}, {-1: (sim.base, sim.quote)}
    for index, (second, side, amount) in enumerate(steps):
        payload, _ = sim.swap(side, amount, exact_in=exact_in)
        txs['cp%03d' % index] = tx(SLOT0 + 3 * second + index, 0, logs(payload), when=T0 + second)
        states[second] = (sim.base, sim.quote)
    return ct.build(POOL_B58, txs, base_mint=BASE_B58, opened=(SLOT0, T0) if opened else None), states


def buy(state, amount=STAKE, fees=FEES, on_input=True):
    return curve.swap_base_input(amount, state[1], state[0], fees, on_input).output_amount


def sell(state, tokens, fees=FEES, on_input=True):
    return curve.swap_base_input(tokens, state[0], state[1], fees, on_input).output_amount


QUIET = [(2, 'buy', 10**9), (4, 'sell', 10**11), (40, 'buy', 10**8), (90, 'sell', 10**10)]


def test_a_quiet_pool_costs_two_fees_and_twice_our_impact():
    line, states = pool(QUIET)
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    assert block['status'] == 'closed' and block['buy_landing_time'] == T0 + 11 and block['sell_landing_time'] == T0 + 32
    tokens = buy(states[4])
    assert block['tokens'] == tokens and block['buy']['by_order_in_landing_second'] == dict(after=tokens, before=tokens)
    value = sell(states[4], tokens)                               # nothing traded in between: the same real reserves
    assert block['value'] == value == block['instant_round_trip_value'] and block['drift_lamports'] == 0
    assert block['cost'] == STAKE + 2 * TX and block['pnl_before_rent'] == value - STAKE - 2 * TX
    loss = (STAKE - value) / STAKE
    share = STAKE / states[4][1]
    assert loss == pytest.approx(2 * 0.0025 + 2 * share, rel=0.02)           # two fees and twice our share of the reserve
    assert block['own_share_of_quote_reserve_ppm'] == STAKE * 10**6 // states[4][1]
    assert block['buy']['fee_source'] == 'buy_swaps_before_landing' and block['sell']['fee_source'] == 'sell_swaps_before_landing'
    assert block['buy']['source'] == block['sell']['source'] == 'next_swap_logged_reserves'
    assert block['creditable'] is False and block['validated_on_real_swaps'] is False and len(block['approximations']) == 5
    rent = 2_039_280
    assert lab.net_return(block, rent) == (value - STAKE - 2 * TX - rent) / (STAKE + 2 * TX + rent) < 0


def test_the_drift_between_the_two_landings_is_the_real_one():
    up = QUIET[:2] + [(20, 'buy', 5 * 10**9), (25, 'buy', 5 * 10**9), (90, 'sell', 10**10)]
    line, states = pool(up)
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    tokens = buy(states[4])
    assert block['tokens'] == tokens and block['value'] == sell(states[25], tokens)
    assert block['instant_round_trip_value'] == sell(states[4], tokens)
    assert block['drift_lamports'] == sell(states[25], tokens) - sell(states[4], tokens) > 0
    assert block['pnl_before_rent'] > 0 and lab.net_return(block, 2_039_280) > 0
    down = QUIET[:2] + [(20, 'sell', 2 * 10**13), (90, 'sell', 10**10)]
    line, states = pool(down)
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    assert block['value'] == sell(states[20], buy(states[4])) and block['drift_lamports'] < 0


def test_the_lower_of_the_two_orders_inside_each_landing_second_is_kept():
    # a real buy in our buy landing second (price up: fewer tokens after it); a real buy in our sale second (more value after it)
    steps = QUIET[:2] + [(11, 'buy', 3 * 10**9), (32, 'buy', 3 * 10**9), (90, 'sell', 10**10)]
    line, states = pool(steps)
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    before, after = buy(states[4]), buy(states[11])
    assert after < before and block['tokens'] == after and block['buy']['kept_order'] == 'after'
    assert block['buy']['by_order_in_landing_second'] == dict(after=after, before=before)
    low, high = sell(states[11], after), sell(states[32], after)
    assert low < high and block['value'] == low and block['sell']['kept_order'] == 'before'
    # real sales instead: the order that is worse for us is now the other one
    steps = QUIET[:2] + [(11, 'sell', 10**13), (32, 'sell', 10**13), (90, 'buy', 10**8)]
    line, states = pool(steps)
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    tokens = buy(states[4])
    assert block['tokens'] == tokens < buy(states[11]) and block['buy']['kept_order'] == 'before'
    assert block['value'] == sell(states[32], tokens) < sell(states[11], tokens) and block['sell']['kept_order'] == 'after'


def test_nothing_after_the_sale_landing_changes_the_result():
    line, _ = pool(QUIET[:2] + [(90, 'buy', 10**8)])
    longer, _ = pool(QUIET[:2] + [(33, 'buy', 20 * 10**9), (34, 'sell', 10**13), (90, 'buy', 10**8), (300, 'buy', 10**9)])
    kwargs = dict(delay_s=10, hold_s=20, window_end_time=T0 + 600, buy_fees=(FEES, True), sell_fees=(FEES, True), **SHARES)
    a, b = lab.probe(line, **kwargs), lab.probe(longer, **kwargs)
    keys = ('status', 'tokens', 'value', 'cost', 'instant_round_trip_value')
    assert a['status'] == 'closed' and [a[k] for k in keys] == [b[k] for k in keys]
    # ... and the last second read is the sale landing: a swap exactly there is read, one second later is not
    edge, _ = pool(QUIET[:2] + [(32, 'sell', 10**13), (90, 'buy', 10**8)])
    assert lab.probe(edge, **kwargs)['value'] < a['value']                    # P-2 keeps the lower order


def test_fee_rates_given_or_read_causally_and_the_worse_bound_when_unknown():
    line, states = pool(QUIET)
    given = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, buy_fees=(FEES, True), sell_fees=(FEES, True), **SHARES)
    read = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    assert given['buy']['fee_source'] == 'given' and (given['tokens'], given['value']) == (read['tokens'], read['value'])
    # at the opening no swap has executed: the rates cannot be read yet, and no number is produced
    early = lab.probe(line, delay_s=0, hold_s=20, window_end_time=T0 + 600, **SHARES)
    assert early['status'] == 'unpriced_fee_rate_not_observable_yet' and 'value' not in early and 'tokens' not in early
    assert lab.net_return(early, 2_039_280) is None
    with_config = lab.probe(line, delay_s=0, hold_s=20, window_end_time=T0 + 600, buy_fees=(FEES, True), sell_fees=(FEES, True), **SHARES)
    assert with_config['status'] == 'closed' and with_config['tokens'] == buy(states[-1])
    assert with_config['buy']['source'] == 'first_swap_logged_reserves'
    # only buys seen before our sale: the rates come from them; with a creator fee its side is unknown: lower value kept
    creator = curve.Fees(2500, 1000, 120_000, 40_000)
    line, states = pool([(2, 'buy', 10**9), (5, 'buy', 10**9), (90, 'buy', 10**8)], fees=creator, on_input=True)
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    assert block['sell']['fee_source'] == 'buy_swaps_before_landing_creator_fee_side_unknown'
    tokens = buy(states[5], fees=creator)
    both = [sell(states[5], tokens, creator, True), sell(states[5], tokens, creator, False)]
    assert block['tokens'] == tokens and block['value'] == min(both) and both[0] != both[1]


def test_unknown_protocol_and_fund_shares_keep_the_worse_bound():
    # no swap follows our landings: the reserves come from the last swap's logged amounts
    for last_side, amount in (('sell', 10**12), ('buy', 10**9)):
        line, states = pool([(2, 'buy', 10**9), (3, 'sell', 10**11), (5, last_side, amount)])
        fees = dict(buy_fees=(FEES, True), sell_fees=(FEES, True))
        exact = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **fees, **SHARES)
        unknown = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **fees)
        assert exact['buy']['source'] == 'logged_amounts_of_last_swap' and exact['tokens'] == buy(states[5])
        assert exact['buy']['input_side_overstated_by_at_most'] == 0 < unknown['buy']['input_side_overstated_by_at_most']
        assert unknown['status'] == 'closed' and unknown['value'] < exact['value']
        if last_side == 'sell':
            assert unknown['tokens'] < exact['tokens']                        # the base reserve may be lower: fewer tokens
    with pytest.raises(ValueError, match='protocol_and_fund_rates_go_together'):
        lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, protocol_fee_rate=120_000)


def test_what_cannot_be_valued_carries_a_status_and_no_number():
    line, _ = pool(QUIET)
    late = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 31, **SHARES)
    assert late['status'] == 'outside_the_collected_window' and 'value' not in late
    assert lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 32, **SHARES)['status'] == 'closed'
    unopened, _ = pool(QUIET, opened=False)
    assert lab.probe(unopened, delay_s=10, hold_s=20, window_end_time=T0 + 600)['status'] == 'unpriced_pool_creation_unknown'
    empty = ct.build(POOL_B58, {}, base_mint=BASE_B58, opened=(SLOT0, T0))
    block = lab.probe(empty, delay_s=10, hold_s=20, window_end_time=T0 + 600, buy_fees=(FEES, True), sell_fees=(FEES, True))
    assert block['status'] == 'unpriced_no_cpmm_state' and 'value' not in block
    # a token with a transfer fee
    sim = Sim(BASE0, QUOTE0, FEES, True)
    got = curve.swap_base_input(10**9, sim.quote, sim.base, FEES, True)
    taxed = events.SWAP_DISCRIMINATOR + struct.pack('<32s6Q?', POOL, sim.quote, sim.base, got.input_amount, got.output_amount, 0, 7, True) \
        + struct.pack('<32s32s2Q?', QUOTE, BASE, got.trade_fee, got.creator_fee, True)
    line = ct.build(POOL_B58, dict(a=tx(SLOT0 + 5, 0, logs(taxed), when=T0 + 2)), base_mint=BASE_B58, opened=(SLOT0, T0))
    assert lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600)['status'] == 'unpriced_token_transfer_fee'
    # a transaction that could not be decoded
    broken = dict(a=tx(SLOT0 + 5, 0, logs(swap_payload(1, 1, 1, 1, True, QUOTE, BASE, 0, 0, True)[:-3]), when=T0 + 2))
    line = ct.build(POOL_B58, broken, base_mint=BASE_B58, opened=(SLOT0, T0))
    assert line.skipped and lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600)['status'] == 'unpriced_undecoded_transactions'
    # liquidity added after the last swap before our landing: the reserves are not known, nothing is bridged
    sim = Sim(BASE0, QUOTE0, FEES, True)
    first, _ = sim.swap('buy', 10**9)
    second, _ = sim.swap('sell', 10**11)
    lp = events.LP_DISCRIMINATOR + struct.pack('<32s7QB', POOL, 1, sim.quote, sim.base, 10**9, 10**13, 0, 0, 0)
    sim.quote, sim.base = sim.quote + 10**9, sim.base + 10**13
    third, _ = sim.swap('buy', 10**9)
    txs = dict(a=tx(SLOT0 + 5, 0, logs(first), when=T0 + 2), b=tx(SLOT0 + 6, 0, logs(second), when=T0 + 3),
               c=tx(SLOT0 + 20, 0, logs(lp), when=T0 + 8), d=tx(SLOT0 + 200, 0, logs(third), when=T0 + 90))
    line = ct.build(POOL_B58, txs, base_mint=BASE_B58, opened=(SLOT0, T0))
    block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, **SHARES)
    assert block['status'] == 'unpriced_lp_change' and 'value' not in block


def test_arguments_are_checked():
    line, _ = pool(QUIET)
    for bad in (dict(delay_s=-1), dict(hold_s=0), dict(latency_s=0), dict(stake=0), dict(delay_s=1.5), dict(window_end_time=None)):
        kwargs = dict(dict(delay_s=10, hold_s=20, window_end_time=T0 + 600), **bad)
        with pytest.raises(ValueError):
            lab.probe(line, **kwargs)


def test_an_unknown_creator_fee_side_keeps_the_worse_candidate_whichever_it_is():
    creator = curve.Fees(2500, 1000, 120_000, 40_000)
    # only sales before our buy: the buy side of the creator fee is unknown; only buys before our sale: the same for the sale
    for stake, worse in ((STAKE, True), (10 * STAKE, False)):               # the worse side changes with our size
        line, states = pool([(2, 'sell', 10**11), (5, 'sell', 10**11), (90, 'buy', 10**8)], fees=creator)
        block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, stake=stake, sell_fees=(creator, True), **SHARES)
        assert block['buy']['fee_source'] == 'sell_swaps_before_landing_creator_fee_side_unknown'
        both = {side: buy(states[5], stake, creator, side) for side in (True, False)}
        assert both[worse] < both[not worse] and block['tokens'] == both[worse]
        assert block['buy']['creator_fee_on_input'] is worse
        line, states = pool([(2, 'buy', 10**9), (5, 'buy', 10**9), (90, 'buy', 10**8)], fees=creator)
        block = lab.probe(line, delay_s=10, hold_s=20, window_end_time=T0 + 600, stake=stake, **SHARES)
        tokens = buy(states[5], stake, creator)
        both = {side: sell(states[5], tokens, creator, side) for side in (True, False)}
        assert block['tokens'] == tokens and both[worse] < both[not worse] and block['value'] == both[worse]
        assert block['sell']['creator_fee_on_input'] is worse
