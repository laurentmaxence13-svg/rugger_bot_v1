"""Index universe freshness must not inflate independent creator sample."""
from copy import deepcopy
import pytest
from bot.p3.index_universe_overlap import audit_index_universes

SOL="So11111111111111111111111111111111111111112"

def report(clock=1000,extra=None):
    rows=[dict(universe_index=n,source_row=dict(mint="mint"+str(n),pool="pool"+str(n),
        creator_claim="creator"+str(n),quote_mint_claim=SOL,
        creation_time_claim_ms=100)) for n in range(2)]
    if extra is not None:
        rows.append(dict(universe_index=2,source_row=dict(mint=extra,
            pool="pool-"+extra,creator_claim="newCreator",
            quote_mint_claim=SOL,creation_time_claim_ms=900)))
    return dict(schema="p3-active-cohort-result-v1",positions_acquired=0,
        qualified_economic_cycles=0,net_pnl_sol=None,execution_verified=False,
        received_index_rows=len(rows),selection=dict(
            decision_at_ms=clock,records=rows))


def test_identical_pages_do_not_create_new_tokens_or_creators():
    x=audit_index_universes([report(),report(clock=2000)])
    assert x["captures"]==2
    assert x["total_index_observations"]==4
    assert x["unique_provider_claimed_token_pool_pairs"]==2
    assert x["unique_provider_claimed_creator_ids"]==2
    assert x["sources"][1]["identical_page_to_previous"] is True
    assert x["sources"][1]["newly_observed_token_pool_pairs"]==0
    assert x["sources"][1]["overlap_with_previous_page"]==2
    assert x["authentic_signed_creation_creator_ids"] is None
    assert x["master_net_pnl_lamports"] is None
    assert x["market_profitability_verified"] is False


def test_one_new_token_does_not_count_old_ones_again():
    x=audit_index_universes([report(),report(clock=2000,extra="mintNew")])
    assert x["total_index_observations"]==5
    assert x["unique_provider_claimed_token_pool_pairs"]==3
    assert x["sources"][1]["newly_observed_token_pool_pairs"]==1
    assert x["sources"][1]["overlap_with_previous_page"]==2


def test_out_of_order_capture_refused():
    with pytest.raises(ValueError,match="strictly_chronological"):
        audit_index_universes([report(2000),report(1000)])


def test_same_pool_conflicting_creator_refused():
    a=report();b=report(2000)
    b["selection"]["records"][1]["source_row"]["creator_claim"]="attacker"
    with pytest.raises(ValueError,match="contradictory_creator"):
        audit_index_universes([a,b])


def test_outcome_ledger_cannot_contaminate_universe():
    r=report();r["positions_acquired"]=1
    with pytest.raises(ValueError,match="untraded"):
        audit_index_universes([r])


def test_missing_one_discovered_row_refused():
    r=report();r["selection"]["records"].pop()
    with pytest.raises(ValueError,match="complete_source_universe"):
        audit_index_universes([r])


def test_new_unavailable_provider_clock_not_recast_as_creation():
    r=report();r["selection"]["records"][0]["source_row"]["creation_time_claim_ms"]=None
    with pytest.raises(ValueError,match="provider_creation_time"):
        audit_index_universes([r])


def test_unbounded_history_refused():
    with pytest.raises(ValueError,match="bounded"):
        audit_index_universes([report(i+1000) for i in range(21)])


def test_reordered_same_page_is_not_identical_but_still_no_new_creators():
    a=report();b=report(2000)
    b["selection"]["records"].reverse()
    for i,row in enumerate(b["selection"]["records"]):
        row["universe_index"]=i
    x=audit_index_universes([a,b])
    assert x["sources"][1]["identical_page_to_previous"] is False
    assert x["sources"][1]["newly_observed_token_pool_pairs"]==0
    assert x["sources"][1]["overlap_with_previous_page"]==2
