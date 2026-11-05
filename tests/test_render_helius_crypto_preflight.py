"""No-network Render Ed25519 preflight regression tests.

Missing verifier must refuse the real signed-source path before Helius can run.
The separate injected test runner remains offline and unaffected.
"""
import json
import sys
from types import ModuleType

from bot.ops import render_readonly_service as service


def test_missing_ed25519_refuses_before_real_source_runner(monkeypatch):
    calls = []
    fake = ModuleType("bot.live.helius_signed_master_paper")
    fake.run_pipeline = lambda **kwargs: calls.append("NETWORK_WOULD_RUN")
    monkeypatch.setitem(sys.modules, fake.__name__, fake)

    def missing_crypto():
        raise ModuleNotFoundError("cryptography not installed")

    monkeypatch.setattr(service, "require_signed_source_ed25519", missing_crypto)
    observer = service.Observer(env={
        "RUGGER_OBSERVATION_ENABLED": "1",
        "HELIUS_API_KEY": "synthetic_key_for_offline_test_123456",
    })
    assert observer.capture_once() is False
    status = observer.snapshot()
    assert calls == []
    assert status["observer_status"] == "CAPTURE_REFUSED"
    assert status["last_safe_error_class"] == "ModuleNotFoundError"
    assert status["last_summary"] is None
    assert status["no_signing_or_order_submission"] is True
    assert status["live_trading_enabled"] is False
    assert "synthetic_key_for_offline_test" not in json.dumps(status)


def test_preflight_precedes_real_source_runner_when_available(monkeypatch):
    order = []
    fake = ModuleType("bot.live.helius_signed_master_paper")

    def fake_readonly_pipeline(**kwargs):
        order.append("signed_source_runner")
        assert kwargs["seconds"] == 30
        assert not kwargs["output_dir"].exists()
        return {
            "financial_order_submitted": False,
            "live_ready_to_arm": False,
            "execution_verified": False,
            "trade_fills_simulated": 0,
            "capture_status": "NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE",
            "crypto_signed_creation_transactions": 0,
            "frozen_S1_decisions": 0,
        }

    fake.run_pipeline = fake_readonly_pipeline
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(service, "require_signed_source_ed25519",
                        lambda: order.append("crypto_preflight"))
    observer = service.Observer(env={
        "RUGGER_OBSERVATION_ENABLED": "1",
        "HELIUS_API_KEY": "synthetic_key_for_offline_test_123456",
    })
    assert observer.capture_once() is True
    assert order == ["crypto_preflight", "signed_source_runner"]
    status = observer.snapshot()
    assert status["observer_status"] == "CAPTURE_COMPLETED_READ_ONLY"
    assert status["last_summary"]["trade_fills_simulated"] == 0
    assert status["last_summary"]["crypto_signed_creation_transactions"] == 0
    assert "synthetic_key_for_offline_test" not in json.dumps(status)
