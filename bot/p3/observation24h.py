"""Bounded, resumable 24h LaunchLab PAPER *sampling* supervisor (NO LIVE).

Runs 96 scheduled independent 60s maximum curve-phase snapshots at 15-minute
intervals, NOT a continuous tick/trade feed. Every window has a separate
preregistered source revision, immutable capture and report. Missed windows
stay missed; failures are recorded without backfilling or best-case selection.

This is OBSERVATION ONLY. Current collectors do NOT authenticate every
creator, supply continuous executable entry/exit quotes, follow all migrations
or measure complete net Master/reference profitability. Nothing can turn the
output into verified profit. No wallet, signing, orders, paid API calls initiated.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from bot.analyser.artifacts import atomic_write_json
from bot.p3.liquidity_smoke import new_smoke_plan
from bot.p3.prospective_campaign import CURVE_PHASE_FIXED,validate_plan
from bot.p3.store import CaptureStore

HOURS=24
INTERVAL_SECONDS=900
WINDOWS=HOURS*3600//INTERVAL_SECONDS
MAX_REQUESTS_PER_WINDOW=20
MAX_TOTAL_REQUESTS=1920
CHILD_TIMEOUT_SECONDS=90
SCHEMA="p3-24h-sampled-observation-supervisor-v1"
COMPARISON_GATE="NOT_READY_VERIFIED_NET_PROFITABILITY"


def _digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preregistration(*,start_ms,revision,max_total_requests=960):
    if (type(start_ms) is not int or start_ms<=0
            or type(revision) is not str or re.fullmatch(r"[0-9a-f]{40}",revision) is None
            or type(max_total_requests) is not int
            or not MAX_REQUESTS_PER_WINDOW<=max_total_requests<=MAX_TOTAL_REQUESTS):
        raise ValueError("invalid_immutable_24h_protocol")
    return dict(schema=SCHEMA,start_at_ms=start_ms,
        deadline_at_ms=start_ms+HOURS*3600*1000,
        interval_seconds=INTERVAL_SECONDS,planned_windows=WINDOWS,
        max_requests_per_window=MAX_REQUESTS_PER_WINDOW,
        max_total_requests=max_total_requests,source_revision=revision,
        p3_plan_schema=CURVE_PHASE_FIXED["schema"],
        market_coverage="sampled_pools_not_continuous_or_complete",
        pnl_scope="no_complete_costed_executable_master_reference_cycles",
        economic_verdict=COMPARISON_GATE,
        source_signed_creator_verified=False,
        true_source_trade_tape_complete=False,
        migration_cpmm_quote_tracking_verified=False,
        executable_full_lot_quotes_verified=False,
        net_cost_attribution_verified=False,
        statistically_independent_holdout_verified=False,
        extra_provider_charges_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        windows=[],status="REGISTERED",actual_requests_used=0)


def preflight(*,revision,max_total_requests=960):
    p=preregistration(start_ms=1,revision=revision,
                       max_total_requests=max_total_requests)
    return dict(schema="p3-24h-observation-readiness-v1",
        technical_collector="CURVE_SNAPSHOT_MODE_AVAILABLE",
        observation_type="96_periodic_two_clock_S1_S2_samples_not_continuous_monitoring",
        observation_window_hours=HOURS,interval_minutes=INTERVAL_SECONDS//60,
        max_total_public_requests=max_total_requests,
        observed_source_provenance="RPC snapshots_hashchained_local_not_independent_cryptographic_attestation",
        missing_profitability_evidence=[
            "finalized_independent_signed_creator_coverage",
            "causal_trade_features_for_both_strategies",
            "phase_correct_executable_full_lot_entry_and_exit",
            "migration_to_CPMM_and_continuous_exit_pricing",
            "complete_network_priority_ATA_and_failed_attempt_costs",
            "realistic_latency_order_fill_slippage_and_open_inventory",
            "creator_disjoint_out_of_sample_statistical_power"],
        status_for_exact_master_profitability=COMPARISON_GATE,
        no_live_trades=True,provider_usage_billing_unverified=True,
        collection_24h_started=False,source_revision=p["source_revision"])


def _root_guard(root):
    root=Path(root)
    if root.is_symlink():
        raise ValueError("symlink_session_root_refused")
    if root.exists() and not root.is_dir():
        raise ValueError("session_path_not_directory")
    if root.exists() and any(p.is_symlink() for p in root.iterdir()):
        raise ValueError("symlink_in_session_refused")
    return root


def _read_manifest(root):
    m=root/"session.json"
    if not m.is_file() or m.is_symlink() or m.stat().st_size>1048576:
        raise ValueError("missing_or_untrusted_24h_manifest")
    value=json.loads(m.read_text(encoding="utf-8"))
    if (type(value) is not dict or value.get("schema")!=SCHEMA
            or type(value.get("windows")) is not list
            or type(value.get("start_at_ms")) is not int
            or value.get("planned_windows")!=WINDOWS
            or value.get("interval_seconds")!=INTERVAL_SECONDS
            or value.get("economic_verdict")!=COMPARISON_GATE
            or value.get("financial_order_submitted") is not False
            or value.get("live_ready_to_arm") is not False):
        raise ValueError("tampered_or_invalid_24h_manifest")
    return value


def _validate_window(root,w,revision):
    index=w.get("index")
    if type(index) is not int or not 0<=index<WINDOWS:
        raise ValueError("invalid_window_index")
    state=w.get("state")
    if state not in ("CAPTURED","SOURCE_GAP","INTERRUPTED","MISSED"):
        raise ValueError("invalid_window_state")
    if state not in ("CAPTURED","SOURCE_GAP"):
        if (state=="MISSED" and w.get("requests_used")!=0
                or state=="INTERRUPTED" and w.get("requests_used")!=MAX_REQUESTS_PER_WINDOW):
            raise ValueError("interrupted_request_usage_must_reserve_worst_case")
        return
    folder=root/"windows"/f"{index:03d}"
    if folder.is_symlink():
        raise ValueError("symlink_window_directory_refused")
    plan_path=folder/"plan.json";db_path=folder/"capture.sqlite";report_path=folder/"report.json"
    if any(p.is_symlink() or not p.is_file() for p in (plan_path,db_path,report_path)):
        raise ValueError("missing_or_symlinked_capture_files")
    if (_file_sha(plan_path)!=w.get("plan_sha256")
            or _file_sha(db_path)!=w.get("db_sha256")
            or _file_sha(report_path)!=w.get("report_sha256")):
        raise ValueError("window_artifact_digest_mismatch")
    plan=json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("source_revision")!=revision or plan.get("schema")!=CURVE_PHASE_FIXED["schema"]:
        raise ValueError("window_source_revision_or_protocol_mismatch")
    validate_plan(plan)
    report=json.loads(report_path.read_text(encoding="utf-8"))
    model_path=folder/"conditional_models.json"
    if w.get("curve_model_sha256") is not None:
        if (model_path.is_symlink() or not model_path.is_file()
                or _file_sha(model_path)!=w["curve_model_sha256"]):
            raise ValueError("conditional_curve_model_artifact_tampered")
    with CaptureStore(db_path,readonly=True) as store:
        tail=store.verify_integrity()
    if w.get("curve_model_sha256") is not None:
        research=json.loads(model_path.read_text(encoding="utf-8"))
        if (research.get("verified_tail_sha256")!=tail
                or research.get("economic_profitability_verified") is not False
                or research.get("realized_net_pnl_lamports") is not None
                or research.get("qualified_executable_cycles")!=0):
            raise ValueError("conditional_model_wrong_provenance")
    if (tail!=report.get("tail_hash") or w.get("tail_hash")!=tail
            or type(report.get("requests_used")) is not int
            or not 0<=report["requests_used"]<=MAX_REQUESTS_PER_WINDOW
            or report["requests_used"]!=w.get("requests_used")
            or report.get("source_revision")!=revision
            or report.get("plan_sha256")!=_digest(plan)
            or report.get("settled_positions")!=0
            or report.get("net_pnl_sol") is not None
            or report.get("execution_verified") is not False):
        raise ValueError("unqualified_or_tampered_window_report")


def verify_session(root,manifest):
    root=_root_guard(root)
    if manifest.get("source_revision") is None:
        raise ValueError("manifest_revision_missing")
    if (manifest.get("planned_windows")!=WINDOWS
            or manifest.get("p3_plan_schema")!=CURVE_PHASE_FIXED["schema"]
            or manifest.get("deadline_at_ms")!=manifest.get("start_at_ms")+86400000
            or type(manifest.get("max_total_requests")) is not int
            or not 20<=manifest["max_total_requests"]<=MAX_TOTAL_REQUESTS):
        raise ValueError("protocol_drift")
    used=0
    seen=set()
    for w in manifest["windows"]:
        if type(w) is not dict or w.get("index") in seen:
            raise ValueError("duplicate_or_invalid_24h_window")
        seen.add(w["index"])
        _validate_window(root,w,manifest["source_revision"])
        used+=w["requests_used"]
    if used!=manifest.get("actual_requests_used") or used>manifest["max_total_requests"]:
        raise ValueError("budget_ledger_inconsistent")
    return used


def _window_files(root,i):
    folder=root/"windows"/f"{i:03d}"
    return folder,folder/"plan.json",folder/"capture.sqlite",folder/"report.json"


def capture_window(root,manifest,i,*,run=subprocess.run,now_ms=None):
    """One real 60s PAPER window, never retry or overwrite a partial attempt."""
    root=_root_guard(root)
    if type(i) is not int or not 0<=i<WINDOWS:
        raise ValueError("invalid_window_index")
    if i in {w["index"] for w in manifest["windows"]}:
        raise ValueError("window_already_attempted")
    if (manifest["actual_requests_used"]+MAX_REQUESTS_PER_WINDOW>
            manifest["max_total_requests"]):
        raise ValueError("remaining_request_budget_less_than_one_full_window")
    now=int(time.time_ns()//1_000_000 if now_ms is None else now_ms)
    planned=manifest["start_at_ms"]+i*INTERVAL_SECONDS*1000
    if now<planned or now>=manifest["deadline_at_ms"]:
        raise ValueError("window_outside_predeclared_time_range")
    folder,plan_path,db_path,report_path=_window_files(root,i)
    folder.mkdir(parents=True,exist_ok=False)
    plan=new_smoke_plan(revision=manifest["source_revision"],
        registered_at_ms=now-1000,curve_phase_only=True)
    # The subprocess has an independent local wall clock. Never predate the
    # plan for an earlier missed window.
    with plan_path.open("x",encoding="utf-8") as f:
        json.dump(plan,f,sort_keys=True,indent=2)
    cmd=[sys.executable,"-m","bot.p3.prospective_campaign",
         "--plan",str(plan_path),"--db",str(db_path),
         "--output",str(report_path),"--network"]
    env=os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1",RUGGER_NO_DOTENV="1")
    # Not used in this public RPC pipeline: withhold provider credentials
    # rather than needlessly passing them to a child process.
    env.pop("HELIUS_API_KEY",None)
    try:
        completed=run(cmd,env=env,timeout=CHILD_TIMEOUT_SECONDS,
                      capture_output=True,text=True,check=False)
        code=completed.returncode
    except subprocess.TimeoutExpired:
        code=-1
    # Never persist stdout/stderr: an upstream error may echo credentials.
    if code!=0 or not report_path.is_file() or not db_path.is_file():
        # Failure can have consumed anywhere from 0 to 20 requests. Reserve
        # all 20 to prevent a broken subprocess from evading the session cap.
        return dict(index=i,state="INTERRUPTED",
            requests_used=MAX_REQUESTS_PER_WINDOW,
            request_usage_exact=False,
            safe_reason="bounded_child_failure_or_timeout",planned_at_ms=planned,
            observed_at_ms=now,financial_order_submitted=False)
    report=json.loads(report_path.read_text(encoding="utf-8"))
    with CaptureStore(db_path,readonly=True) as journal:
        tail=journal.verify_integrity()
        captured_events=journal.events()
    if (tail!=report.get("tail_hash")
            or report.get("source_revision")!=manifest["source_revision"]
            or report.get("plan_sha256")!=_digest(plan)
            or report.get("collection_closed") is not True
            or type(report.get("requests_used")) is not int
            or not 0<=report["requests_used"]<=MAX_REQUESTS_PER_WINDOW
            or report.get("execution_verified") is not False
            or report.get("net_pnl_sol") is not None
            or report.get("settled_positions")!=0):
        raise ValueError("provider_capture_or_report_integrity_failure")
    # Retain the complete model denominator and all reasons, not merely
    # favorable models. Never convert a modeled delta into actual PAPER P&L.
    from bot.p3.curve_cycle_shadow import replay_events
    model=None
    if report.get("selected_corpus_size",0)>0:
        model=replay_events(captured_events,expected_tail=tail)
        audit_path=folder/"conditional_models.json"
        atomic_write_json(audit_path,model,sort_keys=True,allow_nan=False)
    return dict(index=i,
        curve_model_sha256=(_file_sha(folder/"conditional_models.json")
            if model is not None else None),
        conditional_size_models_calculable=(
            model["fixed_size_curve_sensitivity"]["conditional_only_size_markouts"]
            if model is not None else None),
        pre_followup_size_grid_receipts_verified=(
            model["fixed_size_curve_sensitivity"]["pre_followup_size_grids_verified"]
            if model is not None else None),
        state="SOURCE_GAP" if (
            report.get("stop_reason") is not None
            or report.get("selected_corpus_size")==0
            or report.get("frozen_actual_master_reference_candidates")!=report.get("selected_corpus_size")
            or model is None
            or model["fixed_size_curve_sensitivity"]["pre_followup_size_grids_verified"]
               !=report.get("selected_corpus_size")
            ) else "CAPTURED",
        stop_reason=report.get("stop_reason"),
        requests_used=report["requests_used"],request_usage_exact=True,
        planned_at_ms=planned,observed_at_ms=now,
        plan_sha256=_file_sha(plan_path),db_sha256=_file_sha(db_path),
        report_sha256=_file_sha(report_path),tail_hash=tail,
        selected_tokens=report.get("selected_corpus_size"),
        frozen_master_reference=report.get("frozen_actual_master_reference_candidates"),
        master_actions=report.get("shadow_master_action_counts"),
        reference_actions=report.get("shadow_reference_action_counts"),
        full_exit_fills=0,verified_net_pnl_lamports=None,
        financial_order_submitted=False)


def aggregate(root,manifest):
    verify_session(root,manifest)
    counts={k:sum(w["state"]==k for w in manifest["windows"])
            for k in ("CAPTURED","SOURCE_GAP","INTERRUPTED","MISSED")}
    arms={"master":{},"reference":{}}
    seen_mints=set();creator_claims=set()
    frozen=0
    model_size_trials=0
    model_size_calculable=0
    model_failure_reasons={}
    frozen_grid_count=0
    for w in manifest["windows"]:
        if w["state"] not in ("CAPTURED","SOURCE_GAP"):
            continue
        _,_,_,file=_window_files(root,w["index"])
        report=json.loads(file.read_text(encoding="utf-8"))
        frozen+=report.get("frozen_actual_master_reference_candidates",0)
        if w.get("curve_model_sha256") is not None:
            model=json.loads((file.parent/"conditional_models.json").read_text(encoding="utf-8"))
            sensitivity=model["fixed_size_curve_sensitivity"]
            model_size_trials+=sensitivity["assessed_sizes"]
            model_size_calculable+=sensitivity["conditional_only_size_markouts"]
            frozen_grid_count+=sensitivity["pre_followup_size_grids_verified"]
            for code,n in sensitivity["blocked_size_reasons"].items():
                model_failure_reasons[code]=model_failure_reasons.get(code,0)+n
        for c in report["cases"]:
            seen_mints.add(c["mint"])
            claim=c.get("creator_claim")
            if isinstance(claim,str) and claim:creator_claims.add(claim)
        for arm,key in (("master","shadow_master_action_counts"),
                        ("reference","shadow_reference_action_counts")):
            for action,n in report.get(key,{}).items():
                arms[arm][action]=arms[arm].get(action,0)+n
    return dict(schema="p3-24h-sampled-observation-progress-v1",
        session_status=manifest["status"],
        started_at_ms=manifest["start_at_ms"],deadline_at_ms=manifest["deadline_at_ms"],
        planned_windows=WINDOWS,window_counts=counts,
        total_requests_or_failure_reserved_upper_bound=manifest["actual_requests_used"],
        total_requests_confirmed=sum(w["requests_used"] for w in manifest["windows"]
            if w["state"] in ("CAPTURED","SOURCE_GAP")),
        request_cap=manifest["max_total_requests"],
        all_request_usage_exact=not any(w["state"]=="INTERRUPTED"
            for w in manifest["windows"]),
        unique_mints_sampled=len(seen_mints),
        unique_creator_claims_UNVERIFIED=len(creator_claims),
        creator_identity_independence_certified=False,
        frozen_actual_master_reference_s1_decisions=frozen,
        frozen_S1_size_grid_receipts_verified=frozen_grid_count,
        theoretical_S1_S2_curve_size_trials=model_size_trials,
        theoretical_S1_S2_curve_exit_calculable=model_size_calculable,
        theoretical_S1_S2_curve_failures=dict(sorted(model_failure_reasons.items())),
        theoretical_model_delta_not_realized_profit=True,
        master_actions=arms["master"],reference_actions=arms["reference"],
        sampled_not_continuous=True,no_authenticated_continuous_signed_creation_stream=True,
        no_complete_migration_or_cpmm_exit_tracking=True,
        net_pnl_master_lamports=None,net_pnl_reference_lamports=None,
        master_minus_reference_net_lamports=None,
        exact_profitability_determined=False,
        status_for_exact_profitability=COMPARISON_GATE,
        live_ready_to_arm=False,financial_order_submitted=False)


def _run_local(root,*,resume,max_total_requests,revision,clock=time.time,sleep=time.sleep,
               execute=capture_window):
    root=_root_guard(root)
    if resume:
        manifest=_read_manifest(root)
        if manifest["source_revision"]!=revision or manifest["max_total_requests"]!=max_total_requests:
            raise ValueError("resume_revision_or_budget_changed")
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError("fresh_24h_session_directory_required")
        root.mkdir(parents=True,exist_ok=True)
        manifest=preregistration(start_ms=int(clock()*1000),revision=revision,
            max_total_requests=max_total_requests)
        atomic_write_json(root/"session.json",manifest,sort_keys=True,allow_nan=False)
    lock=root/"session.lock"
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w") as f:
            f.write(str(os.getpid()))
            f.flush();os.fsync(f.fileno())
        verify_session(root,manifest)
        manifest["status"]="SAMPLING"
        atomic_write_json(root/"session.json",manifest,sort_keys=True,allow_nan=False)
        attempted={w["index"] for w in manifest["windows"]}
        for i in range(WINDOWS):
            if i in attempted:
                continue
            # Git revision is a provenance promise. A branch switch in
            # the middle of the 24h interval invalidates comparability.
            current_revision=subprocess.check_output(
                ["git","rev-parse","HEAD"],text=True).strip()
            if current_revision!=revision:
                manifest["status"]="HALTED_SOURCE_REVISION_CHANGED"
                break
            target=manifest["start_at_ms"]+i*INTERVAL_SECONDS*1000
            end=manifest["start_at_ms"]+(i+1)*INTERVAL_SECONDS*1000
            if target>=manifest["deadline_at_ms"]:
                break
            current=int(clock()*1000)
            if current<target:
                sleep((target-current)/1000)
                current=int(clock()*1000)
            if current>=end or current>=manifest["deadline_at_ms"]:
                w=dict(index=i,state="MISSED",planned_at_ms=target,
                    observed_at_ms=current,requests_used=0)
            elif manifest["actual_requests_used"]+20>manifest["max_total_requests"]:
                manifest["status"]="REQUEST_BUDGET_EXHAUSTED"
                break
            elif _window_files(root,i)[0].exists():
                # A crash can happen after a child started but before manifest
                # publication. Never re-run into this folder and never pretend
                # its unknown request usage is zero.
                w=dict(index=i,state="INTERRUPTED",planned_at_ms=target,
                    observed_at_ms=current,requests_used=MAX_REQUESTS_PER_WINDOW,
                    request_usage_exact=False,
                    safe_reason="orphan_window_must_be_audited_not_retried")
            else:
                w=execute(root,manifest,i,now_ms=current)
                if w.get("index")!=i:
                    raise ValueError("window_runner_returned_wrong_index")
            manifest["windows"].append(w)
            manifest["actual_requests_used"]+=w["requests_used"]
            atomic_write_json(root/"session.json",manifest,sort_keys=True,allow_nan=False)
            progress=aggregate(root,manifest)
            atomic_write_json(root/"progress.json",progress,sort_keys=True,allow_nan=False)
            # Visible and bounded window telemetry, no raw source responses.
            print(json.dumps(dict(index=i,state=w["state"],
                windows_recorded=len(manifest["windows"]),request_usage_upper_bound=
                manifest["actual_requests_used"],source_revision=revision,
                all_trades_real=False,master_net_profit_verified=False)),flush=True)
            # Never hide 3 consecutive source errors or timed out workers.
            if (len(manifest["windows"])>=3 and
                    all(t["state"] in ("SOURCE_GAP","INTERRUPTED")
                        for t in manifest["windows"][-3:])):
                manifest["status"]="HALTED_REPEATED_SOURCE_FAILURES"
                break
        else:
            # A final sample at T+23h45 does not prove observation until T+24h.
            # The last 15-minute gap is explicitly unsampled.
            remaining_ms=manifest["deadline_at_ms"]-int(clock()*1000)
            if remaining_ms>0:
                sleep(remaining_ms/1000)
            manifest["status"]=("COMPLETE_24H_PERIODIC_SAMPLES"
                if int(clock()*1000)>=manifest["deadline_at_ms"]
                else "CLOCK_INCONSISTENT_NOT_COMPLETE")
        atomic_write_json(root/"session.json",manifest,sort_keys=True,allow_nan=False)
        result=aggregate(root,manifest)
        atomic_write_json(root/"progress.json",result,sort_keys=True,allow_nan=False)
        return result
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight",action="store_true")
    parser.add_argument("--status",action="store_true",
                        help="Read persisted window status without network")
    parser.add_argument("--network",action="store_true",
                        help="Explicit public read-only network authorization")
    parser.add_argument("--accept-observation-only",action="store_true",
                        help="Acknowledge sampling CANNOT verify exact profitability")
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--session-dir",type=Path)
    parser.add_argument("--max-total-requests",type=int,default=960)
    args=parser.parse_args(argv)
    revision=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    # Uncommitted edits to tracked code defeat source-revision provenance.
    tracked_edits=subprocess.check_output(
        ["git","status","--porcelain","--untracked-files=no"],text=True).strip()
    if tracked_edits:
        parser.error("Commit or discard tracked changes before registering a 24h observation")
    check=preflight(revision=revision,max_total_requests=args.max_total_requests)
    if args.preflight:
        print(json.dumps(check,sort_keys=True))
        return 0
    if args.status:
        if args.session_dir is None:
            parser.error("--status needs --session-dir")
        manifest=_read_manifest(_root_guard(args.session_dir))
        print(json.dumps(aggregate(args.session_dir,manifest),sort_keys=True))
        return 0
    if not args.network or not args.accept_observation_only or args.session_dir is None:
        parser.error("NO GO for exact profitability: run --preflight first. Sampling needs --network --accept-observation-only --session-dir.")
    if args.session_dir.is_symlink():
        parser.error("Symlink session directory is forbidden")
    try:
        result=_run_local(args.session_dir,resume=args.resume,
            max_total_requests=args.max_total_requests,revision=revision)
        print(json.dumps(result,sort_keys=True))
        return 0 if result["window_counts"]["CAPTURED"] else 2
    except (ValueError,OSError,KeyError) as e:
        # Do not print raw external URLs, process output, environment or secrets.
        print(json.dumps(dict(status="REFUSED",error_type=type(e).__name__,
            no_real_trades=True,profitability_verified=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
