"""Finite, strictly bounded multi-window FREE public signed-source cohort.

This is a foreground one-off collector with explicit RPC quotas, not a
24/7 daemon. It never places any trade or re-labels conditional S1 projections
as genuine Master PAPER buys. Distinct signatures/creators are deduplicated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.live.public_sol_forward_paper import run_one_public_paper_capture

SCHEMA = "rugger-free-public-signed-cohort-v1"


def _sha(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,
            separators=(",", ":"),allow_nan=False).encode("utf-8")).hexdigest()


def collect_public_cohort(*,directory,window_count=3,seconds=75,
                          capture=run_one_public_paper_capture):
    if (type(window_count) is not int or not 1 <= window_count <= 4
            or type(seconds) is not int or not 30 <= seconds <= 90
            or window_count*seconds > 300):
        raise ValueError("fixed_free_public_observation_budget_required")
    folder = Path(directory)
    if folder.exists() or folder.is_symlink():
        raise ValueError("new_free_public_campaign_directory_required")
    folder.mkdir(parents=True,exist_ok=False)
    seen_signatures=set()
    seen_creators=set()
    observed_sol_creators=set()
    rows=[]
    rpc_total=0
    for i in range(window_count):
        output = folder/f"window_{i:02d}"
        report = capture(seconds=seconds,output_dir=output)
        if (type(report) is not dict or
                report.get("schema") != "rugger-public-solana-forward-signed-paper-v1"
                or report.get("source") != "FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS"
                or report.get("financial_order_submitted") is not False
                or report.get("live_trading_enabled") is not False
                or report.get("genuine_master_paper_buys") != 0
                or report.get("genuine_master_paper_sells") != 0
                or report.get("master_net_pnl_lamports") is not None):
            raise ValueError("unqualified_or_financial_public_window")
        captured=json.loads((output/"public_log_capture.json").read_text())
        paired=json.loads((output/"paired_master_source_shadow.json").read_text())
        if (type(captured.get("events")) is not list or
                type(paired.get("selected")) is not list or
                type(paired.get("observations")) is not list):
            raise ValueError("incomplete_public_signed_cohort_evidence")
        events=captured["events"]
        if len(events)!=report.get("log_events"):
            raise ValueError("source_public_event_count_mismatch")
        for event in events:
            sig=event.get("signature") if type(event) is dict else None
            if type(sig) is not str or not sig or sig in seen_signatures:
                raise ValueError("replayed_or_invalid_cross_window_signature")
            seen_signatures.add(sig)
        for row in paired["selected"]:
            if type(row) is not dict or type(row.get("creator")) is not str:
                raise ValueError("invalid_signed_creator_identity")
            seen_creators.add(row["creator"])
        for row in paired["observations"]:
            if type(row) is not dict:
                raise ValueError("invalid_signed_graph_observation")
            if type(row.get("graph")) is dict:
                if type(row.get("creator")) is not str:
                    raise ValueError("unidentified_native_sol_source_creator")
                observed_sol_creators.add(row["creator"])
        rpc_a=report.get("verification_rpc_calls")
        rpc_b=report.get("bank_rpc_calls")
        if (type(rpc_a) is not int or type(rpc_b) is not int
                or not 0<=rpc_a<=10 or not 0<=rpc_b<=5):
            raise ValueError("free_public_rpc_counts_unqualified")
        rpc_total+=rpc_a+rpc_b
        rows.append(dict(window=i,events=len(events),
            signed_transactions=report["signed_creation_transactions"],
            unique_candidate_creators_so_far=len(seen_creators),
            unique_native_SOL_creators_so_far=len(observed_sol_creators),
            frozen_Master_S1=report["frozen_master_S1_decisions"],
            rpc_calls=rpc_a+rpc_b,source_summary_sha256=_sha(report)))
    if rpc_total>15*window_count:
        raise ValueError("free_public_campaign_budget_exceeded")
    summary=dict(schema=SCHEMA,source="FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS",
        window_count=window_count,window_seconds=seconds,
        observed_unique_events=len(seen_signatures),
        uniquely_selected_signed_creators=len(seen_creators),
        native_SOL_source_creators=len(observed_sol_creators),
        independently_executable_full_lot_quotes_verified=False,
        master_paper_buys=0,master_paper_sells=0,
        master_net_pnl_lamports=None,complete_event_tape_verified=False,
        total_rpc_calls=rpc_total,absolute_rpc_call_cap=15*window_count,
        financial_order_submitted=False,live_trading_enabled=False,
        windows=rows)
    atomic_write_json(folder/"campaign_summary.json",summary,
                      sort_keys=True,allow_nan=False)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--windows",type=int,default=3)
    parser.add_argument("--seconds",type=int,default=75)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        print("FREE_PUBLIC_COHORT_REFUSED:EXPLICIT_NETWORK_OPT_IN_REQUIRED")
        return 2
    try:
        result=collect_public_cohort(directory=args.output_dir,
            window_count=args.windows,seconds=args.seconds)
    except Exception as error:
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
             safe_error_class=type(error).__name__,
             financial_order_submitted=False),sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
