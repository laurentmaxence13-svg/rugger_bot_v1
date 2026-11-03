"""No-key public signed prospective PAPER pipeline: entirely offline tests."""
from io import BytesIO
import json

import pytest

from bot.live import public_sol_forward_paper as mod
from bot.live.helius_ws_forward_paper import ReadOnlyLogAudit
from bot.live.readonly_plan import MAINNET_GENESIS


class FakeResponse:
    status=200
    def __init__(self,doc):
        self.body=BytesIO(json.dumps(doc).encode("utf-8"))
    def __enter__(self):
        return self
    def __exit__(self,*unused):
        return None
    def read(self,size):
        assert size==mod.MAX_BODY_BYTES+1
        return self.body.read(size)


def test_public_rpc_allows_only_bounded_reads_and_no_keys():
    seen=[]
    def open_fake(req,timeout):
        assert req.full_url==mod.HTTP_RPC
        assert req.get_method()=="POST"
        assert timeout==12
        data=json.loads(req.data)
        assert data["method"]=="getGenesisHash"
        assert not any("api-key" in k.lower() for k in req.headers)
        seen.append(data)
        return FakeResponse({"jsonrpc":"2.0","id":1,"result":MAINNET_GENESIS})
    r=mod.PublicReadOnlyRpc(None,max_calls=1,opener=open_fake)
    assert r("getGenesisHash",[])==MAINNET_GENESIS
    assert r.count==1 and len(seen)==1
    with pytest.raises(ValueError,match="budget_exhausted"):
        r("getGenesisHash",[])
    with pytest.raises(ValueError,match="non_readonly"):
        r("sendTransaction",["synthetic-wallet-wire"])
    assert len(seen)==1


def test_key_never_accepted_into_free_public_rpc():
    with pytest.raises(ValueError,match="requires_no_key"):
        mod.PublicReadOnlyRpc("some_private_api_key")
    with pytest.raises(ValueError):
        mod.PublicReadOnlyRpc(None,max_calls=11)


def test_unsupported_rpc_mint_bank_and_transactions_cannot_be_sent():
    rpc=mod.PublicReadOnlyRpc(None,max_calls=1,
        opener=lambda *a,**k: (_ for _ in ()).throw(AssertionError("NETWORK")))
    for method,params in [
        ("simulateTransaction",["abc",{}]),
        ("getMultipleAccounts",[["a"],{}]),
        ("getTransaction",["too-short",{}]),
        ("getSignaturesForAddress",["SOL",{}]),
        ("sendRawTransaction",["wire"]),
    ]:
        with pytest.raises(ValueError,match="non_readonly"):
            rpc(method,params)
    assert rpc.count==0


def test_integrated_real_verifier_no_creation_stays_wait_paper(tmp_path):
    async def observer(*,seconds):
        assert seconds==30
        return ReadOnlyLogAudit(7,100).report(
            duration_ms=30000,handshake_ms=1),[]
    instances=[]
    class FakeRpc:
        def __init__(self,key,max_calls):
            assert key is None
            self.count=0
            self.max_calls=max_calls
            instances.append(self)
        def __call__(self,method,params):
            assert method=="getGenesisHash" and params==[]
            self.count+=1
            assert self.count<=self.max_calls
            return MAINNET_GENESIS
    dest=tmp_path/"public-empty"
    result=mod.run_one_public_paper_capture(
        seconds=30,output_dir=dest,observer=observer,rpc_factory=FakeRpc)
    assert result["source"]=="FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS"
    assert result["log_events"]==0
    assert result["signed_creation_transactions"]==0
    assert result["selected_independent_creators"]==0
    assert result["frozen_master_S1_decisions"]==0
    assert result["native_sol_graphs"]==0
    assert result["verification_rpc_calls"]==1
    assert result["bank_rpc_calls"]==0
    assert result["genuine_master_paper_buys"]==0
    assert result["genuine_master_paper_sells"]==0
    assert result["master_net_pnl_lamports"] is None
    assert result["financial_order_submitted"] is False
    assert sorted(p.name for p in dest.iterdir())==[
        "finalized_creation_proof.json","paired_master_source_shadow.json",
        "public_log_capture.json","summary.json"]
    assert json.loads((dest/"summary.json").read_text())==result
    with pytest.raises(ValueError,match="new_public_evidence_directory"):
        mod.run_one_public_paper_capture(
            seconds=30,output_dir=dest,observer=observer,rpc_factory=FakeRpc)


def test_invalid_network_duration_fails_before_observer(tmp_path):
    calls=[]
    async def observer(**kwargs):
        calls.append("NETWORK")
        raise AssertionError("not called")
    with pytest.raises(ValueError,match="bounded_public"):
        mod.run_one_public_paper_capture(
            seconds=500,output_dir=tmp_path/"invalid",observer=observer)
    assert calls==[]


def test_cli_has_no_automatic_network(monkeypatch,capsys,tmp_path):
    calls=[]
    monkeypatch.setattr(mod,"run_one_public_paper_capture",
        lambda **kw: calls.append("NETWORK"))
    assert mod.main(["--output-dir",str(tmp_path/"test")])==2
    assert calls==[]
    assert "NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_fake_master_profit_or_order_never_accepted(tmp_path):
    async def observer(*,seconds):
        return ReadOnlyLogAudit(7,100).report(
            duration_ms=30000,handshake_ms=1),[]
    class FakeRpc:
        count=0
        def __init__(self,*args,**kwargs):
            pass
    def fake_strategy(*args):
        return {"financial_order_submitted":False,
                "execution_verified":False,
                "live_ready_to_arm":False,
                "master_net_pnl_lamports":100000}
    # The real signed verifier would call getGenesisHash.
    def valid_rpc(*args,**kwargs):
        class R:
            count=0
            def __call__(self,method,params):
                self.count+=1
                return MAINNET_GENESIS
        return R()
    with pytest.raises(ValueError,match="unqualified_paper_or_financial_claim"):
        mod.run_one_public_paper_capture(
            seconds=30,output_dir=tmp_path/"refused",observer=observer,
            rpc_factory=valid_rpc,strategy=fake_strategy)
