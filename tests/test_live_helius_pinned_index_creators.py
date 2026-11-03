"""No-network independent signed creation reconciliation for public P3 index."""
import pytest
from bot.live import helius_pinned_index_creators as m
from bot.live.readonly_plan import MAINNET_GENESIS

class Rpc:
    def __init__(self,raw=None,genesis=MAINNET_GENESIS):
        self.calls=[];self.raw=raw;self.genesis=genesis
    def __call__(self,method,args):
        self.calls.append((method,args))
        if method=="getGenesisHash":return self.genesis
        assert method=="getTransaction"
        assert args[1]==dict(encoding="json",commitment="finalized",
                              maxSupportedTransactionVersion=1)
        assert args[0] in {x["signature"] for x in m.RECORDS}
        return self.raw


def test_missing_rpc_receipts_are_never_profitable_or_verified():
    rpc=Rpc()
    r=m.inspect_pinned_index_signatures(rpc)
    assert len(rpc.calls)==3
    assert r["exact_outer_signed_creators_verified"]==0
    assert r["fully_receipt_classified"] is False
    assert r["qualified_economic_cycles"]==0
    assert r["master_net_pnl_lamports"] is None
    assert r["financial_order_submitted"] is False


def test_correct_outer_signatures_are_recorded_but_not_asof_entry(monkeypatch):
    def proof(raw,sig,slot,rpc,*,commitment):
        assert commitment=="finalized"
        row=next(x for x in m.RECORDS if x["signature"]==sig)
        assert row["slot"]==slot
        return dict(message_sha256="a"*64,launches=[dict(
            mint=row["mint"],pool=row["pool"],creator=row["creator"])])
    monkeypatch.setattr(m,"signed_receipt_proof",proof)
    r=m.inspect_pinned_index_signatures(Rpc(raw={}))
    assert r["exact_outer_signed_creators_verified"]==2
    assert r["asof_market_entry_proven"] is False
    assert r["source_quote_time_and_slot_missing"] is True
    assert r["master_vs_reference_edge_lamports"] is None
    assert r["financial_order_submitted"] is False


def test_provider_identity_disagreement_cannot_be_qualified(monkeypatch):
    monkeypatch.setattr(m,"signed_receipt_proof",
        lambda *args,**kwargs:dict(message_sha256="a"*64,
            launches=[dict(mint="different",pool="different",creator="other")]))
    r=m.inspect_pinned_index_signatures(Rpc(raw={}))
    assert r["exact_outer_signed_creators_verified"]==0
    assert all(x["status"]=="INDEX_AND_SIGNED_CREATION_MISMATCH" for x in r["records"])


def test_inner_or_unverified_creations_do_not_pass(monkeypatch):
    monkeypatch.setattr(m,"signed_receipt_proof",
        lambda *args,**kwargs:dict(message_sha256="a"*64,launches=[]))
    r=m.inspect_pinned_index_signatures(Rpc(raw={}))
    assert all(x["status"]=="SIGNED_OUTER_CREATION_ABSENT" for x in r["records"])
    assert r["exact_outer_signed_creators_verified"]==0


def test_bad_chain_refused_before_receipts():
    rpc=Rpc(genesis="wrong")
    with pytest.raises(ValueError,match="mainnet"):
        m.inspect_pinned_index_signatures(rpc)
    assert len(rpc.calls)==1


def test_cryptographic_refusal_is_not_fake_loss_or_win(monkeypatch):
    def invalid(*args,**kwargs):raise ValueError("invalid exact signature")
    monkeypatch.setattr(m,"signed_receipt_proof",invalid)
    r=m.inspect_pinned_index_signatures(Rpc(raw={}))
    assert r["fully_receipt_classified"] is False
    assert r["exact_outer_signed_creators_verified"]==0
    assert all(x["status"]=="RECEIPT_OR_CRYPTO_REFUSED" for x in r["records"])
