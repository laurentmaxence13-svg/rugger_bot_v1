"""Offline tests: archived campaign overlaps are not independent creators or fills."""
import copy
import hashlib
import json
import pytest

from bot.live.helius_prospective_campaign import CAPTURE_SCHEMA, SCHEMA, _canonical
from bot.p3.cross_campaign_signed_cohort import audit_campaigns


def fixture(run,*,signature="sig",creator="creator",mint="mint",pool="pool",
            finalized=False):
    event=dict(signature=signature,slot=123,reception_utc_ns=1000000000000)
    attempt=dict(signature=signature,status="SIGNED_CONFIRMED_PROVISIONAL",
        signed_outer_creations=[dict(creator=creator,mint=mint,pool=pool)],
        creator=creator,mint=mint,pool=pool,
        finality_verified=finalized,
        frozen_pre_S2=dict(master_action="WAIT",reference_action="NOT_EVALUABLE"))
    report=dict(schema=CAPTURE_SCHEMA,attempts=[attempt],
        financial_order_submitted=False,live_ready_to_arm=False,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None)
    source=dict(events=[event],report=report)
    meta=dict(window=1,source_sha256=hashlib.sha256(_canonical(source).encode()).hexdigest(),
        observed_events=1,repeated_signatures_across_windows=0,
        inspected_attempts=1,verified_signed_launch_candidates=1,
        frozen_S1_decisions=1,conditional_model_markouts=0,
        newly_observed_creator_claims=1)
    summary=dict(schema=SCHEMA,windows_requested=1,windows=[meta],
        observed_events=1,observed_distinct_creator_claims=1,
        financial_order_submitted=False,master_net_pnl_lamports=None,
        live_ready_to_arm=False)
    return run,summary,[source]


def rehash(campaign):
    run,summary,windows=campaign
    summary["windows"][0]["source_sha256"]=hashlib.sha256(
        _canonical(windows[0]).encode()).hexdigest()
    return campaign


def test_one_creator_repeated_in_two_campaigns_not_two_creators():
    a=fixture(11)
    b=fixture(12,signature="different",mint="newMint",pool="newPool")
    x=audit_campaigns([a,b])
    assert x["total_observed_event_rows"]==2
    assert x["unique_observed_event_signatures"]==2
    assert x["unique_signed_creator_claims"]==1
    assert x["unique_signed_mint_pool_pairs"]==2
    assert sum(x["creator_split_counts"].values())==1
    assert x["independently_reverified_finalized_signed_creator_count"]==0
    assert x["qualified_master_reference_holdout_cycles"]==0
    assert x["market_profitability_verified"] is False
    assert x["master_minus_reference_net_pnl_lamports"] is None


def test_repeated_same_signed_creation_not_new_observation():
    x=audit_campaigns([fixture(11),fixture(12)])
    assert x["unique_observed_event_signatures"]==1
    assert x["cross_run_repeated_event_observations"]==1
    assert x["unique_signed_mint_pool_pairs"]==1
    assert x["unique_signed_creator_claims"]==1


def test_distinct_creators_have_one_immutable_group_each():
    x=audit_campaigns([fixture(11),fixture(12,signature="sig2",
        creator="creator2",mint="mint2",pool="pool2")])
    assert x["unique_signed_creator_claims"]==2
    assert len(x["creator_ids_public"])==2
    assert sum(x["creator_split_counts"].values())==2


def test_future_s2_data_does_not_change_precommitted_creator_assignment():
    a=fixture(11)
    b=copy.deepcopy(a)
    b[2][0]["report"]["attempts"][0]["s2_conditional_proceeds_lamports"]="999"
    rehash(b)
    assert (audit_campaigns([a])["creator_split_assignments_sha256"]==
            audit_campaigns([b])["creator_split_assignments_sha256"])


def test_upstream_finality_flag_does_not_count_as_independent_replay():
    a=fixture(11,finalized=True)
    x=audit_campaigns([a])
    assert x["source_reports"][0]["upstream_finality_asserted_creators"]==1
    assert x["independently_reverified_finalized_signed_creator_count"]==0
    assert x["holdout_independence_and_coverage_verified"] is False


def test_modified_source_window_without_matching_hash_rejected():
    a=fixture(11)
    a[2][0]["events"][0]["signature"]="tampered"
    with pytest.raises(ValueError,match="tampered_window"):
        audit_campaigns([a])


def test_inspected_signature_not_captured_rejected_even_with_rehash():
    a=fixture(11)
    a[2][0]["report"]["attempts"][0]["signature"]="unknown"
    rehash(a)
    with pytest.raises(ValueError,match="inspected_signature"):
        audit_campaigns([a])


def test_signed_attempt_claim_conflict_rejected():
    a=fixture(11)
    a[2][0]["report"]["attempts"][0]["creator"]="attacker"
    rehash(a)
    with pytest.raises(ValueError,match="signed_identity_disagree"):
        audit_campaigns([a])


def test_conflicting_creator_for_same_signed_signature_rejected():
    a=fixture(11)
    b=fixture(12,creator="anotherCreator")
    with pytest.raises(ValueError,match="contradictory_signed_creation_signature"):
        audit_campaigns([a,b])


def test_same_mint_pool_claimed_by_different_creator_rejected():
    a=fixture(11)
    b=fixture(12,signature="different",creator="anotherCreator")
    with pytest.raises(ValueError,match="contradictory_pool_creator"):
        audit_campaigns([a,b])


def test_duplicate_campaign_run_refused():
    with pytest.raises(ValueError,match="duplicate_or_invalid"):
        audit_campaigns([fixture(11),fixture(11)])


def test_unsafe_financial_report_rejected():
    a=fixture(11)
    a[1]["financial_order_submitted"]=True
    with pytest.raises(ValueError,match="unsafe_campaign"):
        audit_campaigns([a])


def test_more_than_twelve_campaigns_refused():
    with pytest.raises(ValueError,match="bounded_campaign"):
        audit_campaigns([fixture(i) for i in range(1,14)])


def test_no_synthetic_fills_from_positive_conditional_markout():
    a=fixture(11)
    a[2][0]["report"]["attempts"][0]["s1_s2_conditional_markout_lamports"]="10000"
    a[1]["windows"][0]["conditional_model_markouts"]=1
    rehash(a)
    x=audit_campaigns([a])
    assert x["source_reports"][0]["conditional_model_markouts"]==1
    assert x["actual_master_net_pnl_lamports"] is None
    assert x["actual_reference_net_pnl_lamports"] is None
    assert x["qualified_master_reference_holdout_cycles"]==0
