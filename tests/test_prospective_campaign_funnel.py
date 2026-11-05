"""No-network validation of the per-window Helius prospective campaign funnel."""
import copy
import json
import pytest

from bot.live.helius_prospective_campaign import campaign, CAPTURE_SCHEMA
from bot.p3.prospective_campaign_funnel import funnel


def fixtures(tmp_path):
    path=tmp_path/"bot/live";path.mkdir(parents=True)
    (path/"helius_early_signed_s1s2.py").write_text("# marker")
    calls=[0]
    async def capture(*,seconds,max_events):
        calls[0]+=1
        signature=f"public-{calls[0]}"
        event=dict(signature=signature)
        row=dict(signature=signature,status="SIGNED_CONFIRMED_PROVISIONAL",
            signed_outer_creations=[dict(creator=f"creator-{calls[0]}")],
            root_refusal="pool_account_unavailable")
        report=dict(schema=CAPTURE_SCHEMA,financial_order_submitted=False,
            live_ready_to_arm=False,qualified_economic_cycles=0,
            master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
            forward_log_report=dict(events_received_unique=1),
            attempts=[row],selected=[dict(signature=signature)])
        return report,[event]
    summary=campaign(windows=2,seconds=10,max_events=20,
                     capture=capture,workspace=tmp_path,session="funneltest")
    items=[json.loads((tmp_path/"paper_artifacts"/f"prospective_funneltest_window_{i:02d}.json").read_text())
           for i in (1,2)]
    return summary,items


def test_all_public_evidence_hashes_and_refusals_reconciled(tmp_path):
    summary,items=fixtures(tmp_path)
    out=funnel(summary,items)
    assert out["observed_events"]==2
    assert out["verified_signed_creator_claims"]==2
    assert out["unique_event_signatures"]==2
    assert out["status_counts"]=={"SIGNED_CONFIRMED_PROVISIONAL":2}
    assert out["refusal_reasons"]=={"root_refusal:pool_account_unavailable":2}
    assert out["qualified_executable_buy_sell_cycles"]==0
    assert out["master_net_pnl_lamports"] is None
    assert out["market_profitability_verified"] is False
    assert out["financial_order_submitted"] is False


def test_modify_public_event_rejected_by_hash(tmp_path):
    summary,items=fixtures(tmp_path)
    items[0]["events"][0]["signature"]="attacker-modified"
    with pytest.raises(ValueError,match="tampered_window"):
        funnel(summary,items)


def test_modify_public_receipt_rejected_by_hash(tmp_path):
    summary,items=fixtures(tmp_path)
    items[0]["report"]["attempts"][0]["status"]="VERIFIED_NON_CREATION"
    with pytest.raises(ValueError,match="tampered_window"):
        funnel(summary,items)


def test_claim_of_financial_execution_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    summary["financial_order_submitted"]=True
    with pytest.raises(ValueError,match="unsafe_campaign"):
        funnel(summary,items)


def test_missing_window_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    with pytest.raises(ValueError,match="incomplete_or_unsafe"):
        funnel(summary,items[:1])


def test_inconsistent_creator_count_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    summary["observed_distinct_creator_claims"]=42
    with pytest.raises(ValueError,match="creator_ids_not_reconciled"):
        funnel(summary,items)


def test_mismatched_window_order_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    with pytest.raises(ValueError,match="tampered_window|sequence_or_envelope"):
        funnel(summary,list(reversed(items)))



def _reanchor(summary,items,index):
    """Model a dishonest publisher recomputing the source hash after mutation."""
    import hashlib
    from bot.live.helius_prospective_campaign import _canonical
    summary["windows"][index]["source_sha256"]=hashlib.sha256(
        _canonical(items[index]).encode("utf-8")).hexdigest()


def test_rehashed_unobserved_inspection_is_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    items[0]["report"]["attempts"][0]["signature"]="not-captured"
    _reanchor(summary,items,0)
    with pytest.raises(ValueError,match="inspected_signature_not_in_observed_window"):
        funnel(summary,items)


def test_rehashed_double_inspection_does_not_multiply_creators(tmp_path):
    summary,items=fixtures(tmp_path)
    attempt=copy.deepcopy(items[0]["report"]["attempts"][0])
    items[0]["report"]["attempts"].append(attempt)
    summary["windows"][0]["inspected_attempts"]=2
    summary["windows"][0]["verified_signed_launch_candidates"]=2
    summary["windows"][0]["newly_observed_creator_claims"]=1
    _reanchor(summary,items,0)
    with pytest.raises(ValueError,match="duplicated_inspection_within_window"):
        funnel(summary,items)


def test_rehashed_duplicate_observed_signature_is_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    items[0]["events"].append(copy.deepcopy(items[0]["events"][0]))
    summary["windows"][0]["observed_events"]=2
    summary["windows"][0]["repeated_signatures_across_windows"]=1
    summary["observed_events"]=3
    _reanchor(summary,items,0)
    with pytest.raises(ValueError,match="duplicated_event_signature_within_window"):
        funnel(summary,items)


def test_source_denominator_counts_uninspected_events_as_unknown(tmp_path):
    summary,items=fixtures(tmp_path)
    items[0]["events"].append(dict(signature="captured-but-not-inspected"))
    summary["windows"][0]["observed_events"]=2
    summary["observed_events"]=3
    _reanchor(summary,items,0)
    out=funnel(summary,items)
    assert out["unique_event_signatures"]==3
    assert out["unique_inspected_event_signatures"]==2
    assert out["uninspected_unique_event_signatures"]==1
    assert out["uninspected_events_are_unknown_not_negative"] is True
    assert out["signed_creator_claims_not_independent_crypto_reverification"] is True


def test_signed_creation_claims_count_unique_signatures(tmp_path):
    summary,items=fixtures(tmp_path)
    out=funnel(summary,items)
    assert out["unique_signed_creation_signature_claims"]==2
    assert out["verified_signed_creator_claims"]==2



def test_new_capture_window_clocks_present_but_not_authenticated(tmp_path):
    summary,items=fixtures(tmp_path)
    out=funnel(summary,items)
    assert out["local_capture_clock_provided"] is True
    assert out["local_capture_clock_independently_authenticated"] is False
    assert summary["local_capture_clock_is_not_external_git_or_provider_proof"] is True
    assert all(w["capture_clock_authentication"]=="local_wall_clock_unverified"
               for w in summary["windows"])


def test_reversed_local_capture_windows_are_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    summary["windows"][1]["capture_started_local_ms"]=(
        summary["windows"][0]["capture_completed_local_ms"]-1)
    with pytest.raises(ValueError,match="local_capture_clock_order"):
        funnel(summary,items)


def test_unregistered_partial_local_capture_clock_refused(tmp_path):
    summary,items=fixtures(tmp_path)
    del summary["local_capture_clock_is_not_external_git_or_provider_proof"]
    with pytest.raises(ValueError,match="unregistered_partial_local_capture_clock"):
        funnel(summary,items)


def test_local_wall_clock_cannot_claim_external_authentication(tmp_path):
    summary,items=fixtures(tmp_path)
    summary["windows"][0]["capture_clock_authentication"]="provider_finalized"
    with pytest.raises(ValueError,match="local_capture_clock_order_or_provenance"):
        funnel(summary,items)
