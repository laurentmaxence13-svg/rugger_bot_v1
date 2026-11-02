"""Offline fail-closed evidence arithmetic for the public signed Helius status.

The real bounded observer retains at most 100 log events and has distinct
verification (10) and bank (5) RPC caps. DexScreener PAPER is not a source.
"""
import json

import pytest

from bot.ops.render_readonly_service import Observer, sanitize_public_summary


def _bounded_summary():
    return {
        "financial_order_submitted": False,
        "execution_verified": False,
        "live_ready_to_arm": False,
        "exact_profitability_demonstrated": False,
        "trade_fills_simulated": 0,
        "qualified_economic_cycles": 0,
        "capture_status": "S1_DECISIONS_FROZEN_BEFORE_S2",
        "log_events_retained": 100,
        "crypto_signed_creation_transactions": 4,
        "selected_independent_signed_creators": 3,
        "supported_native_SOL_graphs": 2,
        "frozen_S1_decisions": 1,
        "actual_signed_policy_frozen_paper_cases": 1,
        "actual_verification_rpc_calls_used": 10,
        "actual_bank_rpc_calls_used": 5,
    }


def test_bounded_signed_source_summary_accepts_valid_limits():
    expected = _bounded_summary()
    assert sanitize_public_summary(expected) == expected


@pytest.mark.parametrize(("key", "bad_value"), [
    ("log_events_retained", 101),
    ("actual_verification_rpc_calls_used", 11),
    ("actual_bank_rpc_calls_used", 6),
    ("crypto_signed_creation_transactions", 101),
    ("selected_independent_signed_creators", 5),
    ("frozen_S1_decisions", 3),
    ("actual_signed_policy_frozen_paper_cases", 2),
])
def test_impossible_signed_source_evidence_refused_before_publication(key, bad_value):
    summary = _bounded_summary()
    summary[key] = bad_value
    with pytest.raises(ValueError, match="impossible_signed_source_counter|inconsistent_signed_source_evidence"):
        sanitize_public_summary(summary)


def test_malformed_source_counters_do_not_leak_secret_or_report_success():
    secret = "offline_test_helius_key_never_publish_123456"
    invalid = _bounded_summary()
    invalid["actual_verification_rpc_calls_used"] = 999
    observer = Observer(
        env={"RUGGER_OBSERVATION_ENABLED": "1", "HELIUS_API_KEY": secret},
        runner=lambda **kwargs: invalid,
    )
    assert observer.capture_once() is False
    status = observer.snapshot()
    assert status["observer_status"] == "CAPTURE_REFUSED"
    assert status["last_summary"] is None
    assert status["no_signing_or_order_submission"] is True
    assert status["live_trading_enabled"] is False
    assert secret not in json.dumps(status)
