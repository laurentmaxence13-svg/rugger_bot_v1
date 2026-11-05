"""Offline integration tests for signed Helius source on the existing Render UI.

No sockets are opened, no financial operations or external provider requests.
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
    result = {"status": None}
    handler.send_response = lambda status: result.__setitem__("status", status)
    handler.send_header = lambda key, value: headers.__setitem__(key, value)
    handler.end_headers = lambda: None
    handler.send_error = lambda status, *args: result.__setitem__("status", status)
    getattr(handler, "do_" + method)()
    return result["status"], headers, handler.wfile.getvalue()


def test_signed_source_is_separate_disabled_and_read_only(monkeypatch):
    observer = Observer(env={})
    monkeypatch.setattr(app, "SIGNED_SOURCE", observer)
    status, headers, raw = request("/api/helius")
    payload = json.loads(raw)
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert headers["Access-Control-Allow-Methods"] == "GET"
    assert payload["observer_status"] == "DISABLED_EXPLICITLY"
    assert payload["no_signing_or_order_submission"] is True
    assert payload["live_trading_enabled"] is False
    assert payload["wallet_connected"] is False
    assert payload["cycle_count"] == 0
    assert request("/api/helius", method="POST")[0] == 405
    assert request("/api/helius/execute")[0] == 404


def test_signed_source_and_market_paper_are_not_confused(monkeypatch):
    marker = "fake-key-for-local-injection-only"
    observer = Observer(
        env={"HELIUS_API_KEY": marker, "RUGGER_OBSERVATION_ENABLED": "1"},
        runner=lambda **kwargs: {
            "financial_order_submitted": False,
            "execution_verified": False,
            "live_ready_to_arm": False,
            "trade_fills_simulated": 0,
            "crypto_signed_creation_transactions": 2,
            "frozen_S1_decisions": 1,
            "master_net_pnl_lamports": 9999999,
            "secret": marker,
        })
    assert observer.capture_once()
    monkeypatch.setattr(app, "SIGNED_SOURCE", observer)
    status, _, raw = request("/api/helius")
    payload = json.loads(raw)
    assert status == 200
    assert payload["observer_status"] == "CAPTURE_COMPLETED_READ_ONLY"
    assert payload["last_summary"]["crypto_signed_creation_transactions"] == 2
    assert payload["last_summary"]["frozen_S1_decisions"] == 1
    assert payload["last_summary"]["trade_fills_simulated"] == 0
    assert marker not in raw.decode()
    assert "master_net_pnl_lamports" not in raw.decode()
    assert "secret" not in raw.decode()
    market_status, _, market_raw = request("/api/status")
    assert market_status == 200
    paper = json.loads(market_raw)
    assert paper["service"]["master_trades_executed"] is False
    assert paper["service"]["financial_order_submitted"] is False
    assert paper["service"]["paper_strategy"] == "SEPARATE_EXPERIMENT_NOT_MASTER"


def test_render_page_discloses_observer_provenance_and_refusal():
    status, headers, page = request("/")
    assert status == 200
    assert b"/api/helius" in page
    assert b"DexScreener" in page
    assert b"LaunchLab" in page
    assert b"aucune" not in page.lower() or b"Master" in page
    assert b"/api/helius" in page
    assert "default-src 'self'" in headers["Content-Security-Policy"]
