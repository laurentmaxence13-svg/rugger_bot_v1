"""Offline cross-vendor Solana bytecode comparison. No network."""
from copy import deepcopy

import pytest

from bot.p3.certification import PROGRAM
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.public_program_observer import (
    PUBLIC_MAINNET_RPC, SECONDARY_RPC,
    observe_two_independent_rpc_programs)
from test_live_public_program_observer import ProgramFixture


@pytest.mark.parametrize("damage", [None, "changed_elf", "wrong_endpoint",
                                     "stale_bank", "wrong_genesis"])
def test_public_vendor_comparison_fails_closed(damage):
    primary = ProgramFixture()
    other = ProgramFixture()
    primary.endpoint = PUBLIC_MAINNET_RPC
    other.endpoint = SECONDARY_RPC
    if damage == "changed_elf":
        # Keep structurally valid ELF, change its payload and public SHA.
        import base64
        addr, program, pd, digest = other.rows[CPMM_PROGRAM]
        pd = deepcopy(pd)
        raw = bytearray(base64.b64decode(pd["data"][0]))
        raw[60] ^= 1
        pd["data"][0] = base64.b64encode(raw).decode()
        pd["space"] = len(raw)
        other.rows[CPMM_PROGRAM] = (addr, program, pd, digest)
    elif damage == "wrong_endpoint":
        other.endpoint = PUBLIC_MAINNET_RPC
    elif damage == "stale_bank":
        other.damage = "stale_bank"
    elif damage == "wrong_genesis":
        other.damage = "genesis"
    if damage is None:
        report = observe_two_independent_rpc_programs(primary, other)
        assert report["provider_code_hash_agreement"] is True
        assert report["requests_used"] == 10
        assert set(report["programs"]) == {PROGRAM, CPMM_PROGRAM}
        assert report["operator_pins_independently_approved"] is False
        assert report["rpc_consensus_cryptographically_verified"] is False
        assert report["live_ready_to_arm"] is False
        assert report["economic_edge_validated"] is False
        assert all(x[0] != "sendTransaction" for x in primary.calls + other.calls)
    else:
        with pytest.raises(ValueError):
            observe_two_independent_rpc_programs(primary, other)
    assert len(primary.calls) + len(other.calls) <= 10
