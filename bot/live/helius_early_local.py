"""One bounded, local, NO-ORDER LaunchLab Helius observation.

This module is not an execution adapter. It cannot submit transactions.
Reads HELIUS_API_KEY from current process environment; never reads .env,
persists no credentials and does not need GitHub Actions billing.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from bot.live.helius_early_signed_s1s2 import bounded_early_capture

SCHEMA="rugger-early-confirmed-signed-S1S2-paper-v1"


def local_capture(*, seconds=45, max_events=100, root=None,
                  capture=bounded_early_capture):
    """Capture exactly one session and save public evidence under paper_artifacts."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise ValueError("local_capture_only_not_GitHub_Actions")
    if type(seconds) is not int or not 10 <= seconds <= 60:
        raise ValueError("local_duration_must_be_between_10_and_60_seconds")
    if type(max_events) is not int or not 1 <= max_events <= 100:
        raise ValueError("local_events_must_be_between_1_and_100")
    if not os.environ.get("HELIUS_API_KEY"):
        raise ValueError("HELIUS_API_KEY_not_set_in_current_terminal")
    root=Path.cwd() if root is None else Path(root)
    root=root.resolve(strict=True)
    if not (root/"bot/live/helius_early_signed_s1s2.py").is_file():
        raise ValueError("start_from_rugger_bot_repository_root")
    report,events=asyncio.run(capture(
        seconds=seconds,max_events=max_events))
    if (type(report) is not dict or report.get("schema")!=SCHEMA or
            report.get("financial_order_submitted") is not False or
            report.get("live_ready_to_arm") is not False or
            report.get("qualified_economic_cycles")!=0 or
            report.get("master_net_pnl_lamports") is not None or
            type(events) is not list or len(events)>max_events):
        raise ValueError("not_an_unqualified_readonly_evidence_report")
    # Root-relative hardcoded destination, no user-supplied arbitrary path.
    directory=root/"paper_artifacts"
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ValueError("local_artifact_directory_untrusted")
    instant=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest=directory/("helius_early_local_"+instant+".json")
    if not dest.resolve().is_relative_to(root):
        raise ValueError("local_artifact_path_untrusted")
    evidence=dict(schema="rugger-early-local-public-evidence-v1",
        collected_at_utc=datetime.now(timezone.utc).isoformat(),
        report=report,events=events,
        financial_order_submitted=False,live_ready_to_arm=False,
        master_net_pnl_lamports=None)
    # Exclusive create prevents overwriting earlier market observations.
    with dest.open("x",encoding="utf-8") as out:
        json.dump(evidence,out,sort_keys=True,ensure_ascii=True,allow_nan=False)
        out.write("\n")
    print(json.dumps(dict(status="LOCAL_READONLY_EVIDENCE_RECORDED",
        saved_file=str(dest.relative_to(root)),
        retained=report["forward_log_report"]["events_received_unique"],
        selected=len(report["selected"]),attempts=len(report["attempts"]),
        signed_creations=sum(bool(r.get("signed_outer_creations"))
                             for r in report["attempts"]),
        s1_frozen=sum("frozen_pre_S2" in r for r in report["attempts"]),
        rejections=[dict(status=r.get("status"),
                         root_refusal=r.get("root_refusal"),
                         gap_slots=r.get("creation_to_root_slot_gap"))
                    for r in report["attempts"]],
        master_net_pnl_lamports=None,financial_order_submitted=False),
        sort_keys=True,allow_nan=False))
    return dest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds",type=int,default=45)
    parser.add_argument("--max-events",type=int,default=100)
    args=parser.parse_args(argv)
    try:
        local_capture(seconds=args.seconds,max_events=args.max_events)
        return 0
    except Exception as error:
        # Codes contain no provider secrets, URLs or exception text.
        safe_codes=frozenset((
            "local_capture_only_not_GitHub_Actions",
            "local_duration_must_be_between_10_and_60_seconds",
            "local_events_must_be_between_1_and_100",
            "HELIUS_API_KEY_not_set_in_current_terminal",
            "start_from_rugger_bot_repository_root",
            "not_an_unqualified_readonly_evidence_report",
            "local_artifact_directory_untrusted",
            "local_artifact_path_untrusted"))
        code=str(error)
        print(json.dumps(dict(
            status="LOCAL_CAPTURE_REFUSED",
            error=(code if type(error) is ValueError and code in safe_codes
                   else type(error).__name__),
            financial_order_submitted=False,live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
