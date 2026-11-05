"""S1-only LaunchLab buy->immediate-sell MODEL: quantify baseline curve friction.

Only a conditional, same-state reserve model after a hypothetical own buy.
Unlike observed-S2 sell checks, it updates the hypothetical post-buy reserves,
so it does not incorrectly compare the acquired tokens to the historical
pre-buy circulation. Later observed price movements are NEVER used.
This is NOT an executed order, an actionable provider quote, a projected
strategy return, or a true market-driven Master/reference profit estimate.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.p3.curve_cycle_shadow import _bank_analysis
from bot.p3.curve_size_grid import _s1_inputs, FROZEN_SIZES_LAMPORTS
from bot.p3.launchlab import SnapshotEvidenceError, constant_product_projection
from bot.p3.store import CaptureStore


def _safe_error(error):
    name=str(error)
    return name if len(name)<=96 and name.replace("_","").isalnum() else "invalid_S1_curve_model"


def immediate_roundtrip_cases(events,row):
    """All predeclared amounts on ONE S1 snapshot; no survivor/winner filtering."""
    mint=row["mint"]
    s1,issue=_bank_analysis(events,mint,"initial")
    facts=None
    if issue is None:
        try:
            facts=_s1_inputs(s1["payload"]["analysis"])
        except (ValueError,TypeError,KeyError):
            issue="unqualified_S1_reserves_fees_or_risk_flags"
    cases=[]
    for amount in FROZEN_SIZES_LAMPORTS:
        outcome=dict(
            input_lamports=str(amount),
            S1_bank_observation_id=s1["id"] if s1 is not None else None,
            S1_bank_slot=s1["source_slot"] if s1 is not None else None,
            fixed_before_S2=True,
            source="same_S1_LaunchLab_curve_post_own_hypothetical_buy",
            status="UNQUALIFIED",
            reason=issue,
            buy_output_atomic=None,
            immediate_full_sell_model_lamports=None,
            buy_curve_fee_lamports=None,
            sell_curve_fee_lamports=None,
            roundtrip_curve_friction_lamports=None,
            roundtrip_curve_friction_bps=None,
            unknown_execution_fees_included=False,
            onchain_state_changed=False,
            order_submitted=False,
            entry_fill_verified=False,
            exit_fill_verified=False,
            Master_reference_net_PnL_lamports=None,
            verified_strategy_profitability=False,
        )
        if facts is None:
            cases.append(outcome)
            continue
        try:
            projection=constant_product_projection(
                facts["pool"],input_lamports=amount,
                fee_rates_ppm=facts["fee_rates_ppm"],
                base_vault_atomic=facts["base_vault_atomic"],
                quote_vault_lamports=facts["quote_vault_lamports"],
                share_fee_rate_ppm=facts["share_fee_rate_ppm"])
            exit_lamports=int(projection["sell_output_lamports"])
            # Model output is not a settled PAPER trade; S1 same-state reversal
            # should not claim a positive edge without an outside price move.
            if exit_lamports>amount:
                raise ValueError("impossible_same_state_positive_curve_edge")
            loss=amount-exit_lamports
            outcome.update(
                status="S1_CONDITIONAL_IMMEDIATE_ROUNDTRIP_ONLY",
                reason="modeled_curve_friction_not_realizable_PnL",
                buy_output_atomic=projection["buy_output_atomic"],
                immediate_full_sell_model_lamports=str(exit_lamports),
                buy_curve_fee_lamports=projection["buy_curve_fee_lamports"],
                sell_curve_fee_lamports=projection["sell_curve_fee_lamports"],
                roundtrip_curve_friction_lamports=str(loss),
                roundtrip_curve_friction_bps=str(loss*10000//amount))
        except (ValueError,TypeError,KeyError,SnapshotEvidenceError) as exc:
            outcome["reason"]="S1_"+_safe_error(exc)
        cases.append(outcome)
    return cases


def report_events(events,*,expected_tail):
    if (type(events) is not list or not events
            or type(expected_tail) is not str
            or events[-1].get("record_hash")!=expected_tail
            or len({e.get("id") for e in events})!=len(events)):
        raise ValueError("Verified immutable capture tail required")
    prefix=[e for e in events if e.get("kind")=="checkpoint"
            and e.get("outcome")=="prospective_prefix_fixed"]
    if len(prefix)!=1:
        raise ValueError("Exactly one frozen candidate prefix required")
    candidates=prefix[0].get("payload",{}).get("candidates")
    if type(candidates) is not list or not candidates:
        raise ValueError("Frozen nonempty candidate set required")
    seen=set()
    cases=[]
    for i,row in enumerate(candidates):
        if (type(row) is not dict or row.get("ordinal")!=i
                or type(row.get("mint")) is not str or not row["mint"]
                or type(row.get("pool")) is not str or not row["pool"]
                or row["mint"] in seen):
            raise ValueError("Invalid candidate identity and ordinal")
        seen.add(row["mint"])
        subset=[e for e in events if e.get("mint")==row["mint"]]
        cases.append(dict(mint=row["mint"],ordinal=i,
                          predeclared_sizes=immediate_roundtrip_cases(subset,row)))
    reasons=Counter()
    for c in cases:
        for item in c["predeclared_sizes"]:
            if item["status"]=="UNQUALIFIED":
                reasons[item["reason"] or "unknown"]=reasons[item["reason"] or "unknown"]+1
    return dict(
        schema="p3-S1-model-curve-roundtrip-friction-audit-v1",
        source_tail_sha256=expected_tail,
        selected_tokens=len(cases),
        fixed_sizes_sol=["0.05","0.10","0.25","1.00"],
        scenario_count=len(cases)*len(FROZEN_SIZES_LAMPORTS),
        modeled_same_state_roundtrips=sum(
            row["status"]=="S1_CONDITIONAL_IMMEDIATE_ROUNDTRIP_ONLY"
            for c in cases for row in c["predeclared_sizes"]),
        unqualified_reason_counts=dict(sorted(reasons.items())),
        observation_basis="retained_S1_LaunchLab_bank_only",
        quote_provider_verified_executable=False,
        conditional_same_state_curve_cost_only=True,
        observed_S2_market_price_not_used=True,
        market_profitability_verified=False,
        actual_Master_minus_reference_net_lamports=None,
        qualified_executable_cycles=0,
        financial_order_submitted=False,
        live_ready_to_arm=False,
        cases=cases)


def replay(db,output):
    db,out=Path(db),Path(output)
    if (not db.is_file() or db.is_symlink() or out.exists() or out.is_symlink()
            or out.suffix!=".json" or db.resolve()==out.resolve()):
        raise ValueError("Existing source and unused separate JSON output required")
    with CaptureStore(db,readonly=True) as store:
        anchor=store.verify_integrity()
        report=report_events(store.events(),expected_tail=anchor)
    atomic_write_json(out,report,indent=2,sort_keys=True,allow_nan=False)
    return dict(
        report=str(out),
        selected_tokens=report["selected_tokens"],
        scenario_count=report["scenario_count"],
        modeled_same_state_roundtrips=report["modeled_same_state_roundtrips"],
        unqualified_reason_counts=report["unqualified_reason_counts"],
        per_candidate=[dict(
            ordinal=c["ordinal"],
            s1_immediate_roundtrip_friction=[
                dict(size_sol=f'{int(row["input_lamports"])/1e9:.2f}',
                     friction_lamports=row["roundtrip_curve_friction_lamports"],
                     friction_bps=row["roundtrip_curve_friction_bps"],
                     reason=row["reason"])
                for row in c["predeclared_sizes"]])
            for c in report["cases"]],
        actual_Master_minus_reference_net_lamports=None,
        market_profitability_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(replay(args.db,args.output),sort_keys=True))


if __name__=="__main__":
    main()
