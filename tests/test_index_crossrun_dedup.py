"""No fake statistical independence from successive Raydium index captures."""
import pytest
from bot.p3.index_crossrun_dedup import deduplicate_index_reports


def report(*,mint="mintA",creator="creatorA",at=200000,created=100000):
    row=dict(source_row=dict(mint=mint,pool="pool-"+mint,
        creator_claim=creator,creation_time_claim_ms=created),
        selection_reason="selected_before_provider_outcomes")
    return dict(schema="p3-active-cohort-result-v1",
        qualified_economic_cycles=0,positions_acquired=0,net_pnl_sol=None,
        execution_verified=False,received_index_rows=100,source_revision="a"*40,
        requests_used=18,selection=dict(decision_at_ms=at,records=[row],selected_count=1))


def test_repeated_same_creator_mint_not_independent_or_profitable():
    x=deduplicate_index_reports([report(),report(at=300000)])
    assert x["captures"]==2
    assert x["reported_selected_observations"]==2
    assert x["unique_provider_claimed_mint_pool_pairs"]==1
    assert x["repeated_selected_observations"]==1
    assert x["independent_verified_signed_creation_creators"]==0
    assert x["selected_rows"][0]["provider_claimed_creation_age_ms"]==100000
    assert x["selected_rows"][1]["provider_claimed_creation_age_ms"]==200000
    assert x["master_net_pnl_lamports"] is None
    assert x["market_profitability_verified"] is False
    assert x["financial_order_submitted"] is False


def test_second_new_token_counts_as_new_claim_only():
    x=deduplicate_index_reports([report(),report(mint="mintB",creator="creatorB")])
    assert x["unique_provider_claimed_mint_pool_pairs"]==2
    assert x["unique_provider_claimed_creators"]==2
    assert x["independent_verified_signed_creation_creators"]==0


def test_conflicting_creator_claim_is_not_allowed():
    with pytest.raises(ValueError,match="conflicting_creator"):
        deduplicate_index_reports([report(),report(creator="unknown")])


def test_future_creation_claim_must_be_refused():
    with pytest.raises(ValueError,match="future_claimed_creation_clock"):
        deduplicate_index_reports([report(at=200000,created=200001)])


def test_active_book_or_fake_net_profit_refused():
    bad=report();bad["net_pnl_sol"]=0.5
    with pytest.raises(ValueError,match="unverified_or_active"):
        deduplicate_index_reports([bad])


def test_omitted_selected_row_refused():
    bad=report();bad["selection"]["records"]=[]
    with pytest.raises(ValueError,match="incomplete_frozen"):
        deduplicate_index_reports([bad])


def test_unbounded_input_refused_before_research():
    with pytest.raises(ValueError,match="bounded_cohort"):
        deduplicate_index_reports([report()]*21)
