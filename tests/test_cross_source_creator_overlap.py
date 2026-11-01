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



def with_signed_rows(creators=("c",),signatures=None,mints=None,pools=None):
    p=prospective(creators)
    sigs=signatures or tuple("prospectiveSig"+str(i) for i in range(len(creators)))
    mints=mints or tuple("prospectiveMint"+str(i) for i in range(len(creators)))
    pools=pools or tuple("prospectivePool"+str(i) for i in range(len(creators)))
    p["source_signed_creation_rows"]=[
        dict(signature=sigs[i],creator=creator,mint=mints[i],pool=pools[i],
             first_observed_run_id=41266654485)
        for i,creator in enumerate(creators)]
    p["unique_signed_creation_signatures"]=len(creators)
    p["unique_signed_mint_pool_pairs"]=len(set(zip(mints,pools)))
    return p


def test_new_cross_source_signature_and_pool_identity_audit_has_zero_overlap():
    x=reconcile(pinned(),with_signed_rows())
    assert x["cross_source_signed_creation_identity_rows_available"] is True
    assert x["overlapping_signed_creation_signatures"]==0
    assert x["overlapping_signed_mint_pool_pairs"]==0
    assert x["independently_replayed_ed25519_proofs_in_this_join"]==0


def test_matching_exact_signed_creation_is_one_creator_not_new_independent():
    p=with_signed_rows(("a",),signatures=("sig0",),
                       mints=("mint0",),pools=("pool0",))
    x=reconcile(pinned(),p)
    assert x["overlapping_signed_creation_signatures"]==1
    assert x["overlapping_signed_mint_pool_pairs"]==1
    assert x["unique_creator_ids_across_two_sources"]==2


def test_reused_signature_with_different_identity_fails_closed():
    p=with_signed_rows(("c",),signatures=("sig0",))
    with pytest.raises(ValueError,match="signed_signature_identity_conflict"):
        reconcile(pinned(),p)


def test_reused_pool_with_different_creator_fails_closed():
    p=with_signed_rows(("c",),mints=("mint0",),pools=("pool0",))
    with pytest.raises(ValueError,match="signed_pool_creator_conflict"):
        reconcile(pinned(),p)


def test_partial_signature_identity_rows_refused():
    p=with_signed_rows()
    p["unique_signed_creation_signatures"]=2
    with pytest.raises(ValueError,match="complete_source_signed_creation_identity_rows"):
        reconcile(pinned(),p)


def test_creator_rows_cannot_invent_new_signed_identity():
    p=with_signed_rows()
    p["source_signed_creation_rows"][0]["creator"]="unknown"
    with pytest.raises(ValueError,match="signed_source_rows_do_not_reconcile"):
        reconcile(pinned(),p)


def test_same_source_signature_repeated_is_not_two_creations():
    p=with_signed_rows(("c","d"),signatures=("repeat","repeat"))
    with pytest.raises(ValueError,match="duplicate_or_invalid_signed_source_identity"):
        reconcile(pinned(),p)


def test_source_rows_with_unregistered_extra_field_refused():
    p=with_signed_rows()
    p["source_signed_creation_rows"][0]["realized_profit"]=999
    with pytest.raises(ValueError,match="exact_signed_source_identity"):
        reconcile(pinned(),p)


def test_missing_source_signed_rows_not_claimed_verified():
    x=reconcile(pinned(),prospective())
    assert x["cross_source_signed_creation_identity_rows_available"] is False
    assert x["overlapping_signed_creation_signatures"] is None
    assert x["overlapping_signed_mint_pool_pairs"] is None
