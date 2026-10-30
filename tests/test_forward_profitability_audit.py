"""Adversarial offline checks: no synthetic/unknown market path can arm LIVE."""
from copy import deepcopy

import pytest
from bot.p3.forward_profitability_audit import (
    audit_creator_paper_edge as audit,SCHEMA,SCENARIOS)


def arm(*, action="BUY", cash=100_000_000, proceeds=120_000_000,
        extra=100_000, state="CLOSED"):
    if action=="ABSTAIN":
        return dict(action="ABSTAIN",entry_spend_lamports=0,
            exit_receipts_lamports=0,additional_cost_lamports=0,
            exit_status="NO_TRADE",quote_evidence_sha256=None)
    return dict(action=action,entry_spend_lamports=cash,
        exit_receipts_lamports=proceeds,additional_cost_lamports=extra,
        exit_status=state,quote_evidence_sha256="a"*64)


def sample(*,creators=60,kind="synthetic",edge=30_000_000):
    rows=[]
    for index in range(creators):
        creator=f"creator-{index}"
        for fee,delay in SCENARIOS:
            rows.append(dict(opportunity_id=f"mint-{index}",creator_id=creator,
                signed_creation_sha256=f"{index+1:064x}",
                market_tape_sha256=f"{index+5001:064x}",
                fee_multiplier=fee,decision_delay_ms=delay,
                first_seen_at_ms=2000,decision_at_ms=2000+delay+1,
                outcome_at_ms=4000+delay,
                master=arm(proceeds=100_000_000+edge,
                           extra=100_000*fee),
                reference=arm(proceeds=100_000_000,extra=100_000*fee)))
    return dict(schema=SCHEMA,data_kind=kind,registered_at_ms=1000,
        registration_sha256="f"*64,
        development_creator_ids=["prior-creator"],
        full_creation_denominator_observed=True,
        receipts_cryptographically_checked=True,
        decisions_frozen_before_outcome=True,rows=rows)


def test_real_repository_without_market_rows_is_strict_no_go():
    evidence=sample(creators=0,kind="prospective_market_paper")
    report=audit(evidence)
    assert report["status"]=="NO_GO_REAL_PROFITABILITY_NOT_PROVEN"
    assert report["opportunities_in_denominator"]==0
    assert report["distinct_creator_claims"]==0
    assert report["statistically_credible_actual_profitability"] is False
    assert report["live_ready_to_arm"] is False


def test_synthetic_large_positive_result_does_not_claim_profit():
    result=audit(sample(kind="synthetic",edge=20_000_000))
    assert result["conditional_positive_every_scenario"] is True
    assert result["status"]=="NO_GO_REAL_PROFITABILITY_NOT_PROVEN"
    assert result["actual_bot_fills"]==0
    assert result["economic_edge_validated"] is False


def test_prespecified_market_proxy_still_requires_independent_review():
    example=sample(kind="prospective_market_paper")
    result=audit(example)
    assert result["conditional_positive_every_scenario"] is True
    assert result["status"]=="CONDITIONAL_PAPER_SIGNAL_FOR_INDEPENDENT_REVIEW"
    assert result["statistically_credible_actual_profitability"] is False
    assert result["has_actual_executable_lot_proof"] is False
    assert result["live_ready_to_arm"] is False
    assert all(
        v["clustered_bootstrap_p025_lower_lamports"]>0
        for v in result["scenarios"].values())


def test_real_paper_stress_with_negative_net_effect_blocks_promotion():
    example=sample(kind="prospective_market_paper",edge=-20_000_000)
    result=audit(example)
    assert result["conditional_positive_every_scenario"] is False
    assert all(
        v["clustered_bootstrap_p025_lower_lamports"]<0
        for v in result["scenarios"].values())
    assert result["status"]=="NO_GO_REAL_PROFITABILITY_NOT_PROVEN"


def test_repeated_tokens_from_one_creator_are_not_independent_creators():
    example=sample(creators=60,kind="prospective_market_paper")
    for x in example["rows"]:x["creator_id"]="one-and-only-creator"
    result=audit(example)
    assert result["distinct_creator_claims"]==1
    assert result["conditional_positive_every_scenario"] is False


def test_missing_scenario_does_not_drop_losing_creator():
    example=sample(kind="prospective_market_paper")
    example["rows"]=[x for x in example["rows"]
                     if not (x["opportunity_id"]=="mint-5" and
                             x["fee_multiplier"]==2 and x["decision_delay_ms"]==250)]
    result=audit(example)
    assert result["opportunities_in_denominator"]==60
    assert result["opportunities_missing_scenario"]==1
    assert result["conditional_positive_every_scenario"] is False


def test_open_positions_never_imputed_as_profitable():
    example=sample(kind="prospective_market_paper")
    for x in example["rows"]:
        if x["opportunity_id"]=="mint-10":
            x["master"]["exit_status"]="OPEN"
            x["master"]["exit_receipts_lamports"]=0
    result=audit(example)
    assert result["conditional_positive_every_scenario"] is False
    assert all(v["open_arm_positions"]==1 for v in result["scenarios"].values())


def test_creator_development_overlap_violates_holdout():
    example=sample(kind="prospective_market_paper")
    example["development_creator_ids"].append("creator-2")
    result=audit(example)
    assert result["holdout_creator_overlap_count"]==1
    assert result["conditional_positive_every_scenario"] is False


def test_declared_universe_completeness_must_not_be_inferred():
    example=sample(kind="prospective_market_paper")
    example["full_creation_denominator_observed"]=False
    assert audit(example)["conditional_positive_every_scenario"] is False


def test_same_opportunity_tape_changes_across_stress_are_rejected_from_positive():
    example=sample(kind="prospective_market_paper")
    example["rows"][1]["market_tape_sha256"]="b"*64
    result=audit(example)
    assert result["opportunities_with_inconsistent_identity_or_tape"]==1
    assert result["conditional_positive_every_scenario"] is False


def test_duplicate_scenario_refused_without_silent_drop():
    example=sample(kind="prospective_market_paper")
    example["rows"].append(deepcopy(example["rows"][0]))
    with pytest.raises(ValueError,match="duplicate_opportunity"):
        audit(example)


def test_quote_source_after_decision_not_allowed():
    example=sample()
    example["rows"][0]["decision_at_ms"]=1500
    with pytest.raises(ValueError,match="future_leak"):
        audit(example)
    example=sample()
    example["rows"][0]["outcome_at_ms"]=2000
    with pytest.raises(ValueError,match="future_leak"):
        audit(example)


def test_missing_quote_hash_and_faked_abstention_cashflow_refused():
    example=sample()
    example["rows"][0]["master"]["quote_evidence_sha256"]=None
    with pytest.raises(ValueError,match="buy_requires"):
        audit(example)
    example=sample()
    example["rows"][0]["master"]=arm(action="ABSTAIN")
    example["rows"][0]["master"]["exit_receipts_lamports"]=2_000_000
    with pytest.raises(ValueError,match="abstention"):
        audit(example)


def test_fee_and_lamport_types_must_be_strict_integers():
    example=sample()
    example["rows"][0]["master"]["additional_cost_lamports"]=1.5
    with pytest.raises(ValueError,match="unsigned_atomic"):
        audit(example)
    example=sample()
    example["rows"][0]["master"]["entry_spend_lamports"]=True
    with pytest.raises(ValueError,match="unsigned_atomic"):
        audit(example)


def test_bootstrap_is_reproducible_and_inputs_remain_unmodified():
    data=sample(kind="prospective_market_paper")
    before=deepcopy(data)
    first=audit(data)
    assert first==audit(data)
    assert data==before
    assert all(v["opportunities"]==60 for v in first["scenarios"].values())


def test_fee_double_stress_must_not_reduce_additional_cost():
    data=sample(kind="prospective_market_paper")
    for row in data["rows"]:
        if row["fee_multiplier"]==2 and row["opportunity_id"]=="mint-0":
            row["master"]["additional_cost_lamports"]=0
    result=audit(data)
    assert result["fee_stress_cost_monotonicity_violations"]==2
    assert result["conditional_positive_every_scenario"] is False
    assert result["status"]=="NO_GO_REAL_PROFITABILITY_NOT_PROVEN"
