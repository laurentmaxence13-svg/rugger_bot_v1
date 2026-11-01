"""Long-running Helius read-only websocket with independently audited chunks.

This observer stays subscribed across short (default 30s) verification windows:
WS reception continues while independent worker threads verify signed creation
receipts and inspect S1/S2. Reconnect gaps, dropped buffers, RPC budget
exhaustion and last-known clocks are reported; none is silently backfilled.

This is an OBSERVER, not a master execution engine. The current Master may
legitimately stay WAIT. Token prices are not executable fills. No wallet or
transaction sending methods exist here. 24h is supported on a local powered
host, NOT on a standard GitHub Actions runner.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from bot.analyser.artifacts import atomic_write_json
from bot.live.helius_signed_master_paper import run_pipeline
from bot.live.helius_ws_forward_paper import (
    _ENDPOINT_HOST,ReadOnlyLogAudit,parse_subscription_ack,subscribe_request)

SCHEMA="rugger-continuous-helius-signed-source-paper-v1"
CHUNK_SECONDS=30
CHUNK_MAX_EVENTS=100
MAX_RPC_PER_CHUNK=15
MAX_QUEUED_CHUNKS=3


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
                    separators=(",",":"),allow_nan=False).encode()).hexdigest()


def now_ms():
    return time.time_ns()//1_000_000


def _save_new(path,doc):
    path=Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("attempt_to_overwrite_source_capture")
    atomic_write_json(path,doc,sort_keys=True,allow_nan=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def session_plan(*,duration_seconds,rpc_call_cap=3000,start_ms=None):
    if (type(duration_seconds) is not int or not 30<=duration_seconds<=86400
            or type(rpc_call_cap) is not int or not 15<=rpc_call_cap<=30000):
        raise ValueError("bounded_observation_and_rpc_quota_required")
    timestamp=now_ms() if start_ms is None else start_ms
    if type(timestamp) is not int or timestamp<=0:
        raise ValueError("source_clock_unavailable")
    return dict(schema=SCHEMA,start_ms=timestamp,
        end_ms=timestamp+1000*duration_seconds,
        duration_seconds=duration_seconds,max_rpc_calls=rpc_call_cap,
        rpc_used_or_reserved_upper_bound=0,windows=[],
        events_retained=0,websocket_gaps=[],status="REGISTERED",
        sampling_limitations=[
            "confirmed_websocket_event_not_yet_finalized_creation",
            "finalized_receipts_checked_after_batch_never_at_notification_time",
            "30_second_batches_not_zero_delay_execution",
            "websocket_disconnect_gap_is_unknown_not_reconstructed",
            "new_birth_without_log_hints_can_be_missed_by_bounded_verifier",
            "24h_sample_does_not_prove_future_risk_adjusted_profitability"],
        complete_event_tape_verified=False,
        full_paper_trade_lifecycle_qualified=False,
        exact_master_net_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)


def _check_manifest(directory,manifest):
    if (type(manifest) is not dict or manifest.get("schema")!=SCHEMA
            or type(manifest.get("windows")) is not list
            or manifest.get("financial_order_submitted") is not False
            or manifest.get("live_ready_to_arm") is not False
            or manifest.get("exact_master_net_profitability_verified") is not False):
        raise ValueError("invalid_session_manifest")
    reserved=0
    for i,w in enumerate(manifest["windows"]):
        if (w.get("index")!=i or w.get("state") not in
                ("VERIFIED","SOURCE_REFUSED","INTERRUPTED")
                or type(w.get("rpc_calls_reserved")) is not int
                or not 0<=w["rpc_calls_reserved"]<=15):
            raise ValueError("untrusted_session_window_state")
        artifact=directory/"chunks"/f"{i:06d}"/"received.json"
        if (artifact.is_symlink() or not artifact.is_file()
                or hashlib.sha256(artifact.read_bytes()).hexdigest()!=w.get("source_sha256")):
            raise ValueError("source_capture_changed_or_missing")
        reserved+=w["rpc_calls_reserved"]
    if reserved!=manifest.get("rpc_used_or_reserved_upper_bound"):
        raise ValueError("rpc_budget_accounting_changed")
    if reserved>manifest.get("max_rpc_calls",0):
        raise ValueError("overconsumed_helius_budget")
    return reserved


async def monitor(*,directory,api_key,duration_seconds=120,rpc_call_cap=3000,
                  websocket_factory=None):
    """Single local foreground invocation: no process detached, no background job."""
    if (type(api_key) is not str or api_key=="COLLE_TA_CLE_ICI"
            or re.fullmatch(r"[A-Za-z0-9_-]{16,160}",api_key) is None):
        raise ValueError("helius_env_key_required")
    folder=Path(directory)
    if folder.exists() or folder.is_symlink():
        raise ValueError("new_empty_source_directory_required")
    folder.mkdir(parents=True,exist_ok=False)
    (folder/"chunks").mkdir()
    manifest=session_plan(duration_seconds=duration_seconds,rpc_call_cap=rpc_call_cap)
    atomic_write_json(folder/"manifest.json",manifest,sort_keys=True,allow_nan=False)
    endpoint="wss://"+_ENDPOINT_HOST+"/?api-key="+api_key
    if websocket_factory is None:
        from websockets.asyncio.client import connect
        websocket_factory=connect
    queue=asyncio.Queue(maxsize=MAX_QUEUED_CHUNKS)
    global_seen=set()
    tally=dict(verified_creations=0,frozen_s1_decisions=0,
               source_refusals=0,source_websocket_gaps=0,
               verification_rpc_calls=0)
    deadline=time.monotonic()+duration_seconds
    stop=False
    worker_error=None

    async def verifier_worker():
        nonlocal worker_error
        while True:
            item=await queue.get()
            if item is None:
                queue.task_done()
                return
            index,capture=item
            w=manifest["windows"][index]
            try:
                async def replay_observer(seconds,max_events,key,*,successful_only=False):
                    if key!=api_key or successful_only or max_events!=CHUNK_MAX_EVENTS:
                        raise ValueError("immutable_public_source_batch_required")
                    return capture["report"],capture["events"]
                summary=await asyncio.to_thread(run_pipeline,
                    seconds=30,output_dir=folder/"chunks"/f"{index:06d}"/"verified",
                    api_key=api_key,observer=replay_observer)
                used=(summary.get("actual_verification_rpc_calls_used",0) or 0)+(
                    summary.get("actual_bank_rpc_calls_used",0) or 0)
                if type(used) is not int or not 0<=used<=MAX_RPC_PER_CHUNK:
                    raise ValueError("provider_request_counter_unqualified")
                w["rpc_calls_reserved"]=used
                w["state"]="VERIFIED"
                w["verified_summary_sha256"]=digest(summary)
                w["signed_creations"]=summary["selected_independent_signed_creators"]
                w["master_decisions"]=summary["frozen_S1_decisions"]
                tally["verified_creations"]+=summary["selected_independent_signed_creators"]
                tally["frozen_s1_decisions"]+=summary["frozen_S1_decisions"]
                tally["verification_rpc_calls"]+=used
            except Exception as error:
                # Failures may consume all 15 allowed calls; never re-use them.
                w["state"]="SOURCE_REFUSED"
                w["error_class"]=type(error).__name__
                tally["source_refusals"]+=1
            manifest["rpc_used_or_reserved_upper_bound"]=sum(
                rec["rpc_calls_reserved"] for rec in manifest["windows"])
            _check_manifest(folder,manifest)
            atomic_write_json(folder/"manifest.json",manifest,sort_keys=True,allow_nan=False)
            queue.task_done()

    async def add_batch(audit,started_mono,handshake_ms):
        nonlocal stop
        if not audit.events:
            return
        if (manifest["rpc_used_or_reserved_upper_bound"]+MAX_RPC_PER_CHUNK
                >rpc_call_cap):
            manifest["status"]="HALTED_PROVIDER_CALL_CAP"
            manifest["websocket_gaps"].append(dict(
                started_at_ms=now_ms(),reason="unverified_events_after_request_cap",
                lost_accepted_event_count=len(audit.events),
                unknown_missed_transactions=True))
            stop=True
            return
        idx=len(manifest["windows"])
        chunkdir=folder/"chunks"/f"{idx:06d}"
        chunkdir.mkdir(exist_ok=False)
        report=audit.report(duration_ms=max(0,(time.monotonic_ns()-started_mono)//1_000_000),
                            handshake_ms=handshake_ms)
        captured=dict(report=report,events=audit.events)
        sha=_save_new(chunkdir/"received.json",captured)
        manifest["windows"].append(dict(index=idx,state="INTERRUPTED",
            source_sha256=sha,source_event_count=len(audit.events),
            rpc_calls_reserved=MAX_RPC_PER_CHUNK))
        manifest["events_retained"]+=len(audit.events)
        manifest["rpc_used_or_reserved_upper_bound"]+=MAX_RPC_PER_CHUNK
        atomic_write_json(folder/"manifest.json",manifest,sort_keys=True,allow_nan=False)
        try:
            queue.put_nowait((idx,captured))
        except asyncio.QueueFull:
            stop=True
            manifest["status"]="HALTED_UNDRAINED_VERIFICATION_QUEUE"
            tally["source_refusals"]+=1

    worker=asyncio.create_task(verifier_worker())
    reconnects=0
    try:
        while time.monotonic()<deadline and not stop:
            gap_start=now_ms()
            audit=None
            try:
                async with websocket_factory(endpoint,open_timeout=10,close_timeout=3,
                        ping_interval=15,max_size=262144,compression=None) as socket:
                    await socket.send(json.dumps(subscribe_request(),separators=(",",":")))
                    ack=await asyncio.wait_for(socket.recv(),timeout=8)
                    sub=parse_subscription_ack(ack)
                    handshake_ms=max(0,now_ms()-gap_start)
                    if reconnects:
                        manifest["websocket_gaps"].append(dict(
                            started_at_ms=gap_start,
                            recovered_at_ms=now_ms(),
                            reason="connection_reestablished_after_unknown_gap"))
                        tally["source_websocket_gaps"]+=1
                    window_start=time.monotonic_ns()
                    audit=ReadOnlyLogAudit(sub,CHUNK_MAX_EVENTS)
                    while time.monotonic()<deadline and not stop:
                        remaining=min(2,max(0,deadline-time.monotonic()))
                        if remaining<=0:
                            break
                        try:
                            msg=await asyncio.wait_for(socket.recv(),timeout=remaining)
                        except asyncio.TimeoutError:
                            msg=None
                        if msg is not None:
                            received=time.monotonic_ns()
                            utc=time.time_ns()
                            # Suppress duplicates across batch boundaries/reconnects
                            # before the deterministic signature hash is appended.
                            try:
                                parsed=json.loads(msg)
                                sig=parsed["params"]["result"]["value"]["signature"]
                            except (KeyError,TypeError,ValueError):
                                sig=None
                            if sig not in global_seen:
                                accepted=audit.accept(msg,
                                    received_mono_ns=received,
                                    received_utc_ns=utc,parsed_mono_ns=time.monotonic_ns())
                                if accepted:
                                    global_seen.add(audit.events[-1]["signature"])
                        if (len(audit.events)>=CHUNK_MAX_EVENTS
                                or (time.monotonic_ns()-window_start)//1_000_000_000>=CHUNK_SECONDS):
                            await add_batch(audit,window_start,handshake_ms)
                            audit=ReadOnlyLogAudit(sub,CHUNK_MAX_EVENTS)
                            window_start=time.monotonic_ns()
                    await add_batch(audit,window_start,handshake_ms)
            except Exception as error:
                # A socket break must not silently erase the last retained
                # evidence batch that had not yet reached its 30s boundary.
                if "audit" in locals() and audit is not None and audit.events:
                    await add_batch(audit,window_start,handshake_ms)
                    audit=None
                reconnects+=1
                manifest["websocket_gaps"].append(dict(
                    started_at_ms=gap_start,end_at_ms=now_ms(),
                    reason_class=type(error).__name__,
                    recovered=False,unknown_missed_transactions=True))
                tally["source_websocket_gaps"]+=1
                if reconnects>=10:
                    manifest["status"]="HALTED_RECONNECT_FAILURES"
                    stop=True
                if not stop and time.monotonic()<deadline:
                    await asyncio.sleep(min(5,reconnects))
        await queue.join()
        await queue.put(None)
        await worker
        if manifest["status"]=="REGISTERED":
            manifest["status"]=("COMPLETED_WITH_GAPS" if tally["source_websocket_gaps"]
                 else "COMPLETED_NO_KNOWN_GAP_NOT_PROOF_OF_COMPLETE_TAPE")
        manifest["summary"]=dict(tally,
            unique_log_events=len(global_seen),
            chunks_recorded=len(manifest["windows"]),
            source_complete=False,actual_paper_buys=0,
            exact_master_profitability_verified=False,
            financial_order_submitted=False,
            master_reference_pnl_lamports=None)
        atomic_write_json(folder/"manifest.json",manifest,sort_keys=True,allow_nan=False)
        _check_manifest(folder,manifest)
        return dict(status=manifest["status"],summary=manifest["summary"],
                    artifact_dir=str(folder),financial_order_submitted=False)
    finally:
        if not worker.done():
            worker.cancel()
            try:await worker
            except asyncio.CancelledError:pass


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--duration-seconds",type=int,default=120)
    p.add_argument("--rpc-call-cap",type=int,default=3000)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.network:
        p.error("Explicit read-only --network authorization required")
    try:
        result=asyncio.run(monitor(directory=args.output_dir,
            api_key=os.environ.get("HELIUS_API_KEY"),
            duration_seconds=args.duration_seconds,
            rpc_call_cap=args.rpc_call_cap))
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as error:
        # URL and credential must never appear in logs or error messages.
        print(json.dumps(dict(status="REFUSED",
            safe_error_class=type(error).__name__,
            no_wallet_or_order=True,net_profitability_validated=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
