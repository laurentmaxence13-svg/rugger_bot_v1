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

from bot.p3.prospective_campaign import FIXED,CURVE_PHASE_FIXED


def new_smoke_plan(*, revision, registered_at_ms, curve_phase_only=False):
    if not (type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision)):
        raise ValueError("Require exact source revision")
    if type(registered_at_ms) is not int or registered_at_ms <= 0:
        raise ValueError("Require positive preregistration time")
    if type(curve_phase_only) is not bool:
        raise ValueError("Curve-phase mode must be an explicit boolean")
    return dict(CURVE_PHASE_FIXED if curve_phase_only else FIXED,
                registered_at_ms=registered_at_ms,source_revision=revision)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curve-phase-only",action="store_true",
                        help="Use observed LaunchLab curve banks, no routed AMM API quotes")
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
    plan=new_smoke_plan(revision=revision,registered_at_ms=started//1_000_000-1000,
                        curve_phase_only=args.curve_phase_only)
    unique=str(started)
    basename=("curve_phase_" if args.curve_phase_only else "liquidity_gate_")+unique
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
    # Read the just-closed capture, and report the concrete blocking reason
    # for missing observed LaunchLab curve quotes. This audit has no network.
    venue_summary=None
    curve_summary=None
    try:
        from bot.p3.store import CaptureStore
        from bot.p3.venue_audit import venue_audit
        from bot.p3.curve_cycle_shadow import replay_events
        with CaptureStore(db_path,readonly=True) as journal:
            anchor=journal.verify_integrity()
            events=journal.events()
            venue_summary=venue_audit(events,expected_tail=anchor)
            curve_summary=replay_events(events,expected_tail=anchor)
    except ValueError:
        # An interrupted discovery may correctly have no frozen prefix.
        # The primary error/absence is preserved by the main P3 report.
        venue_summary=None
        curve_summary=None
    print(json.dumps(dict(
        report=str(report_path),
        selected_tokens=report["selected_corpus_size"],
        quote_protocol=plan["schema"],
        Raydium_AMM_trade_api_quotes_requested=not args.curve_phase_only,
        projected_entries=report["projected_entry_observations"],
        recorded_initial_liquidity_gates=report["initial_full_exit_gates_recorded"],
        master_reference_shadow_frozen=report["frozen_actual_master_reference_candidates"],
        master_shadow_action_counts=report["shadow_master_action_counts"],
        reference_shadow_action_counts=report["shadow_reference_action_counts"],
        master_minus_reference_net_lamports=report["shadow_master_minus_reference_net_lamports"],
        observed_curve_sell_estimates=(venue_summary["observed_curve_sell_estimates"]
            if venue_summary is not None else None),
        curve_sell_blocking_reasons=(venue_summary["observed_curve_sell_unqualified_reason_counts"]
            if venue_summary is not None else None),
        active_launchlab_curves=(venue_summary["stage_counts"].get(
            "launchlab_curve_active_status_observed",0)
            if venue_summary is not None else None),
        conditional_s1s2_curve_markouts=(curve_summary["conditional_curve_markouts"]
            if curve_summary is not None else None),
        fixed_size_curve_markouts=(curve_summary["fixed_size_curve_sensitivity"]["conditional_only_size_markouts"]
            if curve_summary is not None else None),
        pre_followup_s1_size_grids_verified=(curve_summary["fixed_size_curve_sensitivity"]["pre_followup_size_grids_verified"]
            if curve_summary is not None else None),
        fixed_size_grid_retrospective_only=(curve_summary["fixed_size_curve_sensitivity"]["historical_replay_not_prospective_preadmission"]
            if curve_summary is not None else None),
        conditional_s1s2_curve_refusals=(
            curve_summary["conditional_curve_markout_refusals"]
            if curve_summary is not None else None),
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
