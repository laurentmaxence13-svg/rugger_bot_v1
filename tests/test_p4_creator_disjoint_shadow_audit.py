"""No outcome-based exclusions or false profitability from prospective cohorts."""
from copy import deepcopy

import pytest

from bot.p4.paired_research_ledger import freeze_pair
from bot.p4.creator_disjoint_shadow_audit import audit_creator_disjoint_shadow, _split


def protocol():
    return dict(schema="rugger-creator-disjoint-prospective-protocol-v1",
        registered_at_ms=1000,split_salt_sha256="6"*64,
        holdout_modulus=10,holdout_buckets=[0,1,2,3,4,5,6],
        minimum_holdout_creators=50,minimum_qualified_cycles=50,
        position_horizon_ms=120000,financial_orders_allowed=False)


def case(i=0,*,creator=None,master="ENTER",reference="WAIT",signed=True,clock=True):
    at=2000+i*100
    frozen=freeze_pair(dict(creator=creator or "creator"+str(i),
        mint="mint"+str(i),pool="pool"+str(i),source_slot=100+i,
        asof_ms=at,features_available_at_ms=at-20,
        feature_receipt_sha256="a"*64,
        policy_sha256_master="b"*64,policy_sha256_reference="c"*64,
        master_action=master,reference_action=reference,
        hypothetical_buy_lamports=100000000,
        source_clock_verified=clock,signed_creator_verified=signed))
    return dict(frozen_pair=frozen,followup=None,engine_trace=None)


def followup(i=0,*,exit_kind="FULL_QUOTE",fees=10000,failed=5000,
             source_clock=True,sell=110000000):
    return dict(source_slot=101+i,available_at_ms=3000+i*100,
        entry_quote_lamports=100000000,exact_lot_atomic=5000000,
        exit_kind=exit_kind,exit_quote_lamports=sell if exit_kind=="FULL_QUOTE" else None,
        extra_costs_lamports=fees,failure_costs_lamports=failed,
        provider_quote_source_clock_verified=source_clock,
        actual_fills_verified=False)


def test_missing_followup_is_retained_and_blocks_all_case_edge():
    r1=case();r1["followup"]=followup()
    r2=case(1)
    x=audit_creator_disjoint_shadow([r1,r2],protocol())
    a=x["splits"]
    assert sum(y["distinct_pool_pairs"] for y in a.values())==2
    assert sum(y["missing_followup"] for y in a.values())==1
    assert sum(y["cases_with_unknown_model_edge"] for y in a.values())==1
    assert x["actual_master_minus_reference_net_pnl_lamports"] is None
    assert x["empirical_net_master_advantage_verified"] is False
    assert x["independently_verified_executed_economic_cycles"]==0


def test_master_enter_reference_wait_conditional_edge_only():
    row=case();row["followup"]=followup()
    x=audit_creator_disjoint_shadow([row],protocol())
    r=x["rows"][0]
    assert r["conditional_model_master_lamports"]==9985000
    assert r["conditional_model_reference_lamports"]==0
    assert r["conditional_model_master_minus_reference_lamports"]==9985000
    assert r["independently_authenticated_provider_clock"] is False
    assert r["actual_fill_verified"] is False
    assert x["empirical_net_master_advantage_verified"] is False


def test_both_enter_have_zero_difference_on_same_quote():
    row=case(reference="ENTER");row["followup"]=followup()
    x=audit_creator_disjoint_shadow([row],protocol())
    assert x["rows"][0]["conditional_model_master_minus_reference_lamports"]==0
    assert x["actual_master_minus_reference_net_pnl_lamports"] is None


@pytest.mark.parametrize("status",["OPEN_UNPRICED","FAILED_EXIT","MIGRATED_NO_QUOTE"])
def test_failed_and_open_positions_never_become_zero_return(status):
    row=case();row["followup"]=followup(exit_kind=status)
    x=audit_creator_disjoint_shadow([row],protocol())
    r=x["rows"][0]
    assert r["followup_class"]==status
    assert r["conditional_model_master_minus_reference_lamports"] is None
    assert sum(s["cases_with_unknown_model_edge"] for s in x["splits"].values())==1


def test_unknown_costs_keep_delta_null_even_with_positive_gross_quote():
    row=case();row["followup"]=followup(fees=None,failed=0)
    x=audit_creator_disjoint_shadow([row],protocol())
    assert x["rows"][0]["conditional_model_master_minus_reference_lamports"] is None


def test_one_creator_with_many_tokens_is_one_group_and_one_split():
    a=case(0,creator="one");b=case(1,creator="one")
    x=audit_creator_disjoint_shadow([a,b],protocol())
    assert x["unique_claimed_creators"]==1
    assert x["rows"][0]["split"]==x["rows"][1]["split"]
    assert sum(y["creator_groups_claimed"] for y in x["splits"].values())==1


def test_same_pool_cannot_be_counted_as_independent_again():
    a=case();b=deepcopy(a)
    b["followup"]=followup()
    with pytest.raises(ValueError,match="repeated_token_pool"):
        audit_creator_disjoint_shadow([a,b],protocol())


def test_future_registered_protocol_blocks_old_quotes_and_decisions():
    with pytest.raises(ValueError,match="predates_registered"):
        audit_creator_disjoint_shadow([case()],dict(protocol(),registered_at_ms=2000))


def test_reordered_decisions_refused_not_resorted_with_hindsight():
    with pytest.raises(ValueError,match="chronologically_complete"):
        audit_creator_disjoint_shadow([case(1),case(0)],protocol())


def test_tampered_frozen_action_cannot_be_rescored():
    row=case();row["frozen_pair"]["research_case"]["master_action"]="WAIT"
    with pytest.raises(ValueError,match="digest_mismatch"):
        audit_creator_disjoint_shadow([row],protocol())


def test_horizon_must_be_frozen_not_chosen_after_price():
    row=case();row["followup"]=followup()
    row["followup"]["available_at_ms"]=122001
    with pytest.raises(ValueError,match="outside_preregistered_horizon"):
        audit_creator_disjoint_shadow([row],protocol())


def test_source_clock_false_never_qualified():
    row=case(clock=False);row["followup"]=followup()
    x=audit_creator_disjoint_shadow([row],protocol())
    assert x["rows"][0]["all_required_clocks_self_attested"] is False
    assert x["empirical_net_master_advantage_verified"] is False


def test_unsigned_provider_creator_is_not_verified_independent_group():
    row=case(signed=False);row["followup"]=followup()
    x=audit_creator_disjoint_shadow([row],protocol())
    assert sum(s["creator_groups_signed_verified"] for s in x["splits"].values())==0
    assert x["empirical_net_master_advantage_verified"] is False


def test_nonmatching_engine_trace_refused():
    row=case();row["engine_trace"]=dict(schema="rugger-real-engines-frozen-shadow-intents-v1",
        frozen_pair=case(1)["frozen_pair"],actual_engines_called_before_outcome=True,
        financial_order_submitted=False)
    with pytest.raises(ValueError,match="engine_trace_must_match"):
        audit_creator_disjoint_shadow([row],protocol())


def test_fake_verified_fills_never_allowed():
    row=case();row["followup"]=followup()
    row["followup"]["actual_fills_verified"]=True
    with pytest.raises(ValueError,match="provider_and_fills"):
        audit_creator_disjoint_shadow([row],protocol())


def test_even_hundred_synthetic_positive_quotes_cannot_prove_real_edge():
    rows=[case(i) for i in range(100)]
    for i,row in enumerate(rows):
        row["followup"]=followup(i)
    x=audit_creator_disjoint_shadow(rows,protocol())
    assert x["total_cases_including_missing"]==100
    assert x["unique_claimed_creators"]==100
    assert x["independently_verified_executed_economic_cycles"]==0
    assert x["qualified_holdout_economic_cycles_requirement_reached"] is False
    assert x["actual_master_minus_reference_net_pnl_lamports"] is None
    assert x["empirical_net_master_advantage_verified"] is False
    assert x["live_ready_to_arm"] is False


def test_bad_protocol_cannot_reduce_holdout_or_requirements():
    bad=dict(protocol(),minimum_holdout_creators=2)
    with pytest.raises(ValueError,match="complete_frozen"):
        audit_creator_disjoint_shadow([],bad)


def test_empty_cohort_does_not_claim_zero_pnl():
    x=audit_creator_disjoint_shadow([],protocol())
    assert x["total_cases_including_missing"]==0
    assert x["splits"]["holdout"]["all_cases_conditional_edge_sum_lamports"] is None
    assert x["actual_master_minus_reference_net_pnl_lamports"] is None


def test_creator_assignment_stable_and_outcome_independent():
    p=protocol()
    assert _split("creator-one",p)==_split("creator-one",p)
    a=case(0,creator="creator-one");b=deepcopy(a)
    b["followup"]=followup()
    assert audit_creator_disjoint_shadow([a],p)["rows"][0]["split"]==(
        audit_creator_disjoint_shadow([b],p)["rows"][0]["split"])


def test_self_attested_creator_flags_cannot_satisfy_verified_holdout_threshold():
    rows=[case(i,signed=True) for i in range(200)]
    result=audit_creator_disjoint_shadow(rows,protocol())
    assert result["splits"]["holdout"]["creator_groups_signed_self_attested"]>=50
    assert result["holdout_minimum_signed_self_attested_creator_groups_reached"] is True
    assert result["holdout_minimum_verified_creator_groups_reached"] is False
    assert result["splits"]["holdout"]["creator_groups_independently_verified"]==0
    assert result["creator_signature_proofs_independently_revalidated"] is False
    assert result["complete_creation_denominator_externally_verified"] is False
    assert result["empirical_net_master_advantage_verified"] is False



def test_censored_entry_capital_not_discarded_when_master_enter_reference_wait():
    open_case=case()
    open_case["followup"]=followup(exit_kind="OPEN_UNPRICED")
    missing_case=case(1)
    resolved_case=case(2)
    resolved_case["followup"]=followup(2)
    x=audit_creator_disjoint_shadow([open_case,missing_case,resolved_case],protocol())
    assert sum(s["master_modelled_entry_notional_lamports"]
               for s in x["splits"].values())==300_000_000
    assert sum(s["master_censored_entry_notional_lamports"]
               for s in x["splits"].values())==200_000_000
    assert sum(s["reference_modelled_entry_notional_lamports"]
               for s in x["splits"].values())==0
    assert sum(s["reference_censored_entry_notional_lamports"]
               for s in x["splits"].values())==0
    assert x["actual_master_minus_reference_net_pnl_lamports"] is None


def test_both_enter_censored_exposure_is_reported_for_both_arms():
    r=case(reference="ENTER")
    r["followup"]=followup(exit_kind="FAILED_EXIT")
    x=audit_creator_disjoint_shadow([r],protocol())
    row=x["rows"][0]
    assert row["master_censored_entry_notional_lamports"]==100_000_000
    assert row["reference_censored_entry_notional_lamports"]==100_000_000
    assert row["conditional_model_master_minus_reference_lamports"] is None


def test_full_exit_quote_without_costs_still_censors_entry_exposure():
    r=case()
    r["followup"]=followup(fees=None)
    x=audit_creator_disjoint_shadow([r],protocol())
    row=x["rows"][0]
    assert row["complete_exit_quote_but_missing_costs"] is True
    assert row["master_censored_entry_notional_lamports"]==100_000_000
    assert sum(s["complete_exit_quote_but_missing_costs"]
               for s in x["splits"].values())==1
    assert x["empirical_net_master_advantage_verified"] is False


def test_wait_wait_never_creates_censored_exposure():
    r=case(master="WAIT",reference="WAIT")
    x=audit_creator_disjoint_shadow([r],protocol())
    row=x["rows"][0]
    assert row["master_hypothetical_entry_notional_lamports"]==0
    assert row["reference_hypothetical_entry_notional_lamports"]==0
    assert row["master_censored_entry_notional_lamports"]==0
    assert row["reference_censored_entry_notional_lamports"]==0


def _matching_trace(row):
    frozen=row["frozen_pair"]
    case_data=frozen["research_case"]
    master={"ENTER":"ENTER","WAIT":"WAIT","REJECT":"NO_TRADE"}[case_data["master_action"]]
    return dict(schema="rugger-real-engines-frozen-shadow-intents-v1",
        frozen_pair=deepcopy(frozen),
        common_feature_frame_hash=case_data["feature_receipt_sha256"],
        original_master_action=master,
        original_reference_enter_intent=case_data["reference_action"]=="ENTER",
        master_decision_sha256="a"*64,reference_intent_sha256="b"*64,
        reference_decision_scope="scorer_intent_without_operational_admission",
        master_decision_scope="actual_master_shadow_full_evidence_and_capital_gate",
        source_signed_creator_verified=case_data["signed_creator_verified"],
        source_provider_price_clock_verified=case_data["source_clock_verified"],
        no_independent_executable_orders=True,
        prospective_strategy_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        actual_engines_called_before_outcome=True)


def test_full_matching_real_engine_trace_is_structurally_accepted_not_cryptographically_proven():
    row=case()
    row["engine_trace"]=_matching_trace(row)
    report=audit_creator_disjoint_shadow([row],protocol())
    assert report["rows"][0]["engine_adapter_trace_present"] is True
    assert report["source_protocol_registration_externally_verified"] is False
    assert report["empirical_net_master_advantage_verified"] is False


@pytest.mark.parametrize("key,bad",[
    ("common_feature_frame_hash","f"*64),
    ("original_master_action","WAIT"),
    ("original_reference_enter_intent",True),
    ("master_decision_sha256","bad-hash"),
    ("reference_intent_sha256",None),
    ("source_signed_creator_verified",False),
    ("source_provider_price_clock_verified",False),
    ("no_independent_executable_orders",False),
    ("prospective_strategy_profitability_verified",True),
    ("live_ready_to_arm",True),
    ("reference_decision_scope","actual_execution"),
    ("master_decision_scope","unverified_reference")
])
def test_forged_engine_trace_rejected_even_with_correct_frozen_pair(key,bad):
    row=case()
    row["engine_trace"]=_matching_trace(row)
    row["engine_trace"][key]=bad
    with pytest.raises(ValueError,match="engine_trace_must_match"):
        audit_creator_disjoint_shadow([row],protocol())


def test_disagreement_counts_and_hypothetical_capital_delta_include_censored_cases():
    rows=[case(0,master="ENTER",reference="WAIT"),
          case(1,master="WAIT",reference="ENTER"),
          case(2,master="ENTER",reference="ENTER"),
          case(3,master="WAIT",reference="REJECT")]
    result=audit_creator_disjoint_shadow(rows,protocol())
    counts={k:sum(x["frozen_action_pair_counts"][k] for x in result["splits"].values())
            for k in ("MASTER_ONLY_ENTER","REFERENCE_ONLY_ENTER","BOTH_ENTER","BOTH_ABSTAIN")}
    assert counts==dict(MASTER_ONLY_ENTER=1,REFERENCE_ONLY_ENTER=1,
                        BOTH_ENTER=1,BOTH_ABSTAIN=1)
    assert sum(x["frozen_action_disagreements"] for x in result["splits"].values())==2
    assert sum(x["hypothetical_entry_notional_master_minus_reference_lamports"]
               for x in result["splits"].values())==0
    assert result["actual_master_minus_reference_net_pnl_lamports"] is None


def test_unknown_outcome_sensitivity_requires_break_even_not_zero_imputation():
    # Same creator => both records in the same split. One fully costed
    # conditional quote plus one censored case must not produce a winner.
    rows=[case(0,creator="same"),case(1,creator="same")]
    rows[0]["followup"]=followup(0,sell=90_000_000)
    result=audit_creator_disjoint_shadow(rows,protocol())
    split=result["rows"][0]["split"]
    stats=result["splits"][split]
    assert stats["cases_with_complete_conditional_model_edge"]==1
    assert stats["cases_with_unknown_model_edge"]==1
    assert stats["conditional_complete_case_only_edge_sum_lamports"]==-10_015_000
    assert stats["minimum_mean_unknown_edge_for_strictly_positive_conditional_total_lamports"]==10_015_001
    assert stats["missing_edge_is_unbounded_without_fee_and_exit_assumptions"] is True
    assert stats["all_cases_conditional_edge_sum_lamports"] is None
    assert result["empirical_net_master_advantage_verified"] is False


def test_all_conditional_rows_do_not_invent_unknown_mean_or_real_profit():
    row=case();row["followup"]=followup()
    result=audit_creator_disjoint_shadow([row],protocol())
    split=result["rows"][0]["split"]
    stats=result["splits"][split]
    assert stats["minimum_mean_unknown_edge_for_strictly_positive_conditional_total_lamports"] is None
    assert stats["missing_edge_is_unbounded_without_fee_and_exit_assumptions"] is False
    assert stats["all_cases_conditional_edge_sum_lamports"]==9_985_000
    assert result["empirical_net_master_advantage_verified"] is False


def test_rehashed_future_feature_clock_cannot_bypass_causal_freeze_without_followup():
    from bot.p4.paired_research_ledger import _sha
    row=case()
    frozen=row["frozen_pair"]
    frozen["research_case"]["features_available_at_ms"]=frozen["research_case"]["asof_ms"]+1
    frozen["freeze_sha256"]=_sha({k:v for k,v in frozen.items() if k!="freeze_sha256"})
    with pytest.raises(ValueError,match="frozen_decision_payload_not_causal"):
        audit_creator_disjoint_shadow([row],protocol())


def test_rehashed_noncanonical_freeze_cannot_claim_engine_independence():
    from bot.p4.paired_research_ledger import _sha
    row=case()
    frozen=row["frozen_pair"]
    frozen["decision_engines_independently_verified"]=True
    frozen["freeze_sha256"]=_sha({k:v for k,v in frozen.items() if k!="freeze_sha256"})
    with pytest.raises(ValueError,match="noncanonical_or_forged"):
        audit_creator_disjoint_shadow([row],protocol())


def test_rehashed_future_source_clock_and_missing_followup_still_rejected():
    from bot.p4.paired_research_ledger import _sha
    row=case()
    frozen=row["frozen_pair"]
    frozen["research_case"]["source_slot"]=-1
    frozen["asof_slot"]=-1
    frozen["freeze_sha256"]=_sha({k:v for k,v in frozen.items() if k!="freeze_sha256"})
    with pytest.raises(ValueError,match="frozen_decision_payload_not_causal"):
        audit_creator_disjoint_shadow([row],protocol())
