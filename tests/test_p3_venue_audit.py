"""Offline venue attribution: a Trade API refusal cannot prove curve illiquidity."""
import json

import pytest

from bot.p3.store import CaptureStore
from bot.p3.venue_audit import venue_audit, replay

MINT="TokenPublicMintOne"
MINT2="TokenPublicMintTwo"


def capture(tmp_path, *, status=0, has_analysis=True, fail=True):
    path=tmp_path/"venue.sqlite"
    with CaptureStore(path,clock_ms=lambda:2000) as store:
        store.append("checkpoint",received_at_ms=800,outcome="prospective_prefix_fixed",
            payload={"candidates":[{"ordinal":0,"mint":MINT,"pool":"pool-1"},
                                   {"ordinal":1,"mint":MINT2,"pool":"pool-2"}]},
            provenance="synthetic")
        if has_analysis:
            store.append("candidate_decision",received_at_ms=900,mint=MINT,
                outcome="not_admitted",reason="instrumental_only",provenance="synthetic",
                payload={"probe_phase":"initial","analysis":{
                    "facts":{"pool":{"status":str(status),"mint_b":
                        "So11111111111111111111111111111111111111112"},
                        "config":{"curve_type":0}},
                    "conditional_projection":None,"blocking_reasons":[]}})
        store.append("quote_attempt",received_at_ms=1200,mint=MINT,
            outcome="unavailable" if fail else "quoted",
            reason="provider_rejected" if fail else None,provenance="synthetic",
            payload={"provider":"raydium_trade_api","quote_side":"sell",
                "probe_phase":"initial","exit_scope":"full_expected",
                "retained_sanitized_response":{"success":False,
                    "msg":"INSUFFICIENT_LIQUIDITY"} if fail else None})
        return path,store.events(),store.verify_integrity()


def test_active_curve_refusal_is_only_plausible_provider_coverage_gap(tmp_path):
    path,events,tail=capture(tmp_path)
    report=venue_audit(events,expected_tail=tail)
    assert report["selected_tokens"]==2
    assert report["active_curve_trade_api_coverage_gap_candidates"]==1
    assert report["cases"][0]["stage"]=="launchlab_curve_active_status_observed"
    assert report["cases"][0]["trade_api_refusal_counts"]=={"INSUFFICIENT_LIQUIDITY":1}
    assert report["cases"][0]["trade_api_refusal_proves_onchain_illiquidity"] is False
    assert report["cases"][0]["migration_verified"] is False
    assert report["cases"][0]["net_pnl_sol"] is None
    assert report["cases"][1]["stage"]=="unknown"
    assert report["venue_aware_executable_cycle_count"]==0
    assert report["financial_order_submitted"] is False


@pytest.mark.parametrize("status,expected",[
    (1,"launchlab_curve_not_active_migration_not_verified"),
    (2,"launchlab_curve_not_active_migration_not_verified")])
def test_nonactive_curve_does_not_claim_migration_or_exchange_liquidity(tmp_path,status,expected):
    _,events,tail=capture(tmp_path,status=status)
    report=venue_audit(events,expected_tail=tail)
    assert report["cases"][0]["stage"]==expected
    assert report["cases"][0]["migration_verified"] is False
    assert not report["cases"][0]["active_curve_trade_api_coverage_gap_plausible"]


def test_missing_bank_analysis_does_not_turn_refusal_into_curve_liquidity_claim(tmp_path):
    _,events,tail=capture(tmp_path,has_analysis=False)
    report=venue_audit(events,expected_tail=tail)
    assert report["cases"][0]["stage"]=="unknown"
    assert not report["cases"][0]["active_curve_trade_api_coverage_gap_plausible"]


def test_positive_provider_route_is_not_misclassified_as_coverage_gap(tmp_path):
    _,events,tail=capture(tmp_path,fail=False)
    report=venue_audit(events,expected_tail=tail)
    assert report["active_curve_trade_api_coverage_gap_candidates"]==0
    assert report["venue_aware_executable_cycle_count"]==0


def test_verified_journal_replay_is_local_and_does_not_overwrite(tmp_path):
    path,_,_=capture(tmp_path)
    before=path.read_bytes()
    out=tmp_path/"venue-report.json"
    summary=replay(path,out)
    assert summary["selected_tokens"]==2
    assert summary["active_curve_trade_api_coverage_gap_candidates"]==1
    assert path.read_bytes()==before
    assert json.loads(out.read_text())["strategy_profitability_verified"] is False
    with pytest.raises(ValueError,match="new separate JSON output"):
        replay(path,out)


def test_unverified_or_tampered_tail_fails_closed(tmp_path):
    _,events,tail=capture(tmp_path)
    with pytest.raises(ValueError):
        venue_audit(events,expected_tail="0"*64)
    events[0]["payload"]["candidates"][0]["ordinal"]=99
    with pytest.raises(ValueError):
        venue_audit(events,expected_tail=tail)
