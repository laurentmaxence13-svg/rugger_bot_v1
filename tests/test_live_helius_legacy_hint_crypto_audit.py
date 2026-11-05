"""Synthetic cryptographic hint audit controls: no network, no promotion."""
from bot.live import helius_legacy_hint_crypto_audit as m
from bot.live.readonly_plan import MAINNET_GENESIS
import pytest


class Rpc:
    def __init__(self,receipts=False,genesis=MAINNET_GENESIS):
        self.calls=[];self.receipts=receipts;self.genesis=genesis
    def __call__(self,method,params):
        self.calls.append((method,params))
        if method=="getGenesisHash":return self.genesis
        assert method=="getTransaction"
        assert params[0] in dict(m.LEGACY_ONLY)
        assert params[1]==dict(encoding="json",commitment="finalized",
                               maxSupportedTransactionVersion=1)
        return {"fake":True} if self.receipts else None


def test_unavailable_finality_never_becomes_negative_or_positive_master_profit():
    rpc=Rpc()
    r=m.inspect_legacy_hints(rpc)
    assert len(rpc.calls)==4
    assert len(r["rows"])==3
    assert r["fully_verified"] is False
    assert r["verdict"]=="INCONCLUSIVE_FINALIZED_EVIDENCE"
    assert r["verified_signed_creations"]==0
    assert r["master_net_pnl_lamports"] is None
    assert r["economic_cycles_qualified"]==0
    assert r["financial_order_submitted"] is False


def test_false_negative_is_explicitly_flagged_and_never_traded(monkeypatch):
    def proof(raw,sig,slot,rpc,*,commitment):
        assert commitment=="finalized"
        assert (sig,slot) in m.LEGACY_ONLY
        return dict(message_sha256="a"*64,
            launches=[{"creator":"first-creator"}] if sig==m.LEGACY_ONLY[1][0] else [])
    monkeypatch.setattr(m,"signed_receipt_proof",proof)
    r=m.inspect_legacy_hints(Rpc(receipts=True))
    assert r["fully_verified"]
    assert r["verified_signed_creations"]==1
    assert r["unique_creator_claims"]==1
    assert r["verdict"]=="SCOPED_HINT_FILTER_REQUIRES_REVIEW"
    assert r["financial_order_submitted"] is False
    assert r["live_ready_to_arm"] is False


def test_all_noncreations_verified_are_not_profit(monkeypatch):
    monkeypatch.setattr(m,"signed_receipt_proof",
        lambda raw,sig,slot,rpc,*,commitment:
            dict(message_sha256="a"*64,launches=[]))
    r=m.inspect_legacy_hints(Rpc(receipts=True))
    assert r["fully_verified"]
    assert r["verified_signed_creations"]==0
    assert r["verdict"]=="NO_SIGNED_CREATION_AMONG_LEGACY_HINTS"


def test_wrong_genesis_rejects_before_receipts():
    rpc=Rpc(genesis="other-chain")
    with pytest.raises(ValueError,match="mainnet_readonly"):
        m.inspect_legacy_hints(rpc)
    assert len(rpc.calls)==1


def test_receipt_refusal_is_not_signed(monkeypatch):
    def nope(*args,**kwargs):
        raise ValueError("malformed")
    monkeypatch.setattr(m,"signed_receipt_proof",nope)
    r=m.inspect_legacy_hints(Rpc(receipts=True))
    assert r["fully_verified"] is False
    assert all(x["status"]=="RECEIPT_OR_CRYPTO_REFUSED" for x in r["rows"])
    assert r["verdict"]=="INCONCLUSIVE_FINALIZED_EVIDENCE"
    assert r["financial_order_submitted"] is False
