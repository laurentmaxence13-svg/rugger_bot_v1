"""Offline signed Helius stage/provenance consistency; never contact providers.

A capture stage must agree with the bounded source graph counts. Signed
creation *transactions* can legitimately contain multiple independent launches.
"""
import json

import pytest

from bot.ops.render_readonly_service import Observer, sanitize_public_summary


def _summary():
    return {
        "financial_order_submitted": False,
        "execution_verified": False,
        "live_ready_to_arm": False,
        "exact_profitability_demonstrated": False,
        "trade_fills_simulated": 0,
        "qualified_economic_cycles": 0,
        "capture_status": "TWO_CLOCK_MODEL_CAPTURE_COMPLETE_NOT_PROFITABILITY",
        "log_events_retained": 20,
        "crypto_signed_creation_transactions": 1,
        "selected_independent_signed_creators": 2,
        "supported_native_SOL_graphs": 2,
        "frozen_S1_decisions": 2,
        "actual_signed_policy_frozen_paper_cases": 2,
    }


def test_valid_multi_launch_signed_transaction_keeps_two_source_graphs():
    report = _summary()
    assert sanitize_public_summary(report) == report


def test_empty_selected_cohort_may_still_have_inspected_signed_transactions():
    report = _summary()
    report.update(capture_status="NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE",
                  selected_independent_signed_creators=0,
                  supported_native_SOL_graphs=0, frozen_S1_decisions=0,
                  actual_signed_policy_frozen_paper_cases=0)
    # Some signed transactions may have no qualifying independently selected
    # creator; never conflate transaction count and creator count.
    assert sanitize_public_summary(report) == report


def test_selected_creators_with_no_supported_native_sol_graphs_is_valid():
    report = _summary()
    report.update(capture_status="NO_VALID_POOL_ACCOUNT_GRAPHS",
                  supported_native_SOL_graphs=0, frozen_S1_decisions=0,
                  actual_signed_policy_frozen_paper_cases=0)
    assert sanitize_public_summary(report) == report


@pytest.mark.parametrize(("updates", "error"), [
    ({"supported_native_SOL_graphs": 3}, "inconsistent_signed_source_evidence"),
    ({"capture_status": "NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE"},
     "inconsistent_signed_capture_stage"),
    ({"capture_status": "NO_VALID_POOL_ACCOUNT_GRAPHS"},
     "inconsistent_signed_capture_stage"),
    ({"capture_status": "NO_VALID_POOL_ACCOUNT_GRAPHS",
      "selected_independent_signed_creators": 0,
      "supported_native_SOL_graphs": 0, "frozen_S1_decisions": 0,
      "actual_signed_policy_frozen_paper_cases": 0},
     "inconsistent_signed_capture_stage"),
    ({"supported_native_SOL_graphs": 0, "frozen_S1_decisions": 0,
      "actual_signed_policy_frozen_paper_cases": 0},
     "inconsistent_signed_capture_stage"),
])
def test_contradictory_stage_or_graph_count_is_rejected(updates, error):
    report = _summary()
    report.update(updates)
    with pytest.raises(ValueError, match=error):
        sanitize_public_summary(report)


def test_refused_stage_never_exposes_key_or_false_signed_evidence():
    secret = "fake_secret_for_offline_stage_test_123456"
    report = _summary()
    report["capture_status"] = "NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE"
    observer = Observer(env={"RUGGER_OBSERVATION_ENABLED": "1",
                             "HELIUS_API_KEY": secret},
                        runner=lambda **kwargs: report)
    assert observer.capture_once() is False
    snapshot = observer.snapshot()
    assert snapshot["observer_status"] == "CAPTURE_REFUSED"
    assert snapshot["last_summary"] is None
    assert snapshot["last_safe_error_class"] == "ValueError"
    assert snapshot["no_signing_or_order_submission"] is True
    assert secret not in json.dumps(snapshot)
