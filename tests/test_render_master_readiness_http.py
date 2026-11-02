"""Integration: Render Master diagnostic GET is signed-source-only and never submits orders.

No sockets, provider requests, wallet signing or financial transactions.
"""
from io import BytesIO
import json

import render_status_service as app
from bot.ops.render_readonly_service import Observer


def request(path, *, method="GET"):
    handler = object.__new__(app.Handler)
    handler.path = path
    handler.wfile = BytesIO()
    headers = {}
    state = {"code": None}
    handler.send_response = lambda code: state.__setitem__("code", code)
    handler.send_header = lambda key, value: headers.__setitem__(key, value)
    handler.end_headers = lambda: None
    handler.send_error = lambda code, *args: state.__setitem__("code", code)
    getattr(handler, "do_" + method)()
    return state["code"], headers, handler.wfile.getvalue()


def test_disabled_master_endpoint_remains_no_go(monkeypatch):
    monkeypatch.setattr(app, "SIGNED_SOURCE", Observer(env={}))
    code, headers, raw = request("/api/master-readiness")
    data = json.loads(raw)
    assert code == 200
    assert headers["Cache-Control"] == "no-store"
    assert data["status"] == "NO_GO"
    assert data["next_blocker"] == "SIGNED_OBSERVER_DISABLED"
    assert data["master_buy_sell_paper_verified"] is False
    assert data["financial_order_submitted"] is False
    assert data["master_net_pnl_sol"] is None
    assert data["experimental_dexscreener_excluded"] is True
    assert request("/api/master-readiness", method="POST")[0] == 405


def test_signed_summary_does_not_become_master_fill_or_leak_secret(monkeypatch):
    marker = "synthetic_key_not_for_publication_123"
    def signed_s1(**kwargs):
        return {
            "capture_status": "TWO_CLOCK_MODEL_CAPTURE_COMPLETE_NOT_PROFITABILITY",
            "financial_order_submitted": False,
            "live_ready_to_arm": False,
            "execution_verified": False,
            "trade_fills_simulated": 0,
            "log_events_retained": 2,
            "crypto_signed_creation_transactions": 2,
            "selected_independent_signed_creators": 1,
            "supported_native_SOL_graphs": 1,
            "frozen_S1_decisions": 1,
            "actual_signed_policy_frozen_paper_cases": 1,
            "master_net_pnl_lamports": 987654321,
            "secret": marker,
        }
    observer = Observer(env={
        "RUGGER_OBSERVATION_ENABLED": "1",
        "HELIUS_API_KEY": marker,
    }, runner=signed_s1)
    assert observer.capture_once() is True
    monkeypatch.setattr(app, "SIGNED_SOURCE", observer)
    code, _, raw = request("/api/master-readiness")
    data = json.loads(raw)
    assert code == 200
    assert data["status"] == "NO_GO"
    # Old deployed signed observer may correctly mark synthetic evidence stale.
    # Do not override freshness merely to satisfy a test fixture.
    if data["signed_evidence_fresh"]:
        assert data["next_blocker"] == "NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH"
    else:
        assert data["next_blocker"] == "SIGNED_EVIDENCE_MISSING_OR_STALE"
    assert data["master_net_pnl_sol"] is None
    assert data["master_reference_edge_sol"] is None
    assert data["master_buy_sell_paper_verified"] is False
    assert marker.encode() not in raw
    assert b"987654321" not in raw

