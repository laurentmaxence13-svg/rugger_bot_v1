"""Deduplicate successive Raydium index PAPER observations before inference.

An index 'new' sort does not prove a candidate has not already appeared in
previous captures. Published creator/creation clocks remain PROVIDER CLAIMS.
This audit requires the original P3 signed-off report shapes, but cannot
authenticate the provider or infer Master profits or independent creator edge.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
        allow_nan=False,separators=(",",":")).encode()).hexdigest()


def _index_selected(report):
    if (type(report) is not dict or report.get("schema")!="p3-active-cohort-result-v1"
            or report.get("qualified_economic_cycles")!=0
            or report.get("positions_acquired")!=0
            or report.get("net_pnl_sol") is not None
            or report.get("execution_verified") is not False
            or type(report.get("selection")) is not dict
            or type(report["selection"].get("records")) is not list):
        raise ValueError("unverified_or_active_index_cohort_refused")
    decision=report["selection"].get("decision_at_ms")
    if type(decision) is not int or decision<=0:
        raise ValueError("decision_clock_required")
    chosen=[]
    for row in report["selection"]["records"]:
        if row.get("selection_reason")!="selected_before_provider_outcomes":
            continue
        source=row.get("source_row")
        if type(source) is not dict:
            raise ValueError("missing_retained_index_row")
        mint=source.get("mint");pool=source.get("pool");creator=source.get("creator_claim")
        creation=source.get("creation_time_claim_ms")
        if (not all(type(x) is str and x for x in (mint,pool,creator))
                or type(creation) is not int or creation<=0 or creation>decision):
            raise ValueError("missing_or_future_claimed_creation_clock")
        chosen.append(dict(mint=mint,pool=pool,creator_claim=creator,
            provider_claimed_creation_age_ms=decision-creation,
            provider_claimed_creation_ms=creation,
            local_decision_ms=decision))
    if len(chosen)!=report["selection"].get("selected_count"):
        raise ValueError("incomplete_frozen_index_selection")
    return chosen


def deduplicate_index_reports(reports):
    if type(reports) is not list or not 1<=len(reports)<=20:
        raise ValueError("bounded_cohort_reports_required")
    seen={}
    sources=[]
    all_rows=[]
    for index,report in enumerate(reports):
        selected=_index_selected(report)
        duplicate=0
        for item in selected:
            id=(item["mint"],item["pool"])
            first=seen.get(id)
            if first is not None:
                if first["creator_claim"]!=item["creator_claim"]:
                    raise ValueError("conflicting_creator_claim_cross_capture")
                duplicate+=1
            else:
                seen[id]=dict(item,first_run_index=index)
            all_rows.append(dict(item,run_index=index,
                first_seen_in_previous_run=first is not None,
                duplicate_of_run_index=first["first_run_index"] if first is not None else None))
        sources.append(dict(run_index=index,report_sha256=_hash(report),
            selected=len(selected),previously_observed_selected=duplicate,
            returned_index_rows=report.get("received_index_rows"),
            source_revision=report.get("source_revision"),
            request_count=report.get("requests_used")))
    return dict(schema="rugger-index-cross-run-dedup-v1",
        captures=len(reports),reported_selected_observations=len(all_rows),
        unique_provider_claimed_mint_pool_pairs=len(seen),
        repeated_selected_observations=len(all_rows)-len(seen),
        unique_provider_claimed_creators=len({v["creator_claim"] for v in seen.values()}),
        independent_verified_signed_creation_creators=0,
        source_creation_time_is_provider_claim_not_cryptographic_evidence=True,
        provenance="multiple_preregistered_local_decision_clocks_not_standalone_trade_fills",
        sources=sources,selected_rows=all_rows,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        qualified_economic_cycles=0,market_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports",nargs="+",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error("new_output_required")
    reports=[json.loads(p.read_text(encoding="utf8")) for p in args.reports]
    out=deduplicate_index_reports(reports)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf8") as f:
        json.dump(out,f,sort_keys=True,indent=2,allow_nan=False)
        f.write("\n")
    print(json.dumps(dict(status=out["schema"],
        selected=out["reported_selected_observations"],
        unique=out["unique_provider_claimed_mint_pool_pairs"],
        repeats=out["repeated_selected_observations"],
        verified_economic_cycles=0,financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
