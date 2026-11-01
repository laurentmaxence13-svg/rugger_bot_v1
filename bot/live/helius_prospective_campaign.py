"""Bounded multi-window LaunchLab mainnet research campaign (strictly PAPER).

One GitHub Actions job, N sequential 60-second snapshots; each window uses
the independent <=10-request Helius read-only client already audited.
No orders, wallets, signing, live execution, or profitability claims.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from bot.live.helius_early_signed_s1s2 import bounded_early_capture

SCHEMA="rugger-prospective-multi-window-campaign-v1"
CAPTURE_SCHEMA="rugger-early-confirmed-signed-S1S2-paper-v1"
MAX_WINDOWS=6
MAX_SECONDS=60
MAX_EVENTS=200


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False,ensure_ascii=True)


def _evidence_root(workspace):
    root=Path(workspace).resolve(strict=True)
    if not (root/"bot/live/helius_early_signed_s1s2.py").is_file():
        raise ValueError("repository_root_required")
    out=root/"paper_artifacts"
    if out.is_symlink():
        raise ValueError("artifact_symlink_refused")
    out.mkdir(mode=0o700,parents=False,exist_ok=True)
    if not out.resolve().is_relative_to(root):
        raise ValueError("artifact_escaped_repository")
    return out


def campaign(*,windows=4,seconds=60,max_events=100,
             capture=bounded_early_capture,workspace=None,
             session="bounded"):
    """Synchronous orchestrator with a separate causal receipt for every window."""
    if (type(windows) is not int or not 1<=windows<=MAX_WINDOWS
            or type(seconds) is not int or not 10<=seconds<=MAX_SECONDS
            or type(max_events) is not int or not 1<=max_events<=MAX_EVENTS):
        raise ValueError("explicit_multi_window_budget_required")
    if type(session) is not str or not session or not session.isascii() or not session.replace("_","").isalnum():
        raise ValueError("bounded_session_id_required")
    workspace = Path.cwd() if workspace is None else Path(workspace)
    out=_evidence_root(workspace)
    seen_signatures=set()
    seen_creators=set()
    receipts=[]
    for index in range(windows):
        # One new provider client and a cryptographically frozen selection per
        # window. Never re-query an earlier decision with future S2 data.
        report,events=asyncio.run(capture(seconds=seconds,max_events=max_events))
        if (type(report) is not dict or report.get("schema")!=CAPTURE_SCHEMA
            or report.get("financial_order_submitted") is not False
            or report.get("live_ready_to_arm") is not False
            or report.get("qualified_economic_cycles")!=0
            or report.get("master_net_pnl_lamports") is not None
            or report.get("reference_net_pnl_lamports") is not None
            or type(events) is not list or len(events)>max_events
            or type(report.get("attempts")) is not list
            or type(report.get("selected")) is not list
            or type(report.get("forward_log_report")) is not dict
            or report["forward_log_report"].get("events_received_unique")!=len(events)):
            raise ValueError("unqualified_capture_refused")
        for event in events:
            if type(event) is not dict or type(event.get("signature")) is not str:
                raise ValueError("invalid_public_log_evidence")
        signatures=[e["signature"] for e in events]
        repeats=sum(sig in seen_signatures for sig in signatures)
        seen_signatures.update(signatures)
        signed=0
        unique_new_creator_count=0
        frozen=0
        conditional=0
        for attempt in report["attempts"]:
            if type(attempt) is not dict:
                raise ValueError("unqualified_attempt_refused")
            launches=attempt.get("signed_outer_creations")
            if launches:
                if type(launches) is not list:
                    raise ValueError("signed_creation_claim_invalid")
                signed+=len(launches)
                for x in launches:
                    if type(x) is not dict or type(x.get("creator")) is not str:
                        raise ValueError("creator_claim_missing")
                    if x["creator"] not in seen_creators:
                        unique_new_creator_count+=1
                        seen_creators.add(x["creator"])
            frozen+=int(type(attempt.get("frozen_pre_S2")) is dict)
            conditional+=int("s1_s2_conditional_markout_lamports" in attempt)
        receipt=dict(window=index+1,observed_events=len(events),
            repeated_signatures_across_windows=repeats,
            inspected_attempts=len(report["attempts"]),
            verified_signed_launch_candidates=signed,
            newly_observed_creator_claims=unique_new_creator_count,
            frozen_S1_decisions=frozen,
            conditional_model_markouts=conditional,
            market_economic_cycles_verified=0,
            financial_order_submitted=False,
            source_sha256=hashlib.sha256(_canonical(dict(events=events,report=report)).encode()).hexdigest())
        # Store each bounded observation independently before entering next window.
        path=out/f"prospective_{session}_window_{index+1:02d}.json"
        with path.open("x",encoding="utf-8") as handle:
            handle.write(_canonical(dict(events=events,report=report))+"\n")
        receipts.append(receipt)
        print(_canonical(dict(status="PAPER_WINDOW_COMPLETE",**receipt)),flush=True)
    summary=dict(schema=SCHEMA,windows_requested=windows,
        seconds_per_window=seconds,max_events_per_window=max_events,
        max_readonly_helius_requests=windows*10,
        windows=receipts,observed_events=sum(w["observed_events"] for w in receipts),
        repeated_signatures_across_windows=sum(w["repeated_signatures_across_windows"] for w in receipts),
        verified_signed_launch_candidates=sum(w["verified_signed_launch_candidates"] for w in receipts),
        observed_distinct_creator_claims=len(seen_creators),
        frozen_S1_decisions=sum(w["frozen_S1_decisions"] for w in receipts),
        conditional_model_markouts=sum(w["conditional_model_markouts"] for w in receipts),
        independent_creator_economic_cycles=0,master_net_pnl_lamports=None,
        reference_net_pnl_lamports=None,master_reference_edge_lamports=None,
        market_profitability_verified=False,financial_order_submitted=False,
        live_ready_to_arm=False)
    target=out/f"prospective_{session}_summary.json"
    with target.open("x",encoding="utf-8") as handle:
        handle.write(_canonical(summary)+"\n")
    print(_canonical(dict(status="PAPER_CAMPAIGN_COMPLETE",
        windows=windows,observed_events=summary["observed_events"],
        creator_claims=summary["observed_distinct_creator_claims"],
        conditional_model_markouts=summary["conditional_model_markouts"],
        market_profitability_verified=False,financial_order_submitted=False)),flush=True)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows",type=int,default=4)
    parser.add_argument("--seconds",type=int,default=60)
    parser.add_argument("--max-events",type=int,default=100)
    args=parser.parse_args(argv)
    if (os.environ.get("GITHUB_ACTIONS")!="true"
        or not os.environ.get("GITHUB_WORKSPACE")
        or not os.environ.get("HELIUS_API_KEY")):
        print(_canonical(dict(status="PAPER_CAMPAIGN_REFUSED",
            error="explicit_GitHub_Actions_and_secret_required",
            financial_order_submitted=False)))
        return 2
    try:
        campaign(windows=args.windows,seconds=args.seconds,
            max_events=args.max_events,workspace=os.environ["GITHUB_WORKSPACE"],
            session=os.environ.get("GITHUB_RUN_ID","bounded"))
        return 0
    except Exception as exc:
        print(_canonical(dict(status="PAPER_CAMPAIGN_REFUSED",
            safe_error_class=type(exc).__name__,financial_order_submitted=False,
            live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
