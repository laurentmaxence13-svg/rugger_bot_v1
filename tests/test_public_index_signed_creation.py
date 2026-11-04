"""Offline signed-index-source intake; untrusted leads never become Master trades."""
import json

import pytest

from bot.live import public_index_signed_creation as mod
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.quotes import SOL_MINT

MINT="ChWZ8yNvMh31yHtkZh3fSjWZaQiv62bHr1WPnUPLvuLF"
POOL="EBA8nnnHuFRMHd3Ac9HMMCNTi52E3GXT7HDreXwvhnCu"
CREATOR="HxM1EeyZ9z71m8mu5x9bsUdtTP1f9qtT7mo9D5tB3xwM"
SIGNATURE="5qqLenzDgNbLkuN482pPEzoZLyygQYsdLzdMZ2cuKqbpXyXRbXZCASRGw2gWNK91cpBZgorjThhJAhiCtwJk6hUk"
SLOT=464432476
PAYER="7AGFdhKYM7D5RjJn5Zk4vG9iA1c4hyR6iHLbo1tsztVn"


def row():
    return {"mint":MINT,"poolId":POOL,"creator":CREATOR,
            "mintB":{"address":SOL_MINT}}


def fake_rpc(*,page=None,wrong=False):
    class Rpc:
        def __init__(self):
            self.count=0
            self.methods=[]
        def __call__(self,method,params):
            self.count+=1
            assert self.count<=mod.MAX_RPC_PER_POOL
            self.methods.append(method)
            if method=="getGenesisHash":
                assert params==[]
                return MAINNET_GENESIS
            if method=="getSignaturesForAddress":
                assert params==[POOL,{"limit":mod.SIGNATURE_PAGE_LIMIT,
                                     "commitment":"finalized"}]
                return page if page is not None else [
                    {"signature":SIGNATURE,"slot":SLOT,"err":None}]
            if method=="getTransaction":
                assert params[0]==SIGNATURE
                return {"slot":SLOT, "meta":{"err":None,
                         "innerInstructions":[{"index":0,"instructions":[]}]},
                         "transaction":{"signatures":[SIGNATURE],
                          "message":{"header":{"numRequiredSignatures":1},
                                     "accountKeys":[PAYER]}}}
            if method=="getMultipleAccounts":
                assert params[1]["commitment"]=="confirmed"
                if len(params[0])==1:
                    return {"context":{"slot":SLOT+1},
                            "value":[{"placeholder":"source pool account"}]}
                assert len(params[0])==7
                return {"context":{"slot":SLOT+2},
                        "value":[{"placeholder":"source"} for _ in range(7)]}
            raise AssertionError("unexpected RPC method")
    return Rpc()


def patch_signed_verified(monkeypatch):
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
        lambda tx:{"cryptographic_signatures_verified":True,
                   "exact_message_sha256":"a"*64})
    def decode_outer(tx):
        assert tx["meta"]["innerInstructions"]==[]
        return [{"creator":CREATOR,"mint":MINT,"pool_state":POOL,
                 "payer":PAYER}]
    monkeypatch.setattr(mod,"compiled_launchlab_creations",decode_outer)
    graph={"pool":POOL,"config":"source-config","platform":"source-platform",
           "mint_a":MINT,"mint_b":SOL_MINT,
           "vault_a":"source-vault-a","vault_b":"source-vault-b"}
    monkeypatch.setattr(mod,"addresses_from_pool",
                        lambda account,mint,pool:graph)
    monkeypatch.setattr(mod,"analyze_snapshot",
        lambda *args,**kwargs:{"risk_flags":[],
            "blocking_reasons":["creation_transaction_not_verified_by_snapshot",
                               "additional_execution_costs_unknown"]})


def test_real_scorer_protection_remains_even_with_signed_SOL_graph(
        monkeypatch,tmp_path):
    patch_signed_verified(monkeypatch)
    instances=[]
    def factory(key,max_calls):
        assert key is None and max_calls==10
        obj=fake_rpc()
        instances.append(obj)
        return obj
    result=mod.run_index_proof_campaign(
        output_dir=tmp_path/"signed-index",
        fetch_rows=lambda:[row()],rpc_factory=factory)
    assert len(instances)==1
    assert instances[0].methods==[
        "getGenesisHash","getSignaturesForAddress","getTransaction",
        "getMultipleAccounts","getMultipleAccounts"]
    assert result["individually_verified_outer_signed_creations"]==1
    assert result["distinct_native_SOL_verified_creators"]==1
    assert result["total_public_rpc_calls"]==5
    assert result["genuine_master_paper_buy_sell_verified"] is False
    assert result["original_master_enter_qualified"] is False
    assert result["master_net_pnl_lamports"] is None
    assert result["financial_order_submitted"] is False
    assert result["source_receipts"][0]["contextual_S1_bank_qualified"] is False
    assert result["source_receipts"][0]["signed_creation_signature"]==SIGNATURE
    assert "additional_execution_costs_unknown" in (
        result["source_receipts"][0]["S1_blocking_reasons"])
    assert json.loads((tmp_path/"signed-index"/"summary.json").read_text())==result


def test_untrusted_index_creator_claim_does_not_count_as_signed(monkeypatch):
    patch_signed_verified(monkeypatch)
    monkeypatch.setattr(mod,"compiled_launchlab_creations",
        lambda tx:[{"creator":"another-creator","mint":MINT,"pool_state":POOL,
                    "payer":PAYER}])
    item=dict(pool=POOL,mint=MINT,creator_claim=CREATOR)
    result=mod.inspect_pool(item,rpc=fake_rpc())
    assert result["outer_signed_create_verified"] is False
    assert result["native_SOL_pool_graph_verified"] is False
    assert result["signed_creation_signature"] is None


def test_wrong_receipt_signature_refused_before_crypto(monkeypatch):
    calls=[]
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
                        lambda tx:calls.append("ED25519"))
    rpc=fake_rpc()
    original=rpc.__call__
    class Tamper:
        def __call__(self,method,params):
            response=original(method,params)
            if method=="getTransaction":
                response["transaction"]["signatures"]=[]
            return response
    result=mod.inspect_pool(dict(pool=POOL,mint=MINT,creator_claim=CREATOR),
                            rpc=Tamper())
    assert result["outer_signed_create_verified"] is False
    assert calls==[]


def test_oversized_signature_page_cannot_overrun_provider_budget():
    oversized=[{"signature":f"sig{i}","slot":100+i,"err":None}
              for i in range(mod.SIGNATURE_PAGE_LIMIT+1)]
    with pytest.raises(ValueError,match="unbounded_source_pool_signature_page"):
        mod.inspect_pool(dict(pool=POOL,mint=MINT,creator_claim=CREATOR),
                         rpc=fake_rpc(page=oversized))


def test_no_network_without_explicit_flag(monkeypatch,capsys,tmp_path):
    called=[]
    monkeypatch.setattr(mod,"run_index_proof_campaign",
                        lambda **kwargs:called.append("NETWORK"))
    assert mod.main(["--output-dir",str(tmp_path/"test")])==2
    assert not called
    assert "NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_unexpected_scorer_financial_projection_is_never_promoted(monkeypatch,tmp_path):
    patch_signed_verified(monkeypatch)
    monkeypatch.setattr(mod,"analyze_snapshot",
        lambda *args,**kwargs:{"risk_flags":[],"blocking_reasons":[],
              "conditional_projection":{"sell_output_lamports":100000000}})
    result=mod.run_index_proof_campaign(
        output_dir=tmp_path/"projection",
        fetch_rows=lambda:[row()],
        rpc_factory=lambda key,max_calls:fake_rpc())
    assert result["genuine_master_paper_buy_sell_verified"] is False
    assert result["master_net_pnl_lamports"] is None
    assert result["independently_executable_quotes_verified"] is False


def test_compiled_outer_payer_must_be_signed(monkeypatch):
    patch_signed_verified(monkeypatch)
    monkeypatch.setattr(mod,"compiled_launchlab_creations",
        lambda tx:[{"creator":CREATOR,"mint":MINT,"pool_state":POOL,
                    "payer":"unsigned-other-account"}])
    result=mod.inspect_pool(dict(pool=POOL,mint=MINT,creator_claim=CREATOR),
                            rpc=fake_rpc())
    assert result["outer_signed_create_verified"] is False
    assert result["signed_creation_signature"] is None
