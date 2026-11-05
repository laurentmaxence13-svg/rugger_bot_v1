"""Read-only replay of an existing P3 capture; no network, keys, orders or fills."""
import argparse
import json
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.p3.prospective_report import build_prospective_report
from bot.p3.store import CaptureStore


def replay(plan_path, db_path, output_path):
    plan_path, db_path, output_path = map(Path,(plan_path,db_path,output_path))
    if (not plan_path.is_file() or not db_path.is_file()
            or plan_path.is_symlink() or db_path.is_symlink()
            or output_path.exists() or output_path.is_symlink()
            or output_path.suffix != ".json"
            or len({p.resolve() for p in (plan_path,db_path,output_path)}) != 3):
        raise ValueError("Require existing separate plan/capture and new JSON report")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    with CaptureStore(db_path,readonly=True) as store:
        tail=store.verify_integrity()
        report=build_prospective_report(plan,store.events(),
                                       integrity_verified=True,expected_tail=tail)
    # Fail closed: a replay cannot introduce executed trades or economic P&L.
    if (report.get("settled_positions") != 0 or report.get("net_pnl_sol") is not None
            or report.get("execution_verified") is not False):
        raise ValueError("Replay unexpectedly claimed executed positions")
    atomic_write_json(output_path,report,indent=2,sort_keys=True,allow_nan=False)
    return dict(
        report=str(output_path),selected_tokens=report["selected_corpus_size"],
        projected_entries=report["projected_entry_observations"],
        initial_full_exit_routes_quoted=report["initial_full_exit_route_quoted"],
        recorded_liquidity_gates=report["initial_full_exit_gates_recorded"],
        full_sell_quotes=report["full_sell_quotes"],
        refused_sell_quotes=report["refused_sell_quotes"],
        settled_positions=report["settled_positions"],
        economic_verdict=report["economic_verdict"])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",required=True,type=Path)
    parser.add_argument("--db",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(replay(args.plan,args.db,args.output),sort_keys=True))


if __name__=="__main__":
    main()
