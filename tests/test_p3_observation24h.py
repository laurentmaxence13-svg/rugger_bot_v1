"""Offline adversarial tests for 24-hour sampled PAPER source supervisor.

Never opens a socket or invokes a real provider. Test executors emulate
only local capture artifacts and must not imply real market profitability.
"""
import json
from pathlib import Path
import subprocess

import pytest

from bot.analyser.artifacts import atomic_write_json
from bot.p3.observation24h import (
    SCHEMA, WINDOWS, MAX_REQUESTS_PER_WINDOW, COMPARISON_GATE,
    preregistration,preflight,_window_files,verify_session,capture_window,
    aggregate,_run_local,_read_manifest,_digest)
from bot.p3.liquidity_smoke import new_smoke_plan
from bot.p3.store import CaptureStore


REV="b"*40
START=1_780_000_000_000


def test_preflight_never_claims_exact_24h_profitability():
    info=preflight(revision=REV)
    assert info["status_for_exact_master_profitability"]==COMPARISON_GATE
    assert len(info["missing_profitability_evidence"])>=7
    assert info["collection_24h_started"] is False
    assert info["provider_usage_billing_unverified"] is True
    plan=preregistration(start_ms=START,revision=REV)
    assert plan["deadline_at_ms"]-START==24*3600*1000
    assert plan["planned_windows"]==WINDOWS==96
    assert plan["max_requests_per_window"]==20
    assert plan["max_total_requests"]==960
    assert plan["live_ready_to_arm"] is False
    assert plan["economic_verdict"]==COMPARISON_GATE
    with pytest.raises(ValueError):
        preregistration(start_ms=START,revision=REV,max_total_requests=1921)
    with pytest.raises(ValueError):
        preregistration(start_ms=START,revision="not_a_commit")
    with pytest.raises(ValueError):
        preregistration(start_ms=START,revision=REV,max_total_requests=19)


def setup(tmp_path,budget=960):
    root=tmp_path/"observation"
    root.mkdir()
    plan=preregistration(start_ms=START,revision=REV,max_total_requests=budget)
    atomic_write_json(root/"session.json",plan)
    return root,plan


def fake_subprocess_with_good_artifacts(*,used=8,selected=0,stop=None):
    def execute(argv,*,env,timeout,capture_output,text,check):
        assert argv[1:3]==["-m","bot.p3.prospective_campaign"]
        assert argv[-1]=="--network"
        assert capture_output is True and text is True and check is False
        assert timeout==90
        assert env.get("RUGGER_NO_DOTENV")=="1"
        assert "HELIUS_API_KEY" not in env
        idx=argv.index("--plan")
        plan_path=Path(argv[idx+1])
        db_path=Path(argv[argv.index("--db")+1])
        report_path=Path(argv[argv.index("--output")+1])
        plan=json.loads(plan_path.read_text())
        assert plan["schema"]=="p3-prospective-launchlab-curve-phase-v1"
        with CaptureStore(db_path,clock_ms=lambda:START+1500) as db:
            db.append("checkpoint",received_at_ms=START,
                outcome="prospective_plan_registered",
                provenance="synthetic",
                payload={"plan_sha256":_digest(plan)})
            tail=db.verify_integrity()
        atomic_write_json(report_path,dict(
            source_revision=REV,plan_sha256=_digest(plan),tail_hash=tail,
            collection_closed=True,requests_used=used,
            stop_reason=stop,selected_corpus_size=selected,
            cases=[],frozen_actual_master_reference_candidates=0,
            shadow_master_action_counts={},shadow_reference_action_counts={},
            settled_positions=0,execution_verified=False,net_pnl_sol=None))
        return subprocess.CompletedProcess(argv,0)
    return execute


def test_capture_window_records_verified_budget_and_no_trading(tmp_path):
    root,p=setup(tmp_path)
    # A fabricated test journal without a frozen prefix must be a SOURCE_GAP,
    # never a full market capture with invented creator evidence.
    w=capture_window(root,p,0,run=fake_subprocess_with_good_artifacts(
        used=8,selected=0),now_ms=START+1000)
    assert w["state"]=="SOURCE_GAP" and w["requests_used"]==8
    assert w["request_usage_exact"] is True
    assert w["financial_order_submitted"] is False
    p["windows"].append(w);p["actual_requests_used"]=8
    assert verify_session(root,p)==8
    result=aggregate(root,p)
    assert result["window_counts"]["SOURCE_GAP"]==1
    assert result["total_requests_confirmed"]==8
    assert result["net_pnl_master_lamports"] is None
    assert result["master_minus_reference_net_lamports"] is None
    assert result["exact_profitability_determined"] is False
    with pytest.raises(ValueError,match="window_already_attempted"):
        capture_window(root,p,0,run=fake_subprocess_with_good_artifacts(),
                       now_ms=START+1000)


def test_artifact_tampering_and_wrong_revision_cannot_pass_resume(tmp_path):
    root,p=setup(tmp_path)
    w=capture_window(root,p,0,run=fake_subprocess_with_good_artifacts(used=3),
                     now_ms=START+1000)
    p["windows"]=[w];p["actual_requests_used"]=3
    assert verify_session(root,p)==3
    report=root/"windows"/"000"/"report.json"
    report.write_text(report.read_text()+"\n")
    with pytest.raises(ValueError,match="artifact_digest_mismatch"):
        verify_session(root,p)


def test_failed_or_timed_out_capture_charges_worst_case_20(tmp_path):
    root,p=setup(tmp_path)
    def timed_out(*a,**k):
        raise subprocess.TimeoutExpired("python",90)
    w=capture_window(root,p,0,run=timed_out,now_ms=START+1000)
    assert w["state"]=="INTERRUPTED"
    assert w["requests_used"]==MAX_REQUESTS_PER_WINDOW
    assert w["request_usage_exact"] is False
    p["windows"]=[w];p["actual_requests_used"]=20
    assert verify_session(root,p)==20
    summary=aggregate(root,p)
    assert summary["total_requests_confirmed"]==0
    assert summary["total_requests_or_failure_reserved_upper_bound"]==20
    assert summary["all_request_usage_exact"] is False


def test_fail_closed_when_report_falsifies_trade_or_budget(tmp_path):
    root,p=setup(tmp_path)
    def dishonest(argv,**kwargs):
        valid=fake_subprocess_with_good_artifacts(used=4,selected=2)
        result=valid(argv,**kwargs)
        report=Path(argv[argv.index("--output")+1])
        v=json.loads(report.read_text())
        v["settled_positions"]=1
        atomic_write_json(report,v)
        return result
    with pytest.raises(ValueError,match="provider_capture_or_report_integrity_failure"):
        capture_window(root,p,0,run=dishonest,now_ms=START+1000)


def test_no_backfill_on_resume_after_crash_or_prior_source_window(tmp_path,monkeypatch):
    monkeypatch.setattr("bot.p3.observation24h.subprocess.check_output",
                        lambda *a,**k: REV)
    root,p=setup(tmp_path)
    _,plan_path,db_path,report_path=_window_files(root,0)
    plan_path.parent.mkdir(parents=True,exist_ok=False)
    plan_path.write_text("{}")
    calls=[]
    def fake_execute(r,m,i,*,now_ms):
        calls.append(i)
        return dict(index=i,state="INTERRUPTED",requests_used=20,
            request_usage_exact=False)
    current=[START/1000]
    result=_run_local(root,resume=True,max_total_requests=20,
        revision=REV,clock=lambda:current[0],sleep=lambda t:None,
        execute=fake_execute)
    assert calls==[]
    assert result["window_counts"]["INTERRUPTED"]==1
    assert result["total_requests_or_failure_reserved_upper_bound"]==20
    assert (root/"windows"/"000"/"plan.json").read_text()=="{}"
    p=_read_manifest(root)
    assert p["status"]=="REQUEST_BUDGET_EXHAUSTED"
    assert verify_session(root,p)==20


def test_session_directory_symlink_and_reused_capture_refused(tmp_path):
    root,p=setup(tmp_path)
    target=tmp_path/"link"
    try:
        target.symlink_to(root,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip("symlink creation unavailable on this runner")
    with pytest.raises(ValueError,match="symlink_session_root_refused"):
        verify_session(target,p)


def test_missing_windows_do_not_mean_zero_losses(tmp_path):
    root,p=setup(tmp_path)
    p["windows"]=[dict(index=0,state="MISSED",requests_used=0,
                        planned_at_ms=START,observed_at_ms=START+900001)]
    result=aggregate(root,p)
    assert result["window_counts"]["MISSED"]==1
    assert result["net_pnl_reference_lamports"] is None
    assert result["master_minus_reference_net_lamports"] is None
    assert result["creator_identity_independence_certified"] is False
    assert result["sampled_not_continuous"] is True
