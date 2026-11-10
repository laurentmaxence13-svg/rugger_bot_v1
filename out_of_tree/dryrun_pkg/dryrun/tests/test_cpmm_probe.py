"""CPMM leg: the frozen exit builder runs offline; the shadow position does not move."""
import asyncio

import pytest

from bot.live.cpmm_swap import CPMM_PROGRAM

from dryrun import Refusal
from dryrun.cycle import StepClock
from dryrun.fixtures import cpmm_fixture_request

run = asyncio.run


def test_cpmm_exit_is_built_and_preflighted_without_touching_shadow_inventory(open_harness):
    open_harness.clock = StepClock(start=1100)  # the frozen CPMM bank was observed at 1000 ms
    harness = open_harness()
    bought = run(harness.buy('decision-1', 100_000_000))
    request = cpmm_fixture_request()  # tests/test_live_cpmm_exit.py:fixture_bank, unchanged
    probe = run(harness.cpmm_exit_probe(request))

    preflight = harness.journal.records[-2]
    assert preflight['kind'] == 'preflight'
    assert preflight['result'] == 'SIMULATION_SUCCEEDED_UNSENT'
    assert preflight['message_sha256'] == probe['message_sha256']
    assert probe['kind'] == 'cpmm_exit_probe' and probe['program_id'] == CPMM_PROGRAM
    assert probe['amount_in'] == request['amount_in'] and probe['minimum_out'] > 0
    # No receipt binds this CPMM pool (another synthetic mint) to the LaunchLab position.
    assert probe['mint'] != harness.bank.mint
    assert probe['migration_receipt_verified'] is False
    assert probe['bound_to_shadow_position'] is False
    assert probe['shadow_position_changed'] is False
    assert harness.position.quantity_atomic == bought['amount_out']
    assert harness.realized_pnl_lamports == 0
    assert harness.wallet_lamports == bought['wallet_after_lamports']
    assert harness.rpc.simulated[-1][:65] == b'\x01' + bytes(64)

    with pytest.raises(Refusal, match='duplicate_decision_id'):
        run(harness.cpmm_exit_probe(request))
    assert open_harness().position == harness.position  # replay: still the LaunchLab position
