"""closedacct: closed-account net return, against the frozen open mode (latelab.net_return)."""
import pytest

from closedacct import model as C
from latelab import study as LL

COST = 100_210_000                   # 0.1 SOL + 2 x (5 000 + 100 000)


def _o(value, migrated=False, tokens=1_000):
    return dict(migrated=migrated, value=None if migrated else value, reason=None if migrated else 'clock',
                cost=COST, tokens=None if migrated else tokens)


def test_open_mode_is_the_frozen_latelab_return():
    for value in (90_000_000, 100_000_000, 110_000_000):
        assert C.net_return_open(_o(value)) == LL.net_return(_o(value))
    assert C.net_return_open(_o(None, migrated=True)) == LL.net_return(_o(None, migrated=True)) == -1.0


def test_closed_mode_recovers_the_rent_and_pays_one_cleanup_fee():
    o = _o(COST)                                                  # break even before rent
    assert C.net_return_open(o) == pytest.approx(-2_039_280 / (COST + 2_039_280))
    assert C.net_return_closed(o) == pytest.approx(-105_000 / COST)
    assert C.net_return_closed(o, cleanup_fee=C.CLEANUP_FEE_LIVE_DEFAULT_LAMPORTS) == pytest.approx(-5_000 / COST)
    assert C.rent_effect(o) == pytest.approx(C.net_return_closed(o) - C.net_return_open(o))
    assert 0.0188 < C.rent_effect(o) < 0.0190                     # +1.89 points: rent 2.00 % less the 0.105 % fee
    assert C.CLEANUP_FEE_LAMPORTS == 5_000 + 100_000 and C.MAX_CLEANUP_ATTEMPTS == 3


def test_failed_attempts_and_the_account_left_open():
    o = _o(COST)
    assert C.net_return_closed(o, failed_attempts=1) == pytest.approx(-2 * 105_000 / COST)
    left_open = C.net_return_closed(o, failed_attempts=3)
    assert left_open == pytest.approx((-2_039_280 - 3 * 105_000) / (COST + 2_039_280))
    assert left_open < C.net_return_open(o)                       # worse than never trying
    with pytest.raises(C.ClosedAccountError, match='failed_attempts_out_of_range'):
        C.net_return_closed(o, failed_attempts=4)


def test_migrated_and_incomplete_sales():
    assert C.net_return_closed(_o(None, migrated=True)) == -1.0  # no sale, no cleanup
    with pytest.raises(C.ClosedAccountError, match='closed_mode_requires_a_total_sale'):
        C.net_return_closed(dict(migrated=False, value=None, cost=COST, tokens=1))
    with pytest.raises(C.ClosedAccountError, match='closed_mode_requires_a_total_sale'):
        C.net_return_closed(dict(migrated=False, value=COST, cost=COST, tokens=None))


def test_on_a_real_replay_of_the_frozen_pack():
    """One real run_rule outcome (frozen pack, statelab clock exit): closed = open + the rent effect, exactly."""
    from pathlib import Path

    import bot
    from bot.market.collector import summarize
    from bot.p4 import historical_research_replay as hrr
    from statelab.exits import run_rule
    from statelab.points import whole
    from v3lab import plan
    from v4sim.io import actors_from_archive
    from w1aux.lazy import clear_cache, load_fixtures_lazy
    pools = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    try:
        archive = next(a for e, a in load_fixtures_lazy(pools)[2] if e['pool'].startswith('C7F9'))
        summary, timeline = summarize(archive)
        timeline, _m = hrr.usable_timeline(archive, summary, timeline)
        events = timeline.events
        k = [i for i in range(len(events)) if whole(events, i)][3]
        actors, _s = actors_from_archive(archive, events)
        model = hrr.ReplayParams(latency_slots=plan.REPLAY['latency_slots']).execution_model()
        outcome = run_rule(timeline, k, actors, model, dict(id='CLOCK30', clock_s=30))
    finally:
        clear_cache()
    assert outcome is not None and not outcome['migrated'] and outcome['tokens'] > 0
    closed, opened = C.net_return_closed(outcome), C.net_return_open(outcome)
    assert closed == pytest.approx((outcome['value'] - outcome['cost'] - 105_000) / outcome['cost'])
    assert closed > opened
