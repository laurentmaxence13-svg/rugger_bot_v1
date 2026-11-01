"""Bounded full-horizon Master capture: validated source sample, never a trade."""
import pytest

from bot.p3.certification import _encode
from bot.live.helius_ws_forward_paper import ReadOnlyLogAudit
from bot.live.helius_ws_signed_creation_probe import _verify_capture
from bot.live.helius_horizon_sampler import (
    select_horizon_events,capture_report,observe_horizon,RAW_CAP)


def sample(count=140, *, every_hint=9, failed=0):
    audit=ReadOnlyLogAudit(7,200)
    for i in range(count):
        signature=_encode(bytes([i+1])*64)
        logs=["Program log: Instruction: InitializeV2"] if i%every_hint==0 else [
            "Program log: Instruction: BuyExactIn"]
        message=dict(jsonrpc="2.0",method="logsNotification",
            params=dict(subscription=7,result=dict(context=dict(slot=100+i),
                value=dict(signature=signature,err={"failed":True} if i<failed else None,
                           logs=logs))))
        assert audit.accept(message,received_mono_ns=1000+i*10,
                            parsed_mono_ns=1001+i*10,
                            received_utc_ns=2000+i*10)
    return audit.events


def test_horizon_sample_uses_late_source_events_not_just_first_100():
    events=sample()
    selected=select_horizon_events(events,60)
    assert len(selected)==60
    assert any(e["slot"]>200 for e in selected)
    assert len({e["signature"] for e in selected})==60
    assert [e["slot"] for e in selected]==sorted(e["slot"] for e in selected)
    assert sum(e["untrusted_initialize_log_hint"] for e in selected)>0


def test_full_horizon_capture_verifies_exact_retained_hash_and_denominator():
    events=sample()
    chosen=select_horizon_events(events,40)
    report=capture_report(chosen,events,handshake_ms=70,
        duration_ms=30000,raw_cap_reached=False,
        subscription=7,duplicates=2,invalid=3)
    assert report["events_received_unique"]==40
    assert report["captured_raw_unique_notifications"]==140
    assert report["unretained_successful_notifications"]==100
    assert report["unique_valid_notifications_seen"]==140
    assert report["retention_policy"].startswith("whole_horizon")
    assert report["financial_order_submitted"] is False
    assert report["live_ready_to_arm"] is False
    assert report["whole_horizon_sample_not_complete_creation_universe"] is True
    _verify_capture(report,chosen)


def test_failed_raw_events_remain_in_denominator_without_becoming_trades():
    events=sample(50,failed=5)
    chosen=select_horizon_events(events,25)
    assert all(not e["on_chain_transaction_failed"] for e in chosen)
    report=capture_report(chosen,events,handshake_ms=10,
        duration_ms=20000,raw_cap_reached=False,
        subscription=7,duplicates=0,invalid=0)
    assert report["onchain_failed_transactions_in_notifications"]==5
    assert report["discarded_failed_notifications"]==5
    assert report["unretained_successful_notifications"]==45-len(chosen)
    _verify_capture(report,chosen)


def test_tamper_sample_or_invalid_inputs_fail_closed():
    events=sample(3)
    with pytest.raises(ValueError):
        select_horizon_events(events,101)
    with pytest.raises(ValueError):
        select_horizon_events(events+events[:1],2)
    chosen=select_horizon_events(events,2)
    report=capture_report(chosen,events,handshake_ms=0,
        duration_ms=30000,raw_cap_reached=False,
        subscription=7,duplicates=0,invalid=0)
    chosen[0]["slot"]+=1
    with pytest.raises(ValueError,match="hash_chain"):
        _verify_capture(report,chosen)


def test_readonly_horizon_refuses_invalid_secret_without_network():
    import asyncio
    with pytest.raises(ValueError,match="bounded_readonly_horizon_required"):
        asyncio.run(observe_horizon(30,100,""))
    with pytest.raises(ValueError,match="bounded_readonly_horizon_required"):
        asyncio.run(observe_horizon(30,101,"a"*24))
