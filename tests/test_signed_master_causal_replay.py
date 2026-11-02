"""Offline regression for genuine signed-source Master S1 replay (NO ORDERS)."""
from copy import deepcopy
import json

import pytest

from bot.p4.signed_master_causal_replay import (
    replay_public_signed_cohort, _hash)
from bot.live.public_sol_forward_paper import run_one_public_paper_capture
from bot.live.public_sol_forward_cohort import collect_public_cohort
from bot.live.helius_ws_forward_paper import ReadOnlyLogAudit
from bot.live.readonly_plan import MAINNET_GENESIS
from test_signed_creation_forward_bank import signed_pair,POOL,MINT,CREATOR


def write(path,doc):
    path.write_text(json.dumps(doc,sort_keys=True,allow_nan=False))


def signed_s1_campaign(tmp_path,monkeypatch):
    import bot.p3.signed_creation_forward_bank as bank
    import bot.p3.certification as certification
    c,v=signed_pair()
    def addr(n):
        return certification._encode(bytes([n])*32)
    graph=dict(pool=POOL,config=addr(31),platform=addr(32),mint_a=MINT,
               mint_b=bank.SOL_MINT,vault_a=addr(33),vault_b=addr(34))
    calls=[]
    def banks(rpc,addresses,floor):
        i=len(calls);calls.append((addresses,floor))
        if i==0:
            return 463809742,{POOL:{"source":"pool"}}
        if i==1:
            return 463809743,{key:{"source":"S1"} for key in addresses}
        return 463809744,{key:{"source":"S2"} for key in addresses}
    def analysis(accounts,**kwargs):
        if kwargs.get("compute_projection") is False:
            return dict(evidence_profile="published_metadata_v1",
                blocking_reasons=[],risk_flags=[],
                facts=dict(pool=dict(status=0),
                config=dict(trade_fee_rate_ppm=2500,curve_type=0),
                platform=dict(platform_fee_rate_ppm=0,creator_fee_rate_ppm=0),
                quote_vault=dict(amount_atomic="1000000000")))
        return dict(evidence_profile="published_metadata_v1",
            blocking_reasons=["execution_not_verified"],
            risk_flags=[],
            conditional_projection=dict(buy_output_atomic="200"))
    monkeypatch.setattr(bank,"_bank",banks)
    monkeypatch.setattr(bank,"addresses_from_pool",lambda *args:graph)
    monkeypatch.setattr(bank,"analyze_snapshot",analysis)
    monkeypatch.setattr(bank,"observed_sell_projection",
                        lambda *args,**kwargs:dict(output_lamports="900000000"))
    def rpc(method,params):
        assert method=="getGenesisHash"
        return MAINNET_GENESIS
    paired=bank.signed_creator_asof_paper(c,v,rpc,
        sleep=lambda delay:None,clock_ms=lambda:1793475669400,
        delay_seconds=1)
    assert len(calls)==3
    assert paired["observations"][0]["frozen_decision_before_S2"]["master_action"]=="WAIT"
    source=tmp_path/"campaign"
    window=source/"window_00"
    window.mkdir(parents=True)
    docs=dict(public_log_capture=c,finalized_creation_proof=v,
              paired_master_source_shadow=paired)
    summary=dict(schema="rugger-public-solana-forward-signed-paper-v1",
        source="FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS",
        log_events=1,signed_creation_transactions=1,
        selected_independent_creators=1,
        frozen_master_S1_decisions=1,
        native_sol_graphs=1,
        verification_rpc_calls=1,bank_rpc_calls=3,
        financial_order_submitted=False,
        genuine_master_paper_buys=0,genuine_master_paper_sells=0,
        master_net_pnl_lamports=None,
        artifact_sha256={k:_hash(x) for k,x in docs.items()})
    for k,x in docs.items():
        write(window/(k+".json"),x)
    write(window/"summary.json",summary)
    campaign=dict(schema="rugger-free-public-signed-cohort-v1",
        source="FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS",
        window_count=1,windows=[dict(window=0,rpc_calls=4,
          source_summary_sha256=_hash(summary))],
        observed_unique_events=1,
        uniquely_selected_signed_creators=1,native_SOL_source_creators=1,
        total_rpc_calls=4,master_paper_buys=0,master_paper_sells=0,
        master_net_pnl_lamports=None,
        financial_order_submitted=False,live_trading_enabled=False)
    write(source/"campaign_summary.json",campaign)
    return source


def test_genuine_s1_master_ref_recomputed_and_ledger_stays_empty(tmp_path,monkeypatch):
    folder=signed_s1_campaign(tmp_path,monkeypatch)
    result=replay_public_signed_cohort(folder)
    assert result["status"]=="GENUINE_MASTER_CAUSAL_WAIT_REPRODUCED"
    assert result["genuine_master_S1_decisions_recomputed"]==1
    assert result["signed_distinct_creators"]==1
    assert result["native_SOL_creator_graphs"]==1
    assert result["master_paper_entries"]==0
    assert result["master_paper_exits"]==0
    assert result["master_net_pnl_lamports"] is None
    assert result["exact_real_master_buy_sell_paper_cycle_verified"] is False
    assert result["financial_order_submitted"] is False
    assert result["archived_Ed25519_signatures_reverified_from_bytes_here"] is False


def test_missing_original_preoutcome_master_inputs_must_refuse(tmp_path,monkeypatch):
    folder=signed_s1_campaign(tmp_path,monkeypatch)
    path=folder/"window_00"/"paired_master_source_shadow.json"
    paired=json.loads(path.read_text())
    del paired["observations"][0]["s1_preoutcome_frame"]
    write(path,paired)
    summary_path=folder/"window_00"/"summary.json"
    summary=json.loads(summary_path.read_text())
    summary["artifact_sha256"]["paired_master_source_shadow"]=_hash(paired)
    write(summary_path,summary)
    campaign_path=folder/"campaign_summary.json"
    campaign=json.loads(campaign_path.read_text())
    campaign["windows"][0]["source_summary_sha256"]=_hash(summary)
    write(campaign_path,campaign)
    with pytest.raises(ValueError,match="noncausal_signed_master_frame"):
        replay_public_signed_cohort(folder)


def test_forged_master_paper_fill_cannot_pass_even_with_rehashed_summary(tmp_path,monkeypatch):
    folder=signed_s1_campaign(tmp_path,monkeypatch)
    path=folder/"campaign_summary.json"
    doc=json.loads(path.read_text())
    doc["master_paper_buys"]=1
    write(path,doc)
    with pytest.raises(ValueError,match="signed_source_campaign_readiness_not_verified"):
        replay_public_signed_cohort(folder)


def test_wrong_provider_sha_does_not_validate_borrowed_frame(tmp_path,monkeypatch):
    folder=signed_s1_campaign(tmp_path,monkeypatch)
    path=folder/"window_00"/"paired_master_source_shadow.json"
    report=json.loads(path.read_text())
    report["observations"][0]["s1_preoutcome_frame"]["creator"]="SPOOFED"
    write(path,report)
    with pytest.raises(ValueError,match="tampered_public_source_artifact"):
        replay_public_signed_cohort(folder)


def test_missing_candidate_campaign_keeps_null_profit_without_calls(tmp_path):
    async def empty(*,seconds):
        return ReadOnlyLogAudit(5,100).report(duration_ms=30000,
                                              handshake_ms=1),[]
    class R:
        def __init__(self,key,max_calls):
            assert key is None
            self.count=0
        def __call__(self,method,params):
            self.count+=1
            assert method=="getGenesisHash"
            return MAINNET_GENESIS
    def capture(*,seconds,output_dir):
        return run_one_public_paper_capture(
            seconds=seconds,output_dir=output_dir,observer=empty,
            rpc_factory=R)
    folder=tmp_path/"empty"
    collect_public_cohort(directory=folder,window_count=1,seconds=30,
                          capture=capture)
    result=replay_public_signed_cohort(folder)
    assert result["genuine_master_S1_decisions_recomputed"]==0
    assert result["status"]=="NO_GENUINE_MASTER_S1_TO_REPLAY"
    assert result["source_original_Ed25519_proofs_used"] is False
    assert result["master_net_pnl_lamports"] is None
    assert result["master_paper_entries"]==0


def test_rehashed_edited_signed_slot_still_breaks_source_binding(tmp_path,monkeypatch):
    folder=signed_s1_campaign(tmp_path,monkeypatch)
    window=folder/"window_00"
    source=json.loads((window/"public_log_capture.json").read_text())
    verified=json.loads((window/"finalized_creation_proof.json").read_text())
    paired=json.loads((window/"paired_master_source_shadow.json").read_text())
    summary=json.loads((window/"summary.json").read_text())
    campaign=json.loads((folder/"campaign_summary.json").read_text())
    verified["records"][0]["slot"]+=1
    paired["frozen_source_hash_sha256"]=_hash(dict(
        log_chain=source["report"]["signature_ledger_sha256"],
        verified_receipts=verified))
    write(window/"finalized_creation_proof.json",verified)
    write(window/"paired_master_source_shadow.json",paired)
    summary["artifact_sha256"]["finalized_creation_proof"]=_hash(verified)
    summary["artifact_sha256"]["paired_master_source_shadow"]=_hash(paired)
    write(window/"summary.json",summary)
    campaign["windows"][0]["source_summary_sha256"]=_hash(summary)
    write(folder/"campaign_summary.json",campaign)
    with pytest.raises(ValueError,match="invalid_signed_receipt_identity"):
        replay_public_signed_cohort(folder)
