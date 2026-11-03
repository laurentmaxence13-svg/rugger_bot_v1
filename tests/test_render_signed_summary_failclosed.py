"""Fail-closed public Helius summary regression tests; offline, no sockets/RPC."""
import json

import pytest

from bot.ops.render_readonly_service import Observer, sanitize_public_summary


def clean_result():
    return {
        "financial_order_submitted": False,
        "live_ready_to_arm": False,
        "execution_verified": False,
        "trade_fills_simulated": 0,
        "qualified_economic_cycles": 0,
        "paper_portfolio_open_positions": 0,
        "paper_portfolio_closed_positions": 0,
        "exact_profitability_demonstrated": False,
        "capture_status": "TWO_CLOCK_MODEL_CAPTURE_COMPLETE_NOT_PROFITABILITY",
        "crypto_signed_creation_transactions": 2,
        "frozen_S1_decisions": 1,
        "actual_verification_rpc_calls_used": None,
        "extra_secret": "never-exposed",
    }


def test_safe_signed_source_summary_keeps_only_typed_public_facts():
    safe = sanitize_public_summary(clean_result())
    assert safe["crypto_signed_creation_transactions"] == 2
    assert safe["frozen_S1_decisions"] == 1
    assert safe["qualified_economic_cycles"] == 0
    assert safe["actual_verification_rpc_calls_used"] is None
    assert "extra_secret" not in safe
    assert "never-exposed" not in json.dumps(safe)


@pytest.mark.parametrize("field,value", [
    ("capture_status", "HELIUS_API_KEY=private-secret"),
    ("capture_status", "not-an-audited-source-status"),
    ("crypto_signed_creation_transactions", "private-secret"),
    ("frozen_S1_decisions", -1),
    ("frozen_S1_decisions", True),
    ("actual_verification_rpc_calls_used", {"api_key": "private-secret"}),
    ("trade_fills_simulated", False),  # bool == 0 in Python, but not a count
    ("qualified_economic_cycles", 1),
    ("paper_portfolio_open_positions", 1),
    ("paper_portfolio_closed_positions", 1),
    ("exact_profitability_demonstrated", True),
    ("financial_order_submitted", 0),
])
def test_malformed_or_false_economic_summary_is_refused(field, value):
    report = clean_result()
    report[field] = value
    with pytest.raises(ValueError):
        sanitize_public_summary(report)


def test_failed_capture_never_publishes_secret_or_fake_master_profitability():
    report = clean_result()
    report["capture_status"] = "private-secret"
    observer = Observer(
        env={"RUGGER_OBSERVATION_ENABLED": "1",
             "HELIUS_API_KEY": "fake-private-key"},
        runner=lambda **kwargs: report,
    )
    assert observer.capture_once() is False
    status = observer.snapshot()
    assert status["observer_status"] == "CAPTURE_REFUSED"
    assert status["last_summary"] is None
    assert status["last_safe_error_class"] == "ValueError"
    assert "private-secret" not in json.dumps(status)
    assert "fake-private-key" not in json.dumps(status)
    assert status["no_signing_or_order_submission"] is True
    assert status["live_trading_enabled"] is False
