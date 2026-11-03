"""Bounded public signature checks, offline fixtures only; no wallet or HTTP."""
from copy import deepcopy
import pytest

from bot.live.pinned_migration_probe import probe_pinned_migrations
from bot.live.readonly_plan import MAINNET_GENESIS
from test_live_migration_evidence import migration
from test_live_signed_migration_reference import signed_rpc_migration

class FakeRpc:
    def __init__(self, tx=None, sig=None, *, wrong_genesis=False):
        self.tx, self.sig, self.wrong_genesis=tx,sig,wrong_genesis
        self.count=0
        self.methods=[]
    def __call__(self, method, params):
        self.count+=1
        self.methods.append(method)
        if method=="getGenesisHash":
            assert params==[]
            return "wrong" if self.wrong_genesis else MAINNET_GENESIS
        assert method=="getTransaction"
        assert params[1]==dict(encoding="json",commitment="finalized",
                              maxSupportedTransactionVersion=0)
        return deepcopy(self.tx) if params[0]==self.sig else None

def test_verified_real_shape_requires_exact_signed_fixture():
    tx, sig=signed_rpc_migration(migration())
    rpc=FakeRpc(tx,sig)
    report=probe_pinned_migrations(rpc,candidates=(sig,))
    assert report["matches"]==1
    assert report["results"][0]["status"]=="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED"
    assert report["source_RPC_claim_finalized"] is True
    assert report["independent_RPC_consensus_verified"] is False
    assert report["financial_order_submitted"] is False
    assert report["live_ready_to_arm"] is False
    assert rpc.methods==["getGenesisHash","getTransaction"]

def test_no_transaction_is_not_promoted_to_migration():
    tx,sig=signed_rpc_migration(migration())
    report=probe_pinned_migrations(FakeRpc(),candidates=(sig,))
    assert report["status"]=="NO_CRYPTOGRAPHIC_MATCH"
    assert report["results"][0]["status"]=="HISTORICAL_TRANSACTION_NOT_RETURNED"

def test_tampered_message_refused_and_subsequent_candidates_still_checked():
    tx,sig=signed_rpc_migration(migration())
    tx["transaction"]["message"]["recentBlockhash"]=tx["transaction"]["message"]["accountKeys"][0]
    probe=probe_pinned_migrations(FakeRpc(tx,sig),candidates=(sig,))
    assert probe["matches"]==0

def test_genesis_mismatch_fails_before_transaction():
    tx,sig=signed_rpc_migration(migration())
    rpc=FakeRpc(tx,sig,wrong_genesis=True)
    with pytest.raises(ValueError,match="genesis"):
        probe_pinned_migrations(rpc,candidates=(sig,))
    assert rpc.methods==["getGenesisHash"]

def test_candidate_set_rejects_duplicates_and_unbounded_pages():
    tx,sig=signed_rpc_migration(migration())
    rpc=FakeRpc(tx,sig)
    for signatures in ((sig,sig),tuple([sig]*5),()):
        with pytest.raises(ValueError):
            probe_pinned_migrations(rpc,candidates=signatures)
    assert rpc.count==0
