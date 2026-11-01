"""Actual frozen Master vs reference SCORER INTENT, before future market evidence.

These synthetic tests deliberately never promote a scorer intent to a fill.
"""
from copy import deepcopy
import pytest
from bot.p4.actual_master_reference_freeze import freeze_real_master_reference
from test_p4_experiment import corpus


def frame():
    row=corpus()["frames"][0]
    # Synthetic quote fixture reports contextSlot=101 while its outer frame
    # originally declares slot=100. Align the test frame to the quote source.
    row["source_slot"]=101
    row.update(source_clock_verified=False,signed_creator_verified=False)
    return row


def test_actual_master_and_reference_intent_frozen_from_one_preoutcome_frame():
    source=frame()
    original=deepcopy(source)
    result=freeze_real_master_reference(source,[])
    assert source==original
    assert result["actual_engines_called_before_outcome"] is True
    assert result["reference_decision_scope"]=="scorer_intent_without_operational_admission"
    assert result["master_decision_scope"]=="actual_master_shadow_full_evidence_and_capital_gate"
    assert result["no_independent_executable_orders"] is True
    assert result["frozen_pair"]["phase"]=="FROZEN_PRE_OUTCOME"
    assert result["frozen_pair"]["future_prices_consumed"] is False
    assert result["original_master_action"]!="ENTER"
    assert result["frozen_pair"]["research_case"]["master_action"]!="ENTER"
    assert result["frozen_pair"]["research_case"]["reference_action"] in ("ENTER","WAIT")
    assert result["prospective_strategy_profitability_verified"] is False
    assert result["financial_order_submitted"] is False


def test_future_feature_timestamp_rejected():
    x=frame();x["features_available_at_ms"]=x["available_at_ms"]+1
    with pytest.raises(ValueError,match="causal_scorer_features"):
        freeze_real_master_reference(x)


def test_future_history_is_not_retrospectively_filtered():
    x=frame();past=deepcopy(x)
    with pytest.raises(ValueError,match="future_or_unordered_history"):
        freeze_real_master_reference(x,[past])


def test_future_exit_in_frame_is_rejected_even_when_hidden_from_engines():
    x=frame();x["future_S2_price"]=100000
    with pytest.raises(ValueError,match="postoutcome_features"):
        freeze_real_master_reference(x)


def test_missing_known_feature_availability_prevents_false_freeze():
    x=frame();x["features_available_at_ms"]=None
    with pytest.raises(ValueError,match="causal_scorer_features"):
        freeze_real_master_reference(x)


def test_invalid_reference_name_rejected_before_evaluation():
    with pytest.raises(ValueError,match="bounded_actual_scorer"):
        freeze_real_master_reference(frame(),reference_strategy="unregistered")


def test_nested_future_price_in_features_rejected_before_scorers():
    x=frame();x["features"]["future_S2_price"]=10**12
    with pytest.raises(ValueError,match="postoutcome_features"):
        freeze_real_master_reference(x)


def test_nested_future_price_in_history_rejected_before_scorers():
    x=frame();x["available_at_ms"]+=2000;x["source_slot"]+=2
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    prior=frame();prior["features"]["postdecision_results"]={"win":True}
    with pytest.raises(ValueError,match="postoutcome_features"):
        freeze_real_master_reference(x,[prior])


def test_out_of_order_historical_frames_rejected():
    x=frame();x["available_at_ms"]+=3000;x["source_slot"]+=3
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    a=frame();b=deepcopy(a);b["available_at_ms"]+=1000;b["source_slot"]+=1
    b["slot_available_at_ms"]=b["available_at_ms"]
    b["features_available_at_ms"]=b["available_at_ms"]
    with pytest.raises(ValueError,match="future_or_unordered_history"):
        freeze_real_master_reference(x,[b,a])


def test_future_historical_slot_clock_rejected():
    x=frame();x["available_at_ms"]+=2000;x["source_slot"]+=2
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    prior=frame();prior["slot_available_at_ms"]=x["available_at_ms"]
    with pytest.raises(ValueError,match="noncausal_historical_source_clock"):
        freeze_real_master_reference(x,[prior])


def test_future_historical_feature_clock_rejected():
    x=frame();x["available_at_ms"]+=2000;x["source_slot"]+=2
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    prior=frame();prior["features_available_at_ms"]=x["available_at_ms"]
    with pytest.raises(ValueError,match="noncausal_historical_source_clock"):
        freeze_real_master_reference(x,[prior])



def test_nested_future_provider_quote_availability_rejected():
    x=frame()
    x["features"]["provider_quote"]={"quote_available_at_ms":x["available_at_ms"]+1,
                                      "price":123}
    with pytest.raises(ValueError,match="nested_future_availability_clock"):
        freeze_real_master_reference(x)


def test_nested_future_provider_quote_slot_rejected():
    x=frame()
    x["features"]["provider_quote"]={"quote_slot":x["source_slot"]+1,
                                      "price":123}
    with pytest.raises(ValueError,match="nested_future_source_slot"):
        freeze_real_master_reference(x)


def test_nested_future_history_quote_rejected_against_its_own_past_clock():
    x=frame();x["available_at_ms"]+=3000;x["source_slot"]+=3
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    past=frame()
    past["features"]["provider_quote"]={"observed_at_ms":past["available_at_ms"]+1}
    with pytest.raises(ValueError,match="nested_future_availability_clock"):
        freeze_real_master_reference(x,[past])


def test_nested_future_history_slot_rejected_even_if_before_current_slot():
    x=frame();x["available_at_ms"]+=3000;x["source_slot"]+=3
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    past=frame()
    past["features"]["provider_quote"]={"context_slot":past["source_slot"]+1}
    with pytest.raises(ValueError,match="nested_future_source_slot"):
        freeze_real_master_reference(x,[past])



def test_raw_provider_camelcase_future_source_time_rejected():
    x=frame()
    x["features"]["raw_quote_payload"]={"data":{
        "sourceTimeMs":x["available_at_ms"]+1}}
    with pytest.raises(ValueError,match="nested_future_availability_clock"):
        freeze_real_master_reference(x)


def test_raw_provider_camelcase_future_context_slot_rejected():
    x=frame()
    x["features"]["raw_quote_payload"]={"data":{
        "contextSlot":x["source_slot"]+1}}
    with pytest.raises(ValueError,match="nested_future_source_slot"):
        freeze_real_master_reference(x)


@pytest.mark.parametrize("clock_field",["slot_available_at_ms"])
@pytest.mark.parametrize("invalid_clock",[-1,0])
def test_nonpositive_current_slot_availability_refused(clock_field,invalid_clock):
    x=frame()
    x[clock_field]=invalid_clock
    with pytest.raises(ValueError,match="causal_scorer_features"):
        freeze_real_master_reference(x)


@pytest.mark.parametrize("clock_field",["slot_available_at_ms","features_available_at_ms"])
@pytest.mark.parametrize("invalid_clock",[-1,0])
def test_nonpositive_historical_availability_refused(clock_field,invalid_clock):
    x=frame();x["available_at_ms"]+=2000;x["source_slot"]+=2
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    prior=frame()
    prior[clock_field]=invalid_clock
    with pytest.raises(ValueError,match="noncausal_historical_source_clock"):
        freeze_real_master_reference(x,[prior])


@pytest.mark.parametrize("identity",["mint","pool","creator"])
def test_cross_asset_or_creator_history_refused_before_both_scorers(identity):
    x=frame();x["available_at_ms"]+=2000;x["source_slot"]+=2
    x["slot_available_at_ms"]=x["available_at_ms"]
    x["features_available_at_ms"]=x["available_at_ms"]
    prior=frame()
    prior[identity]="different_identity"
    with pytest.raises(ValueError,match="cross_asset_or_creator_history"):
        freeze_real_master_reference(x,[prior])
