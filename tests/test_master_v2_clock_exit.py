"""Clock exit on a silent curve (research option, off by default).

Phase 2 on P0 showed most entered positions never closing: max_hold was only examined at
the next real trade, so a position in a pool that falls silent stayed ``open_at_end``. On a
bonding curve our own sale needs no counterparty: with ``ExitRule(clock_exit=True)`` the
sale is sent at the deadline (entry block_time + max_hold_s) and lands after every real
event up to the deadline plus the latency (rounded up to whole seconds), on the curve state
those events leave. Off by default: every registered protocol and L1 fingerprint is unchanged.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from bot.market.collector import summarize
from bot.market.launchlab_curve import sell_exact_in
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import ExecutionModel, Strategy, replay
from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol
from bot.p4 import historical_research_replay as hrr

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
PROTOCOL = hrr.ReplayParams(latency_slots=4, exit_horizon_ms=25_000)


def _timeline(index=1):
    archives = [archive for _, archive in hrr.load_fixtures(PACK)[2]]
    archive = archives[index]
    summary, timeline = summarize(archive)
    return archive, hrr.usable_timeline(archive, summary, timeline)[0]


class _Timed(Strategy):
    """Enter at the first event; never exit on events; deadline ``hold`` seconds after entry."""

    def __init__(self, hold):
        self.hold = hold

    def entry(self, history):
        return 100_000_000

    def exit(self, history, position, mark):
        return False

    def exit_deadline(self, position):
        return position.entry_time + self.hold


def test_clock_exit_is_off_by_default_and_changes_nothing():
    _, timeline = _timeline()
    default = replay(timeline, _Timed(5), ExecutionModel(), quote_mint=WSOL_MINT)
    assert default.outcome == 'open_at_end' and default.clock_exit is None


def test_clock_exit_sells_on_the_state_left_by_events_up_to_deadline_plus_latency():
    _, timeline = _timeline()
    events = timeline.events
    model = ExecutionModel(clock_exit_latency_s=1)
    result = replay(timeline, _Timed(5), model, quote_mint=WSOL_MINT)
    assert result.outcome == 'closed' and 'clock_exit' in result.notes
    entry_time = events[result.entry_index].block_time
    landing = entry_time + 5 + 1
    last = result.exit_index
    assert events[last].block_time <= landing                       # every event up to landing is applied
    assert last == len(events) - 1 or events[last + 1].block_time > landing   # and none after it
    assert result.clock_exit == dict(deadline=entry_time + 5, landing_time=landing, last_index=last)
    # Proceeds equal the exact sale on the shifted curve after event ``last`` (own buy included).
    reference = replay(timeline, _Timed(10 ** 6), ExecutionModel(), quote_mint=WSOL_MINT)
    assert reference.outcome == 'open_at_end'
    assert result.received > 0 and result.tx_costs == 2 * model.tx_cost


def test_a_silent_pool_closes_at_the_deadline_instead_of_staying_open():
    _, timeline = _timeline()
    hold = timeline.events[-1].block_time - timeline.events[0].block_time + 100    # beyond the data
    result = replay(timeline, _Timed(hold), ExecutionModel(clock_exit_latency_s=1), quote_mint=WSOL_MINT)
    assert result.outcome == 'closed' and result.exit_index == len(timeline.events) - 1
    marked = replay(timeline, _Timed(hold), ExecutionModel(), quote_mint=WSOL_MINT)
    assert marked.outcome == 'open_at_end' and result.received == marked.received   # same exact quote, now closed


def test_harness_rule_flag_trigger_and_conservative_exit_slot():
    rule = h.ExitRule(max_hold_s=5, clock_exit=True)
    with pytest.raises(ValueError, match='clock_exit_requires_max_hold_s'):
        h.ExitRule(stop_loss=0.1, clock_exit=True)
    archive, timeline = _timeline()
    record = h.run_policy_pool(archive, pol.ImmediateSnipe(max_age_s=10_000), rule, PROTOCOL, quote_mint=WSOL_MINT)
    trade = record['trade']
    assert trade['outcome'] == 'closed' and trade['exit_trigger']['reason'] == 'max_hold_clock'
    landing = trade['entry_block_time'] + 5 + h.clock_latency_s(PROTOCOL)
    assert trade['exit_block_time'] == landing and trade['exit_signature'] is None
    last_slot = timeline.events[trade['exit_index']].slot
    last_time = timeline.events[trade['exit_index']].block_time
    assert trade['exit_slot'] == last_slot + hrr.slots_for_ms((landing - last_time) * 1000) + PROTOCOL.latency_slots
    off = h.run_policy_pool(archive, pol.ImmediateSnipe(max_age_s=10_000), replace(rule, clock_exit=False),
                            PROTOCOL, quote_mint=WSOL_MINT)['trade']
    assert off['exit_trigger'] is None or off['exit_trigger']['reason'] != 'max_hold_clock'


def test_clock_latency_rounds_up_to_whole_seconds():
    assert h.clock_latency_s(hrr.ReplayParams(latency_slots=4)) == 1      # 4 x 215 ms = 0.86 s
    assert h.clock_latency_s(hrr.ReplayParams(latency_slots=5)) == 2      # 1.075 s
    assert h.clock_latency_s(hrr.ReplayParams(latency_slots=2)) == 1


def test_window_counts_a_clock_exit_beyond_the_window_as_open():
    archive, timeline = _timeline()
    events = timeline.events
    window = dict(entry_cutoff_slot=events[-1].slot, window_slot_max=events[-1].slot + 1)
    record = h.run_policy_pool(archive, pol.ImmediateSnipe(max_age_s=10_000), h.ExitRule(max_hold_s=600, clock_exit=True),
                               PROTOCOL, quote_mint=WSOL_MINT, window=window)
    assert record['trade']['outcome'] == 'open_at_window_end'


def test_default_runs_are_byte_identical_without_the_flag():
    base = h.run_policy(PACK, pol.ImmediateSnipe(), h.ExitRule(max_hold_s=25), PROTOCOL)
    assert all('clock_exit' not in row['trade']['notes'] for row in base['pools'])
    assert 'clock_exit' not in base['exit_rule']                     # pre-registrations of old configs unchanged


def test_policy_arm_exposes_a_deadline_only_with_the_flag():
    from bot.market.replay import Position
    position = Position(0, 100, 1_000, 100_000_000, 5)
    on = h.PolicyArm(pol.NoTrade(), h.ExitRule(max_hold_s=25, clock_exit=True), {}, {}, 1)
    off = h.PolicyArm(pol.NoTrade(), h.ExitRule(max_hold_s=25), {}, {}, 1)
    assert on.exit_deadline(position) == 1_025 and off.exit_deadline(position) is None
