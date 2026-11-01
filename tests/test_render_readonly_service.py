"""Offline-only tests: no Helius requests, signing, wallets or LIVE submission."""
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading

import pytest

from bot.ops import render_readonly_service as mod


def test_no_secret_means_zero_network_calls():
    called=[]
    obj=mod.Observer(env={"RUGGER_OBSERVATION_ENABLED":"1"},
                     runner=lambda **kw: called.append(kw))
    assert obj.capture_once() is False
    assert obj.snapshot()["observer_status"]=="WAITING_FOR_HELIUS_API_KEY"
    assert called==[]
    assert obj.snapshot()["live_trading_enabled"] is False
    assert obj.snapshot()["wallet_connected"] is False


def test_verified_public_summary_never_fabricates_pnl_or_exposes_keys():
    seen=[]
    def capture(**kw):
        assert kw["seconds"]==30
        assert kw["api_key"]=="private_api_key_fake_123456789"
        assert not kw["output_dir"].exists()
        seen.append(True)
        return dict(financial_order_submitted=False,live_ready_to_arm=False,
                    execution_verified=False,trade_fills_simulated=0,
                    crypto_signed_creation_transactions=1,frozen_S1_decisions=1,
                    capture_status="TWO_CLOCK_MODEL_CAPTURE_COMPLETE_NOT_PROFITABILITY",
                    secret="MUST_NOT_LEAK",master_net_pnl_lamports=9876543)
    obj=mod.Observer(env={"RUGGER_OBSERVATION_ENABLED":"1",
                          "HELIUS_API_KEY":"private_api_key_fake_123456789"},
                     runner=capture)
    assert obj.capture_once()
    status=obj.snapshot()
    assert status["observer_status"]=="CAPTURE_COMPLETED_READ_ONLY"
    assert status["last_summary"]["crypto_signed_creation_transactions"]==1
    assert status["last_summary"]["trade_fills_simulated"]==0
    assert status["last_summary"]["execution_verified"] is False
    assert "MUST_NOT_LEAK" not in str(status)
    assert "master_net_pnl_lamports" not in str(status)
    assert "private_api_key" not in str(status)
    assert status["cycle_count"]==1
    assert seen==[True]


def test_failed_requests_never_leak_provider_key():
    def fail(**kw): raise RuntimeError("API_KEY=private_api_key_fake_123456789")
    obj=mod.Observer(env={"RUGGER_OBSERVATION_ENABLED":"1",
                          "HELIUS_API_KEY":"private_api_key_fake_123456789"},
                     runner=fail)
    assert obj.capture_once() is False
    status=obj.snapshot()
    assert status["observer_status"]=="CAPTURE_REFUSED"
    assert status["last_safe_error_class"]=="RuntimeError"
    assert "private_api_key" not in str(status)
    assert status["last_summary"] is None


def test_unexpected_execution_claim_refused():
    obj=mod.Observer(env={"RUGGER_OBSERVATION_ENABLED":"1",
                          "HELIUS_API_KEY":"private_api_key_fake_123456789"},
        runner=lambda **kw:dict(financial_order_submitted=True,
                                live_ready_to_arm=False,execution_verified=False,
                                trade_fills_simulated=0))
    assert obj.capture_once() is False
    assert obj.snapshot()["observer_status"]=="CAPTURE_REFUSED"


@pytest.mark.parametrize("env",[
    {"RUGGER_OBSERVATION_ENABLED":"yes"},
    {"RUGGER_INTERVAL_SECONDS":"0"},
    {"RUGGER_INTERVAL_SECONDS":"60"},
    {"RUGGER_INTERVAL_SECONDS":"3601"},
    {"RUGGER_INTERVAL_SECONDS":"3.14"},
    {"RUGGER_CAPTURE_SECONDS":"46"},
    {"RUGGER_CAPTURE_SECONDS":"0"},
])
def test_bad_config_fails_closed(env):
    with pytest.raises(ValueError):mod.Observer(env=env)


def test_http_health_and_status_have_no_credentials():
    # The repository's isolated CI forbids actual socket.bind. Exercise the
    # real handler without opening a TCP port or weakening network isolation.
    from io import BytesIO
    obj=mod.Observer(env={})
    Handler=mod.handler_factory(obj)
    def request(path):
        handler=object.__new__(Handler)
        handler.path=path
        handler.wfile=BytesIO()
        headers={}
        result={"status":None}
        handler.send_response=lambda status:result.__setitem__("status",status)
        handler.send_header=lambda key,value:headers.__setitem__(key,value)
        handler.end_headers=lambda:None
        handler.send_error=lambda status,*args:result.__setitem__("status",status)
        handler.do_GET()
        return result["status"],headers,handler.wfile.getvalue()
    status,headers,payload=request("/healthz")
    assert status==200
    assert headers["Access-Control-Allow-Origin"]==mod.ALLOWED_ORIGIN
    assert json.loads(payload)["financial_orders_enabled"] is False
    status,headers,payload=request("/api/status")
    value=json.loads(payload)
    assert status==200
    assert value["observer_status"]=="DISABLED_EXPLICITLY"
    assert value["mode"]=="READ_ONLY_MASTER_PAPER_EVIDENCE"
    assert value["is_24_7_guaranteed"] is False
