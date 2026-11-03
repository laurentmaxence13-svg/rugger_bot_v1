"""Native Helius bank features are causal; USD and creator data are never guessed."""
from copy import deepcopy

import pytest

from bot.p4.native_asof_signal_bridge import native_asof_bank,verified_full_asof_features
from bot.p4_experiment import decide_prefix
from bot.master_decision import MasterDecisionOrchestrator
from test_p3_curve_size_grid import bank


MINT="verified-native-source-mint"
POOL="verified-native-source-pool"
CREATOR="verified-outer-signer"


def native():
    a=bank(101,"initial")["payload"]["analysis"]
    a["facts"]["pool"]["mint_a"]=MINT
    return native_asof_bank(analysis=a,mint=MINT,creator=CREATOR,
        pool=POOL,source_slot=101,available_at_ms=260000)


def evidence():
    return dict(
        native=native(),
        creation=dict(mint=MINT,creator=CREATOR,pool=POOL,
                      cryptographic_creation=True,
                      detected_at_ms=100000,verified_at_ms=250000),
        sol_usd=dict(source="certified_onchain_SOL_USD_oracle",
                     source_chain_verified=True,value=200.0,
                     available_at_ms=299000),
        creator_history=dict(creator=CREATOR,
            complete_prior_creation_coverage=True,prior_launches=0,
            available_at_ms=270000),
        verified_transactions=[],market_price_history=[],
        decision_at_ms=300000)


def test_native_asof_real_account_spot_without_usd_fabrication():
    item=native()
    assert item["source_native_facts_observed"] is True
    assert item["source_price_is_curve_model_not_executable_quote"] is True
    assert item["complete_SignalFeatures_available"] is False
    assert item["price_usd"] is None
    assert item["liquidity_usd"] is None
    assert item["spot_sol_per_token_fraction"]["denominator"]!="0"
    assert item["funding_sol_fraction"]["numerator"]!="0"


def test_missing_fx_or_unsigned_creator_fails_closed_before_decision():
    e=evidence()
    e["sol_usd"]=None
    output=verified_full_asof_features(**e)
    assert output["status"]=="INSUFFICIENT_CAUSAL_FEATURE_EVIDENCE"
    assert output["features"] is None
    assert "fresh_verified_SOL_USD_oracle_missing" in output["missing"]
    e=evidence();e["creation"]["cryptographic_creation"]=False
    output=verified_full_asof_features(**e)
    assert "signed_creator_finalized_proof_not_available_asof" in output["missing"]


def test_complete_synthetic_signed_source_frame_feeds_real_scorers():
    result=verified_full_asof_features(**evidence())
    assert result["status"]=="COMPLETE_TYPED_ASOF_FEATURES"
    features=result["features"]
    assert features["mint"]==MINT
    assert features["creator"]==CREATOR
    assert features["quote_source"]=="launchlab_curve"
    assert features["price_usd"]>0
    assert features["liquidity_usd"]>0
    assert features["behavior_known"] is False
    assert features["holder_data_known"] is False
    frame=dict(id="synthetic-s1",mint=MINT,creator=CREATOR,pool=POOL,
        detected_at_ms=100000,available_at_ms=300000,source_slot=101,
        slot_available_at_ms=260000,features_available_at_ms=300000,
        features=features)
    ref=decide_prefix("early_sniping",frame,[])
    assert type(ref["enter"]) is bool and ref["reason"]!="features_unknown_or_stale"
    master=MasterDecisionOrchestrator().evaluate(frame,[],health=None,capital=None)
    assert master["action"] in ("WAIT","NO_TRADE")
    assert master["action"]!="ENTER"


def test_future_transaction_or_price_tape_rejected_not_silently_ignored():
    e=evidence()
    e["verified_transactions"]=[dict(timestamp_sec=301,
        available_at_ms=301000,source_slot=102,
        signed_receipt_verified=True,signature="demo",
        transaction={})]
    output=verified_full_asof_features(**e)
    assert "unverified_or_future_transaction_in_feature_tape" in output["missing"]
    e=evidence()
    e["market_price_history"]=[dict(observed_at_sec=301,
        available_at_ms=301000,price_usd=1,liquidity_usd=1)]
    output=verified_full_asof_features(**e)
    assert "unverified_or_future_price_history" in output["missing"]


def test_spoofed_creator_or_wrong_native_source_slot_refused():
    e=evidence()
    e["creation"]["mint"]="different"
    assert verified_full_asof_features(**e)["features"] is None
    bad=bank(101,"initial")["payload"]["analysis"]
    bad["facts"]["pool"]["mint_a"]=MINT
    with pytest.raises(ValueError,match="causal_signed_creation_bank"):
        native_asof_bank(analysis=bad,mint=MINT,creator=CREATOR,
            pool=POOL,source_slot=102,available_at_ms=260000)
