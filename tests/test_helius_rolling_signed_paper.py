"""Read-only Helius long-running capture guards; no network or paid calls."""
import asyncio
import json
from pathlib import Path

import pytest

from bot.live.helius_rolling_signed_paper import (
    _check_manifest,session_plan,monitor,_save_new,digest)

KEY="SampleReadOnlyHeliusKey000000000"


def test_24h_sustained_subscription_plan_not_a_profitability_verdict():
    plan=session_plan(duration_seconds=86400,rpc_call_cap=3000,start_ms=1000)
    assert plan["start_ms"]==1000
    assert plan["end_ms"]==86401000
    assert plan["max_rpc_calls"]==3000
    assert plan["complete_event_tape_verified"] is False
    assert plan["full_paper_trade_lifecycle_qualified"] is False
    assert plan["financial_order_submitted"] is False
    assert plan["exact_master_net_profitability_verified"] is False
    with pytest.raises(ValueError,match="bounded_observation"):
        session_plan(duration_seconds=86401)
    with pytest.raises(ValueError,match="bounded_observation"):
        session_plan(duration_seconds=40,rpc_call_cap=30001)


def test_verification_source_sha_and_worst_case_rpc_budget(tmp_path):
    directory=tmp_path/"session"
    chunks=directory/"chunks"
    folder=chunks/"000000"
    folder.mkdir(parents=True)
    captured=dict(report={"status":"NO_LOGS_OBSERVED"},events=[])
    sha=_save_new(folder/"received.json",captured)
    m=session_plan(duration_seconds=45,rpc_call_cap=15,start_ms=1000)
    m["windows"]=[dict(index=0,state="INTERRUPTED",
                       source_sha256=sha,rpc_calls_reserved=15)]
    m["rpc_used_or_reserved_upper_bound"]=15
    assert _check_manifest(directory,m)==15
    m["rpc_used_or_reserved_upper_bound"]=0
    with pytest.raises(ValueError,match="rpc_budget_accounting_changed"):
        _check_manifest(directory,m)
    m["rpc_used_or_reserved_upper_bound"]=15
    (folder/"received.json").write_text('{"damaged":true}')
    with pytest.raises(ValueError,match="source_capture_changed"):
        _check_manifest(directory,m)


def test_bad_key_refused_before_websocket_created(tmp_path):
    called=[]
    def no_socket(*args,**kwargs):
        called.append(True)
        raise AssertionError("network forbidden")
    with pytest.raises(ValueError,match="helius_env_key_required"):
        asyncio.run(monitor(directory=tmp_path/"bad",
            api_key="COLLE_TA_CLE_ICI",duration_seconds=35,
            websocket_factory=no_socket))
    assert not called and not (tmp_path/"bad").exists()


def test_fail_closed_ten_reconnects_not_equivalent_to_complete_capture(tmp_path,monkeypatch):
    class FailsAfterAck:
        def __init__(self):
            self.calls=0
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def send(self,message):
            assert json.loads(message)["method"]=="logsSubscribe"
        async def recv(self):
            self.calls+=1
            if self.calls==1:
                return json.dumps({"jsonrpc":"2.0","id":1,"result":123})
            raise OSError("simulated_websocket_dropout")
    endpoints=[]
    def socket(endpoint,**options):
        assert endpoint.endswith("?api-key="+KEY)
        assert options["max_size"]==262144
        endpoints.append(endpoint)
        return FailsAfterAck()
    async def immediate_sleep(_):return None
    monkeypatch.setattr("bot.live.helius_rolling_signed_paper.asyncio.sleep",immediate_sleep)
    result=asyncio.run(monitor(directory=tmp_path/"gaps",api_key=KEY,
        duration_seconds=40,rpc_call_cap=30,websocket_factory=socket))
    assert result["status"]=="HALTED_RECONNECT_FAILURES"
    assert result["summary"]["source_websocket_gaps"]==10
    assert result["summary"]["unique_log_events"]==0
    assert result["summary"]["exact_master_profitability_verified"] is False
    assert result["summary"]["actual_paper_buys"]==0
    assert len(endpoints)==10
    manifest=(tmp_path/"gaps"/"manifest.json").read_text()
    assert KEY not in manifest
    assert json.loads(manifest)["exact_master_net_profitability_verified"] is False
