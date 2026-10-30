"""Network-free Helius cohort contract: no fake P4 profitability from detections."""
from copy import deepcopy
import pytest
from bot.live import helius_launchlab_cohort_probe as c
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.certification import _encode

SIG=_encode(bytes([1])*64)


class Fake:
    def __init__(self, page=None, raw=None, parsed=None, wrong_chain=False):
        self.page=[dict(signature=SIG,slot=1234,err=None)] if page is None else page
        self.raw=raw
        self.parsed=parsed
        self.wrong_chain=wrong_chain
        self.methods=[]
        self.count=0
    def __call__(self, method, params):
        self.count+=1;self.methods.append(method)
        if method=="getGenesisHash":
            assert params==[]
            return "wrong" if self.wrong_chain else MAINNET_GENESIS
        if method=="getSignaturesForAddress":
            assert params==[c.PROGRAM,dict(limit=20,commitment="finalized")]
            return deepcopy(self.page)
        assert method=="getTransaction"
        assert params[0]==SIG and params[1] in (c.RAW_OPTS,c.PARSED_OPTS)
        return deepcopy(self.raw if params[1]["encoding"]=="json" else self.parsed)


def tx():
    return dict(slot=1234,meta=dict(err=None),
        transaction=dict(signatures=[SIG],message=dict(accountKeys=[])))


def test_wrong_genesis_stops_before_discovery():
    rpc=Fake(wrong_chain=True)
    with pytest.raises(ValueError,match="genesis"):
        c.read_launchlab_creation_sample(rpc)
    assert rpc.methods==["getGenesisHash"]


def test_missing_historical_body_keeps_unknown_not_zero_pnl():
    rpc=Fake()
    out=c.read_launchlab_creation_sample(rpc)
    assert out["records"][0]["status"]=="TRANSACTION_NOT_AVAILABLE"
    assert out["signed_creation_candidates"]==0
    assert out["master_vs_reference_edge_validated"] is False
    assert out["actual_buy_sell_cycles"]==0
    assert out["independent_creators_economically_qualified"]==0
    assert out["financial_order_submitted"] is False
    assert rpc.methods==["getGenesisHash","getSignaturesForAddress",
                         "getTransaction","getTransaction"]


def test_inconsistent_signatures_cannot_become_candidates():
    v=tx();other=deepcopy(v)
    other["transaction"]["signatures"]=[_encode(bytes([2])*64)]
    rpc=Fake(raw=v,parsed=other)
    out=c.read_launchlab_creation_sample(rpc)
    assert out["records"][0]["status"]=="INCONSISTENT_FINALIZED_TRANSACTION"
    assert out["signed_creation_candidates"]==0


def test_signed_creation_requires_raw_cryptographic_validation(monkeypatch):
    t=tx();rpc=Fake(raw=t,parsed=t)
    def rejected(_):
        raise ValueError("bad_signature")
    monkeypatch.setattr(c,"verify_compiled_rpc_signatures",rejected)
    out=c.read_launchlab_creation_sample(rpc)
    assert out["records"][0]["status"]=="SIGNATURE_OR_CREATION_REJECTED"
    assert out["distinct_creator_claims_in_sample"]==0


def test_mocked_signed_creation_remains_historical_not_market_edge(monkeypatch):
    t=tx();rpc=Fake(raw=t,parsed=t)
    creator=_encode(bytes([6])*32)
    mint=_encode(bytes([7])*32)
    pool=_encode(bytes([8])*32)
    monkeypatch.setattr(c,"verify_compiled_rpc_signatures",
                        lambda _:dict(cryptographic_signatures_verified=True,
                                      exact_message_sha256="a"*64))
    monkeypatch.setattr(c,"normalized_compiled_transaction",
        lambda _:dict(transaction=dict(message=dict(
            accountKeys=[dict(pubkey=k) for k in (creator,mint,pool)]))))
    monkeypatch.setattr(c,"find_raydium_launches",
        lambda _: [dict(mint=mint,creator=creator,pool_state=pool)])
    out=c.read_launchlab_creation_sample(rpc)
    assert out["signed_creation_candidates"]==1
    assert out["distinct_creator_claims_in_sample"]==1
    assert out["independent_creators_economically_qualified"]==0
    assert out["data_kind"]=="historical_backfill_not_prospective_asof"
    assert out["master_vs_reference_edge_validated"] is False


def test_duplicate_or_bloated_page_refused_before_fetching_transactions():
    row=dict(signature=SIG,slot=1234,err=None)
    for page in ([row,row],[row]*21):
        rpc=Fake(page=page)
        with pytest.raises(ValueError):
            c.read_launchlab_creation_sample(rpc)
        assert rpc.methods==["getGenesisHash","getSignaturesForAddress"]


def test_unsigned_or_unapproved_launch_discovery_cannot_query_helius(monkeypatch):
    from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
    from test_live_helius_readonly_rpc import KEY,Opener
    opener=Opener()
    rpc=HeliusReadOnlyRpc(KEY,opener=opener)
    with pytest.raises(ValueError,match="allowlisted"):
        rpc("getSignaturesForAddress",[
            c.PROGRAM,dict(limit=20,commitment="finalized")])
    permitted=HeliusReadOnlyRpc(KEY,opener=opener,allow_launch_discovery=True)
    for addr,limit,finality in (
        ("not-the-program",20,"finalized"),
        (c.PROGRAM,21,"finalized"),
        (c.PROGRAM,20,"confirmed")):
        with pytest.raises(ValueError,match="bounded"):
            permitted("getSignaturesForAddress",[
                addr,dict(limit=limit,commitment=finality)])
    assert opener.calls==[]
