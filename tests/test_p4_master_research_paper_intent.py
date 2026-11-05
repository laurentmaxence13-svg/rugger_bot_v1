"""Real Master scorer PAPER intents may be tested before required LIVE edge proof."""
from copy import deepcopy

import pytest

from bot.p4.master_research_paper_intent import (
    ENTRY_PAPER_LAMPORTS,freeze_master_research_paper)
from bot.p4.live_like_paper_ledger import PaperLedger
from bot.p4.native_asof_signal_bridge import verified_full_asof_features
from test_p4_native_asof_signal_bridge import evidence,MINT,POOL,CREATOR


def frame(*,signed=True,source_clock=True):
    scored=verified_full_asof_features(**evidence())
    assert scored["status"]=="COMPLETE_TYPED_ASOF_FEATURES"
    return dict(id="frozen-research-s1",mint=MINT,creator=CREATOR,pool=POOL,
        detected_at_ms=100000,available_at_ms=300000,source_slot=101,
        slot_available_at_ms=260000,features_available_at_ms=300000,
        signed_creator_verified=signed,source_clock_verified=source_clock,
        features=scored["features"],data_kind="market_observation",
        independent_buyers=None)


def test_research_uses_real_master_scorers_without_faking_history_gate():
    result=freeze_master_research_paper(frame())
    assert result["schema"]=="rugger-causal-master-research-paper-intents-v1"
    assert result["original_operational_master_action"]!="ENTER"
    assert result["provisional_reference_research_intent"]=="ENTER"
    assert result["provisional_master_research_intent"]=="ENTER"
    assert result["selected_paper_entry_budget_lamports"]==ENTRY_PAPER_LAMPORTS
    assert result["original_master_economic_and_operational_gate_still_enforced"] is True
    assert result["no_executable_price_or_fill_proven"] is True
    assert result["financial_order_submitted"] is False
    book=PaperLedger()
    book.register(result["research_freeze"])
    report=book.snapshot()
    assert report["frozen_decisions"]==1
    assert report["open_inventory_present"] is False
    assert report["policy_paired_model_net_edge_lamports"] is None
    assert report["exact_live_profitability_verified"] is False


def test_unverified_creation_or_clock_cannot_enter_even_shadow_paper():
    for field in ("signed","source_clock"):
        f=dict(signed=True,source_clock=True)
        f[field]=False
        result=freeze_master_research_paper(frame(**f))
        assert result["research_freeze"]["case"]["decisions"]==(
            {"master":"WAIT","reference":"WAIT"})
        assert result["financial_order_submitted"] is False


def test_future_nested_price_or_cross_token_history_rejected():
    f=frame()
    f["features"]["future_profitability"]=500
    with pytest.raises(ValueError,match="postoutcome"):
        freeze_master_research_paper(f)
    f=frame()
    f["features_available_at_ms"]=f["available_at_ms"]+1
    with pytest.raises(ValueError,match="causal_scorer"):
        freeze_master_research_paper(f)
    f=frame()
    h=deepcopy(f);h["available_at_ms"]-=1000;h["features_available_at_ms"]-=1000
    h["mint"]="other-mint"
    with pytest.raises(ValueError,match="cross_asset_or_creator"):
        freeze_master_research_paper(f,[h])
