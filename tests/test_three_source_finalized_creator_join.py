"""No inflation of archived Ed25519 creator counts across three sources."""
from copy import deepcopy
import pytest
from bot.p3.three_source_finalized_creator_join import join_finalized_creator_proofs

RUN=41266654485
SOURCE_HASH="f"*64


def fixtures():
    rows=[]
    for i,c in enumerate(("pinnedA","pinnedB")):
        identity=dict(creator=c,mint="pinnedMint"+str(i),pool="pinnedPool"+str(i))
        rows.append(dict(status="EXACT_OUTER_SIGNED_CREATION_VERIFIED",
            signature="pinnedSig"+str(i),verified_exact_message_sha256=str(i+1)*64,
            signed_outer_creations=[identity],**identity))
    pinned=dict(schema="rugger-pinned-index-creators-finalized-proof-v1",
        records=rows,financial_order_submitted=False,qualified_economic_cycles=0)
    prospective=dict(schema="rugger-cross-campaign-signed-creator-audit-v1",
        financial_order_submitted=False,qualified_master_reference_holdout_cycles=0,
        market_profitability_verified=False,
        creator_ids_public=["heliusC"],unique_signed_creator_claims=1,
        unique_signed_creation_signatures=1,unique_signed_mint_pool_pairs=1,
        source_reports=[dict(run_id=RUN,source_campaign_sha256=SOURCE_HASH)],
        source_signed_creation_rows=[dict(signature="heliusSig",creator="heliusC",
            mint="heliusMint",pool="heliusPool",first_observed_run_id=RUN)])
    replay=dict(schema="rugger-finalized-campaign-ed25519-replay-v1",
        financial_order_submitted=False,eligible_for_future_registered_holdout=False,
        exact_lot_executable_buy_sell_cycles=0,
        net_master_reference_advantage_lamports=None,
        source_campaign_sha256=SOURCE_HASH,
        signed_creation_claim_signatures=1,independently_verified_finalized_creator_ids=1,
        records=[dict(signature="heliusSig",creator="heliusC",
            mint="heliusMint",pool="heliusPool",
            status="EXACT_FINALIZED_ED25519_CREATION_VERIFIED",
            source_confirmed_message_sha256="a"*64,
            independently_verified_finalized_message_sha256="a"*64)])
    return pinned,prospective,replay


def test_three_historical_signed_keys_but_no_future_holdout_or_profit():
    p,c,r=fixtures()
    x=join_finalized_creator_proofs(p,c,r)
    assert x["distinct_historical_finalized_ed25519_public_creator_keys"]==3
    assert x["historical_helius_replayed_ed25519_creator_keys"]==1
    assert x["replayed_helius_creator_overlap_with_pinned"]==0
    assert x["cross_artifact_join_replays_ed25519_itself"] is False
    assert x["independent_economic_operators_verified"] is False
    assert x["eligible_for_future_preregistered_holdout"] is False
    assert x["verified_executable_economic_cycles"]==0
    assert x["actual_master_reference_net_advantage_lamports"] is None


def test_replayed_source_digest_must_match_archived_run():
    p,c,r=fixtures();r["source_campaign_sha256"]="e"*64
    with pytest.raises(ValueError,match="digest_not_in"):
        join_finalized_creator_proofs(p,c,r)


def test_replayed_signed_creator_identity_must_match_original_capture():
    p,c,r=fixtures();r["records"][0]["creator"]="forged"
    with pytest.raises(ValueError,match="identity_not_bound"):
        join_finalized_creator_proofs(p,c,r)


def test_replayed_message_hash_must_match_confirmed_message():
    p,c,r=fixtures();r["records"][0]["independently_verified_finalized_message_sha256"]="b"*64
    with pytest.raises(ValueError,match="message_hash_mismatch"):
        join_finalized_creator_proofs(p,c,r)


def test_replay_verified_creator_count_cannot_be_self_inflated():
    p,c,r=fixtures();r["independently_verified_finalized_creator_ids"]=50
    with pytest.raises(ValueError,match="count_or_source_denominator"):
        join_finalized_creator_proofs(p,c,r)


def test_duplicate_creator_key_not_counted_twice_across_sources():
    p,c,r=fixtures()
    p["records"][0]["creator"]="heliusC"
    p["records"][0]["signed_outer_creations"][0]["creator"]="heliusC"
    x=join_finalized_creator_proofs(p,c,r)
    assert x["replayed_helius_creator_overlap_with_pinned"]==1
    assert x["distinct_historical_finalized_ed25519_public_creator_keys"]==2


def test_unverified_replay_is_not_an_authenticated_creator():
    p,c,r=fixtures()
    r["records"][0]["status"]="FINALIZED_RECEIPT_UNAVAILABLE"
    r["records"][0]["independently_verified_finalized_message_sha256"]=None
    r["independently_verified_finalized_creator_ids"]=0
    x=join_finalized_creator_proofs(p,c,r)
    assert x["distinct_historical_finalized_ed25519_public_creator_keys"]==2
    assert x["unverified_helius_creator_claims"]==1
