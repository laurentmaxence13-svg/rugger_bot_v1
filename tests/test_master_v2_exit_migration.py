"""An event-driven sale still pending when the curve migrated is never a closed cycle (R02 B2).

The replay sends an event-driven sale at the trigger and lands it after every real event up
to trigger slot + latency. A migrated timeline ends just before the buy that crosses the
boundary, so a sale pending at its end used to be filled on the bonding curve and counted
``closed`` although the curve had migrated before it could land. The conservative landing
slot (trigger + latency) is now the row's ``exit_slot``; a sale landing at or after the
boundary slot is ``migrated_unpriced``, for timed and event-driven sales, in V2 and in L1.
"""
from pathlib import Path

import pytest

from bot.market.collector import summarize
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import ExecutionModel, Strategy, replay
from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol
from bot.p4 import historical_research_replay as hrr

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
LATENCY = 4
LONG = hrr.ReplayParams(latency_slots=LATENCY, exit_horizon_ms=10 ** 9)   # only max_hold triggers
SNIPE = pol.ImmediateSnipe(max_age_s=10_000)


def _archive(index=1):
    return [archive for _, archive in hrr.load_fixtures(PACK)[2]][index]


def _events(archive):
    summary, timeline = summarize(archive)
    return hrr.usable_timeline(archive, summary, timeline)[0].events


def _migrating(monkeypatch, boundary_slot):
    original = hrr.usable_timeline

    def fake(archive, summary, timeline):
        timeline, _ = original(archive, summary, timeline)
        return timeline, dict(rule='test', boundary_signatures=['x'], boundary_slot=boundary_slot,
                              boundary_transaction_index=0, max_progress_ppm=999_999)
    monkeypatch.setattr(hrr, 'usable_timeline', fake)


def _late_rule(events):
    """max_hold reached only in the last second of data: the trigger is one of the last events."""
    return h.ExitRule(max_hold_s=events[-1].block_time - events[0].block_time)


class _ExitAtLast(Strategy):
    """Enter at the first event, trigger the sale on the last observed event."""

    def __init__(self, count):
        self.count = count

    def entry(self, history):
        return 100_000_000

    def exit(self, history, position, mark):
        return len(history) == self.count


def test_event_sale_exposes_its_conservative_landing_slot():
    archive = _archive()
    events = _events(archive)
    summary, timeline = summarize(archive)
    timeline = hrr.usable_timeline(archive, summary, timeline)[0]
    result = replay(timeline, _ExitAtLast(len(events)), ExecutionModel(latency_slots=LATENCY), quote_mint=WSOL_MINT)
    assert result.outcome == 'closed' and result.exit_index == len(events) - 1
    assert result.exit_landing_slot == events[-1].slot + LATENCY > events[-1].slot
    marked = replay(timeline, _ExitAtLast(10 ** 9), ExecutionModel(latency_slots=LATENCY), quote_mint=WSOL_MINT)
    assert marked.outcome == 'open_at_end' and marked.exit_landing_slot is None


def test_event_exit_slot_is_trigger_plus_latency_not_the_last_applied_event():
    archive = _archive()
    events = _events(archive)
    trade = h.run_policy_pool(archive, SNIPE, _late_rule(events), LONG, quote_mint=WSOL_MINT)['trade']
    assert trade['outcome'] == 'closed' and trade['exit_trigger']['reason'] == 'max_hold'
    trigger_slot = events[trade['exit_trigger']['index']].slot
    assert trade['exit_slot'] == trigger_slot + LATENCY
    assert trade['exit_slot'] > events[trade['exit_index']].slot          # the landing, not the last event


def test_event_sale_pending_across_the_migration_is_unpriced_r02_b2(monkeypatch):
    archive = _archive()
    events = _events(archive)
    _migrating(monkeypatch, events[-1].slot + 1)       # R02 probe: boundary right after the last kept event
    trade = h.run_policy_pool(archive, SNIPE, _late_rule(events), LONG, quote_mint=WSOL_MINT)['trade']
    assert trade['outcome'] == 'migrated_unpriced' and trade['pnl_lamports'] is None
    assert trade['net_return'] is None and 'exit_after_migration' in trade['notes']


@pytest.mark.parametrize('offset, outcome', ((0, 'migrated_unpriced'), (1, 'closed')))
def test_event_sale_boundary_equality(monkeypatch, offset, outcome):
    archive = _archive()
    events = _events(archive)
    landing = h.run_policy_pool(archive, SNIPE, _late_rule(events), LONG, quote_mint=WSOL_MINT)['trade']['exit_slot']
    _migrating(monkeypatch, landing + offset)          # landing == boundary is unpriced; one slot before is not
    trade = h.run_policy_pool(archive, SNIPE, _late_rule(events), LONG, quote_mint=WSOL_MINT)['trade']
    assert trade['outcome'] == outcome


@pytest.mark.parametrize('offset, outcome', ((0, 'migrated_unpriced'), (1, 'closed')))
def test_clock_sale_boundary_equality(monkeypatch, offset, outcome):
    archive = _archive()
    rule = h.ExitRule(max_hold_s=5, clock_exit=True)
    protocol = hrr.ReplayParams(latency_slots=LATENCY, exit_horizon_ms=25_000)
    landing = h.run_policy_pool(archive, SNIPE, rule, protocol, quote_mint=WSOL_MINT)['trade']['exit_slot']
    _migrating(monkeypatch, landing + offset)
    trade = h.run_policy_pool(archive, SNIPE, rule, protocol, quote_mint=WSOL_MINT)['trade']
    assert trade['outcome'] == outcome and 'clock_exit' in trade['notes']


def test_l1_replay_pool_applies_the_same_rule(monkeypatch):
    archive = _archive()
    events = _events(archive)
    original = hrr.replay

    def at_last(timeline, arm, model, *, quote_mint):
        return original(timeline, _ExitAtLast(len(timeline.events)), model, quote_mint=quote_mint)
    monkeypatch.setattr(hrr, 'replay', at_last)
    params = hrr.ReplayParams(latency_slots=LATENCY, exit_horizon_ms=25_000)
    closed = hrr.replay_pool(archive, params, quote_mint=WSOL_MINT)
    assert {row['outcome'] for row in closed['arms'].values()} == {'closed'}
    assert {row['exit_slot'] for row in closed['arms'].values()} == {events[-1].slot + LATENCY}
    _migrating(monkeypatch, events[-1].slot + 1)
    migrated = hrr.replay_pool(archive, params, quote_mint=WSOL_MINT)
    for row in migrated['arms'].values():
        assert row['outcome'] == 'migrated_unpriced' and row['pnl_lamports'] is None
        assert 'exit_after_migration' in row['notes']


def test_window_uses_the_landing_slot_of_an_event_sale():
    archive = _archive()
    events = _events(archive)
    landing = h.run_policy_pool(archive, SNIPE, _late_rule(events), LONG, quote_mint=WSOL_MINT)['trade']['exit_slot']
    window = dict(entry_cutoff_slot=events[-1].slot, window_slot_max=landing - 1)   # after every event, before landing
    assert window['window_slot_max'] >= events[-1].slot
    trade = h.run_policy_pool(archive, SNIPE, _late_rule(events), LONG, quote_mint=WSOL_MINT, window=window)['trade']
    assert trade['outcome'] == 'open_at_window_end'


def test_exit_after_migration_helper():
    migration = dict(boundary_slot=100)
    closed = dict(outcome='closed', exit_slot=99, pnl_lamports=5, net_return=0.1, notes=[])
    assert hrr._exit_after_migration(closed, migration) is closed
    assert hrr._exit_after_migration(closed, None) is closed
    for slot in (100, 101):
        row = hrr._exit_after_migration(dict(closed, exit_slot=slot), migration)
        assert (row['outcome'], row['pnl_lamports'], row['net_return']) == ('migrated_unpriced', None, None)
    other = dict(closed, outcome='open_at_end', exit_slot=500)
    assert hrr._exit_after_migration(other, migration) is other       # open positions: _migrated's job
