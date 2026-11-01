"""One explicitly authorized, bounded READ-ONLY PAPER collection.

Creates a new immutable plan, capture database and report per invocation.
Never uses wallets, signs messages, executes transactions or starts LIVE.
A single run is <=60 seconds / <=20 public provider requests, not 24h.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from bot.p3.prospective_campaign import FIXED


def new_smoke_plan(*, revision, registered_at_ms):
    if not (type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision)):
        raise ValueError("Require exact source revision")
    if type(registered_at_ms) is not int or registered_at_ms <= 0:
        raise ValueError("Require positive preregistration time")
    return dict(FIXED,registered_at_ms=registered_at_ms,source_revision=revision)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true",
                        help="Explicitly authorize the <=20 public quote/RPC requests")
    parser.add_argument("--output-dir",type=Path,default=Path("paper_artifacts"))
    args=parser.parse_args()
    if not args.network:
        parser.error("Explicit --network required; NO LIVE trading is available")
    if args.output_dir.is_symlink():
        parser.error("Refusing symlink output directory")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(
        ["git","rev-parse","HEAD"],text=True).strip()
    started=time.time_ns()
    plan=new_smoke_plan(revision=revision,registered_at_ms=started//1_000_000-1000)
    unique=str(started)
    basename="liquidity_gate_"+unique
    plan_path=args.output_dir/(basename+"_plan.json")
    db_path=args.output_dir/(basename+"_capture.sqlite")
    report_path=args.output_dir/(basename+"_report.json")
    # Exclusive plan creation: never overwrite an earlier preregistration.
    with plan_path.open("x",encoding="utf-8") as f:
        json.dump(plan,f,sort_keys=True,indent=2)
    print("PAPER plan:",plan_path,flush=True)
    print("PAPER DB:",db_path,flush=True)
    command=[sys.executable,"-m","bot.p3.prospective_campaign",
             "--plan",str(plan_path),"--db",str(db_path),
             "--output",str(report_path),"--network"]
    result=subprocess.run(command,check=False)
    if result.returncode or not report_path.is_file():
        print("PAPER capture did not complete; preserve the new plan and DB.")
        return result.returncode or 2
    report=json.loads(report_path.read_text(encoding="utf-8"))
    print(json.dumps(dict(
        report=str(report_path),
        selected_tokens=report["selected_corpus_size"],
        projected_entries=report["projected_entry_observations"],
        recorded_initial_liquidity_gates=report["initial_full_exit_gates_recorded"],
        initial_full_exit_routes_quoted=report["initial_full_exit_route_quoted"],
        full_sell_quotes=report["full_sell_quotes"],
        refused_sell_quotes=report["refused_sell_quotes"],
        qualified_economic_quote_scenarios=report["qualified_economic_quote_scenarios"],
        settled_positions=report["settled_positions"],
        net_pnl_sol=report["net_pnl_sol"],
        economic_verdict=report["economic_verdict"]),sort_keys=True))
    return 0


if __name__=="__main__":
    sys.exit(main())
