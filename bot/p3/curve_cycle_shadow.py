"""Causal, quote-only LaunchLab S1->S2 PAPER *research* markouts.

Unlike the routed Raydium API buy-inventory probe, this always uses the
PRE-FOLLOWUP LaunchLab S1 fixed-size *curve* buy model to determine the token
quantity, and later observed LaunchLab S2 bank facts for a hypothetical sell.

This is a conditional sensitivity calculation, NOT a simulated executable
position. In particular, the S2 bank did not include our hypothetical S1 buy.
No true paired Master/reference net P&L is inferred here.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.p3.curve_quote_audit import indicative_curve_sell
from bot.p3.store import CaptureStore

SCHEMA = "p3-venue-correct-s1s2-conditional-curve-replay-v1"


def _uint(value):
    if type(value) is int and 0 < value < 2**64:
        return value
    if (type(value) is str and 1 <= len(value) <= 20 and value.isdecimal()
            and 0 < int(value) < 2**64):
        return int(value)
    return None


def _bank_analysis(events, mint, phase):
    rows = [e for e in events
            if e.get("mint") == mint and e.get("kind") == "candidate_decision"
            and type(e.get("payload")) is dict
            and e["payload"].get("probe_phase") == phase
            and type(e["payload"].get("analysis")) is dict]
    # More than one bank in the same phase is not an invitation to
    # cherry-pick a favorable observation.
    if len(rows) != 1:
        return None, "missing_or_duplicated_" + phase + "_bank"
    event = rows[0]
    if (type(event.get("source_slot")) is not int
            or event["source_slot"] <= 0
            or type(event.get("available_at_ms")) is not int
            or event["available_at_ms"] <= 0):
        return None, "invalid_" + phase + "_bank_clock"
    analysis = event["payload"]["analysis"]
    if analysis.get("context_slot") != event["source_slot"]:
        return None, "bank_context_slot_mismatch"
    return event, None


def conditional_curve_case(events, row, *, registered_at_ms=None):
    """Calculate each candidate independently; never drop failed/no-quote rows."""
    mint = row["mint"]
    case = dict(
        ordinal=row["ordinal"], mint=mint, pool=row["pool"],
        status="UNQUALIFIED", reason=None,
        curve_s1_buy_input_lamports=None, curve_s1_buy_quantity_atomic=None,
        curve_s2_sell_output_lamports=None,
        conditional_market_markout_before_extra_costs_lamports=None,
        s1_bank_slot=None,s2_bank_slot=None,
        s1_observation_id=None,s2_observation_id=None,
        source="retained_onchain_LaunchLab_curve_model_not_Raydium_Trade_API",
        s1_model_frozen_before_s2=False,
        own_hypothetical_buy_not_applied_to_observed_s2_bank=True,
        actual_master_action_not_inferred=True,
        reference_action_not_inferred=True,
        model_only_not_executable=True,
        actual_acquired_inventory=False, actual_sell_executed=False,
        extra_costs_known=False, net_pnl_lamports=None,
        market_profitability_verified=False,
    )
    s1, failure = _bank_analysis(events,mint,"initial")
    if failure:
        case["reason"]=failure
        return case
    case["s1_bank_slot"]=s1["source_slot"]
    case["s1_observation_id"]=s1["id"]
    s1_analysis=s1["payload"]["analysis"]
    projection=s1_analysis.get("conditional_projection")
    if type(projection) is not dict:
        case["reason"]="initial_curve_buy_projection_missing_or_blocked"
        reasons=s1_analysis.get("blocking_reasons")
        case["s1_blocking_reasons"]=(reasons if type(reasons) is list else [])
        return case
    if (projection.get("kind")!="conditional_constant_product_projection"
            or projection.get("position_acquired") is not False
            or projection.get("execution_verified") is not False):
        case["reason"]="s1_projection_provenance_or_execution_state_invalid"
        return case
    amount=_uint(projection.get("buy_input_lamports"))
    quantity=_uint(projection.get("buy_output_atomic"))
    if amount is None or quantity is None:
        case["reason"]="initial_curve_buy_amount_or_quantity_invalid"
        return case
    case["curve_s1_buy_input_lamports"]=str(amount)
    case["curve_s1_buy_quantity_atomic"]=str(quantity)
    s2, failure = _bank_analysis(events,mint,"followup")
    if failure:
        case["reason"]=failure
        return case
    if (s2["id"]<=s1["id"] or s2["source_slot"]<=s1["source_slot"]
            or s2["available_at_ms"]<=s1["available_at_ms"]):
        case["reason"]="followup_not_causal_or_newer_bank"
        return case
    case["s2_bank_slot"]=s2["source_slot"]
    case["s2_observation_id"]=s2["id"]
    # The selected inventory is derived exclusively from S1, before S2.
    # No input amount was chosen by looking at the future exit results.
    case["s1_model_frozen_before_s2"]=True
    result=indicative_curve_sell(s2["payload"]["analysis"],
                                quantity_atomic=quantity)
    if result.get("curve_estimate_available") is not True:
        case["reason"]="followup_curve_sell_"+str(result.get("reason","unqualified"))
        return case
    proceeds=_uint(result.get("sell_output_lamports"))
    if proceeds is None:
        case["reason"]="followup_curve_output_invalid"
        return case
    case.update(status="CONDITIONAL_CURVE_MARKOUT_ONLY",
        reason="observed_s2_bank_omits_hypothetical_s1_buy_and_external_costs",
        curve_s2_sell_output_lamports=str(proceeds),
        conditional_market_markout_before_extra_costs_lamports=str(proceeds-amount),
        s2_curve_fee_lamports=result.get("curve_fee_lamports"),
        s2_observed_spendable_quote_vault_lamports=
            result.get("quote_vault_spendable_lamports"),
    )
    return case


def replay_events(events, *, expected_tail):
    if (type(events) is not list or not events
            or type(expected_tail) is not str
            or events[-1].get("record_hash") != expected_tail
            or len({e.get("id") for e in events}) != len(events)):
        raise ValueError("Immutable verified capture required")
    prefixes=[e for e in events if e.get("kind")=="checkpoint"
              and e.get("outcome")=="prospective_prefix_fixed"]
    if len(prefixes)!=1:
        raise ValueError("Exactly one frozen candidate prefix required")
    rows=prefixes[0].get("payload",{}).get("candidates")
    if type(rows) is not list or not rows:
        raise ValueError("Nonempty frozen candidate prefix required")
    seen=set()
    cases=[]
    for i,row in enumerate(rows):
        if (type(row) is not dict or row.get("ordinal")!=i
                or type(row.get("mint")) is not str or not row["mint"]
                or type(row.get("pool")) is not str or not row["pool"]
                or row["mint"] in seen):
            raise ValueError("Invalid original candidate order and identities")
        seen.add(row["mint"])
        related=[e for e in events if e.get("mint")==row["mint"]]
        cases.append(conditional_curve_case(related,row))
    reasons=Counter(c["reason"] for c in cases
                    if c["status"]!="CONDITIONAL_CURVE_MARKOUT_ONLY")
    return dict(schema=SCHEMA,verified_tail_sha256=expected_tail,
        selected_tokens=len(rows),
        conditional_curve_markouts=sum(c["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
                                      for c in cases),
        conditional_curve_markout_refusals=dict(sorted(reasons.items())),
        source="S1_LaunchLab_curve_buy_and_S2_observed_curve_sell_not_executable",
        real_master_and_reference_net_comparison_lamports=None,
        realized_net_pnl_lamports=None,
        qualified_executable_cycles=0,
        economic_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        cases=cases)


def replay(db,output):
    db,out=Path(db),Path(output)
    if (not db.is_file() or db.is_symlink() or out.exists()
            or out.is_symlink() or out.suffix!=".json"
            or db.resolve()==out.resolve()):
        raise ValueError("Existing journal and unused JSON destination required")
    with CaptureStore(db,readonly=True) as store:
        tail=store.verify_integrity()
        report=replay_events(store.events(),expected_tail=tail)
    atomic_write_json(out,report,indent=2,sort_keys=True,allow_nan=False)
    return dict(output=str(out),selected_tokens=report["selected_tokens"],
        conditional_curve_markouts=report["conditional_curve_markouts"],
        conditional_curve_markout_refusals=report["conditional_curve_markout_refusals"],
        conditional_markouts=[dict(
            mint=c["mint"],
            s1_quantity_atomic=c["curve_s1_buy_quantity_atomic"],
            conditional_delta_before_extra_costs_lamports=c[
                "conditional_market_markout_before_extra_costs_lamports"])
            for c in report["cases"] if c["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"],
        qualified_executable_cycles=0,
        actual_master_reference_edge_lamports=None,
        economic_profitability_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(replay(args.db,args.output),sort_keys=True))


if __name__=="__main__":
    main()
