"""No-network freshness tests for signed Helius evidence shown in Rugger Wallet.

A signed source capture is historical, not perpetual current market data.
DexScreener's experimental PAPER engine is never involved.
"""
from bot.ops.render_readonly_service import Observer


ENV = {
    "RUGGER_OBSERVATION_ENABLED": "1",
    "HELIUS_API_KEY": "offline_fake_key_for_unit_tests_12345",
}


def _valid_summary(**_kwargs):
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


def test_signed_evidence_expires_after_next_bounded_observation_window():
    now = [1_800_000_000.0]
    obj = Observer(env=ENV, runner=_valid_summary, clock=lambda: now[0])
    assert obj.snapshot()["signed_evidence_fresh"] is False
    assert obj.capture_once() is True

    accepted = obj.snapshot()
    assert accepted["signed_evidence_fresh"] is True
    assert accepted["last_summary"]["crypto_signed_creation_transactions"] == 0
    assert accepted["successful_capture_count"] == 1

    # Default interval 300s plus capture budget 30s, inclusive.
    now[0] += 330
    assert obj.snapshot()["signed_evidence_fresh"] is True
    now[0] += 0.002
    stale = obj.snapshot()
    assert stale["signed_evidence_fresh"] is False
    assert stale["last_summary"] is None
    assert stale["observer_status"] == "CAPTURE_COMPLETED_READ_ONLY"
    assert stale["cycle_count"] == 1
    assert stale["successful_capture_count"] == 1
    assert stale["no_signing_or_order_submission"] is True
    assert "offline_fake_key" not in str(stale)

    # Time moving backward must never revalidate old evidence.
    now[0] = 1_799_999_999.0
    assert obj.snapshot()["signed_evidence_fresh"] is False
    assert obj.snapshot()["last_summary"] is None


def test_prior_capture_is_hidden_during_next_capture_and_after_refusal():
    now = [1_800_000_000.0]
    observed_during_capture = []
    fail = [False]
    obj = None

    def runner(**kwargs):
        observed_during_capture.append(obj.snapshot())
        if fail[0]:
            raise RuntimeError("HELIUS_API_KEY=offline_fake_key_for_unit_tests_12345")
        return _valid_summary(**kwargs)

    obj = Observer(env=ENV, runner=runner, clock=lambda: now[0])
    assert obj.capture_once() is True
    assert obj.snapshot()["signed_evidence_fresh"] is True
    now[0] += 1
    fail[0] = True
    assert obj.capture_once() is False

    during = observed_during_capture[-1]
    assert during["observer_status"] == "CAPTURING_HELIUS_READ_ONLY"
    assert during["signed_evidence_fresh"] is False
    assert during["last_summary"] is None

    refused = obj.snapshot()
    assert refused["observer_status"] == "CAPTURE_REFUSED"
    assert refused["signed_evidence_fresh"] is False
    assert refused["last_summary"] is None
    assert refused["successful_capture_count"] == 1
    assert refused["refused_capture_count"] == 1
    assert "offline_fake_key" not in str(refused)

    now[0] += 1
    fail[0] = False
    assert obj.capture_once() is True
    recovered = obj.snapshot()
    assert recovered["signed_evidence_fresh"] is True
    assert recovered["last_summary"] is not None
    assert recovered["successful_capture_count"] == 2
    assert recovered["refused_capture_count"] == 1


def test_disabled_observer_never_publishes_fresh_evidence_or_calls_runner():
    calls = []
    obj = Observer(env={}, runner=lambda **kw: calls.append(kw))
    assert obj.capture_once() is False
    snapshot = obj.snapshot()
    assert snapshot["observer_status"] == "DISABLED_EXPLICITLY"
    assert snapshot["signed_evidence_fresh"] is False
    assert snapshot["last_summary"] is None
    assert calls == []
