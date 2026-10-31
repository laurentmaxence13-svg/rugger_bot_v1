"""Offline, read-only review of prospectively frozen LaunchLab S1/S2 models.

Never calls RPC, never submits trades and never interprets a conditional
curve model as an executable fill or as the Master Trader's net P&L.
"""
import argparse
import hashlib
import json
from pathlib import Path

INITIAL_INPUT_LAMPORTS = 1_000_000_000
COST_STRESS_LAMPORTS = (15_000, 1_000_000, 10_000_000)
SUPPORTED = {
    "rugger-early-confirmed-signed-S1S2-paper-v1": (
        "attempts", "frozen_pre_S2", "s2_conditional_proceeds_lamports",
        "s1_s2_conditional_markout_lamports"),
    "rugger-signed-creator-asof-paired-paper-v1": (
        "observations", "frozen_decision_before_S2",
        "s2_same_exact_qty_conditional_sell_lamports",
        "s1_to_s2_conditional_curve_markout_lamports"),
}


def _strict_int(value, label, *, nonnegative=False):
    if type(value) is not int or (nonnegative and value < 0):
        raise ValueError(label + "_invalid")
    return value


def _atomic(value, label):
    if type(value) is not str or not value.isascii() or not value.isdigit():
        raise ValueError(label + "_must_be_unsigned_atomic_string")
    return int(value)


def _signed_atomic(value, label):
    if (type(value) is not str or not value.isascii() or
            not (value.isdigit() or (value.startswith("-") and value[1:].isdigit()))):
        raise ValueError(label + "_must_be_signed_atomic_string")
    return int(value)


def _source_row(row, schema, index):
    kind, freeze_key, output_key, markout_key = SUPPORTED[schema]
    if type(row) is not dict:
        raise ValueError("non_object_observation")
    identification = {k: row.get(k) for k in ("signature", "creator", "mint", "pool")}
    if type(identification["signature"]) is not str or not identification["signature"]:
        raise ValueError("missing_source_signature")
    item = dict(index=index, **identification,
                scenario="one_sol_conditional_curve_roundtrip_not_executed",
                qualification="UNQUALIFIED", reason="incomplete_S1_S2_or_frozen_decision",
                financial_order_submitted=False, master_executed_pnl_lamports=None,
                reference_executed_pnl_lamports=None)
    freeze = row.get(freeze_key)
    if type(freeze) is not dict:
        item["reason"] = (row.get("refusal") or row.get("root_refusal") or
                          row.get("status") or "no_frozen_S1_decision")
        return item
    if schema == "rugger-early-confirmed-signed-S1S2-paper-v1":
        if len(row.get("signed_outer_creations", [])) != 1 or freeze.get("future_S2_consumed") is not False:
            item["reason"] = "no_single_signed_creation_or_future_leakage"
            return item
        decision_ms = freeze.get("decision_at_ms")
        if freeze.get("financial_order_submitted") is not False:
            raise ValueError("frozen_early_trade_claim_invalid")
        master_action = freeze.get("master_action")
        reference_action = freeze.get("reference_action")
        if row.get("finality_verified") is not True:
            item["finality"] = "confirmed_not_finalized_independently"
        else:
            item["finality"] = "finalized_verified_by_source"
    else:
        if row.get("cryptographic_creation") is not True or freeze.get("future_S2_used") is not False:
            item["reason"] = "signed_creation_or_future_leakage_not_qualified"
            return item
        if freeze.get("real_order") is not False:
            raise ValueError("frozen_trade_claim_invalid")
        decision_ms = freeze.get("at_ms")
        master_action = freeze.get("master_action")
        reference_action = freeze.get("reference_action")
        item["finality"] = "finalized_attested_by_source_not_reverified"
    item["frozen_master_action"] = master_action
    item["frozen_reference_action"] = reference_action
    if master_action in ("BUY", "ENTER") or reference_action in ("BUY", "ENTER"):
        raise ValueError("research_model_cannot_replace_authorized_trading")
    if type(master_action) is not str or type(reference_action) is not str:
        raise ValueError("paired_decisions_missing")
    if output_key not in row or markout_key not in row:
        item["reason"] = row.get("s2_refusal") or row.get("root_refusal") or "missing_S2_model_exit"
        return item
    if schema == "rugger-early-confirmed-signed-S1S2-paper-v1":
        quantity = row.get("s1_model_buy_output_atomic")
    else:
        buy_model = row.get("s1_buy_model")
        quantity = buy_model.get("buy_output_atomic") if type(buy_model) is dict else None
    if quantity is None:
        item["reason"] = "missing_S1_exact_lot_buy_model"
        return item
    if type(quantity) is not str or not quantity.isascii() or not quantity.isdigit() or int(quantity) <= 0:
        raise ValueError("invalid_S1_exact_buy_quantity")
    source_slot = _strict_int(row.get("source_slot"), "source_slot", nonnegative=True)
    s1_slot = _strict_int(row.get("s1_slot"), "s1_slot", nonnegative=True)
    s2_slot = _strict_int(row.get("s2_slot"), "s2_slot", nonnegative=True)
    s1_ms = _strict_int(row.get("s1_received_ms"), "s1_received_ms", nonnegative=True)
    s2_ms = _strict_int(row.get("s2_received_ms"), "s2_received_ms", nonnegative=True)
    decision_ms = _strict_int(decision_ms, "frozen_decision_ms", nonnegative=True)
    if not (source_slot <= s1_slot < s2_slot and s1_ms <= decision_ms < s2_ms):
        raise ValueError("noncausal_S1_freeze_S2_order")
    proceeds = _atomic(row[output_key], "sell_proceeds")
    delta = _signed_atomic(row[markout_key], "markout")
    if proceeds - INITIAL_INPUT_LAMPORTS != delta:
        raise ValueError("nonreconciled_conditional_model_markout")
    item.update(qualification="CONDITIONAL_MODEL_ONLY", reason="executable_quote_and_extra_costs_not_observed",
                s1_slot=s1_slot, s2_slot=s2_slot, s1_received_ms=s1_ms,
                s2_received_ms=s2_ms, decision_frozen_at_ms=decision_ms,
                conditional_buy_input_lamports=str(INITIAL_INPUT_LAMPORTS),
                conditional_buy_quantity_atomic=quantity,
                conditional_sell_proceeds_lamports=str(proceeds),
                conditional_model_markout_before_external_costs_lamports=str(delta),
                # These are predeclared costs for stress testing, not measured fees.
                assumed_extra_cost_stress=[dict(extra_lamports=str(cost),
                    conditional_result_lamports=str(delta-cost)) for cost in COST_STRESS_LAMPORTS],
                observed_external_costs=False, executable_fill_proven=False)
    return item


def audit_report(source):
    original = source
    # Early GitHub artifact stores {events, report}; signed bank is raw report.
    if type(source) is dict and set(source) == {"events", "report"}:
        if type(source["events"]) is not list:
            raise ValueError("invalid_capture_wrapper_events")
        source = source["report"]
    if type(source) is not dict or source.get("schema") not in SUPPORTED:
        raise ValueError("unsupported_capture_schema")
    if (source.get("financial_order_submitted") is not False or
            source.get("master_net_pnl_lamports") is not None or
            source.get("reference_net_pnl_lamports") is not None or
            source.get("live_ready_to_arm") is not False):
        raise ValueError("input_not_readonly_unprofitable_claim")
    schema = source["schema"]
    kind = SUPPORTED[schema][0]
    rows = source.get(kind)
    if type(rows) is not list:
        raise ValueError("capture_rows_missing")
    seen_signatures = set()
    seen_creators = set()
    results = []
    for index, row in enumerate(rows):
        item = _source_row(row, schema, index)
        if item["signature"] in seen_signatures:
            item["qualification"] = "UNQUALIFIED"
            item["reason"] = "duplicate_source_signature"
        elif item.get("qualification") == "CONDITIONAL_MODEL_ONLY":
            creator = item.get("creator")
            if not isinstance(creator, str) or not creator or creator in seen_creators:
                item["qualification"] = "UNQUALIFIED"
                item["reason"] = "missing_or_duplicate_creator"
            else:
                seen_creators.add(creator)
        seen_signatures.add(item["signature"])
        results.append(item)
    count = sum(r["qualification"] == "CONDITIONAL_MODEL_ONLY" for r in results)
    canonical = json.dumps(original, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf8")
    return dict(schema="rugger-prospective-conditional-markout-audit-v1",
        source_schema=schema,
        source_sha256=hashlib.sha256(canonical).hexdigest(),
        source_authentication="attested_by_input_not_reverified_in_offline_audit",
        denominator_observations=len(rows),
        independently_identified_model_opportunities=count,
        conditional_model_opportunities=results,
        master_net_pnl_lamports=None, reference_net_pnl_lamports=None,
        master_minus_reference_lamports=None,
        verified_market_paper_cycles=0,
        financial_order_submitted=False, live_ready_to_arm=False,
        profitability_verified=False,
        verdict="MODEL_MARKOUT_ONLY_NO_VERIFIED_PAPER_PNL")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error("input_and_output_must_differ")
    # No URLs, no access keys, no network. Only a previously saved observation.
    source = json.loads(args.input.read_text(encoding="utf8"))
    report = audit_report(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, allow_nan=False, indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(status=report["verdict"],
        denominator=report["denominator_observations"],
        model_opportunities=report["independently_identified_model_opportunities"],
        verified_market_paper_cycles=0,financial_order_submitted=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
