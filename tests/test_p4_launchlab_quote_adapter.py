"""Strict real-source LaunchLab bank -> two-arm PAPER quote integration tests."""
from copy import deepcopy

import pytest

from bot.p4.launchlab_quote_adapter import asof_launchlab_quote
from bot.p4.live_like_paper_ledger import PaperLedger,freeze_decision
from test_p3_curve_size_grid import bank


MINT="verified-source-mint"
POOL="verified-curve-pool"


def source(slot,phase,*,outstanding=10**15):
    event=bank(slot,phase,real_a=outstanding)
    analysis=event["payload"]["analysis"]
    pool=analysis["facts"]["pool"]
    pool["mint_a"]=MINT
    event["source_observation_sha256"]="c"*64
    return event,analysis


def paper_quote(event,analysis,side,amount,**extra):
    return asof_launchlab_quote(
        analysis=analysis,source_event=event,
        mint=MINT,pool=POOL,side=side,amount_atomic=amount,
        network_and_priority_fee_lamports=5000,
        account_creation_fee_lamports=0,
        failed_attempt_fee_lamports=0,**extra)


def test_buy_curve_model_source_stamped_paper_quote_real_sdk():
    e,a=source(101,"followup")
    result=paper_quote(e,a,"BUY",50_000_000)
    q=result["paper_quote"]
    assert q["input_atomic"]==50_000_000
    assert q["output_atomic"]>0
    assert q["source_slot"]==101
    assert q["provenance"]=="OBSERVED_CHAIN_MODEL"
    assert result["hypothetical_fill_not_actual"] is True
    assert result["onchain_price_quote_independently_executable"] is False


def test_causal_decision_synthetic_then_model_filled_buy_and_observed_sell():
    # This proves the engine's integration, NOT that Master has issued ENTER
    # on a true mainnet creation. Source and decisions are fixture values.
    e,a=source(101,"followup",outstanding=10**15)
    frozen=freeze_decision(dict(
        id="t1",mint=MINT,creator="fixture-signed",pool=POOL,
        source_slot=100,available_at_ms=1000,
        decisions={"master":"ENTER","reference":"WAIT"},
        signed_creator_verified=True,asof_features_verified=True,
        source_quote_clock_verified=True,policy_sha256="a"*64))
    exchange=PaperLedger(minimum_delay_ms=250)
    exchange.register(frozen)
    e["available_at_ms"]=1500
    buy=paper_quote(e,a,"BUY",50_000_000)["paper_quote"]
    exchange.quote("t1","master","BUY",buy)
    qty=exchange.snapshot()["accounts"]["master"]["open_inventory"][0]["quantity_atomic"]
    # New bank source slot/time for an actually observed later quote; enough
    # circulation is needed to quote the hypothetical inventory.
    next_e,next_analysis=source(102,"followup",outstanding=10**15)
    next_e["available_at_ms"]=3000
    sell=paper_quote(next_e,next_analysis,"SELL",qty)["paper_quote"]
    exchange.quote("t1","master","SELL",sell)
    result=exchange.snapshot()
    assert result["accounts"]["master"]["closed_paper_cycles"]==1
    assert result["accounts"]["master"]["open_positions"]==0
    assert result["accounts"]["master"]["extra_network_and_account_fees_lamports"]==10000
    assert result["accounts"]["reference"]["closed_paper_cycles"]==0
    assert result["accounts"]["reference"]["complete_cycle_net_pnl_lamports"]==0
    assert type(result["policy_paired_model_net_edge_lamports"]) is int
    assert result["exact_live_profitability_verified"] is False


def test_no_1sol_amm_inventory_substitution_and_no_future_or_missing_fees():
    e,a=source(101,"followup",outstanding=10**12)
    with pytest.raises(ValueError,match="extra_source_network_fee_evidence_missing"):
        asof_launchlab_quote(
            analysis=a,source_event=e,mint=MINT,pool=POOL,
            side="BUY",amount_atomic=50_000_000)
    mismatch=deepcopy(a)
    mismatch["context_slot"]=999
    with pytest.raises(ValueError,match="causal_source_receipt_missing"):
        paper_quote(e,mismatch,"BUY",50_000_000)
    wrong=deepcopy(a)
    wrong["facts"]["pool"]["mint_a"]="other-token"
    with pytest.raises(ValueError,match="active_source_mint"):
        paper_quote(e,wrong,"BUY",50_000_000)
    with pytest.raises(Exception):
        paper_quote(e,a,"SELL",2**63)
