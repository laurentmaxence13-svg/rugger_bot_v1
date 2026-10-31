"""Offline invariants for the zero-order mainnet WebSocket sensor."""
import asyncio
import json

import pytest

from bot.live import helius_ws_forward_paper as mod
from bot.p3.certification import PROGRAM

SIG_A = "2" * 80
SIG_B = "3" * 80


def message(signature=SIG_A, *, slot=100, subscription=7, error=None, logs=None):
    return dict(jsonrpc="2.0", method="logsNotification",
                params=dict(subscription=subscription,
                    result=dict(context=dict(slot=slot),
                        value=dict(signature=signature, err=error,
                                   logs=["Program log: hello"] if logs is None else logs))))


def test_subscription_exactly_launchlab_logs_only():
    value = mod.subscribe_request()
    assert value["method"] == "logsSubscribe"
    assert value["params"] == [{"mentions": [PROGRAM]}, {"commitment": "confirmed"}]
    assert set(value.keys()) == {"jsonrpc", "id", "method", "params"}
    assert mod.parse_subscription_ack(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": 7})) == 7


@pytest.mark.parametrize("payload", [
    {}, {"jsonrpc": "2.0", "id": 1, "result": "7"},
    {"jsonrpc": "2.0", "id": 1, "result": -1},
    {"jsonrpc": "2.0", "id": 9, "result": 7},
    {"jsonrpc": "2.0", "id": 1, "error": {"code": 429}},
])
def test_bad_subscription_ack_refused(payload):
    with pytest.raises(ValueError):
        mod.parse_subscription_ack(payload)


def test_dedup_failure_and_invalid_notifications_are_not_invented_trades():
    audit = mod.ReadOnlyLogAudit(7, 10)
    assert audit.accept(message(), received_mono_ns=100,
                        parsed_mono_ns=101, received_utc_ns=1000)
    assert not audit.accept(json.dumps(message()), received_mono_ns=120,
                            parsed_mono_ns=121, received_utc_ns=1020)
    assert audit.accept(message(SIG_B, slot=102, error={"InstructionError": []}),
                        received_mono_ns=200, parsed_mono_ns=201,
                        received_utc_ns=1100)
    assert not audit.accept(message("bad!", slot=103), received_mono_ns=300,
                            parsed_mono_ns=301, received_utc_ns=1200)
    assert not audit.accept(message(SIG_A, subscription=9),
                            received_mono_ns=350, parsed_mono_ns=351,
                            received_utc_ns=1300)
    report = audit.report(duration_ms=2000, handshake_ms=90)
    assert report["events_received_unique"] == 2
    assert report["duplicates_ignored"] == 1
    assert report["invalid_notifications"] == 2
    assert report["onchain_failed_transactions_in_notifications"] == 1
    assert report["economically_qualified_cycles"] == 0
    assert report["independent_verified_creators"] == 0
    assert report["decision_to_execution_latency_ms"] is None
    assert report["chain_event_to_reception_latency_ms"] is None
    assert report["execution_verified"] is False
    assert report["live_ready_to_arm"] is False
    assert len(report["signature_ledger_sha256"]) == 64
    assert all(item["filled"] is False for item in audit.events)
    assert "UNCLASSIFIED" in audit.events[0]["classification"]


def test_no_events_is_not_an_error_or_proof_of_liquidity():
    report = mod.ReadOnlyLogAudit(5, 1).report(duration_ms=3000,
                                                handshake_ms=500)
    assert report["status"] == "NO_LOGS_OBSERVED"
    assert report["local_parse_p95_ms"] is None
    assert report["master_edge_validated"] is False


def test_malformed_timestamps_and_event_cap_refused():
    audit = mod.ReadOnlyLogAudit(7, 1)
    with pytest.raises(ValueError):
        audit.accept(message(), received_mono_ns=200,
                     parsed_mono_ns=100, received_utc_ns=0)
    audit.accept(message(), received_mono_ns=200,
                 parsed_mono_ns=201, received_utc_ns=1)
    with pytest.raises(ValueError, match="bounded_event_cap"):
        audit.accept(message(SIG_B), received_mono_ns=202,
                     parsed_mono_ns=203, received_utc_ns=2)
    assert len(audit.events) == 1


def test_bad_or_missing_provider_secret_never_connects():
    with pytest.raises(ValueError, match="invalid_provider_secret"):
        asyncio.run(mod.observe(10, 10, ""))
    with pytest.raises(ValueError, match="invalid_duration"):
        asyncio.run(mod.observe(1, 10, "not-a-real-key"))
    with pytest.raises(ValueError, match="invalid_maximum"):
        asyncio.run(mod.observe(10, 0, "not-a-real-key"))


def test_no_live_financial_execution_calls_in_subscribe_contract():
    serialized = json.dumps(mod.subscribe_request())
    assert "sendTransaction" not in serialized
    assert "simulateTransaction" not in serialized
    assert "wallet" not in serialized


def test_success_only_retention_preserves_failed_denominator_and_hash():
    from bot.p3.certification import _encode
    valid_sig=_encode(bytes([8])*64)
    a=mod.ReadOnlyLogAudit(7,2,successful_only=True)
    assert not a.accept(message(SIG_A,slot=100,error={"InstructionError":[0]}),
                        received_mono_ns=100,parsed_mono_ns=101,received_utc_ns=1000)
    assert not a.accept(message(SIG_A,slot=100,error={"InstructionError":[0]}),
                        received_mono_ns=102,parsed_mono_ns=103,received_utc_ns=1001)
    assert a.accept(message(valid_sig,slot=101,logs=["Program log: Instruction: InitializeV2"]),
                    received_mono_ns=104,parsed_mono_ns=105,received_utc_ns=1002)
    r=a.report(duration_ms=1000,handshake_ms=10)
    assert r["events_received_unique"]==1
    assert r["unique_valid_notifications_seen"]==2
    assert r["discarded_failed_notifications"]==1
    assert r["onchain_failed_transactions_in_notifications"]==1
    assert r["duplicates_ignored"]==1
    assert r["retention_policy"]=="successful_only_with_failed_denominator"
    assert len(r["signature_ledger_sha256"])==64
    assert a.events[0]["signature"]==valid_sig
    assert a.events[0]["untrusted_initialize_log_hint"] is True
    from bot.live.helius_ws_signed_creation_probe import _verify_capture
    _verify_capture(r,a.events)
    assert r["financial_order_submitted"] is False


def test_default_capture_still_retains_failed_notification():
    a=mod.ReadOnlyLogAudit(7,2)
    assert a.accept(message(SIG_A,error={"InstructionError":[0]}),
                    received_mono_ns=100,parsed_mono_ns=101,received_utc_ns=1000)
    r=a.report(duration_ms=1000,handshake_ms=10)
    assert r["retention_policy"]=="all_notifications"
    assert r["discarded_failed_notifications"]==0
    assert r["onchain_failed_transactions_in_notifications"]==1
