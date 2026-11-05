"""The curve fee rate is a per-pool input read at decision time, never a global 1.25 %."""
import gzip
import json
from pathlib import Path

from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT, extract_trade_events
from bot.market.pool_timeline import build_timeline
from bot.market.replay import ExecutionModel, Strategy, replay, _event_rate
from test_launchlab_market_events import FRESH, POOL, _event_from_fill

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
ZERO = dict(latency_slots=0, priority_fee_lamports=0, base_fee_lamports=0)


class BuyThenHold(Strategy):
    def __init__(self, spend):
        self.spend = spend

    def entry(self, history):
        return self.spend if len(history) == 1 else 0

    def exit(self, history, position, mark):
        return False


def _pool(rate, n=4):
    state, events = FRESH, []
    for i in range(n):
        fill = buy_exact_in(state, 2_000_000_000, rate)
        events.append(_event_from_fill(fill, slot=100 + i, sig=f'r{rate}-{i:03d}'))
        state = fill.after
    return build_timeline(POOL, events), events


def test_default_model_uses_the_pool_rate_observed_at_decision():
    timeline, events = _pool(18_000)
    assert _event_rate(events[0]) == 18_000
    result = replay(timeline, BuyThenHold(10**9), ExecutionModel(**ZERO), quote_mint=WSOL_MINT)
    assert (result.fee_rate_ppm, result.fee_rate_source) == (18_000, 'pool_event_at_decision')
    expected = buy_exact_in(events[0].state_after(), 10**9, 18_000).amount_out
    assert result.tokens == expected
    # The old global default would have under-charged this pool.
    assert result.tokens < buy_exact_in(events[0].state_after(), 10**9, 12_500).amount_out


def test_explicit_model_rate_is_respected_and_labelled():
    timeline, events = _pool(18_000)
    result = replay(timeline, BuyThenHold(10**9), ExecutionModel(fee_rate_ppm=10_000, **ZERO),
                    quote_mint=WSOL_MINT)
    assert (result.fee_rate_ppm, result.fee_rate_source) == (10_000, 'model')
    assert result.tokens == buy_exact_in(events[0].state_after(), 10**9, 10_000).amount_out


def test_exit_mark_uses_the_same_pool_rate():
    timeline, events = _pool(18_000)
    result = replay(timeline, BuyThenHold(10**9), ExecutionModel(**ZERO), quote_mint=WSOL_MINT)
    assert result.outcome == 'open_at_end'
    # Rebuild the shifted curve: our buy, then the later real trades replayed on it.
    state = buy_exact_in(events[0].state_after(), 10**9, 18_000).after
    for event in events[1:]:
        state = buy_exact_in(state, event.amount_in, 18_000).after
    assert result.received == sell_exact_in(state, result.tokens, 18_000).amount_out


def test_committed_fixture_pools_have_three_distinct_rates():
    rates = {}
    for path in sorted(PACK.glob('*.json.gz')):
        data = json.loads(gzip.decompress(path.read_bytes()))
        observed = {_event_rate(e) for tx in data['transactions'].values() for e in extract_trade_events(tx)}
        assert len(observed) == 1, data['pool']
        rates[data['pool']] = observed.pop()
    assert sorted(rates.values()) == [10_000, 12_500, 18_000]
