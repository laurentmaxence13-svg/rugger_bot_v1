"""Prospective REAL SOL market -> frozen decisions -> conditional PAPER markout.

This run acquires actual LaunchLab/SOL seven-account S1/S2 banks from Helius.
Before S2 it freezes two REAL policy score outputs (Master and reference)
and a separately labeled research execution PROBE of 0.05 SOL. A fixed-size
probe tests the data/price plumbing; it is NOT the Master action when Master
votes WAIT and must never be promoted to a Master P&L result.

Exit model prices the hypothetical bought lot at a later source bank. The
unobserved impact of the hypothetical buy on future reserves, fills and
network/ATA/failure fees mean P&L is COST-SCENARIO CONDITIONAL ONLY.
Absence of a trusted quote means censored open exposure, never zero profit.
No wallets, real trades, signer operations, or LIVE.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from bot.analyser.artifacts import atomic_write_json
from bot.live.helius_active_launchlab_cohort import observe_active_survivor_cohort
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.master_decision import MasterDecisionOrchestrator
from bot.p4_experiment import decide_prefix
from bot.p3.curve_size_grid import _s1_inputs
from bot.p3.launchlab import constant_product_projection,SnapshotEvidenceError

SCHEMA="rugger-real-sol-prospective-conditional-paper-cycle-v1"
SIZING_LAMPORTS=50_000_000
COST_STRESS_LAMPORTS=(0,15_000,1_000_000,10_000_000)
DEFAULT_CAPITAL_LAMPORTS=10_000_000_000


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
                    separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _freeze_before_followup(s1):
    """Called within the S1 collector BEFORE it sleeps or reads S2."""
    if (type(s1) is not dict or type(s1.get("s1_slot")) is not int
            or s1["s1_slot"]<=0 or type(s1.get("s1_received_at_ms")) is not int
            or s1["s1_received_at_ms"]<=0
            or type(s1.get("s1_observations")) is not list
            or type(s1.get("selected_before_S1")) is not list):
        raise ValueError("pinned_S1_observations_required")
    core=MasterDecisionOrchestrator()
    at=s1["s1_received_at_ms"]
    frozen=[]
    for i,item in enumerate(s1["s1_observations"]):
        source=item["row"]
        analysis=item["s1_analysis"]
        frame=dict(id="SOL-survivor-S1-"+str(i)+"-"+_hash(
            [source["pool"],s1["s1_slot"],at]),
            mint=source["mint"],creator=source["creator_claim"],
            pool=source["pool"],detected_at_ms=at,
            available_at_ms=at,source_slot=s1["s1_slot"],
            slot_available_at_ms=at,
            features=None,features_available_at_ms=None,
            source_clock_verified=False,signed_creator_verified=False,
            independent_buyers=None,bank_state=None,
            data_kind="market_observation",
            unknowns=["signed_creation_proof","independent_market_features",
                      "fee_and_routing_evidence","full_exit_execution"])
        master=core.evaluate(frame,[],health=None,capital=None)
        ref=decide_prefix("early_sniping",frame,[])
        if master["action"] not in ("WAIT","NO_TRADE") or ref["enter"] is not False:
            raise ValueError("unverified_survivor_must_not_trigger_real_master_entry")
        decision=dict(pool=source["pool"],mint=source["mint"],
            creator_claim=source["creator_claim"],s1_slot=s1["s1_slot"],
            S1_received_at_ms=at,source_S1_hash=source.get("s1_analysis_sha256"),
            actual_Master_action=master["action"],
            actual_Master_policy_sha256=core.policy_sha256,
            actual_Master_decision_sha256=_hash(master),
            actual_reference_action="WAIT",
            actual_reference_decision_sha256=_hash(ref),
            source_signed_creator_verified=False,
            complete_asof_Master_features=False,
            hypothetical_research_probe_action="REJECT",
            hypothetical_probe_size_lamports=SIZING_LAMPORTS,
            hypothetical_probe_token_quantity_atomic=None,
            hypothetical_probe_curve_buy_fee_lamports=None,
            hypothetical_S1_buy_fill_executed=False,
            research_only_quoted_not_real_entry=True,
            S2_future_evidence_used=False)
        if (type(analysis) is dict and analysis.get("risk_flags")==[]
                and type(analysis.get("conditional_projection")) is dict):
            try:
                inputs=_s1_inputs(analysis)
                buy=constant_product_projection(inputs["pool"],
                    input_lamports=SIZING_LAMPORTS,
                    fee_rates_ppm=inputs["fee_rates_ppm"],
                    base_vault_atomic=inputs["base_vault_atomic"],
                    quote_vault_lamports=inputs["quote_vault_lamports"],
                    share_fee_rate_ppm=inputs["share_fee_rate_ppm"])
                qty=int(buy["buy_output_atomic"])
                if qty<=0:
                    raise ValueError("empty_S1_probe_lot")
                decision.update(
                    hypothetical_research_probe_action="ENTER_CONDITIONAL_MODEL",
                    hypothetical_probe_token_quantity_atomic=str(qty),
                    hypothetical_probe_curve_buy_fee_lamports=buy["buy_curve_fee_lamports"],
                    probe_decision_reason="fixed_0_05_SOL_S1_model_only_no_Master_entry")
            except (SnapshotEvidenceError,ValueError,TypeError,KeyError):
                decision["probe_decision_reason"]="S1_curve_model_unqualified"
        else:
            decision["probe_decision_reason"]="S1_account_identity_or_risk_refused"
        frozen.append(decision)
    return dict(schema=SCHEMA,
        s1_registration_sha256=s1["registration_sha256"],
        s1_slot=s1["s1_slot"],freeze_available_at_ms=at,
        frozen_before_any_S2_reads=True,
        frozen_actions=frozen,
        selection_without_future_market_outcomes=True,
        actual_Master_and_reference_trades=0,
        S2_available_at_ms=None,
        future_S2_used=False,financial_order_submitted=False,
        live_ready_to_arm=False)


def evaluate_probe(research):
    """A S1-fixed, conditional market-price scenario; never realized P&L."""
    frozen=research.get("preregistered_research_freeze")
    if (research.get("status")!="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE"
            or type(frozen) is not dict or frozen.get("schema")!=SCHEMA
            or frozen.get("future_S2_used") is not False
            or frozen.get("financial_order_submitted") is not False
            or research.get("S1_research_freeze_before_S2_sha256")!=_hash(frozen)
            or type(research.get("second_bank_slot")) is not int
            or research["second_bank_slot"]<=frozen["s1_slot"]):
        raise ValueError("prospective_S1_freeze_and_later_S2_required")
    originals={r["mint"]:r for r in research["observations"]}
    if (len(originals)!=len(research["observations"]) or
            len(frozen["frozen_actions"])!=len(originals)):
        raise ValueError("frozen_and_observed_creator_denominator_mismatch")
    cases=[]
    for p in frozen["frozen_actions"]:
        row=originals.get(p["mint"])
        if (row is None or row["pool"]!=p["pool"]
                or row["s1_slot"]!=p["s1_slot"]
                or p["actual_Master_action"] not in ("WAIT","NO_TRADE")
                or p["actual_reference_action"]!="WAIT"):
            raise ValueError("changed_source_asset_or_actual_scorer_decisions")
        item=dict(mint=p["mint"],pool=p["pool"],
            actual_Master_action=p["actual_Master_action"],
            actual_reference_action="WAIT",
            hypothetical_probe_action=p["hypothetical_research_probe_action"],
            hypothetical_probe_size_lamports=p["hypothetical_probe_size_lamports"],
            hypothetical_probe_quantity_atomic=p["hypothetical_probe_token_quantity_atomic"],
            S1_slot=p["s1_slot"],S2_slot=row.get("s2_slot"),
            conditional_S2_sell_lamports=None,
            conditional_markout_before_extra_costs_lamports=None,
            extra_cost_scenarios=[],
            own_buy_overlay_sell_lamports=None,
            own_buy_overlay_delta_before_extra_costs_lamports=None,
            own_buy_overlay_cost_scenarios=[],
            own_buy_overlay_status="NOT_QUALIFIED",
            own_buy_overlay_refusal=None,
            own_buy_overlay_public_bank_replay_verified=False,
            own_buy_overlay_observed_reserve_activity=None,
            own_buy_overlay_observed_source_reserve_deltas=None,
            own_buy_overlay_path_dependent_not_executable=True,
            model_only_executable_buy_sell_not_verified=True,
            true_Master_net_pnl_lamports=None,
            true_reference_net_pnl_lamports=None,
            exact_verified_Master_edge_lamports=None,
            actual_paper_buy_fill_count=0,
            actual_paper_sell_fill_count=0)
        ladder=row.get("research_size_ladder")
        sized=next((r for r in ladder
                    if r.get("entry_lamports")==str(SIZING_LAMPORTS)),
                   None) if type(ladder) is list else None
        if p["hypothetical_research_probe_action"]!="ENTER_CONDITIONAL_MODEL":
            item["status"]="S1_RESEARCH_PROBE_NOT_ADMISSIBLE"
            item["reason"]=p["probe_decision_reason"]
        elif (row.get("s2_slot")!=research["second_bank_slot"]
                or not sized or sized.get("s1_exact_buy_quantity_atomic")!=
                    p["hypothetical_probe_token_quantity_atomic"]
                or sized.get("s2_conditional_sell_lamports") is None):
            item["status"]="CENSORED_OPEN_HYPOTHETICAL_PROBE_NO_S2_EXIT"
            item["reason"]=(sized.get("s2_refusal","missing_S2_quote")
                if sized else "missing_S2_quote")
        else:
            proceeds=int(sized["s2_conditional_sell_lamports"])
            gross=proceeds-SIZING_LAMPORTS
            item.update(status="CONDITIONAL_MODEL_ROUNDTRIP_NOT_FILL",
                conditional_S2_sell_lamports=str(proceeds),
                conditional_markout_before_extra_costs_lamports=str(gross),
                extra_cost_scenarios=[dict(assumed_extra_cost_lamports=str(cost),
                    conditional_net_lamports=str(gross-cost),
                    conditional_net_SOL=str((gross-cost)/1_000_000_000))
                    for cost in COST_STRESS_LAMPORTS],
                own_buy_not_reflected_in_real_future_source_bank=True,
                source_quote_not_independently_executable=True,
                source_snapshot_risk_flags=row.get("s2_risk_flags"))
        # The untouched real S2 bank does not contain our imaginary S1
        # purchase. Show the own-buy-adjusted overlay separately. Its price
        # depends on an unknowable future swap trajectory; no fill is asserted.
        if (sized and p["hypothetical_research_probe_action"]==
                "ENTER_CONDITIONAL_MODEL" and
                sized.get("s1_exact_buy_quantity_atomic")==
                p["hypothetical_probe_token_quantity_atomic"]):
            overlay_lamports=sized.get("s2_own_buy_overlay_sell_lamports")
            if (type(overlay_lamports) is str and overlay_lamports.isdecimal()
                    and sized.get("s2_own_buy_overlay_status")==
                    "MODEL_CONDITIONAL_NOT_EXECUTABLE"):
                amount=int(overlay_lamports)
                delta=amount-SIZING_LAMPORTS
                if str(delta)!=sized.get(
                        "s2_own_buy_overlay_delta_before_extra_costs_lamports"):
                    raise ValueError("S2_own_buy_overlay_markout_inconsistent")
                # Future campaigns retain decoded PUBLIC seven-account
                # banks and exact hash receipts for independent offline model
                # replay. Earlier campaigns remain transparently unverified.
                s1_public=row.get("s1_decoded_public_bank_replay")
                s2_public=row.get("s2_decoded_public_bank_replay")
                replay_verified=False
                reserve_activity=sized.get(
                    "s2_own_buy_overlay_source_curve_activity_observed")
                reserve_deltas=sized.get(
                    "s2_own_buy_overlay_source_reserve_deltas")
                if type(s1_public) is dict and type(s2_public) is dict:
                    from bot.p3.own_buy_s2_overlay import own_buy_s2_overlay
                    if (_hash(s1_public)!=row.get("s1_analysis_sha256") or
                            _hash(s2_public)!=row.get("s2_decoded_public_bank_sha256")):
                        raise ValueError("archived_public_S1_S2_bank_digest_mismatch")
                    replay=own_buy_s2_overlay(
                        s1_analysis=s1_public,s2_analysis=s2_public,
                        input_lamports=SIZING_LAMPORTS,
                        expected_mint=p["mint"],expected_pool=p["pool"])
                    if (_hash(replay)!=sized.get(
                            "s2_own_buy_overlay_receipt_sha256")
                            or replay["overlay_S2_sell_lamports"]!=overlay_lamports
                            or replay["paper_bought_tokens_atomic"]!=
                               p["hypothetical_probe_token_quantity_atomic"]
                            or replay["source_curve_reserve_activity_observed"]!=
                               reserve_activity
                            or replay["observed_S1_to_S2_reserve_deltas"]!=
                               reserve_deltas):
                        raise ValueError("archived_public_overlay_model_replay_failed")
                    replay_verified=True
                item.update(
                    own_buy_overlay_status="CONDITIONAL_PATH_DEPENDENT_MODEL_ONLY",
                    own_buy_overlay_public_bank_replay_verified=replay_verified,
                    own_buy_overlay_observed_reserve_activity=reserve_activity,
                    own_buy_overlay_observed_source_reserve_deltas=reserve_deltas,
                    own_buy_overlay_sell_lamports=overlay_lamports,
                    own_buy_overlay_delta_before_extra_costs_lamports=str(delta),
                    own_buy_overlay_cost_scenarios=[
                        dict(assumed_extra_cost_lamports=str(cost),
                             conditional_net_lamports=str(delta-cost),
                             conditional_net_SOL=str((delta-cost)/1_000_000_000))
                        for cost in COST_STRESS_LAMPORTS],
                    own_buy_overlay_model_sha256=sized.get(
                        "s2_own_buy_overlay_receipt_sha256"))
            else:
                item["own_buy_overlay_refusal"]=sized.get(
                    "s2_own_buy_overlay_refusal","missing_or_unqualified_overlay")
        cases.append(item)
    overlay_quoted=sum(row["own_buy_overlay_status"]==
        "CONDITIONAL_PATH_DEPENDENT_MODEL_ONLY" for row in cases)
    overlay_source_replay_verified=sum(
        row["own_buy_overlay_public_bank_replay_verified"] is True for row in cases)
    overlay_with_actual_reserve_activity=sum(
        row["own_buy_overlay_observed_reserve_activity"] is True for row in cases)
    overlay_with_flat_reserves=sum(
        row["own_buy_overlay_observed_reserve_activity"] is False for row in cases)
    quoted=sum(row["status"]=="CONDITIONAL_MODEL_ROUNDTRIP_NOT_FILL"
               for row in cases)
    return dict(schema=SCHEMA,
        status=("REAL_SOL_S1S2_PAPER_MODEL_MARKOUTS" if quoted else
                "NO_COMPLETE_QUOTABLE_REAL_SOL_MODEL_ROUNDTRIP"),
        source="Helius_real_first_page_active_SOL_survivors_not_signed_creations",
        S1_source_slot=frozen["s1_slot"],
        S2_source_slot=research["second_bank_slot"],
        original_selection_sha256=research["registration_sha256"],
        frozen_before_followup_SHA256=_hash(frozen),
        exact_model_roundtrips=quoted,number_of_frozen_cases=len(cases),
        own_buy_overlay_conditional_models=overlay_quoted,
        own_buy_overlay_source_replay_verified_models=overlay_source_replay_verified,
        own_buy_overlay_models_with_actual_reserve_activity=overlay_with_actual_reserve_activity,
        own_buy_overlay_models_with_flat_source_reserves=overlay_with_flat_reserves,
        own_buy_overlay_uses_unobserved_counterfactual_reserves=True,
        own_buy_overlay_master_trades_executed=0,
        rejected_or_censored_models=len(cases)-quoted,
        size_lamports=SIZING_LAMPORTS,initial_cash_lamports=DEFAULT_CAPITAL_LAMPORTS,
        simulated_model_probe_not_actual_Master_strategy=True,
        actual_Master_research_executed_orders=0,
        actual_reference_executed_orders=0,
        conditional_costs_only_unknown_provider_fees=True,
        complete_post_buy_market_counterfactual_missing=True,
        exact_net_Master_pnl_lamports=None,
        exact_net_reference_pnl_lamports=None,
        measured_Master_minus_reference_edge_lamports=None,
        profitability_demonstrated=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        cases=cases)


def run(*,rpc,wait_seconds=12,sample_page=0,sleep=time.sleep):
    evidence=observe_active_survivor_cohort(rpc,
        wait_seconds=wait_seconds,sample_page=sample_page,
        sleep=sleep,prefer_root_activity=True,research_ladder=True,
        freeze_at_s1=_freeze_before_followup)
    if evidence.get("status")!="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE":
        return dict(schema=SCHEMA,status=evidence.get("status"),
            source_scan=evidence,financial_order_submitted=False,
            actual_Master_qualified_cycles=0,
            exact_net_Master_pnl_lamports=None)
    if evidence.get("selected_count")==0:
        # A predeclared SHA slice can have no viable active pools.
        # This is a normal denominator outcome, not a crash nor a trade.
        return dict(schema=SCHEMA,
            status="NO_QUALIFIED_ACTIVE_SOL_POOLS_IN_PREDECLARED_SLICE",
            source_evidence=evidence,
            paper_model_report=dict(
                status="NO_QUALIFIED_ACTIVE_SOL_POOLS_IN_PREDECLARED_SLICE",
                exact_model_roundtrips=0,number_of_frozen_cases=0,
                true_Master_net_pnl_lamports=None,
                measured_Master_minus_reference_edge_lamports=None,
                financial_order_submitted=False,profitability_demonstrated=False),
            financial_order_submitted=False,actual_Master_qualified_cycles=0,
            exact_net_Master_pnl_lamports=None)
    return dict(schema=SCHEMA,source_evidence=evidence,
                paper_model_report=evaluate_probe(evidence))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--sample-page",type=int,default=0)
    p.add_argument("--wait-seconds",type=int,default=12)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.network:
        p.error("explicit read-only --network required")
    if args.output.exists() or args.output.is_symlink():
        p.error("output artifact must be new")
    try:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=6,
            allow_active_pool_scan=True)
        result=run(rpc=rpc,wait_seconds=args.wait_seconds,
                   sample_page=args.sample_page)
        result["rpc_calls_used"]=rpc.count
        result["source_commitment"]="confirmed"
        result["financial_order_submitted"]=False
        result["live_ready_to_arm"]=False
        args.output.parent.mkdir(parents=True,exist_ok=True)
        atomic_write_json(args.output,result,sort_keys=True,allow_nan=False)
        report=result.get("paper_model_report",{})
        print(json.dumps(dict(status=report.get("status",result.get("status")),
            selected=result.get("source_evidence",{}).get("selected_count",0),
            source_slots=[report.get("S1_source_slot"),report.get("S2_source_slot")],
            conditional_model_roundtrips=report.get("exact_model_roundtrips",0),
            path_dependent_own_buy_overlay_models=report.get(
                "own_buy_overlay_conditional_models",0),
            actual_Master_full_cycles=0,Master_net_pnl=None,
            no_real_orders=True,artifact_sha256=hashlib.sha256(
            args.output.read_bytes()).hexdigest()),sort_keys=True))
        return 0
    except Exception as e:
        print(json.dumps(dict(status="SOURCE_OR_PROBE_REFUSED",
            safe_error_class=type(e).__name__,no_real_orders=True,
            Master_net_pnl=None),sort_keys=True))
        return 2


if __name__=="__main__":
    sys.exit(main())
