"""Strict, source-specific NO-GO diagnosis for genuine Rugger Master PAPER.

No execution imports, wallet access, provider calls, or P&L projections.
The existing signed-source runner ONLY observes S1 and records WAIT/NO_TRADE;
it never produces Master PAPER fills. Do not promote DexScreener outcomes.
"""
from __future__ import annotations

SCHEMA = "rugger-genuine-master-paper-readiness-v1"
SOURCE = "HELIUS_SIGNED_LAUNCHLAB_ONLY"
STATE_TO_BLOCKER = {
    "DISABLED_EXPLICITLY": "SIGNED_OBSERVER_DISABLED",
    "WAITING_FOR_HELIUS_API_KEY": "SIGNED_SOURCE_UNCONFIGURED",
    "READY_TO_CAPTURE": "AWAITING_FIRST_SIGNED_CAPTURE",
    "STARTING": "AWAITING_FIRST_SIGNED_CAPTURE",
    "CAPTURING_HELIUS_READ_ONLY": "SIGNED_CAPTURE_IN_PROGRESS",
    "CAPTURE_REFUSED": "SIGNED_CAPTURE_REFUSED",
}

def _count(summary, key):
    value = summary.get(key)
    if type(value) is not int or value < 0:
        return None
    return value


def assess_master_paper_readiness(signed_snapshot):
    """Diagnose the NEXT verified blocker without fabricating a Master fill.

    Only the source's already-sanitized signed summary may be inspected.
    Missing, expired, or contradictory source state always fails closed.
    This report deliberately cannot declare readiness: there is no actual
    Master BUY/SELL PAPER execution path in the current signed observer.
    """
    if type(signed_snapshot) is not dict:
        signed_snapshot = {}
    state = signed_snapshot.get("observer_status")
    summary = signed_snapshot.get("last_summary")
    fresh = signed_snapshot.get("signed_evidence_fresh") is True
    blocker = STATE_TO_BLOCKER.get(state) if type(state) is str else None
    if blocker is None:
        if state != "CAPTURE_COMPLETED_READ_ONLY":
            blocker = "UNRECOGNIZED_SIGNED_SOURCE_STATE"
        elif not fresh or type(summary) is not dict:
            blocker = "SIGNED_EVIDENCE_MISSING_OR_STALE"
        else:
            # Require the source to remain explicitly incapable of executing.
            if (signed_snapshot.get("live_trading_enabled") is not False
                    or signed_snapshot.get("no_signing_or_order_submission") is not True
                    or summary.get("financial_order_submitted") is not False
                    or summary.get("execution_verified") is not False
                    or summary.get("trade_fills_simulated") != 0
                    or type(summary.get("trade_fills_simulated")) is not int):
                blocker = "SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED"
            else:
                creations = _count(summary, "crypto_signed_creation_transactions")
                graphs = _count(summary, "supported_native_SOL_graphs")
                decisions = _count(summary, "frozen_S1_decisions")
                if creations is None or graphs is None or decisions is None:
                    blocker = "SIGNED_SOURCE_COUNTERS_INCOMPLETE"
                elif creations == 0:
                    blocker = "NO_SIGNED_LAUNCHLAB_CREATION"
                elif graphs == 0:
                    blocker = "NO_VERIFIED_SOL_QUOTED_POOL_GRAPH"
                elif decisions == 0:
                    blocker = "NO_FROZEN_CAUSAL_MASTER_DECISION"
                else:
                    blocker = "NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH"
    # Both numbers are intentionally null, NOT zero P&L. DexScreener
    # experimental PAPER fills must never populate a genuine Master result.
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "mode": "GENUINE_MASTER_PAPER_READ_ONLY",
        "status": "NO_GO",
        "next_blocker": blocker,
        "signed_evidence_fresh": fresh and state == "CAPTURE_COMPLETED_READ_ONLY",
        "master_buy_sell_paper_verified": False,
        "master_net_pnl_sol": None,
        "master_reference_edge_sol": None,
        "experimental_dexscreener_excluded": True,
        "financial_order_submitted": False,
        "live_trading_enabled": False,
        "requires_explicit_new_evidence_to_advance": True,
    }
