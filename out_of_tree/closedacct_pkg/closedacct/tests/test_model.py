"""closedacct 0.2: one denominator (the stake) in both modes; failed attempts frozen at 0, sensitivity 1."""
import pytest

from closedacct import model as C

STAKE, TX, RENT, FEE = 100_000_000, 210_000, 2_039_280, 105_000
COST = STAKE + TX


def _o(value, migrated=False, tokens=1_000):
    return dict(migrated=migrated, value=None if migrated else value, reason=None if migrated else 'clock',
                cost=COST, tokens=None if migrated else tokens)


def test_one_denominator_the_stake_in_both_modes():
    o = _o(103_000_000)
    assert C.net_return_open(o) == pytest.approx((103_000_000 - COST - RENT) / STAKE)
    assert C.net_return_closed(o) == pytest.approx((103_000_000 - COST - FEE) / STAKE)
    assert C.rent_effect(o) == pytest.approx((RENT - FEE) / STAKE)              # exact identity of the costs
    assert C.rent_effect(o) == pytest.approx(0.0193428)                          # +1.93 points on 0.1 SOL
    assert C.net_return_closed(o, cleanup_fee=C.CLEANUP_FEE_LIVE_DEFAULT_LAMPORTS) == pytest.approx((103_000_000 - COST - 5_000) / STAKE)
    assert C.CLEANUP_FEE_LAMPORTS == 5_000 + 100_000 and C.STAKE_LAMPORTS == STAKE and C.SPL_RENT_LAMPORTS == RENT


def test_frozen_failed_attempts_and_the_sensitivity():
    o = _o(COST)
    assert C.FROZEN_FAILED_ATTEMPTS == 0 and C.SENSITIVITY_FAILED_ATTEMPTS == 1 and C.MAX_CLEANUP_ATTEMPTS == 3
    assert C.net_return_closed(o) == pytest.approx(-FEE / STAKE)
    assert C.net_return_closed(o, failed_attempts=C.SENSITIVITY_FAILED_ATTEMPTS) == pytest.approx(-2 * FEE / STAKE)
    left_open = C.net_return_closed(o, failed_attempts=3)
    assert left_open == pytest.approx((-RENT - 3 * FEE) / STAKE) and left_open < C.net_return_open(o)
    with pytest.raises(C.ClosedAccountError, match='failed_attempts_out_of_range'):
        C.net_return_closed(o, failed_attempts=4)


def test_migrated_and_incomplete_sales():
    m = _o(None, migrated=True)
    assert C.net_return_open(m) == C.net_return_closed(m) == pytest.approx((-COST - RENT) / STAKE)   # no cleanup
    with pytest.raises(C.ClosedAccountError, match='closed_mode_requires_a_total_sale'):
        C.net_return_closed(dict(migrated=False, value=None, cost=COST, tokens=1))
    with pytest.raises(C.ClosedAccountError, match='closed_mode_requires_a_total_sale'):
        C.net_return_open(dict(migrated=False, value=COST, cost=COST, tokens=None))


def test_on_a_real_replay_of_the_frozen_pack():
    """One real run_rule outcome (frozen pack): both modes on the stake, their gap = (rent - fee) / stake exactly."""
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
    assert outcome['cost'] == COST
    assert C.net_return_closed(outcome) == pytest.approx((outcome['value'] - COST - FEE) / STAKE)
    assert C.net_return_closed(outcome) - C.net_return_open(outcome) == pytest.approx((RENT - FEE) / STAKE)
