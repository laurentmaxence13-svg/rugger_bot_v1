"""Two-phase causal PAPER shadow ledger: freeze Master and reference BEFORE outcomes.

A valid signed creation and a provider price response are distinct facts. This
module cannot submit trades, open live positions or attest to executable fills.
Unknown costs, censored positions and failed exits remain missing liabilities;
never turn them into zero P&L or a positive strategy advantage.
"""
import hashlib
import json

ARMS=("master","reference")
ACTIONS=frozenset(("WAIT","REJECT","ENTER"))
SCHEMA="rugger-paired-shadow-causal-ledger-v1"


def _sha(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _num(value,name,*,zero=True):
    if type(value) is not int or value < (0 if zero else 1) or value>10**15:
        raise ValueError(name+"_invalid")
    return value


def freeze_pair(case):
    """Pure phase 1: results, post-entry states and S2 data not accepted."""
    if type(case) is not dict or set(case)!={
        "creator","mint","pool","source_slot","asof_ms",
        "features_available_at_ms","feature_receipt_sha256",
        "policy_sha256_master","policy_sha256_reference",
        "master_action","reference_action","hypothetical_buy_lamports",
        "source_clock_verified","signed_creator_verified"
    }:
        raise ValueError("exact_preoutcome_case_required")
    for k in ("creator","mint","pool"):
        if type(case[k]) is not str or not case[k]:
            raise ValueError("explicit_public_identity_required")
    for k in ("feature_receipt_sha256","policy_sha256_master","policy_sha256_reference"):
        if (type(case[k]) is not str or len(case[k])!=64
                or any(c not in "0123456789abcdef" for c in case[k])):
            raise ValueError("frozen_evidence_hash_required")
    asof=_num(case["asof_ms"],"asof",zero=False)
    feature=_num(case["features_available_at_ms"],"feature_clock",zero=False)
    if feature>asof:
        raise ValueError("future_features_forbidden")
    _num(case["source_slot"],"source_slot",zero=False)
    _num(case["hypothetical_buy_lamports"],"buy_size",zero=False)
    if (type(case["source_clock_verified"]) is not bool
            or type(case["signed_creator_verified"]) is not bool
            or case["master_action"] not in ACTIONS
            or case["reference_action"] not in ACTIONS):
        raise ValueError("causal_policy_decisions_required")
    # Policy SHA is an external identifier: execution of actual named scorers
    # must be independently audited, it cannot be proven by a hash alone.
    frozen=dict(schema=SCHEMA,phase="FROZEN_PRE_OUTCOME",
        asof_ms=asof,asof_slot=case["source_slot"],
        research_case=case,preregistered_master_action=case["master_action"],
        preregistered_reference_action=case["reference_action"],
        future_prices_consumed=False,
        decision_engines_independently_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)
    frozen["freeze_sha256"]=_sha(frozen)
    return frozen


def score_pair(frozen,outcome):
    """Phase 2: one shared quote tape, explicit exits/failure/open/costs."""
    if (type(frozen) is not dict or frozen.get("phase")!="FROZEN_PRE_OUTCOME"
            or frozen.get("schema")!=SCHEMA or type(frozen.get("research_case")) is not dict
            or frozen.get("future_prices_consumed") is not False
            or frozen.get("financial_order_submitted") is not False):
        raise ValueError("signed_frozen_paper_register_required")
    digest=frozen.get("freeze_sha256")
    if (type(digest) is not str or
        _sha({k:v for k,v in frozen.items() if k!="freeze_sha256"})!=digest):
        raise ValueError("preoutcome_freeze_integrity_mismatch")
    if type(outcome) is not dict or set(outcome)!={
        "source_slot","available_at_ms","entry_quote_lamports","exact_lot_atomic",
        "exit_kind","exit_quote_lamports","extra_costs_lamports",
        "failure_costs_lamports","provider_quote_source_clock_verified",
        "actual_fills_verified"
    }:
        raise ValueError("exact_followup_outcome_required")
    case=frozen["research_case"]
    at=_num(outcome["available_at_ms"],"outcome_time",zero=False)
    slot=_num(outcome["source_slot"],"outcome_slot",zero=False)
    if at<=case["asof_ms"] or slot<=case["source_slot"]:
        raise ValueError("followup_must_be_after_frozen_decision")
    if (type(outcome["provider_quote_source_clock_verified"]) is not bool
            or outcome["actual_fills_verified"] is not False):
        raise ValueError("provider_and_fills_must_be_explicit")
    lot=_num(outcome["exact_lot_atomic"],"exact_lot",zero=False)
    entry=_num(outcome["entry_quote_lamports"],"entry_quote",zero=False)
    if entry!=case["hypothetical_buy_lamports"]:
        raise ValueError("must_use_preregistered_same_buy_size")
    status=outcome["exit_kind"]
    if status not in ("FULL_QUOTE","FAILED_EXIT","OPEN_UNPRICED","MIGRATED_NO_QUOTE"):
        raise ValueError("exit_status_must_be_explicit")
    out=outcome["exit_quote_lamports"]
    if status=="FULL_QUOTE":
        _num(out,"sell_quote",zero=False)
    elif out is not None:
        raise ValueError("censored_exit_must_have_null_quote")
    costs=outcome["extra_costs_lamports"]
    failed=outcome["failure_costs_lamports"]
    if costs is not None:_num(costs,"extra_costs")
    if failed is not None:_num(failed,"failure_costs")
    pre_cost_delta=out-entry if status=="FULL_QUOTE" else None
    # Unknown costs are never implicitly zero. Sensitivity upper bound holds
    # only if additional applicable costs are nonnegative.
    conditional_net=(pre_cost_delta-costs-failed
                     if pre_cost_delta is not None and costs is not None and failed is not None
                     else None)
    results={}
    for arm in ARMS:
        action=case[arm+"_action"]
        if action!="ENTER":
            state="NO_POSITION_POLICY_ABSTAINED"
            # Abstaining incurs no entry, exit or failure costs for this
            # hypothetical position. Its conditional *incremental* P&L is
            # exactly zero; this is not a realized trading profit.
            projection=0
        elif status=="FULL_QUOTE":
            state="HYPOTHETICAL_FULL_EXIT_QUOTE_NOT_FILLED"
            projection=conditional_net
        else:
            state="HYPOTHETICAL_"+status
            projection=None
        results[arm]=dict(action_frozen_before_outcome=action,
            outcome_class=state,
            notional_model_lamports=entry if action=="ENTER" else 0,
            modelled_unfilled_exact_lot_atomic=lot if action=="ENTER" else None,
            delta_before_unknown_costs_lamports=pre_cost_delta if action=="ENTER" else None,
            conditional_net_if_all_costs_provided_lamports=projection,
            actual_realized_net_pnl_lamports=None,
            unrealized_open_position_pnl_lamports=None,
            capital_at_risk_real_lamports=0,
            hypothetical_inventory_is_not_real=True)
    # Distinguish a genuine conditional comparison of ENTER versus WAIT
    # from the older BOTH-ENTER-only diagnostic. Unpriced ENTER remains
    # censored, not a zero loss. Neither metric establishes actual edge.
    arm_pnl={arm:results[arm]["conditional_net_if_all_costs_provided_lamports"]
             for arm in ARMS}
    conditional_pair_edge=(arm_pnl["master"]-arm_pnl["reference"]
        if all(v is not None for v in arm_pnl.values()) else None)
    candidate_model_edge=(conditional_pair_edge
        if all(case[arm+"_action"]=="ENTER" for arm in ARMS) else None)
    return dict(schema=SCHEMA,phase="SCORED_PAPER_FOLLOWUP",
        freeze_sha256=digest,outcome_sha256=_sha(outcome),
        source_quote_time_validated=outcome["provider_quote_source_clock_verified"],
        master_and_reference=results,
        modelled_full_quote_delta_before_unknown_costs_lamports=pre_cost_delta,
        nonnegative_extra_costs_upper_bound_lamports=pre_cost_delta,
        conditional_cost_adjusted_delta_lamports=conditional_net,
        candidate_both_enter_illustrative_delta_lamports=candidate_model_edge,
        conditional_modelled_master_minus_reference_lamports=conditional_pair_edge,
        comparison_censored_due_to_unknown_enter_costs_or_exit=(
            conditional_pair_edge is None),
        decision_arms_with_hypothetical_entries=sum(
            case[arm+"_action"]=="ENTER" for arm in ARMS),
        conditional_comparison_is_not_realized_pnl=True,
        source_decision_clock_verified=case["source_clock_verified"],
        signed_creator_verified=case["signed_creator_verified"],
        independent_scoring_engines_verified=False,
        qualified_executed_economic_cycles=0,
        economically_validated_master_advantage_lamports=None,
        market_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)
