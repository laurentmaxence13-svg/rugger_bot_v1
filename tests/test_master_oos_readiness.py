"""Regression: synthetic or survivor cohorts cannot manufacture Master edge."""
import json
from pathlib import Path
import pytest
from bot.p3.master_oos_readiness import evaluate_master_oos_readiness

ROOT=Path(__file__).resolve().parents[1]
BENCH=json.loads((ROOT/"validation/master_v2/FINAL_VALIDATION.json").read_text())
FIXTURE=json.loads((ROOT/"validation/master_v2/COMPARISON_SUMMARY.json").read_text())

def test_existing_real_repository_reports_are_no_go_not_automatically_promoted():
    report=evaluate_master_oos_readiness(BENCH,FIXTURE,{})
    assert report["status"]=="NO_GO_INSUFFICIENT_VERIFIED_MARKET_COHORT"
    assert report["passed"]==0
    assert report["checklist"]["real_qualified_cycle_count"] is False
    assert report["checklist"]["real_observation_comparison_not_synthetic"] is False
    assert report["live_ready_to_arm"] is False
    assert report["financial_order_submitted"] is False

def test_many_active_survivors_not_equal_signed_launches_or_holdout():
    cohort=dict(independently_verified_holdout_creator_count=1000,
                discovery_denominator_complete=True,
                inactive_failed_launches_included=False,
                signed_creation_receipts_verified=False)
    report=evaluate_master_oos_readiness(BENCH,FIXTURE,cohort)
    assert report["checklist"]["minimum_fifty_independent_verified_holdout_creators"] is False

def test_positive_synthetic_returns_never_validate_market_edge():
    cohort=dict(bootstrap_lower_bound_on_creator_clustered_net_delta_lamports=100000,
                net_advantage_over_reference_after_all_costs=True)
    report=evaluate_master_oos_readiness(BENCH,FIXTURE,cohort)
    assert report["checklist"]["positive_net_outofsample_lower_bound_master_vs_reference"] is True
    assert report["status"]=="NO_GO_INSUFFICIENT_VERIFIED_MARKET_COHORT"
    assert report["checklist"]["real_observation_comparison_not_synthetic"] is False

@pytest.mark.parametrize("value",[None,1,[],dict(foo=1)])
def test_wrong_evidence_schema_refused(value):
    with pytest.raises(ValueError):
        evaluate_master_oos_readiness(value,FIXTURE,{})

def test_missing_stress_scenarios_refuses_even_if_other_flags_injected():
    cohort=dict(qualified_holdout_scenarios=[[1,0],[1,250]])
    result=evaluate_master_oos_readiness(BENCH,FIXTURE,cohort)
    assert result["checklist"]["four_prespecified_fee_delay_stress_checks"] is False
