"""Shared factory: one journal file, re-openable on the same initial fixture bank."""
import sys

sys.dont_write_bytecode = True  # the frozen source tree stays untouched even without -B

import pytest

from dryrun.cycle import StepClock
from dryrun.fixtures import fixture_config, fixture_rpc, launchlab_fixture
from dryrun.harness import DryRunHarness


@pytest.fixture
def open_harness(tmp_path):
    """Each call opens (or re-opens, as after a restart) ``tmp_path/dry-run.jsonl``."""
    def factory(*, rpc=None, **config):
        bank, request = launchlab_fixture()
        return DryRunHarness(factory.path, bank, fixture_config(request, **config),
                             rpc=rpc or fixture_rpc(), clock_ms=factory.clock)
    factory.path = tmp_path / 'dry-run.jsonl'
    factory.clock = StepClock()
    return factory
