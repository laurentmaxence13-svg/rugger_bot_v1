"""No mixing signed creation claims with unlabeled quote or invented PnL."""
import copy
import pytest

from bot.p3.index_proof_quote_join import join_signed_index_quotes

MINT="mint-one"
POOL="pool-one"
CREATOR="creator-one"
TAIL="f"*64

def fixtures():
    index=dict(schema="p3-active-cohort-result-v1",
        qualified_economic_cycles=0,net_pnl_sol=None,tail_hash=TAIL,
        selection=dict(selected_count=1,records=[dict(
            selection_reason="selected_before_provider_outcomes",
            source_row=dict(mint=MINT,pool=POOL,creator_claim=CREATOR))]))
    audit=dict(schema="rugger-index-provider-exact-lot-roundtrip-audit-v1",
        qualified_economic_cycles=0,master_net_pnl_lamports=None,
        source_capture_tail_hash=TAIL,rows=[dict(mint=MINT,creator_claim=CREATOR,
            hypothetical_buy_sol_lamports="100000000",
            provider_roundtrip_deltas=[dict(
                status="INDICATIVE_FULL_EXACT_LOT_QUOTE_ONLY",
                position_acquired=False,quote_execution_guaranteed=False,
                source_timestamp_or_slot_available=False,phase="followup",
                estimated_sell_sol_lamports="96918845",
                delta_before_unknown_costs_lamports="-3081155")])])
    proof=dict(schema="rugger-pinned-index-creators-finalized-proof-v1",
        financial_order_submitted=False,qualified_economic_cycles=0,
        records=[dict(status="EXACT_OUTER_SIGNED_CREATION_VERIFIED",
            mint=MINT,pool=POOL,creator=CREATOR,signature="sig",
            verified_exact_message_sha256="a"*64,
            signed_outer_creations=[dict(mint=MINT,pool=POOL,creator=CREATOR)])])
    return index,audit,proof


def test_signed_and_indicative_quote_can_be_joined_without_filled_profit():
    x=join_signed_index_quotes(*fixtures())
    assert x["cryptographically_authenticated_selected_creators"]==1
    assert x["matched_full_lot_quote_scenarios"]==1
    assert x["rows"][0]["indicative_full_lot_quote_scenarios"][0][
        "conditional_delta_before_unknown_costs_lamports"]=="-3081155"
    assert x["qualified_economic_cycles"]==0
    assert x["master_net_pnl_lamports"] is None
    assert x["market_profitability_verified"] is False
    assert x["financial_order_submitted"] is False


def test_signed_creator_mismatch_never_fabricates_identical_identity():
    a,b,c=fixtures()
    c["records"][0]["creator"]="intruder"
    with pytest.raises(ValueError,match="tampered|conflict"):
        join_signed_index_quotes(a,b,c)


def test_quote_and_journal_mismatch_refused():
    a,b,c=fixtures()
    b["source_capture_tail_hash"]="e"*64
    with pytest.raises(ValueError,match="cross_evidence_contract"):
        join_signed_index_quotes(a,b,c)


def test_unverified_creation_not_counted_but_quote_retained():
    a,b,c=fixtures()
    c["records"][0]["status"]="SIGNED_OUTER_CREATION_ABSENT"
    x=join_signed_index_quotes(a,b,c)
    assert x["cryptographically_authenticated_selected_creators"]==0
    assert x["matched_full_lot_quote_scenarios"]==1
    assert x["rows"][0]["proof_signature"] is None
    assert x["market_profitability_verified"] is False


def test_claimed_executed_position_refused():
    a,b,c=fixtures()
    b["rows"][0]["provider_roundtrip_deltas"][0]["position_acquired"]=True
    with pytest.raises(ValueError,match="unreliable_paper_quote"):
        join_signed_index_quotes(a,b,c)


def test_quoted_mint_cannot_be_substituted():
    a,b,c=fixtures()
    b["rows"][0]["mint"]="different"
    with pytest.raises(ValueError,match="quote_mint_not_in_frozen"):
        join_signed_index_quotes(a,b,c)


def test_duplicate_selected_mint_is_not_independent_sample():
    a,b,c=fixtures()
    a["selection"]["records"].append(copy.deepcopy(a["selection"]["records"][0]))
    with pytest.raises(ValueError,match="duplicate_or_invalid"):
        join_signed_index_quotes(a,b,c)


def test_two_signed_launches_from_same_creator_count_one_independent_group():
    a,b,c=fixtures()
    row=copy.deepcopy(a["selection"]["records"][0])
    row["source_row"]["mint"]="mint-two"
    row["source_row"]["pool"]="pool-two"
    a["selection"]["records"].append(row)
    a["selection"]["selected_count"]=2
    quote=copy.deepcopy(b["rows"][0]);quote["mint"]="mint-two"
    b["rows"].append(quote)
    proof=copy.deepcopy(c["records"][0]);proof["mint"]="mint-two"
    proof["pool"]="pool-two";proof["signature"]="sig-two"
    proof["signed_outer_creations"][0]["mint"]="mint-two"
    proof["signed_outer_creations"][0]["pool"]="pool-two"
    c["records"].append(proof)
    result=join_signed_index_quotes(a,b,c)
    assert result["selected_creator_claims"]==2
    assert result["selected_distinct_provider_claimed_creator_ids"]==1
    assert result["authenticated_selected_creation_count"]==2
    assert result["cryptographically_authenticated_selected_creators"]==1
    assert result["matched_full_lot_quote_scenarios"]==2
    assert result["market_profitability_verified"] is False
