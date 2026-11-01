"""Conservative cost upper bound on signed-creator, full-lot, unfilled quotes.

A nonnegative unobserved cost cannot turn an already NEGATIVE indicative
full-lot roundtrip quote into a positive hypothetical net result. This is a
one-sided quote arithmetic conclusion, not execution or Master superiority.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _amount(x,name):
    if type(x) is not str or not x.isascii() or not x.isdigit():
        if name=="delta" and type(x) is str and x.startswith("-") and x[1:].isascii() and x[1:].isdigit():
            return -int(x[1:])
        raise ValueError(name+"_canonical_integer_required")
    if (x!="0" and x.startswith("0")) or (x.startswith("-") and x[1:] in ("","0")):
        raise ValueError(name+"_canonical_integer_required")
    value=int(x)
    if abs(value)>10**18:
        raise ValueError(name+"_amount_out_of_bounds")
    return value


def cost_upper_bounds(join):
    if (type(join) is not dict or
        join.get("schema")!="rugger-signed-creators-and-quotes-evidence-join-v1"
        or join.get("financial_order_submitted") is not False
        or join.get("qualified_economic_cycles")!=0
        or join.get("market_profitability_verified") is not False
        or join.get("master_net_pnl_lamports") is not None
        or type(join.get("rows")) is not list):
        raise ValueError("signed_creator_quote_only_evidence_required")
    rows=[]
    for source in join["rows"]:
        if type(source) is not dict or type(source.get("mint")) is not str:
            raise ValueError("quote_identity_required")
        scenarios=source.get("indicative_full_lot_quote_scenarios")
        if type(scenarios) is not list or len(scenarios)>5:
            raise ValueError("bounded_quote_scenarios_required")
        scenarios_out=[]
        seen=set()
        for scenario in scenarios:
            if type(scenario) is not dict:
                raise ValueError("scenario_shape_invalid")
            phase=scenario.get("phase")
            if phase not in ("initial","followup") or phase in seen:
                raise ValueError("quote_phase_duplicate_or_unknown")
            seen.add(phase)
            delta=_amount(scenario.get("conditional_delta_before_unknown_costs_lamports"),"delta")
            proceeds=_amount(scenario.get("estimated_proceeds_lamports"),"proceeds")
            if proceeds<=0:
                raise ValueError("indicative_sell_proceeds_must_be_positive")
            input_lamports=proceeds-delta
            if input_lamports<=0:
                raise ValueError("unqualified_implicit_buy_input")
            scenarios_out.append(dict(
                phase=phase,
                hypothetical_buy_lamports=str(input_lamports),
                estimated_sell_lamports=str(proceeds),
                best_case_delta_if_additional_costs_nonnegative_lamports=str(delta),
                strictly_negative_under_nonnegative_additional_costs=delta<0,
                break_even_additional_cost_budget_lamports=(str(delta) if delta>=0 else None),
                independent_filled_roundtrip=False,
                source_quote_execution_verified=False,
                master_action_unverified=True,
                economically_qualified=False))
        rows.append(dict(mint=source["mint"],
            creator_claim=source.get("creator_claim"),
            signed_creator_verification_status=source.get("authenticated_outer_creation"),
            scenarios=scenarios_out))
    count=sum(len(row["scenarios"]) for row in rows)
    all_negative=count>0 and all(
        x["strictly_negative_under_nonnegative_additional_costs"]
        for row in rows for x in row["scenarios"])
    return dict(schema="rugger-signed-creator-cost-upper-bound-v1",
        source_join_sha256=hashlib.sha256(json.dumps(join,sort_keys=True,
            separators=(",",":"),allow_nan=False).encode()).hexdigest(),
        distinct_token_pool_candidates=len(rows),
        independently_verified_creators_in_this_join=sum(
            row["signed_creator_verification_status"] is True for row in rows),
        conditional_quote_scenarios=count,
        quoted_roundtrip_scenarios_all_negative_before_extra_costs=all_negative,
        zero_extra_costs_are_an_upside_bound_not_an_observed_cost=True,
        scenarios_are_not_independent_creators=True,
        rows=rows,
        realized_net_master_pnl_lamports=None,
        master_reference_validated_edge_lamports=None,
        future_strategy_profitability_verified=False,
        financially_submitted_orders=0,live_ready_to_arm=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--join",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv)
    if args.join.resolve()==args.output.resolve() or args.output.exists():
        parser.error("different_new_output_required")
    join=json.loads(args.join.read_text(encoding="utf8"))
    result=cost_upper_bounds(join)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf8") as out:
        json.dump(result,out,indent=2,sort_keys=True,allow_nan=False)
        out.write("\n")
    print(json.dumps(dict(status=result["schema"],
        distinct_candidates=result["distinct_token_pool_candidates"],
        conditional_scenarios=result["conditional_quote_scenarios"],
        all_negative_before_additional_costs=result[
            "quoted_roundtrip_scenarios_all_negative_before_extra_costs"],
        qualified_cycles=0,realized_net_master_pnl_lamports=None)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
