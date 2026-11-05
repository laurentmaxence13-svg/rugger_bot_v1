"""Strict read-only completeness gate for prospective Master/reference claims.

This gate never authorizes trading. A passing software regression, public
pool scan, modelled S1/S2 quote or success on synthetic P4 fixtures cannot
stand in for a 50-independent-creator real-market out-of-sample cohort.
"""
import json
import sys
from pathlib import Path

REQUIRED_HOLDOUT_CREATORS=50
REQUIRED_STRESS_SCENARIOS=((1,0),(2,0),(1,250),(2,250))

def evaluate_master_oos_readiness(benchmark,comparison,cohort):
    if (type(benchmark) is not dict or type(comparison) is not dict
            or type(cohort) is not dict):
        raise ValueError("explicit_three_evidence_sources_required")
    if benchmark.get("schema")!="rugger-master-v2-final-validation-v1":
        raise ValueError("verified_Master_benchmark_schema_required")
    if comparison.get("schema")!="master-v2-fixture-measurements-v1":
        raise ValueError("explicit_Master_comparison_fixture_schema_required")
    # Source-tagged development/validation cohort, NEVER inferred from
    # repeated quotes, S1/S2 slots, synthetic tests or modelled PnL.
    statuses={}
    statuses["real_observation_comparison_not_synthetic"]=(
        comparison.get("data_kind")=="market_observation")
    statuses["minimum_fifty_independent_verified_holdout_creators"]=(
        type(cohort.get("independently_verified_holdout_creator_count")) is int
        and cohort["independently_verified_holdout_creator_count"]>=REQUIRED_HOLDOUT_CREATORS
        and cohort.get("signed_creation_receipts_verified") is True
        and cohort.get("discovery_denominator_complete") is True
        and cohort.get("inactive_failed_launches_included") is True)
    statuses["temporal_holdout_and_creator_nonoverlap_proven"]=(
        cohort.get("decisions_frozen_before_outcomes") is True
        and cohort.get("development_validation_creators_disjoint") is True
        and cohort.get("outside_sample_after_development") is True)
    statuses["exact_lot_sell_outcomes_and_all_costs_observed"]=(
        cohort.get("exact_buy_inventory_and_sell_lot_verified") is True
        and cohort.get("all_market_fees_network_costs_known") is True
        and cohort.get("failed_exits_and_open_positions_reported") is True
        and cohort.get("no_unqualified_or_imputed_missing_outcomes") is True)
    statuses["real_qualified_cycle_count"]=(
        type(benchmark.get("strict_market_economic_cycles")) is int
        and benchmark["strict_market_economic_cycles"]>=REQUIRED_HOLDOUT_CREATORS
        and type(cohort.get("qualifying_creator_cycles")) is int
        and cohort["qualifying_creator_cycles"]>=REQUIRED_HOLDOUT_CREATORS)
    statuses["same_market_tape_and_identical_financial_accounting"]=(
        cohort.get("same_observations_for_both_engines") is True
        and cohort.get("same_financial_accountant_for_both") is True)
    # Repeated outcomes of the same creator or size do not increase sample N.
    # Stress-scenario evidence must be independent of discovery/optimization.
    scenarios=cohort.get("qualified_holdout_scenarios")
    statuses["four_prespecified_fee_delay_stress_checks"]=(
        type(scenarios) is list and len(scenarios)==4
        and set(tuple(x) for x in scenarios if type(x) in (list,tuple) and len(x)==2)
            ==set(REQUIRED_STRESS_SCENARIOS))
    statuses["positive_net_outofsample_lower_bound_master_vs_reference"]=(
        cohort.get("bootstrap_lower_bound_on_creator_clustered_net_delta_lamports") is not None
        and type(cohort.get("bootstrap_lower_bound_on_creator_clustered_net_delta_lamports")) is int
        and cohort["bootstrap_lower_bound_on_creator_clustered_net_delta_lamports"]>0
        and cohort.get("net_advantage_over_reference_after_all_costs") is True)
    # Existing P4 fixture cannot self-promote merely because the Master
    # wins on a synthetic input, even if confidence fields are injected.
    statuses["existing_benchmark_confirms_market_validation"]=(
        benchmark.get("promotion_allowed") is True
        and benchmark.get("new_market_observations",0)>=REQUIRED_HOLDOUT_CREATORS)
    satisfied=sum(v is True for v in statuses.values())
    return dict(schema="rugger-master-strict-holdout-readiness-v1",
        status="NO_GO_INSUFFICIENT_VERIFIED_MARKET_COHORT" if satisfied<len(statuses)
            else "EXTERNAL_ECONOMIC_AUDIT_REQUIRED",
        checklist=statuses,passed=satisfied,total=len(statuses),
        minimum_distinct_holdout_creators=REQUIRED_HOLDOUT_CREATORS,
        real_executed_orders=0,
        represents_real_profitability_certification=False,
        live_ready_to_arm=False,financial_order_submitted=False,
        independent_security_signoff_required=True)

def main():
    root=Path(__file__).resolve().parents[2]
    benchmark=json.loads((root/"validation/master_v2/FINAL_VALIDATION.json").read_text())
    fixture=json.loads((root/"validation/master_v2/COMPARISON_SUMMARY.json").read_text())
    # Sources not present are UNKNOWN and must remain false; this is not an
    # imputation of a dataset or an inference from a successful RPC scan.
    result=evaluate_master_oos_readiness(benchmark,fixture,cohort={})
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"]=="NO_GO_INSUFFICIENT_VERIFIED_MARKET_COHORT" else 2

if __name__=="__main__":
    sys.exit(main())
