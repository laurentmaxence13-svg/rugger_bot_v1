"""Actual frozen Master vs reference SCORER INTENT, before future market evidence.

These synthetic tests deliberately never promote a scorer intent to a fill.
"""
from copy import deepcopy
import pytest
from bot.p4.actual_master_reference_freeze import freeze_real_master_reference
from test_p4_experiment import corpus


def frame():
    row=corpus()["frames"][0]
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
