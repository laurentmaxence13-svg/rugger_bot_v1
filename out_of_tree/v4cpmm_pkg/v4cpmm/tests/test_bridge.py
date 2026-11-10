"""v4cpmm bridge: synthetic curve that migrates while we hold, synthetic CPMM pool. No real data."""
import copy
import dataclasses

import pytest

from bot.market.launchlab_curve import CurveError, CurveState, buy_exact_in
from bot.market.launchlab_events import WSOL_MINT, TradeEvent
from bot.market.pool_timeline import PoolTimeline
from bot.market.replay import ExecutionModel

from cpmmx import curve, timeline as cpmm_timeline
from cpmmx.tests.test_cpmmx import BASE_B58, POOL_B58, Sim, logs, swap_payload, tx, QUOTE, BASE
from v4sim import engine
from v4sim.batch import FixedOrder
from v4sim.engine import Execution

from v4cpmm import bridge

VIRTUAL_BASE, VIRTUAL_QUOTE, TOTAL_BASE_SELL = 1_073_025_605_596_382, 30_000_852_951, 793_100_000_000_000
RATE = 10_000
MODEL = ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval', clock_exit_latency_s=2)
FEES = curve.Fees(2500, 0, 120_000, 40_000)
T0 = 1_790_000_000


def curve_timeline():
    """Buys that fill the bonding curve to its end: any extra buyer (us) makes a later buy cross the boundary."""
    state = CurveState(VIRTUAL_BASE, VIRTUAL_QUOTE, 0, 0, TOTAL_BASE_SELL)
    events, slot = [], 400_000_000
    for amount in [10**9] * 3 + [5 * 10**9] * 40 + [10**9] * 40 + [10**8] * 40 + [10**7] * 40:
        try:
            fill = buy_exact_in(state, amount, RATE)
        except CurveError:
            continue
        slot += 2
        events.append(TradeEvent(
            signature=f'curve{len(events):04d}', slot=slot, block_time=T0 + (slot - 400_000_000) * 2 // 5,
            event_index=0, fee_payer=f'actor{len(events) % 7}', pool='LaunchPool', side='buy', exact_in=True,
            pool_status=0, total_base_sell=TOTAL_BASE_SELL, virtual_base=VIRTUAL_BASE, virtual_quote=VIRTUAL_QUOTE,
            real_base_before=state.real_base, real_quote_before=state.real_quote,
            real_base_after=fill.after.real_base, real_quote_after=fill.after.real_quote,
            amount_in=fill.amount_in, amount_out=fill.amount_out, protocol_fee=fill.fee, platform_fee=0,
            creator_fee=0, share_fee=0))
        state = fill.after
    return PoolTimeline('LaunchPool', tuple(events), ())


CURVE = curve_timeline()
OPEN_SLOT = CURVE.events[-1].slot + 20
OPEN_TIME = CURVE.events[-1].block_time + 8


class Clock(FixedOrder):
    def __init__(self, hold_s):
        super().__init__(0, 100_000_000, 10**9)
        self.hold_s = hold_s

    def exit_deadline(self, position):
        return position.entry_time + self.hold_s


def cpmm_pool(steps, *, fees=FEES, on_input=True, opened=True):
    """``steps``: (slot offset from the opening, side, amount). Returns (timeline, {slot offset: (base, quote)})."""
    sim = Sim(206_900_000 * 10**6, 85 * 10**9, fees, on_input)
    txs, states = {}, {-1: (sim.base, sim.quote)}
    for index, (offset, side, amount) in enumerate(steps):
        payload, _ = sim.swap(side, amount)
        txs[f'cp{index:03d}'] = tx(OPEN_SLOT + offset, index, logs(payload), when=OPEN_TIME + offset * 2 // 5)
        states[offset] = (sim.base, sim.quote)
    line = cpmm_timeline.build(POOL_B58, txs, base_mint=BASE_B58,
                               opened=(OPEN_SLOT, OPEN_TIME) if opened else None)
    return line, states


def run(strategy=None, **kwargs):
    return bridge.replay(CURVE, strategy or FixedOrder(0, 100_000_000, 10**9), kwargs.pop('model', MODEL),
                         quote_mint=WSOL_MINT, **kwargs)


def test_the_synthetic_position_migrates_and_v4sim_leaves_it_unpriced():
    plain = engine.replay(CURVE, FixedOrder(0, 100_000_000, 10**9), MODEL, quote_mint=WSOL_MINT)
    assert plain.outcome == 'migrated_unpriced' and plain.tokens > 0 and plain.pnl is None


def test_v4sim_result_is_returned_unchanged():
    line, _ = cpmm_pool([(1, 'buy', 10**9), (3, 'sell', 10**11), (9, 'buy', 10**9)])
    plain = engine.replay(CURVE, FixedOrder(0, 100_000_000, 10**9), MODEL, quote_mint=WSOL_MINT)
    before = copy.deepcopy(dataclasses.asdict(plain))
    got = run(cpmm=line)
    assert dataclasses.asdict(got) == before and got.v4 == plain.v4
    assert got.outcome == 'migrated_unpriced' and got.pnl is None            # the frozen accounting still says unpriced
    assert got.cpmm['status'] == 'sold' and got.cpmm['validated_on_real_swaps'] is False
    assert len(got.cpmm['approximations']) == 6


def test_sale_when_the_pool_opens_is_the_program_output_on_the_landing_state():
    line, states = cpmm_pool([(1, 'buy', 10**9), (3, 'sell', 10**11), (5, 'buy', 2 * 10**9), (9, 'buy', 10**9)])
    got = run(cpmm=line, protocol_fee_rate=120_000, fund_fee_rate=40_000)
    block = got.cpmm
    base, quote = states[3]                                      # every swap up to opening + 4 slots has executed
    expected = curve.swap_base_input(got.tokens, base, quote, FEES, True).output_amount
    assert block['landing'] == dict(slot_limit=OPEN_SLOT + 4) and block['received'] == expected
    assert block['evidence']['source'] == 'next_swap_logged_reserves'
    assert block['evidence']['fee_source'] == 'sell_swaps_before_landing'
    costs = got.tx_costs + MODEL.tx_cost
    assert block['total_tx_costs'] == costs == 2 * MODEL.tx_cost
    assert block['pnl_lamports'] == expected - got.spent - costs
    assert block['net_return'] == (expected - got.spent - costs) / (got.spent + costs)
    assert block['value_without_impact_or_fee'] > expected


def test_h1_the_lower_of_the_two_orders_inside_the_landing_slot_is_kept():
    for side, amount, kept, other_state in (('buy', 5 * 10**9, 'before', 3), ('sell', 20 * 10**12, 'after', 4)):
        line, states = cpmm_pool([(1, 'buy', 10**9), (3, 'sell', 10**11), (4, side, amount), (9, 'buy', 10**9)])
        got = run(cpmm=line, fees=(FEES, True), protocol_fee_rate=120_000, fund_fee_rate=40_000)
        evidence = got.cpmm['evidence']
        values = {name: curve.swap_base_input(got.tokens, *states[offset], FEES, True).output_amount
                  for name, offset in (('before', 3), ('after', 4))}
        assert evidence['value_by_order_in_landing_slot'] == values and values['before'] != values['after']
        assert evidence['kept_order'] == kept and got.cpmm['received'] == min(values.values())
        assert got.cpmm['received'] == values['before' if other_state == 3 else 'after']


def test_h5_displaced_demand_is_published_and_the_lower_value_is_kept():
    from bot.market.launchlab_curve import fee_for
    line, states = cpmm_pool([(1, 'buy', 10**9), (3, 'sell', 10**11), (9, 'buy', 10**9)])
    got = run(cpmm=line, fees=(FEES, True), protocol_fee_rate=120_000, fund_fee_rate=40_000)
    evidence = got.cpmm['evidence']
    base, quote = states[3]
    net = got.spent - fee_for(got.spent, got.fee_rate_ppm)
    displaced = curve.swap_base_input(net, quote, base, FEES, True)
    quote_after, base_after = curve.reserves_after(quote, base, displaced)
    other = curve.swap_base_input(got.tokens, base_after, quote_after, FEES, True).output_amount
    assert evidence['value_with_displaced_demand'] == other > evidence['value_on_real_reserves']
    assert got.cpmm['received'] == evidence['value_on_real_reserves']


def test_x1_the_curve_invariant_fixes_the_quote_at_the_boundary_whatever_our_purchase():
    """The pool opens with what the curve holds at its end: that amount does not depend on the path."""
    from bot.market.launchlab_curve import CurveError, buy_exact_in

    def quote_at_the_boundary(state):
        k = state.base_reserve * state.quote_reserve
        return k // (state.virtual_base - state.total_base_sell) - state.virtual_quote

    real = CURVE.events[-1].state_after()
    state = buy_exact_in(CURVE.events[0].state_after(), 100_000_000, RATE).after      # our purchase, then the same flow
    for event in CURVE.events[1:]:
        try:
            state = buy_exact_in(state, event.amount_in, RATE).after
        except CurveError:
            break
    assert abs(quote_at_the_boundary(state) - quote_at_the_boundary(real)) <= 1


def test_nothing_is_creditable_before_a12_and_the_reasons_are_listed():
    line, _ = cpmm_pool([(1, 'buy', 10**9), (3, 'sell', 10**11), (9, 'buy', 10**9)])
    read = run(cpmm=line, fees=(FEES, True), protocol_fee_rate=120_000, fund_fee_rate=40_000).cpmm
    assert read['creditable'] is False and read['credit_blockers'] == ['a12_not_passed_on_real_swaps']
    deduced = run(cpmm=line).cpmm
    assert deduced['creditable'] is False
    assert deduced['credit_blockers'] == ['a12_not_passed_on_real_swaps', 'fee_rates_not_read_from_the_amm_config']


def test_no_number_without_a_fee_rate_or_a_pool_state():
    line, states = cpmm_pool([(6, 'buy', 10**9)])                # nobody has traded when our order lands
    block = run(cpmm=line).cpmm
    assert block['status'] == 'unpriced_fee_rate_not_observable_yet' and 'received' not in block
    given = run(cpmm=line, fees=(FEES, True)).cpmm               # rates read from the pool's AmmConfig
    assert given['status'] == 'sold' and given['evidence']['source'] == 'first_swap_logged_reserves'
    assert given['received'] == curve.swap_base_input(run().tokens, *states[-1], FEES, True).output_amount
    assert run(cpmm=None).cpmm['status'] == 'unpriced_no_cpmm_timeline'
    assert run(cpmm=cpmm_pool([(1, 'buy', 10**9)], opened=False)[0]).cpmm['status'] == 'unpriced_pool_creation_unknown'
    empty = cpmm_timeline.build(POOL_B58, {}, base_mint=BASE_B58, opened=(OPEN_SLOT, OPEN_TIME))
    assert run(cpmm=empty, fees=(FEES, True)).cpmm['status'] == 'unpriced_no_cpmm_state'


def test_a_closed_position_is_not_touched():
    line, _ = cpmm_pool([(1, 'buy', 10**9)])
    got = run(FixedOrder(0, 100_000_000, 3), cpmm=line)
    assert got.outcome == 'closed' and got.cpmm['status'] == 'not_applicable'


def test_clock_rule_lands_at_the_deadline_or_at_the_opening_when_it_is_past():
    steps = [(1, 'buy', 10**9), (2, 'sell', 10**11), (300, 'buy', 20 * 10**9), (600, 'sell', 10**11)]
    line, states = cpmm_pool(steps)
    entry_time = CURVE.events[run().entry_index].block_time      # decision at 0, landing 4 slots later
    hold = OPEN_TIME + 150 - entry_time                          # deadline 150 s after the opening
    late = run(Clock(hold), cpmm=line, rule='strategy_clock').cpmm
    assert late['landing'] == dict(time_limit=OPEN_TIME + 150 + 2)
    base, quote = states[300]                                    # swaps at +300 slots (120 s) executed, +600 not yet
    assert late['received'] == curve.swap_base_input(run().tokens, base, quote, FEES, True).output_amount
    past = OPEN_TIME - 3 - entry_time                            # deadline after the curve's end, before the opening
    early = run(Clock(past), cpmm=line, rule='strategy_clock').cpmm
    assert early['landing'] == dict(slot_limit=OPEN_SLOT + 4)
    assert run(Clock(1), cpmm=line, rule='strategy_clock').cpmm['status'] == 'not_applicable'   # sold on the curve
    assert early['received'] == run(cpmm=line).cpmm['received'] < late['received']
    with pytest.raises(ValueError):
        run(cpmm=line, rule='strategy_clock')                    # the strategy has no clock deadline
    with pytest.raises(ValueError):
        run(cpmm=line, rule='at_close')


def test_non_inclusion_is_charged_and_moves_the_landing():
    line, states = cpmm_pool([(1, 'sell', 10**11), (5, 'sell', 3 * 10**12), (9, 'buy', 10**9)])
    execution = next(Execution(p_fail=0.5, max_retries=3, salt=f's{i}') for i in range(200)
                     if engine.not_included(Execution(p_fail=0.5, salt=f's{i}'), 'LaunchPool', 'cpmm_sell', 4, 0)
                     and not engine.not_included(Execution(p_fail=0.5, salt=f's{i}'), 'LaunchPool', 'cpmm_sell', 4, 1)
                     and not engine.not_included(Execution(p_fail=0.5, salt=f's{i}'), 'LaunchPool', 'buy', 0, 0))
    got = run(cpmm=line, execution=execution)
    block = got.cpmm
    assert block['failed_attempts'] == [dict(attempt=0, kind='not_included', cost=MODEL.base_fee_lamports,
                                             landing=dict(slot_limit=OPEN_SLOT + 4))]
    assert block['landing'] == dict(slot_limit=OPEN_SLOT + 8) and block['attempt'] == 1
    assert block['added_tx_costs'] == MODEL.base_fee_lamports + MODEL.tx_cost
    assert block['received'] == curve.swap_base_input(got.tokens, *states[5], FEES, True).output_amount
    assert block['pnl_lamports'] == block['received'] - got.spent - got.tx_costs - block['added_tx_costs']


def test_slippage_limit_fails_the_sale_and_retries_until_exhausted():
    line, _ = cpmm_pool([(1, 'buy', 10**9), (2, 'sell', 10**11), (3, 'sell', 60 * 10**12), (20, 'buy', 10**9)])
    limit = Execution(slippage_bps=2000, max_retries=1)          # 20 %
    block = run(cpmm=line, execution=limit, fees=(FEES, True)).cpmm
    assert block['status'] == 'unsold_exit_retries_exhausted' and 'received' not in block
    assert [a['kind'] for a in block['failed_attempts']] == ['slippage', 'slippage']
    assert block['added_tx_costs'] == 2 * MODEL.tx_cost and block['slippage_reference'] > 0
    loose = run(cpmm=line, execution=Execution(slippage_bps=9000, max_retries=1), fees=(FEES, True)).cpmm
    assert loose['status'] == 'sold' and not loose['failed_attempts']
    # without a fee rate at the creation of the pool no value can be expected: the limit is not applied, and it is said
    blind = run(cpmm=line, execution=limit).cpmm
    assert blind['status'] == 'sold' and blind['slippage_reference'] is None
    assert blind['slippage_limit_not_applied'].startswith('no_exact_input_swap')


def test_unknown_creator_fee_side_keeps_the_lower_value():
    fees = curve.Fees(2500, 1000, 120_000, 40_000)
    line, states = cpmm_pool([(1, 'buy', 10**9), (2, 'buy', 10**9), (9, 'buy', 10**9)], fees=fees, on_input=True)
    got = run(cpmm=line)
    block = got.cpmm
    assert block['evidence']['fee_source'] == 'buy_swaps_before_landing_creator_fee_side_unknown'
    both = [curve.swap_base_input(got.tokens, *states[2], curve.Fees(2500, 1000), flag).output_amount
            for flag in (True, False)]
    assert block['received'] == min(both) and both[0] != both[1]


def test_token_transfer_fee_is_not_modelled():
    payload = bytearray(swap_payload(10**15, 10**11, 10**9, 10**12, True, QUOTE, BASE, 2500, 0, True))
    payload[8 + 32 + 4 * 8:8 + 32 + 5 * 8] = (7).to_bytes(8, 'little')          # input_transfer_fee
    txs = dict(a=tx(OPEN_SLOT + 1, 0, logs(bytes(payload))))
    line = cpmm_timeline.build(POOL_B58, txs, base_mint=BASE_B58, opened=(OPEN_SLOT, OPEN_TIME))
    assert run(cpmm=line).cpmm['status'] == 'unpriced_token_transfer_fee'


def test_a_pool_that_opens_before_the_curve_ends_is_a_binding_error():
    txs = dict(a=tx(OPEN_SLOT - 30, 0, logs(Sim(10**15, 10**11, FEES, True).swap('buy', 10**9)[0])))
    line = cpmm_timeline.build(POOL_B58, txs, base_mint=BASE_B58, opened=(OPEN_SLOT - 40, OPEN_TIME - 16))
    with pytest.raises(ValueError):
        run(cpmm=line)
