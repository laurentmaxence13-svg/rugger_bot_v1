"""Read-only Master readiness contract; no Helius, DexScreener or sockets."""
from copy import deepcopy
import pytest

from bot.ops.render_master_readiness import assess_master_paper_readiness as assess


def base():
    return {
        "observer_status": "CAPTURE_COMPLETED_READ_ONLY",
        "signed_evidence_fresh": True,
        "live_trading_enabled": False,
        "no_signing_or_order_submission": True,
        "last_summary": {
            "financial_order_submitted": False,
            "execution_verified": False,
            "trade_fills_simulated": 0,
            "crypto_signed_creation_transactions": 2,
            "supported_native_SOL_graphs": 1,
            "frozen_S1_decisions": 1,
        },
    }


def test_qualified_signed_observation_is_not_master_trade():
    report = assess(base())
    assert report["status"] == "NO_GO"
    assert report["next_blocker"] == "NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH"
    assert report["source"] == "HELIUS_SIGNED_LAUNCHLAB_ONLY"
    assert report["master_buy_sell_paper_verified"] is False
    assert report["master_net_pnl_sol"] is None
    assert report["master_reference_edge_sol"] is None
    assert report["experimental_dexscreener_excluded"] is True
    assert report["financial_order_submitted"] is False


@pytest.mark.parametrize("state,blocker", [
    ("DISABLED_EXPLICITLY", "SIGNED_OBSERVER_DISABLED"),
    ("WAITING_FOR_HELIUS_API_KEY", "SIGNED_SOURCE_UNCONFIGURED"),
    ("READY_TO_CAPTURE", "AWAITING_FIRST_SIGNED_CAPTURE"),
    ("STARTING", "AWAITING_FIRST_SIGNED_CAPTURE"),
    ("CAPTURING_HELIUS_READ_ONLY", "SIGNED_CAPTURE_IN_PROGRESS"),
    ("CAPTURE_REFUSED", "SIGNED_CAPTURE_REFUSED"),
    ("unexpected", "UNRECOGNIZED_SIGNED_SOURCE_STATE"),
])
def test_state_diagnosis_is_fail_closed(state, blocker):
    snapshot = base()
    snapshot["observer_status"] = state
    assert assess(snapshot)["next_blocker"] == blocker
    assert assess(snapshot)["status"] == "NO_GO"


@pytest.mark.parametrize("summary_override,blocker", [
    ({"crypto_signed_creation_transactions": 0},
     "NO_SIGNED_LAUNCHLAB_CREATION"),
    ({"supported_native_SOL_graphs": 0},
     "NO_VERIFIED_SOL_QUOTED_POOL_GRAPH"),
    ({"frozen_S1_decisions": 0},
     "NO_FROZEN_CAUSAL_MASTER_DECISION"),
    ({"crypto_signed_creation_transactions": None},
     "SIGNED_SOURCE_COUNTERS_INCOMPLETE"),
    ({"frozen_S1_decisions": True},
     "SIGNED_SOURCE_COUNTERS_INCOMPLETE"),
    ({"trade_fills_simulated": 1},
     "SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED"),
    ({"financial_order_submitted": True},
     "SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED"),
])
def test_observations_and_invalid_financial_claims(summary_override, blocker):
    snapshot = base()
    snapshot["last_summary"].update(summary_override)
    assert assess(snapshot)["next_blocker"] == blocker
    assert assess(snapshot)["master_buy_sell_paper_verified"] is False


@pytest.mark.parametrize("snapshot", [None, {}, [], "secret"])
def test_untrusted_snapshot_cannot_claim_readiness(snapshot):
    result = assess(snapshot)
    assert result["status"] == "NO_GO"
    assert result["master_net_pnl_sol"] is None


def test_stale_evidence_never_promotes():
    snapshot = base()
    snapshot["signed_evidence_fresh"] = False
    assert assess(snapshot)["next_blocker"] == "SIGNED_EVIDENCE_MISSING_OR_STALE"
    assert assess(snapshot)["signed_evidence_fresh"] is False


def test_invalid_source_security_flags_are_refused():
    snapshot = base()
    snapshot["no_signing_or_order_submission"] = False
    assert assess(snapshot)["next_blocker"] == "SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED"
    snapshot = base()
    snapshot["live_trading_enabled"] = True
    assert assess(snapshot)["next_blocker"] == "SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED"


def test_experimental_trades_and_credential_text_never_enter_report():
    snapshot = base()
    snapshot["cash_sol"] = 1000
    snapshot["positions"] = [{"strategy": "DexScreener", "pnl_sol": 1000}]
    snapshot["HELIUS_API_KEY"] = "SHOULD_NOT_BE_VISIBLE_ANYWHERE"
    snapshot["last_summary"]["private_key"] = "SHOULD_NOT_BE_VISIBLE_ANYWHERE"
    result = assess(snapshot)
    assert result["status"] == "NO_GO"
    assert "SHOULD_NOT_BE_VISIBLE_ANYWHERE" not in repr(result)
    assert "1000" not in repr(result)
