"""Replay exact-lot public Raydium index-cohort quote pairs without false fills.

No network, no trades, and no source clock guess. The hash-verified P3 journal
is authoritative for quote receipt ordering; an HTTP 200 indicative quote is
not proof of executability, portfolio inventory or Master strategy PnL.
"""
import argparse
import json
from pathlib import Path

from bot.p3.store import CaptureStore

POSITION_LAMPORTS=100_000_000


def _atomic(raw, name, *, positive=True):
    if (type(raw) is not str or not raw.isascii() or not raw.isdigit()
            or str(int(raw)) != raw or (positive and int(raw)==0)):
        raise ValueError(name+"_invalid")
    return int(raw)


def audit_quote_pairs(report, events, *, expected_tail):
    if (type(report) is not dict or report.get("schema")!="p3-active-cohort-result-v1"
            or report.get("tail_hash")!=expected_tail
            or report.get("positions_acquired")!=0
            or report.get("settled_legs")!=0
            or report.get("qualified_economic_cycles")!=0
            or report.get("net_pnl_sol") is not None
            or report.get("execution_verified") is not False
            or type(events) is not list):
        raise ValueError("hash_anchored_readonly_cohort_report_required")
    selected=report.get("selection",{}).get("records")
    if type(selected) is not list:
        raise ValueError("frozen_selection_required")
    creators={}
    for item in selected:
        if item.get("selection_reason")=="selected_before_provider_outcomes":
            row=item.get("source_row")
            if type(row) is not dict or not isinstance(row.get("mint"),str):
                raise ValueError("selected_identity_missing")
            mint=row["mint"]
            if mint in creators:
                raise ValueError("duplicate_selected_mint")
            creators[mint]=row.get("creator_claim")
    if len(creators)!=report.get("projected_positions") or len(creators)>2:
        raise ValueError("selected_observation_and_inventory_mismatch")
    quotes={}
    for event in events:
        if type(event) is not dict:
            raise ValueError("invalid_capture_event")
        payload=event.get("payload")
        if (event.get("kind")!="quote_attempt" or type(payload) is not dict
                or payload.get("provider")!="raydium_trade_api"):
            continue
        if (event.get("outcome")!="quoted" or payload.get("http_status")!=200
                or payload.get("quote_kind")!="size_specific_route_estimate"
                or payload.get("executable_confirmed") is not False
                or payload.get("execution_guaranteed") is not False):
            raise ValueError("unsafe_quote_admission")
        mint=event.get("mint")
        if mint not in creators:
            raise ValueError("unsampled_quote_cannot_be_counted")
        side=payload.get("quote_side");phase=payload.get("probe_phase")
        if (side,phase) not in (("buy","initial"),("sell","initial"),("sell","followup")):
            raise ValueError("unexpected_quote_side_or_phase")
        key=(mint,side,phase)
        if key in quotes:
            raise ValueError("repeated_provider_quote_role")
        if (payload.get("source_time_ms") is not None
                or payload.get("source_slot") is not None):
            raise ValueError("source_clocks_not_in_this_regime")
        _atomic(payload.get("input_amount_atomic"),"input")
        _atomic(payload.get("output_amount_atomic"),"output")
        _atomic(payload.get("min_output_amount_atomic"),"minimum")
        quotes[key]=event
    rows=[]
    for mint,creator in creators.items():
        buy=quotes.get((mint,"buy","initial"))
        if buy is None:
            rows.append(dict(mint=mint,creator_claim=creator,status="NO_PROVIDER_BUY",
                provider_roundtrip_deltas=[],qualified_economic_cycles=0))
            continue
        purchase=buy["payload"]
        size=_atomic(purchase["input_amount_atomic"],"buy_input")
        if size!=POSITION_LAMPORTS:
            raise ValueError("unregistered_position_size")
        lot=_atomic(purchase["output_amount_atomic"],"buy_quantity")
        mins=_atomic(purchase["min_output_amount_atomic"],"buy_minimum")
        if mins>lot:
            raise ValueError("buy_minimum_exceeds_expected")
        results=[]
        for phase in ("initial","followup"):
            sale=quotes.get((mint,"sell",phase))
            if sale is None:
                results.append(dict(phase=phase,status="NO_FULL_LOT_SELL_QUOTE",
                    delta_before_unknown_costs_lamports=None))
                continue
            payout=sale["payload"]
            if (_atomic(payout["input_amount_atomic"],"sell_lot")!=lot
                    or payout.get("actual_input_amount_atomic")!=str(lot)
                    or payout.get("inventory_buy_observation_id")!=buy["id"]
                    or payout.get("exit_scope")!="full_expected"
                    or payout.get("input_mint")!=mint
                    or payout.get("output_mint")!="So11111111111111111111111111111111111111112"
                    or sale["available_at_ms"]<=buy["available_at_ms"]
                    or sale["id"]<=buy["id"]):
                raise ValueError("incorrect_lot_or_noncausal_buy_sell_pair")
            amount=_atomic(payout["output_amount_atomic"],"sell_output")
            min_amount=_atomic(payout["min_output_amount_atomic"],"sell_minimum")
            if min_amount>amount:
                raise ValueError("sell_minimum_exceeds_expected")
            delta=amount-size
            results.append(dict(phase=phase,status="INDICATIVE_FULL_EXACT_LOT_QUOTE_ONLY",
                quote_event_id=sale["id"],received_at_ms=sale["available_at_ms"],
                ms_after_buy_receipt=sale["available_at_ms"]-buy["available_at_ms"],
                sell_input_token_atomic=str(lot),
                estimated_sell_sol_lamports=str(amount),
                delta_before_unknown_costs_lamports=str(delta),
                delta_pct_of_hypothetical_buy=round(100*delta/size,6),
                source_timestamp_or_slot_available=False,
                quote_execution_guaranteed=False,position_acquired=False))
        rows.append(dict(mint=mint,creator_claim=creator,
            status="PAPER_QUOTE_PAIR_REPLAY_NOT_FILLED",
            buy_event_id=buy["id"],buy_received_at_ms=buy["available_at_ms"],
            hypothetical_buy_sol_lamports=str(size),
            expected_token_lot_atomic=str(lot),
            provider_roundtrip_deltas=results,qualified_economic_cycles=0))
    return dict(schema="rugger-index-provider-exact-lot-roundtrip-audit-v1",
        source_capture_tail_hash=expected_tail,
        sampled_creator_claims=len(set(creators.values())),
        selected_mints=len(creators),
        full_lot_provider_sell_quotes=sum(
            x["status"]=="INDICATIVE_FULL_EXACT_LOT_QUOTE_ONLY"
            for row in rows for x in row["provider_roundtrip_deltas"]),
        rows=rows,
        evidence="source_receipt_clocks_only_provider_source_time_and_slot_missing",
        own_additional_costs_verified=False,
        creation_signed_cryptographic_proof_complete=False,
        master_strategy_entered=False,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        master_vs_reference_edge_lamports=None,
        qualified_economic_cycles=0,financial_order_submitted=False,
        live_ready_to_arm=False,market_profitability_verified=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report",required=True,type=Path)
    p.add_argument("--journal",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args(argv)
    if len({args.report.resolve(),args.journal.resolve(),args.output.resolve()})!=3:
        p.error("distinct_readonly_inputs_and_new_output_required")
    if args.output.exists() or args.output.is_symlink():
        p.error("new_output_file_required")
    report=json.loads(args.report.read_text(encoding="utf8"))
    with CaptureStore(args.journal,readonly=True) as db:
        tail=db.verify_integrity()
        events=db.events()
    result=audit_quote_pairs(report,events,expected_tail=tail)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf8") as output:
        json.dump(result,output,indent=2,sort_keys=True,allow_nan=False)
        output.write("\n")
    print(json.dumps(dict(status=result["schema"],
        pairs=result["full_lot_provider_sell_quotes"],cycles_verified=0,
        master_net_pnl_lamports=None,financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
