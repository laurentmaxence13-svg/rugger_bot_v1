"""Real-session recovery never silently resets source clocks or RPC budget."""
import hashlib
import json

import pytest

from bot.analyser.artifacts import atomic_write_json
from bot.live.helius_rolling_signed_paper import (
    _recover_session,_check_manifest,_save_new,digest,session_plan)


def original(tmp_path,*,verified=True,expired=False):
    root=tmp_path/"original"
    chunks=root/"chunks"/"000000"
    chunks.mkdir(parents=True)
    manifest=session_plan(duration_seconds=86400,rpc_call_cap=3000,
        start_ms=1000)
    log=dict(report=dict(signature_ledger_sha256="b"*64),
        events=[dict(signature="a"*86,reception_utc_ns=1_000_000_000)])
    source_sha=_save_new(chunks/"received.json",log)
    row=dict(index=0,state="INTERRUPTED",source_sha256=source_sha,
        source_event_count=1,rpc_calls_reserved=15)
    if verified:
        summary=dict(financial_order_submitted=False,execution_verified=False,
            capture_status="NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE",
            selected_independent_signed_creators=0,frozen_S1_decisions=0,
            supported_native_SOL_graphs=0,non_native_SOL_pool_count=0,
            source_market_refusal_reason_counts={},
            actual_verification_rpc_calls_used=9,
            actual_bank_rpc_calls_used=0)
        (chunks/"verified").mkdir()
        atomic_write_json(chunks/"verified"/"summary.json",summary,
            sort_keys=True,allow_nan=False)
        row.update(state="VERIFIED",rpc_calls_reserved=9,
            verified_summary_sha256=digest(summary))
    manifest["windows"].append(row)
    manifest["rpc_used_or_reserved_upper_bound"]=row["rpc_calls_reserved"]
    manifest["events_retained"]=1
    atomic_write_json(root/"manifest.json",manifest,
        sort_keys=True,allow_nan=False)
    return root


def test_restore_verified_original_keeps_events_budget_and_visible_gap(tmp_path):
    root=original(tmp_path)
    recovered,seen,tally=_recover_session(root,
        duration_seconds=86400,rpc_call_cap=3000,restart_at_ms=2000)
    assert recovered["status"]=="RESUMED_WITH_GAP"
    assert len(seen)==1 and "a"*86 in seen
    assert recovered["events_retained"]==1
    assert recovered["rpc_used_or_reserved_upper_bound"]==9
    assert tally["verification_rpc_calls"]==9
    assert tally["source_websocket_gaps"]==1
    assert recovered["websocket_gaps"][-1]["unknown_missed_transactions"] is True
    assert recovered["end_ms"]==86401000
    assert _check_manifest(root,recovered)==9


def test_crash_mid_verification_preserves_max_rpc_reservation(tmp_path):
    root=original(tmp_path,verified=False)
    recovered,seen,tally=_recover_session(root,
        duration_seconds=86400,rpc_call_cap=3000,restart_at_ms=3000)
    assert recovered["windows"][0]["state"]=="SOURCE_REFUSED"
    assert recovered["rpc_used_or_reserved_upper_bound"]==15
    assert tally["verification_rpc_calls"]==0
    assert tally["source_refusals"]==1
    assert tally["source_websocket_gaps"]==1
    assert recovered["windows"][0]["error_class"]=="UNCERTAIN_CRASH_DURING_VERIFICATION"


def test_recovery_rejects_tampered_summary_wrong_quota_or_reset_horizon(tmp_path):
    root=original(tmp_path)
    proof=root/"chunks"/"000000"/"verified"/"summary.json"
    data=json.loads(proof.read_text())
    data["capture_status"]="FALSE_PROFITABILITY"
    proof.write_text(json.dumps(data))
    with pytest.raises(ValueError,match="summary_tampered"):
        _recover_session(root,duration_seconds=86400,
            rpc_call_cap=3000,restart_at_ms=2000)
    assert json.loads((root/"manifest.json").read_text())["status"]=="REGISTERED"
    atomic_write_json(proof,dict(data,capture_status=
        "NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE"),sort_keys=True,allow_nan=False)
    with pytest.raises(ValueError,match="resume_original_horizon"):
        _recover_session(root,duration_seconds=1000,
            rpc_call_cap=3000,restart_at_ms=2000)
    with pytest.raises(ValueError,match="resume_original_horizon"):
        _recover_session(root,duration_seconds=86400,
            rpc_call_cap=3100,restart_at_ms=2000)
    with pytest.raises(ValueError,match="resume_original_horizon"):
        _recover_session(root,duration_seconds=86400,
            rpc_call_cap=3000,restart_at_ms=86401000)


def test_completed_sessions_never_restarted_as_new_profitability_study(tmp_path):
    root=original(tmp_path)
    manifest=json.loads((root/"manifest.json").read_text())
    manifest["status"]="COMPLETED_WITH_GAPS"
    atomic_write_json(root/"manifest.json",manifest,
        sort_keys=True,allow_nan=False)
    with pytest.raises(ValueError,match="resume_original_horizon"):
        _recover_session(root,duration_seconds=86400,
            rpc_call_cap=3000,restart_at_ms=2000)
