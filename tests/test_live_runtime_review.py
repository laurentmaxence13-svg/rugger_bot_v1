"""Counter-review of causal runtime/service binding; no live services or keys."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from bot.live.journal import ExecutionJournal
from bot.live.runtime import LiveRuntime
from bot.live.safety import Mode
from bot.scanner.supervision import ScannerHealth
from test_live_engine import configured
from test_master_decision import qualified


@pytest.mark.parametrize('field',['features_available_at_ms','research_evidence'])
def test_processing_delay_cannot_make_future_data_part_of_earlier_source_frame(tmp_path,field):
    async def scenario():
        _,frame,health,capital=qualified()
        source_at=frame['available_at_ms'];now=source_at+1
        if field=='features_available_at_ms':frame[field]=source_at+1
        else:frame[field]['available_at_ms']=source_at+1
        health['observed_at_ms']=capital['observed_at_ms']=now
        async def context():return dict(health=health,capital=capital)
        async def route(*_):raise AssertionError('Shadow runtime must not request execution route')
        journal=ExecutionJournal(tmp_path/'private-review.sqlite')
        engine=SimpleNamespace(journal=journal,mode=Mode.SHADOW,result=lambda *_:None)
        runtime=LiveRuntime(engine=engine,decision_context_provider=context,
            route_request_provider=route,clock_ms=lambda:now)
        try:
            with pytest.raises(ValueError,match='future|source|asof|causal'):
                await runtime.observe(frame)
        finally:journal.close()
    asyncio.run(scenario())


def test_actual_scanner_disconnect_during_final_rpc_prevents_submission(tmp_path):
    async def scenario():
        engine,order,rpc,signer,clock=configured(tmp_path)
        health=ScannerHealth(require_observations=True,
            clock_ms=lambda:clock[0],monotonic_ms=lambda:clock[0])
        task=health.start_task(asyncio.Event().wait(),'counterreview-scanner')
        health.observe_rpc(True);health.observe_websocket('subscribed')
        original_provider=engine.evidence_provider
        class BoundOperationalEvidence:
            async def __call__(self,*args):return await original_provider(*args)
            def assert_operational_now(self):
                if not health.permits_entries() or not health.services_fresh(max_age_ms=1000):
                    raise ValueError('current_scanner_service_disconnected')
        engine.evidence_provider=BoundOperationalEvidence()
        original_height=rpc.get_block_height
        async def disconnected_height():
            value=await original_height()
            if signer.calls:health.observe_websocket('disconnected')
            return value
        rpc.get_block_height=disconnected_height
        try:
            with pytest.raises(ValueError,match='disconnected'):
                await engine.execute(json.loads(order.rebuild_request_json)['decision_id'],order)
            assert not rpc.send_calls
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())
