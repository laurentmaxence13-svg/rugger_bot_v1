"""Independent creator count and missing S2 must not be overclaimed."""
import pytest
from bot.p3.readonly_evidence_archive import build_archive
from bot.p3.readonly_evidence_rollup import aggregate_evidence


def make(rows,run="12345",kind="active_survivor_cohort"):
    if kind=="active_survivor_cohort":
        observation=dict(status="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE",
                         financial_order_submitted=False,live_ready_to_arm=False,
                         observations=rows)
    else:
        observation=dict(status="PREDECLARED_S1_CAPACITY_SAMPLE_RECORDED",
                         financial_order_submitted=False,live_ready_to_arm=False,
                         results=rows)
    return build_archive(observation,kind=kind,run_id=run,
                         commit_sha="a"*40,
                         now_iso="2026-10-30T14:30:00+00:00")


def test_repeated_same_pool_creator_never_counts_twice_as_verified_creator():
    a=make([dict(pool="one",creator_claim="creatorA",
                 S1_slot=100,s2_refusal="unknown")],run="123")
    b=make([dict(pool="one",creator_claim="creatorA",
                 S1_slot=200,conditional_sell_lamports=9000000),
            dict(pool="two",creator_claim="creatorB",
                 S1_slot=200)],run="124")
    out=aggregate_evidence([a,a,b])
    assert out["archives_unique_by_hash"]==2
    assert out["distinct_active_pool_creator_claims"]==2
    assert out["creator_signature_verified_count"]==0
    assert out["independently_qualified_market_creators"]==0
    assert out["modelled_S2_sell_observation_count"]==1
    assert out["S2_refusal_count"]==2
    assert out["realized_buy_sell_cycles"]==0
    assert out["master_vs_baseline_oos_validated"] is False
    assert out["live_ready_to_arm"] is False


def test_corrupt_archive_or_fabricated_signatures_does_not_pass():
    a=make([dict(pool="pool",creator_claim="claim")])
    a["observation"]["observations"][0]["profitable"]=True
    with pytest.raises(ValueError,match="integrity"):
        aggregate_evidence([a])


def test_nonzero_real_trades_in_paper_evidence_rejected():
    a=make([dict(pool="pool",creator_claim="claim")])
    a["observation"]["real_buy_sell_trades"]=1
    # Force a syntactically valid recomputed hash, to exercise the semantic guard.
    from bot.p3.readonly_evidence_rollup import _hash
    a["observation_sha256"]=_hash(a["observation"])
    with pytest.raises(ValueError,match="unapproved_live"):
        aggregate_evidence([a])


def test_empty_or_too_many_archives_refused():
    with pytest.raises(ValueError):
        aggregate_evidence([])
    with pytest.raises(ValueError):
        aggregate_evidence([{}]*501)
