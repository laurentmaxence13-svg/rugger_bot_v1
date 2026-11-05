"""Offline tests for public-mainnet program observation. NO network/wallet."""
import base64
from copy import deepcopy
import hashlib
import struct

import pytest

from bot.live.public_program_observer import observe_public_programs
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.program_pin import LOADER
from bot.p3.certification import PROGRAM, _decode, _encode, find_program_address
from bot.live.cpmm_swap import CPMM_PROGRAM


def _account(data, executable):
    return dict(owner=LOADER, executable=executable, lamports=123456,
                space=len(data), data=[base64.b64encode(data).decode(), "base64"])


class ProgramFixture:
    def __init__(self, damage=None):
        self.damage = damage
        self.calls = []
        self.count = 0
        self.rows = {}
        for i, program in enumerate((PROGRAM, CPMM_PROGRAM)):
            pd_id, _ = find_program_address((_decode(program),), program_id=LOADER)
            raw_program = struct.pack("<I", 2) + _decode(pd_id)
            authority = _encode(bytes([81+i])*32)
            raw_pd = (struct.pack("<IQB", 3, 90+i, 1)
                      + _decode(authority)
                      + b"\x7fELF" + bytes([3+i, 5, 7, 11])*60)
            self.rows[program] = (
                pd_id, _account(raw_program, True), _account(raw_pd, False),
                hashlib.sha256(raw_pd[45:]).hexdigest())

    def __call__(self, method, params):
        self.calls.append((method, deepcopy(params)))
        self.count += 1
        if method == "getGenesisHash":
            return PROGRAM if self.damage == "genesis" else MAINNET_GENESIS
        assert method == "getMultipleAccounts"
        keys, options = params
        assert options["commitment"] == "finalized"
        assert options["encoding"] == "base64"
        assert len(keys) in (1, 2)
        current = keys[0]
        pd_id, program, pd, _ = self.rows[current]
        first = len(keys) == 1
        if not first:
            assert keys == [current, pd_id]
        slot = 300 if first else 301
        if self.damage == "stale_bank" and not first and current == CPMM_PROGRAM:
            slot = 299
        if self.damage == "pointer_change" and not first and current == CPMM_PROGRAM:
            program = deepcopy(program)
            program["data"][0] = base64.b64encode(
                struct.pack("<I", 2) + bytes([9])*32).decode()
        if self.damage == "bad_programdata" and not first and current == CPMM_PROGRAM:
            pd = deepcopy(pd)
            raw = bytearray(base64.b64decode(pd["data"][0]))
            raw[45:49] = b"BAD!"
            pd["data"][0] = base64.b64encode(raw).decode()
        return dict(context=dict(slot=slot),
                    value=[deepcopy(program)] if first
                    else [deepcopy(program), deepcopy(pd)])


def test_observes_two_real_program_identities_without_approving_either():
    rpc = ProgramFixture()
    report = observe_public_programs(rpc)
    assert report["status"] == "OBSERVED_UNAPPROVED"
    assert report["rpc_requests"] == 5
    assert len(rpc.calls) == 5
    assert [call[0] for call in rpc.calls] == [
        "getGenesisHash", "getMultipleAccounts", "getMultipleAccounts",
        "getMultipleAccounts", "getMultipleAccounts"]
    assert set(report["programs"]) == {PROGRAM, CPMM_PROGRAM}
    for program in (PROGRAM, CPMM_PROGRAM):
        assert report["programs"][program]["elf_sha256"] == rpc.rows[program][3]
        assert report["programs"][program]["joint_slot"] == 301
    assert report["financial_order_submitted"] is False
    assert report["operator_pins_independently_approved"] is False
    assert report["independent_rpc_consensus_verified"] is False
    assert report["live_ready_to_arm"] is False
    assert report["economic_edge_validated"] is False
    assert all(method in ("getGenesisHash", "getMultipleAccounts")
               for method, _params in rpc.calls)


@pytest.mark.parametrize("damage", [
    "genesis", "stale_bank", "pointer_change", "bad_programdata",
])
def test_refuses_untrusted_program_or_stale_bank(damage):
    rpc = ProgramFixture(damage=damage)
    with pytest.raises(ValueError):
        observe_public_programs(rpc)
    assert len(rpc.calls) <= 5
    assert all(method in ("getGenesisHash", "getMultipleAccounts")
               for method, _params in rpc.calls)
