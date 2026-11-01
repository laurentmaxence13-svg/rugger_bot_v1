"""Cross-source creator identity tests: no count inflation or fake crypto replay."""
import copy
import pytest
from bot.p3.cross_source_creator_overlap import reconcile


def pinned(creators=("a","b")):
    rows=[]
    for i,c in enumerate(creators):
        match=dict(creator=c,mint=f"mint{i}",pool=f"pool{i}")
        rows.append(dict(status="EXACT_OUTER_SIGNED_CREATION_VERIFIED",
            **match,signature=f"sig{i}",verified_exact_message_sha256=f"{i+1}"*64,
            signed_outer_creations=[match]))
    return dict(schema="rugger-pinned-index-creators-finalized-proof-v1",
        records=rows,financial_order_submitted=False,qualified_economic_cycles=0)


def prospective(creators=("c",)):
    return dict(schema="rugger-cross-campaign-signed-creator-audit-v1",
        creator_ids_public=list(creators),unique_signed_creator_claims=len(creators),
        financial_order_submitted=False,
        qualified_master_reference_holdout_cycles=0,
        market_profitability_verified=False)


def test_three_distinct_creators_across_two_upstream_sources_not_crypto_replay():
    x=reconcile(pinned(),prospective())
    assert x["pinned_upstream_verified_signed_creator_count"]==2
    assert x["prospective_source_claimed_signed_creator_count"]==1
    assert x["overlapping_creator_ids"]==0
    assert x["unique_creator_ids_across_two_sources"]==3
    assert x["independently_replayed_ed25519_proofs_in_this_join"]==0
    assert x["master_minus_reference_net_pnl_lamports"] is None
    assert x["financial_order_submitted"] is False


def test_same_creator_in_both_sources_counted_once():
    x=reconcile(pinned(),prospective(("a",)))
    assert x["overlapping_creator_ids"]==1
    assert x["unique_creator_ids_across_two_sources"]==2


def test_multiple_pinned_creations_same_creator_not_independent():
    x=reconcile(pinned(("a","a")),prospective(("c",)))
    assert x["pinned_upstream_verified_signed_creator_count"]==1
    assert x["unique_creator_ids_across_two_sources"]==2


def test_forged_message_digest_rejected():
    p=pinned();p["records"][0]["verified_exact_message_sha256"]="x"*64
    with pytest.raises(ValueError,match="conflicted_pinned"):
        reconcile(p,prospective())


def test_duplicate_signed_message_hash_rejected():
    p=pinned();p["records"][1]["verified_exact_message_sha256"]="1"*64
    with pytest.raises(ValueError,match="conflicted_pinned"):
        reconcile(p,prospective())


def test_inconsistent_signed_outer_identity_rejected():
    p=pinned();p["records"][0]["signed_outer_creations"][0]["creator"]="other"
    with pytest.raises(ValueError,match="conflicted_pinned"):
        reconcile(p,prospective())


def test_prospective_creator_count_not_self_attestable():
    p=prospective();p["unique_signed_creator_claims"]=50
    with pytest.raises(ValueError,match="creator_set_not_reconciled"):
        reconcile(pinned(),p)


def test_prospective_duplicate_creator_refused():
    p=prospective(("a","a"))
    with pytest.raises(ValueError,match="creator_set_not_reconciled"):
        reconcile(pinned(),p)


def test_live_trade_or_profitable_assertion_refused():
    p=prospective();p["market_profitability_verified"]=True
    with pytest.raises(ValueError,match="strict_readonly"):
        reconcile(pinned(),p)
