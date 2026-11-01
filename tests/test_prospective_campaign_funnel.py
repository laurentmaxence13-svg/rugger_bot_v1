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
