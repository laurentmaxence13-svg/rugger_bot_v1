"""Offline fake RPC for real-world migration discovery: no network or keys."""
from copy import deepcopy

import pytest

from bot.live.public_migration_discovery import (
    discover_one_qualified_migration, candidate_role_mapping,
    PUBLIC_MIGRATION_PAYER, MAX_SIGNATURES)
from bot.live.readonly_plan import MAINNET_GENESIS
from test_live_migration_evidence import migration, MINT, OLD, NEW
from test_live_signed_migration_reference import signed_rpc_migration


class FakeHistory:
    def __init__(self, raw, sig, *, problem=None):
        self.raw, self.signature, self.problem = deepcopy(raw), sig, problem
        self.count = 0
        self.calls = []

    def __call__(self, method, params):
        self.count += 1
        self.calls.append((method, deepcopy(params)))
        if method == "getGenesisHash":
            return "wrong_genesis" if self.problem == "genesis" else MAINNET_GENESIS
        if method == "getSignaturesForAddress":
            assert params[0] == PUBLIC_MIGRATION_PAYER
            assert params[1]["limit"] == MAX_SIGNATURES
            return [dict(signature=self.signature,slot=100,err=None)]
        assert method == "getTransaction"
        assert params[0] == self.signature
        if self.problem == "missing":
            return None
        raw = deepcopy(self.raw)
        if self.problem == "slot":
            raw["slot"] = 101
        if self.problem == "invalid_signature":
            raw["transaction"]["message"]["recentBlockhash"] = MINT
        return raw


def test_finds_and_verifies_exact_source_and_destination_on_signed_fixture():
    signed, sig = signed_rpc_migration(migration())
    assert candidate_role_mapping(signed) == dict(
        mint=MINT, original_pool=OLD, cpmm_pool=NEW)
    rpc = FakeHistory(signed, sig)
    result = discover_one_qualified_migration(rpc)
    assert result["status"] == "FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED"
    assert result["mint"] == MINT
    assert result["original_pool"] == OLD
    assert result["cpmm_pool"] == NEW
    assert result["signed_message_Ed25519_verified"] is True
    assert result["independent_RPC_consensus_verified"] is False
    assert result["actual_sell_simulated"] is False
    assert result["live_ready_to_arm"] is False
    assert rpc.count == 3
    assert [c[0] for c in rpc.calls] == [
        "getGenesisHash","getSignaturesForAddress","getTransaction"]


@pytest.mark.parametrize("fault",["genesis","missing","slot","invalid_signature"])
def test_rejects_fabricated_or_unavailable_historical_migration(fault):
    signed, sig = signed_rpc_migration(migration())
    rpc = FakeHistory(signed,sig,problem=fault)
    if fault == "genesis":
        with pytest.raises(ValueError,match="wrong_network"):
            discover_one_qualified_migration(rpc)
    elif fault == "missing":
        result = discover_one_qualified_migration(rpc)
        assert result["status"]=="NO_QUALIFIED_MIGRATION_IN_FIXED_BOUNDED_PAGE"
    else:
        with pytest.raises(ValueError):
            discover_one_qualified_migration(rpc)
    assert rpc.count <= 3
    assert all(m in ("getGenesisHash","getSignaturesForAddress",
                     "getTransaction") for m,_ in rpc.calls)
