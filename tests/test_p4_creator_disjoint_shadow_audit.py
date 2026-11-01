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
