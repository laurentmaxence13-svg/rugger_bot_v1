"""No-network dual-arm PAPER ledger: rigorously clocked model fills and P&L."""
from copy import deepcopy

import pytest

from bot.p4.live_like_paper_ledger import (
    freeze_decision,PaperLedger,sha,source_quote)

MINT="fixture-signed-public-mint"
POOL="fixture-launchlab-curve"


def freeze(master="ENTER",reference="ENTER",**overrides):
    case=dict(id="frozen-1",mint=MINT,creator="verified-signed-creator",
        pool=POOL,source_slot=100,available_at_ms=1000,
        decisions={"master":master,"reference":reference},
        entry_size_lamports=100_000_000,
        signed_creator_verified=True,asof_features_verified=True,
        source_quote_clock_verified=True,policy_sha256="a"*64)
    case.update(overrides)
    return freeze_decision(case)


def quote(side,*,id="source-1",pool=POOL,venue="LAUNCHLAB_CURVE",
          slot=101,available=1500,input=100_000_000,output=1_000_000,
          network_fee=5000,ata=2000,failed_fee=0,provenance="OBSERVED_CHAIN_MODEL",
          proof=None):
    return dict(id=id,mint=MINT,pool=pool,venue=venue,side=side,
        input_atomic=input,output_atomic=output,source_slot=slot,
        available_at_ms=available,source_produced_at_ms=available,
        source_observation_sha256="b"*64,
        provenance=provenance,
        network_and_priority_fee_lamports=network_fee,
        account_creation_fee_lamports=ata,
        failed_attempt_fee_lamports=failed_fee,migration_proof=proof)


def test_synthetic_but_complete_same_tape_paper_roundtrip_both_arms():
    engine=PaperLedger()
    engine.register(freeze())
    buy=quote("BUY")
    assert engine.quote("frozen-1","master","BUY",buy)["actual_transaction_fill"] is False
    engine.quote("frozen-1","reference","BUY",buy)
    sell=quote("SELL",id="source-2",slot=102,available=3000,
        input=1_000_000,output=110_000_000,network_fee=8000,ata=0)
    engine.quote("frozen-1","master","SELL",sell)
    engine.quote("frozen-1","reference","SELL",sell)
    r=engine.snapshot()
    assert r["frozen_decisions"]==1 and r["event_count"]==5
    assert r["accounts"]["master"]["closed_paper_cycles"]==1
    assert r["accounts"]["reference"]["closed_paper_cycles"]==1
    net=110_000_000-8000-100_000_000-5000-2000
    assert r["accounts"]["master"]["complete_cycle_net_pnl_lamports"]==net
    assert r["accounts"]["reference"]["complete_cycle_net_pnl_lamports"]==net
    assert r["policy_paired_model_net_edge_lamports"]==0
    assert r["accounts"]["master"]["cash_lamports"]==10_000_000_000+net
    assert r["any_model_conditional_prices"] is True
    assert r["actual_financial_orders_submitted"]==0
    assert r["exact_live_profitability_verified"] is False
    assert r["live_ready_to_arm"] is False


def test_master_enters_reference_waits_and_edge_is_conditional_only():
    engine=PaperLedger()
    engine.register(freeze(reference="WAIT"))
    engine.quote("frozen-1","master","BUY",quote("BUY"))
    with pytest.raises(ValueError,match="policy_abstention"):
        engine.quote("frozen-1","reference","BUY",quote("BUY",id="ref-no-buy"))
    assert engine.snapshot()["policy_paired_model_net_edge_lamports"] is None
    engine.quote("frozen-1","master","SELL",quote("SELL",
        id="source-2",slot=102,available=3500,
        input=1_000_000,output=75_000_000,network_fee=5000,ata=0))
    result=engine.snapshot()
    assert result["accounts"]["master"]["complete_cycle_net_pnl_lamports"]==(
        75_000_000-5000-100_000_000-7000)
    assert result["accounts"]["reference"]["complete_cycle_net_pnl_lamports"]==0
    assert result["policy_paired_model_net_edge_lamports"]<0
    assert result["exact_live_profitability_verified"] is False


def test_migrated_cpmm_exit_requires_signed_exact_identity_and_full_token_lot():
    engine=PaperLedger()
    engine.register(freeze())
    engine.quote("frozen-1","master","BUY",quote("BUY"))
    migrated=quote("SELL",id="cpmm-final",pool="signed-migrated-cpmm",
        venue="RAYDIUM_CPMM",slot=130,available=2500,
        input=1_000_000,output=90_000_000,ata=0)
    with pytest.raises(ValueError,match="exact_signed_migration"):
        engine.quote("frozen-1","master","SELL",migrated)
    proof=dict(mint=MINT,from_pool=POOL,to_pool="signed-migrated-cpmm",
        source_slot=129,signed_transaction_verified=True,
        transaction_sha256="c"*64)
    migrated["migration_proof"]=proof
    with pytest.raises(ValueError,match="sell_lot"):
        engine.quote("frozen-1","master","SELL",dict(migrated,input_atomic=999_999))
    with pytest.raises(ValueError,match="unverified_or_wrong"):
        engine.quote("frozen-1","master","SELL",dict(migrated,
            migration_proof=dict(proof,from_pool="wrong-from")))
    engine.quote("frozen-1","master","SELL",migrated)
    result=engine.snapshot()
    assert result["accounts"]["master"]["closed_trades"][0]["migration_to_cpmm"] is True
    assert result["accounts"]["reference"]["closed_paper_cycles"]==0


def test_missing_fees_or_wrong_quote_provenance_cannot_generate_pnl():
    engine=PaperLedger()
    engine.register(freeze())
    wrong=quote("BUY")
    wrong.pop("network_and_priority_fee_lamports")
    with pytest.raises(ValueError,match="exact_quote"):
        engine.quote("frozen-1","master","BUY",wrong)
    wrong=quote("BUY",provenance="invented")
    with pytest.raises(ValueError,match="exact_price_source"):
        engine.quote("frozen-1","master","BUY",wrong)
    wrong=quote("BUY",available=1020)
    with pytest.raises(ValueError,match="noncausal"):
        engine.quote("frozen-1","master","BUY",wrong)
    assert engine.snapshot()["accounts"]["master"]["closed_paper_cycles"]==0


def test_future_decision_without_verified_creator_or_features_cannot_enter():
    for field in ("signed_creator_verified","asof_features_verified",
                  "source_quote_clock_verified"):
        with pytest.raises(ValueError,match="unverified_entry"):
            freeze(**{field:False})
    wait=freeze(master="WAIT",reference="WAIT",
                signed_creator_verified=False,
                asof_features_verified=False,
                source_quote_clock_verified=False)
    engine=PaperLedger()
    engine.register(wait)
    assert engine.snapshot()["accounts"]["master"]["complete_cycle_net_pnl_lamports"]==0
    assert engine.snapshot()["policy_paired_model_net_edge_lamports"] is None
    with pytest.raises(ValueError,match="freeze_was_modified"):
        tampered=deepcopy(wait)
        tampered["case"]["decisions"]["master"]="ENTER"
        engine.register(tampered)


def test_open_inventory_censored_not_hidden_as_zero_and_no_repeated_buy():
    engine=PaperLedger(capital_lamports=100_000_000)
    engine.register(freeze(entry_size_lamports=99_000_000))
    engine.quote("frozen-1","master","BUY",quote("BUY",input=99_000_000))
    report=engine.snapshot()
    assert report["accounts"]["master"]["open_positions"]==1
    assert report["accounts"]["master"]["complete_cycle_net_pnl_lamports"] is None
    assert report["policy_paired_model_net_edge_lamports"] is None
    assert report["open_inventory_present"] is True
    with pytest.raises(ValueError,match="quote_receipt_reuse"):
        engine.quote("frozen-1","master","BUY",quote("BUY",input=99_000_000))
    with pytest.raises(ValueError,match="duplicate_position"):
        engine.quote("frozen-1","master","BUY",quote("BUY",id="different",input=99_000_000))


def test_failed_exit_unknown_fees_never_fills_or_silently_zero():
    engine=PaperLedger()
    engine.register(freeze())
    engine.quote("frozen-1","master","BUY",quote("BUY"))
    with pytest.raises(ValueError):
        engine.quote("frozen-1","master","SELL",quote("SELL",
            id="exit",slot=105,available=3500,input=1_000_000,
            output=500,network_fee=1000,ata=0))
    assert engine.snapshot()["accounts"]["master"]["open_positions"]==1
    assert engine.snapshot()["accounts"]["master"]["complete_cycle_net_pnl_lamports"] is None
