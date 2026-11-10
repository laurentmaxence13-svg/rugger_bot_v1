"""One complete offline BUY -> hold -> SELL cycle on the fixture bank."""
import asyncio

from .fixtures import fixture_config, fixture_rpc, launchlab_fixture
from .harness import DryRunHarness

OTHERS = (('BUY', 300_000_000), ('SELL', 1_000_000_000_000), ('BUY', 50_000_000))


class StepClock:
    """Deterministic logical milliseconds: the same run writes the same journal."""

    def __init__(self, start=1_000_000):
        self.now = start

    def __call__(self):
        self.now += 1
        return self.now


def run_fixture_cycle(journal_path, *, buy_lamports=100_000_000, others=OTHERS,
                      clock_ms=None, rpc=None, **config):
    """Return ``(harness, buy_fill, sell_fill)``; every step is in the journal."""
    bank, request = launchlab_fixture()
    harness = DryRunHarness(journal_path, bank, fixture_config(request, **config),
                            rpc=rpc or fixture_rpc(), clock_ms=clock_ms or StepClock())

    async def cycle():
        bought = await harness.buy('dry-run-buy-1', buy_lamports)
        harness.hold(others)
        return bought, await harness.sell('dry-run-sell-1')

    return (harness, *asyncio.run(cycle()))
