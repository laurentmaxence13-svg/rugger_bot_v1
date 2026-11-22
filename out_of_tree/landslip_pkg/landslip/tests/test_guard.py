"""landslip.guard: the slippage guard fixed by R02 (buy 2 % primary / 5 % sensitivity, no sale guard in the primary)."""
import pytest

from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
from landslip import guard as G
from paperstream.tests.test_engine import _timelines

STAKE, RATE = 100_000_000, 10_000
SOL = 10 ** 9


@pytest.fixture(scope='module')
def state():
    busy = max(_timelines(), key=lambda t: len(t.events))
    return busy.events[20].state_after()


def _after_buy(state, lamports):
    return buy_exact_in(state, lamports, RATE).after


def _after_sell(state, tokens):
    return sell_exact_in(state, tokens, RATE).after


def test_the_declared_thresholds():
    assert (G.BUY_GUARD_PPM, G.BUY_GUARD_SENSITIVITY_PPM, G.SELL_GUARD_SENSITIVITY_PPM) == (20_000, 50_000, 50_000)
    assert G.SELL_MAX_FAILURES == 3 and G.FAILED_TX_FEE_LAMPORTS == 105_000
    assert G.minimum(1_000_000, 20_000) == 980_000 and G.minimum(999, 20_000) == 979          # floored
    for bad in (10_000, 30_000, 0):
        with pytest.raises(G.GuardError, match='buy_guard_not_a_declared_threshold'):
            G.buy(None, [None], STAKE, RATE, bad)
        with pytest.raises(G.GuardError, match='sell_guard_not_a_declared_threshold'):
            G.sell(None, [[None]], 1, RATE, bad)


def test_buy_inside_the_band_fills_at_the_worst_landing_state(state):
    small = _after_buy(state, SOL // 1000)                    # a tiny real buy moves the price a little
    status, fill = G.buy(state, [state, small], STAKE, RATE)
    assert status == 'filled' and fill.amount_out == buy_exact_in(small, STAKE, RATE).amount_out
    assert fill.amount_out < buy_exact_in(state, STAKE, RATE).amount_out


def test_buy_beyond_the_band_fails_without_entry_and_the_sensitivity_is_wider(state):
    expected = buy_exact_in(state, STAKE, RATE).amount_out
    moved = None
    for lamports in range(SOL // 10, 50 * SOL, SOL // 10):       # the smallest real buy that moves the fill by 2-5 %
        got = buy_exact_in(_after_buy(state, lamports), STAKE, RATE).amount_out
        if G.minimum(expected, 50_000) <= got < G.minimum(expected, 20_000):
            moved = _after_buy(state, lamports)
            break
    assert moved is not None
    assert G.buy(state, [moved], STAKE, RATE) == ('failed', None)
    assert G.buy(state, [state, moved], STAKE, RATE) == ('failed', None)              # the worst landing state counts
    assert G.buy(state, [moved], STAKE, RATE, G.BUY_GUARD_SENSITIVITY_PPM)[0] == 'filled'
    assert G.buy(state, [moved], STAKE, RATE, None)[0] == 'filled'                    # guard off = the frozen engine
    with pytest.raises(G.GuardError, match='no_landing_state'):
        G.buy(state, [], STAKE, RATE)


def test_sale_has_no_guard_in_the_primary_and_retries_in_the_sensitivity(state):
    tokens = buy_exact_in(state, STAKE, RATE).amount_out
    expected = sell_exact_in(state, tokens, RATE).amount_out
    dumped = None
    for k in range(10, 2_000, 10):                             # a real sale big enough to cut our value by > 5 %
        candidate = _after_sell(state, tokens * k)
        if sell_exact_in(candidate, tokens, RATE).amount_out < G.minimum(expected, 50_000):
            dumped = candidate
            break
    assert dumped is not None
    status, sale, failures = G.sell(state, [[dumped]], tokens, RATE)
    assert status == 'sold' and failures == 0 and sale.amount_out == sell_exact_in(dumped, tokens, RATE).amount_out
    # sensitivity: three failed guarded attempts, then the unguarded fourth one
    status, sale, failures = G.sell(state, [[dumped]] * 4, tokens, RATE, G.SELL_GUARD_SENSITIVITY_PPM)
    assert failures == 3 and sale.amount_out == sell_exact_in(dumped, tokens, RATE).amount_out
    # recovered at the second retry: sold there, 2 failures charged
    status, sale, failures = G.sell(state, [[dumped], [dumped], [state], [dumped]], tokens, RATE,
                                    G.SELL_GUARD_SENSITIVITY_PPM)
    assert failures == 2 and sale.amount_out == sell_exact_in(state, tokens, RATE).amount_out
    # worst state of an attempt (H-1)
    assert G.sell(state, [[state, dumped]], tokens, RATE)[1].amount_out == sell_exact_in(dumped, tokens, RATE).amount_out
    with pytest.raises(G.GuardError, match='need_an_attempt_after_the_last_failure'):
        G.sell(state, [[dumped]] * 2, tokens, RATE, G.SELL_GUARD_SENSITIVITY_PPM)
    with pytest.raises(G.GuardError, match='no_landing_state'):
        G.sell(state, [[]], tokens, RATE)
