"""Three-way verification of finalized creators and indicative PAPER exit quotes.

Import signatures only from separately archived finalized Ed25519 receipts.
Match creator+mint+pool to the P3 frozen selection and exact buy/sell audit.
This is a research evidence JOIN, not an economically executed trade ledger.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def join_signed_index_quotes(index_report,quote_audit,signed):
    if (type(index_report) is not dict
            or index_report.get("schema")!="p3-active-cohort-result-v1"
            or index_report.get("qualified_economic_cycles")!=0
            or index_report.get("net_pnl_sol") is not None
            or quote_audit.get("schema")!="rugger-index-provider-exact-lot-roundtrip-audit-v1"
            or quote_audit.get("qualified_economic_cycles")!=0
            or quote_audit.get("master_net_pnl_lamports") is not None
            or quote_audit.get("source_capture_tail_hash")!=index_report.get("tail_hash")
            or signed.get("schema")!="rugger-pinned-index-creators-finalized-proof-v1"
            or signed.get("financial_order_submitted") is not False
            or signed.get("qualified_economic_cycles")!=0):
        raise ValueError("read_only_cross_evidence_contract_required")
    pre={}
    for r in index_report.get("selection",{}).get("records",[]):
        if r.get("selection_reason")=="selected_before_provider_outcomes":
            row=r.get("source_row",{})
            mint=row.get("mint")
            if type(mint) is not str or mint in pre:
                raise ValueError("duplicate_or_invalid_selected_mint")
            pre[mint]=dict(creator=row.get("creator_claim"),pool=row.get("pool"))
    if len(pre)!=index_report.get("selection",{}).get("selected_count"):
        raise ValueError("frozen_selection_incomplete")
    confirmed={}
    for r in signed.get("records",[]):
        if r.get("status")!="EXACT_OUTER_SIGNED_CREATION_VERIFIED":
            continue
        mint=r.get("mint")
        match=r.get("signed_outer_creations")
        if (type(mint) is not str or mint in confirmed
                or type(match) is not list or len(match)!=1
                or any(match[0].get(key)!=r.get(key) for key in ("mint","pool","creator"))
                or type(r.get("verified_exact_message_sha256")) is not str
                or len(r["verified_exact_message_sha256"])!=64):
            raise ValueError("tampered_or_conflicted_signed_creator")
        confirmed[mint]=r
    rows=[]
    for row in quote_audit.get("rows",[]):
        mint=row.get("mint")
        if type(mint) is not str or mint not in pre:
            raise ValueError("quote_mint_not_in_frozen_index_cohort")
        claimed=pre[mint]
        is_verified=(mint in confirmed and
            confirmed[mint]["creator"]==claimed["creator"] and
            confirmed[mint]["pool"]==claimed["pool"] and
            row.get("creator_claim")==claimed["creator"])
        if mint in confirmed and not is_verified:
            raise ValueError("signed_creation_and_provider_identity_conflict")
        quoted=row.get("provider_roundtrip_deltas")
        if type(quoted) is not list:
            raise ValueError("provider_exit_evidence_missing")
        amount=row.get("hypothetical_buy_sol_lamports")
        if type(amount) is not str or not amount.isascii() or not amount.isdigit():
            raise ValueError("unsigned_quote_budget_required")
        results=[]
        for outcome in quoted:
            if outcome.get("status")!="INDICATIVE_FULL_EXACT_LOT_QUOTE_ONLY":
                continue
            if (outcome.get("position_acquired") is not False
                    or outcome.get("quote_execution_guaranteed") is not False
                    or outcome.get("source_timestamp_or_slot_available") is not False):
                raise ValueError("unreliable_paper_quote_claim")
            results.append(dict(phase=outcome["phase"],
                estimated_proceeds_lamports=outcome["estimated_sell_sol_lamports"],
                conditional_delta_before_unknown_costs_lamports=outcome[
                    "delta_before_unknown_costs_lamports"]))
        rows.append(dict(mint=mint,pool=claimed["pool"],creator_claim=claimed["creator"],
            authenticated_outer_creation=is_verified,
            proof_signature=confirmed[mint]["signature"] if is_verified else None,
            historical_source_clocks_missing=True,
            observed_executable_fill=False,
            indicative_full_lot_quote_scenarios=results,
            master_net_pnl_lamports=None))
    if len(rows)!=len(pre):
        raise ValueError("incomplete_selected_cohort_reconciliation")
    return dict(schema="rugger-signed-creators-and-quotes-evidence-join-v1",
        source_index_sha256=_hash(index_report),
        source_quote_audit_sha256=_hash(quote_audit),
        source_signed_proof_sha256=_hash(signed),
        selected_creator_claims=len(pre),
        cryptographically_authenticated_selected_creators=sum(
            x["authenticated_outer_creation"] for x in rows),
        matched_full_lot_quote_scenarios=sum(
            len(x["indicative_full_lot_quote_scenarios"]) for x in rows),
        rows=rows,
        status="SIGNED_CREATOR_AND_INDICATIVE_QUOTES_NOT_EXECUTED",
        quote_source_clock_verified=False,
        additional_own_execution_costs_verified=False,
        independent_strategy_holdout_validated=False,
        qualified_economic_cycles=0,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        master_vs_reference_edge_lamports=None,
        market_profitability_verified=False,financial_order_submitted=False,
        live_ready_to_arm=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("index","quotes","signed","output"):
        parser.add_argument("--"+key,required=True,type=Path)
    args=parser.parse_args(argv)
    files=[args.index,args.quotes,args.signed,args.output]
    if len({p.resolve() for p in files})!=4 or args.output.exists():
        parser.error("distinct_inputs_and_new_output_required")
    read=lambda p:json.loads(p.read_text(encoding="utf8"))
    result=join_signed_index_quotes(read(args.index),read(args.quotes),read(args.signed))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf8") as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=result["status"],
        authenticated_creators=result["cryptographically_authenticated_selected_creators"],
        quote_scenarios=result["matched_full_lot_quote_scenarios"],
        market_economic_cycles=0,master_net_pnl_lamports=None,
        financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
