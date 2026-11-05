"""Offline regression for accepted/refused Helius read-only capture accounting.

No provider calls, credentials, wallets, signing, or financial execution.
"""
from bot.ops.render_readonly_service import Observer


def _safe_summary():
    return {
        "capture_status": "NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE",
        "financial_order_submitted": False,
        "live_ready_to_arm": False,
        "execution_verified": False,
        "trade_fills_simulated": 0,
        "crypto_signed_creation_transactions": 0,
        "selected_independent_signed_creators": 0,
        "supported_native_SOL_graphs": 0,
        "frozen_S1_decisions": 0,
    }


def test_refused_capture_does_not_count_as_accepted_signed_summary():
    secret = "fake_helius_key_do_not_publish"
    calls = []

    def runner(**kwargs):
        assert kwargs["api_key"] == secret
        calls.append(len(calls))
        if len(calls) == 2:
            raise RuntimeError("provider failed: " + secret)
        return _safe_summary()

    observer = Observer(
        env={"RUGGER_OBSERVATION_ENABLED": "1", "HELIUS_API_KEY": secret},
        runner=runner,
    )
    assert observer.capture_once() is True
    first = observer.snapshot()
    assert first["cycle_count"] == 1
    assert first["successful_capture_count"] == 1
    assert first["refused_capture_count"] == 0

    assert observer.capture_once() is False
    failed = observer.snapshot()
    assert failed["cycle_count"] == 2
    assert failed["successful_capture_count"] == 1
    assert failed["refused_capture_count"] == 1
    assert failed["observer_status"] == "CAPTURE_REFUSED"
    assert failed["last_summary"] is None
    assert secret not in str(failed)

    assert observer.capture_once() is True
    recovered = observer.snapshot()
    assert recovered["cycle_count"] == 3
    assert recovered["successful_capture_count"] == 2
    assert recovered["refused_capture_count"] == 1
    assert recovered["observer_status"] == "CAPTURE_COMPLETED_READ_ONLY"
    assert recovered["last_summary"]["trade_fills_simulated"] == 0
    assert secret not in str(recovered)
    assert len(calls) == 3


def test_disabled_and_unconfigured_observer_do_not_count_attempts():
    for env in ({}, {"RUGGER_OBSERVATION_ENABLED": "1"}):
        observer = Observer(env=env, runner=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("must never invoke provider")
        ))
        assert observer.capture_once() is False
        state = observer.snapshot()
        assert state["cycle_count"] == 0
        assert state["successful_capture_count"] == 0
        assert state["refused_capture_count"] == 0
        assert state["last_summary"] is None
