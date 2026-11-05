"""Causal replay engine: causality, latency, exact fills, own impact, migration."""
from dataclasses import replace

import pytest

from bot.market.launchlab_curve import CurveError, CurveState, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT
from bot.market.pool_timeline import build_timeline
from bot.market.replay import ExecutionModel, Strategy, replay
from test_launchlab_market_events import FRESH, POOL, _event_from_fill

RATE = 12_500
ZERO_COST = ExecutionModel(latency_slots=0, priority_fee_lamports=0, base_fee_lamports=0)
OTHER_QUOTE = 'TSM2Hiuf7Z9REcwZFQvsBEekBYCYziWBABfFnj6V6gQ'   # 6-decimal non-SOL quote on chain


def run(timeline, strategy, model=ZERO_COST, quote_mint=WSOL_MINT):
    return replay(timeline, strategy, model, quote_mint=quote_mint)


def _timeline(trades, state=FRESH, slots=None):
    """trades: list of ('buy', quote) / ('sell', fraction_of_curve_inventory)."""
    events = []
    for i, (side, size) in enumerate(trades):
        if side == 'buy':
            fill = buy_exact_in(state, size, RATE)
        else:
            fill = sell_exact_in(state, max(1, int(state.real_base * size)), RATE)
        slot = slots[i] if slots else 100 + i
        events.append(_event_from_fill(fill, slot=slot, sig=f's{i:03d}'))
        state = fill.after
    return build_timeline(POOL, events)


class Scripted(Strategy):
    def __init__(self, enter_at, spend, exit_at=None):
        self.enter_at, self.spend, self.exit_at = enter_at, spend, exit_at
        self.seen = []

    def entry(self, history):
        self.seen.append(len(history))
        return self.spend if len(history) - 1 == self.enter_at else None

    def exit(self, history, position, mark):
        self.seen.append(len(history))
        return self.exit_at is not None and len(history) - 1 >= self.exit_at


def test_strategy_only_ever_sees_a_growing_prefix():
    timeline = _timeline([('buy', 10**9)] * 6)
    strategy = Scripted(enter_at=1, spend=10**8, exit_at=4)
    run(timeline, strategy, ZERO_COST)
    assert strategy.seen == sorted(strategy.seen) and max(strategy.seen) <= 6
    assert strategy.seen[:2] == [1, 2]


def test_zero_latency_immediate_exit_equals_exact_round_trip():
    timeline = _timeline([('buy', 10**9), ('buy', 10**9)])
    result = run(timeline, Scripted(enter_at=0, spend=5 * 10**8, exit_at=1), ZERO_COST)
    # Buy after event 0, then event 1 is replayed on the shifted curve, then sell.
    state = timeline.events[0].state_after()
    buy = buy_exact_in(state, 5 * 10**8, RATE)
    shifted = buy_exact_in(buy.after, 10**9, RATE).after
    sale = sell_exact_in(shifted, buy.amount_out, RATE)
    assert result.outcome == 'closed'
    assert (result.tokens, result.received) == (buy.amount_out, sale.amount_out)
    assert result.pnl == sale.amount_out - 5 * 10**8


def test_own_buy_makes_later_buyers_pay_more_than_on_chain():
    timeline = _timeline([('buy', 10**9), ('buy', 2 * 10**9)])
    real_tokens = timeline.events[1].amount_out
    state = buy_exact_in(timeline.events[0].state_after(), 10**9, RATE).after
    assert buy_exact_in(state, 2 * 10**9, RATE).amount_out < real_tokens


def test_latency_lets_same_and_next_slot_trades_go_first():
    slots = [100, 100, 101, 102, 105]
    timeline = _timeline([('buy', 10**9)] * 5, slots=slots)
    model = replace(ZERO_COST, latency_slots=1)
    result = run(timeline, Scripted(enter_at=0, spend=10**8, exit_at=10), model)
    assert result.entry_index == 2            # lands after the last event of slot 101
    assert result.outcome == 'open_at_end'


def test_costs_are_charged_per_transaction():
    timeline = _timeline([('buy', 10**9)] * 3)
    model = ExecutionModel(latency_slots=0, priority_fee_lamports=50_000)
    free = run(timeline, Scripted(0, 10**8, 1), ZERO_COST)
    paid = run(timeline, Scripted(0, 10**8, 1), model)
    assert paid.tx_costs == 2 * 55_000
    assert free.pnl - paid.pnl == 110_000


def test_round_trip_in_a_quiet_pool_always_loses():
    timeline = _timeline([('buy', 10**9)] + [('sell', 0.01)] * 3)
    result = run(timeline, Scripted(0, 10**9, 1), ExecutionModel(latency_slots=0))
    assert result.outcome == 'closed' and result.pnl < 0


def test_migration_during_position_is_unpriced_not_profit():
    # Launch-to-date history on a small curve, so that a real trade can reach the cap.
    start = CurveState(FRESH.virtual_base, FRESH.virtual_quote, 0, 0, 5 * 10**13)
    first = buy_exact_in(start, 10**9, RATE)
    remaining = start.total_base_sell - first.after.real_base
    # Largest real buy that fits on the chain without our order (bisection).
    low, high = 10**6, 10**12
    while low < high:
        middle = (low + high + 1) // 2
        try:
            buy_exact_in(first.after, middle, RATE)
            low = middle
        except CurveError:
            high = middle - 1
    real_big = buy_exact_in(first.after, low, RATE)
    ours = 3 * 10**8
    ours_fill = buy_exact_in(first.after, ours, RATE)
    assert ours_fill.amount_out < remaining
    with pytest.raises(CurveError, match='buy_crosses_migration_boundary'):
        buy_exact_in(ours_fill.after, low, RATE)      # our buy makes that real buy impossible
    events = [_event_from_fill(first, slot=100, sig='a'),
              _event_from_fill(real_big, slot=101, sig='b')]
    timeline = build_timeline(POOL, events)
    assert timeline.complete                           # history starts at launch
    result = run(timeline, Scripted(0, ours), ZERO_COST)
    assert result.outcome == 'migrated_unpriced' and result.pnl is None
    assert result.notes and 'buy_crosses_migration_boundary' in result.notes[0]


def test_mid_curve_history_is_refused_by_replay():
    mid = buy_exact_in(FRESH, 10**9, RATE).after
    timeline = _timeline([('buy', 10**9)] * 2, state=mid)
    assert [g.reason for g in timeline.gaps] == ['history_starts_mid_curve']
    with pytest.raises(ValueError, match='timeline_incomplete'):
        run(timeline, Scripted(0, 10**8), ZERO_COST)


def test_non_sol_quote_is_refused_because_costs_are_lamports():
    timeline = _timeline([('buy', 10**9)] * 2)
    with pytest.raises(ValueError, match='quote_not_sol'):
        run(timeline, Scripted(0, 10**8, 1), ZERO_COST, quote_mint=OTHER_QUOTE)


def test_no_entry_when_strategy_never_buys():
    timeline = _timeline([('buy', 10**9)] * 3)
    result = run(timeline, Scripted(enter_at=99, spend=1), ZERO_COST)
    assert result.outcome == 'no_entry' and result.pnl is None and result.spent == 0


# --- share fee of a third party must not leak into our own fills --------------

def _timeline_with_share(share_fee):
    base = _timeline([('buy', 10**9)] * 3)
    ev = list(base.events)
    first = ev[0]
    assert first.protocol_fee > share_fee
    ev[0] = replace(first, protocol_fee=first.protocol_fee - share_fee, share_fee=share_fee)
    return build_timeline(POOL, ev), first


def test_own_rate_excludes_third_party_share_fee():
    share = 3_000_000
    timeline, original = _timeline_with_share(share)
    no_share = run(_timeline([('buy', 10**9)] * 3), Scripted(0, 10**8, 1),
                   ExecutionModel(latency_slots=0, priority_fee_lamports=0, base_fee_lamports=0))
    res = run(timeline, Scripted(0, 10**8, 1),
              ExecutionModel(latency_slots=0, priority_fee_lamports=0, base_fee_lamports=0))
    # Total event fee is unchanged; only 3_000_000 of it was a share fee, so our
    # rate must be strictly lower than the all-in rate, and below the 12_500 ppm.
    assert res.fee_rate_ppm < no_share.fee_rate_ppm
    expected = ((original.protocol_fee - share - 1) * 1_000_000) // 10**9 + 1
    assert res.fee_rate_ppm == expected


def test_explicit_model_rate_is_unaffected_by_share_exclusion():
    timeline, _ = _timeline_with_share(3_000_000)
    res = run(timeline, Scripted(0, 10**8, 1),
              ExecutionModel(latency_slots=0, fee_rate_ppm=RATE, priority_fee_lamports=0,
                             base_fee_lamports=0))
    assert res.fee_rate_ppm == RATE and res.fee_rate_source == 'model'
