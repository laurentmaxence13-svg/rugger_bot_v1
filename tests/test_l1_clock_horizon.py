"""W1 protocol R1: the L1 research horizon enforced by the clock (opt-in, off by default).

The scorer's exit plan keeps TP/SL only (hold_seconds and trailing_stop_pct stay off, R02 D4).
With ``ExitOptions(clock_horizon=True)`` the 30 s research horizon sells at entry block_time
+ 30 s even when the curve is silent, landing ``clock_exit_latency_s`` later on the shifted
curve left by the real events of that second (R02 Q1, D3). Off by default: every recorded L1
fingerprint and every V2 bundle is unchanged.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from bot.market.collector import summarize
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import Position
from bot.p4 import historical_research_replay as hrr

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'
DECLARED = hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')
PLAN = dict(tp_pct=10.0, sl_pct=8.0, trailing_stop_pct=5.0, hold_seconds=1800, cost_bps=200)
CLOCK = hrr.ExitOptions(clock_horizon=True)
ORIGINAL_OBSERVER = hrr._PoolObserver


def _archive(pool=P5PZ):
    return next(archive for _entry, archive in hrr.load_fixtures(PACK)[2] if archive.pool == pool)


def _events(pool=P5PZ):
    archive = _archive(pool)
    summary, timeline = summarize(archive)
    return hrr.usable_timeline(archive, summary, timeline)[0].events


def _force(monkeypatch, enter_index=0):
    """Real observer with an ENTER forced at ``enter_index`` (scorer plan PLAN)."""
    class Forced(ORIGINAL_OBSERVER):
        def _evaluate(self, history):
            result = super()._evaluate(history)
            if len(history) - 1 == enter_index:
                result = dict(result, exit_conditions={k: PLAN[k] for k in ('tp_pct', 'sl_pct')},
                              scorer_exit_plan=dict(PLAN), decisions={
                                  arm: dict(intent='ENTER', blocking_reasons=[]) for arm in hrr.ARMS})
            return result
    monkeypatch.setattr(hrr, '_PoolObserver', Forced)


def _migrating(monkeypatch, boundary_slot):
    original = hrr.usable_timeline

    def fake(archive, summary, timeline):
        timeline, _ = original(archive, summary, timeline)
        return timeline, dict(rule='test', boundary_signatures=['x'], boundary_slot=boundary_slot,
                              boundary_transaction_index=0, max_progress_ppm=999_999)
    monkeypatch.setattr(hrr, 'usable_timeline', fake)


def _master(options, params=DECLARED):
    return hrr.replay_pool(_archive(), params, quote_mint=WSOL_MINT, exit_options=options)['arms']['master']


def test_option_is_off_by_default_validated_and_recorded_only_when_on():
    assert not hrr.ExitOptions().clock_horizon and not hrr.ExitOptions().enabled
    assert hrr.ExitOptions(True, True) == hrr.ExitOptions(True, True, False)      # positional order kept
    with pytest.raises(ValueError, match='invalid_exit_options'):
        hrr.ExitOptions(clock_horizon=1)
    assert hrr.ExitOptions(True, True).record() == dict(trailing_stop=True, max_hold=True)
    assert CLOCK.record() == dict(trailing_stop=False, max_hold=False, clock_horizon=True)


def test_default_bundles_are_unchanged_without_the_option():
    default = hrr.run_replay(PACK)
    explicit = hrr.run_replay(PACK, exit_options=hrr.ExitOptions(clock_horizon=False))
    assert explicit['bundle_sha256'] == default['bundle_sha256'] and 'exit_options' not in default
    on = hrr.run_replay(PACK, exit_options=CLOCK)
    assert on['exit_options'] == CLOCK.record()


def test_clock_sells_a_silent_position_at_the_horizon(monkeypatch):
    _force(monkeypatch)
    off = _master(None)
    assert off['outcome'] == 'open_at_end'                         # event-driven: the curve fell silent
    on = _master(CLOCK)
    assert on['outcome'] == 'closed' and on['exit_trigger']['reason'] == 'exit_horizon_clock'
    assert on['exit_conditions'] == dict(tp_pct=10.0, sl_pct=8.0)  # hold and trailing never applied (D4)
    latency = hrr.clock_exit_latency_s(DECLARED.latency_slots)
    landing = on['entry_block_time'] + 30 + latency
    assert on['exit_block_time'] == landing and on['exit_signature'] is None
    events = _events()
    last = events[on['exit_index']]
    assert last.block_time <= landing                              # every event up to the landing second
    assert on['exit_index'] == len(events) - 1 or events[on['exit_index'] + 1].block_time > landing
    assert on['exit_slot'] == (last.slot + hrr.slots_for_ms((landing + 1 - last.block_time) * 1000)
                               + DECLARED.latency_slots)
    assert on['received'] == off['received']                       # same exact quote, now a closed cycle


def test_latency_rounds_up_and_matches_the_v2_harness():
    from bot.master_v2 import harness as h
    for slots, seconds in ((1, 1), (2, 1), (4, 1), (5, 2), (10, 3)):
        assert hrr.clock_exit_latency_s(slots) == seconds == h.clock_latency_s(hrr.ReplayParams(latency_slots=slots))


def test_event_horizon_trigger_is_off_only_with_the_clock():
    def walk(options, last_time):
        arm = hrr.ResearchArm('master', None, hrr.ReplayParams(exit_horizon_ms=30_000), exit_options=options)
        arm.exit_plan = dict(tp_pct=10.0, sl_pct=8.0)
        history = [type('E', (), dict(block_time=100))(), type('E', (), dict(block_time=last_time))()]
        arm.exit(history, Position(0, 1, 100, 1_000, 5), 1_000)
        return arm.exit_trigger
    assert walk(None, 130)['reason'] == 'exit_horizon'
    assert walk(CLOCK, 130) is None and walk(CLOCK, 10_000) is None
    position = Position(0, 1, 100, 1_000, 5)
    assert hrr.ResearchArm('master', None, DECLARED, exit_options=CLOCK).exit_deadline(position) == 130
    assert hrr.ResearchArm('master', None, DECLARED).exit_deadline(position) is None
    odd = hrr.ResearchArm('master', None, hrr.ReplayParams(exit_horizon_ms=30_001), exit_options=CLOCK)
    assert odd.exit_deadline(position) == 131                      # whole seconds, rounded up


@pytest.mark.parametrize('offset, outcome', ((0, 'migrated_unpriced'), (1, 'closed')))
def test_timed_sale_at_the_migration_boundary(monkeypatch, offset, outcome):
    _force(monkeypatch)
    landing_slot = _master(CLOCK)['exit_slot']
    _migrating(monkeypatch, landing_slot + offset)
    trade = _master(CLOCK)
    assert trade['outcome'] == outcome
    if outcome == 'migrated_unpriced':
        assert trade['pnl_lamports'] is None and 'exit_after_migration' in trade['notes']


def test_migration_between_the_deadline_and_the_landing_is_unpriced(monkeypatch):
    _force(monkeypatch)
    events = _events()
    _migrating(monkeypatch, events[-1].slot + 1)        # after every kept event, before the timed sale lands
    trade = _master(CLOCK)
    assert trade['outcome'] == 'migrated_unpriced' and 'clock_exit' in trade['notes']


def test_cli_flag(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location('hrr_cli', ROOT / 'tools' / 'historical_research_replay.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / 'b.json'
    cli.main(['--fixtures', str(PACK), '--clock-horizon', '--out', str(out)])
    capsys.readouterr()
    assert json.loads(out.read_text('utf-8'))['exit_options'] == CLOCK.record()
