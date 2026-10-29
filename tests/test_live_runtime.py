"""The existing Master freezes decisions before entering the execution path."""
import asyncio
from copy import deepcopy

import pytest

from bot.live.runtime import LiveRuntime, JournalDecisionContext
from bot.live.engine import ExecutionEngine
from bot.live.journal import ExecutionJournal
from bot.live.safety import Mode
from bot.scanner.supervision import ScannerHealth
from test_master_decision import qualified
from test_live_engine import FakeRpc


def run(value):return asyncio.run(value)


def runtime(tmp_path,*,mode=Mode.SHADOW):
    _,frame,health,capital=qualified()
    journal=ExecutionJournal(tmp_path/'runtime.sqlite')
    engine=ExecutionEngine(journal=journal,rpc=FakeRpc(),mode=mode,
        clock_ms=lambda:frame['available_at_ms'])
    calls=[]
    async def context():return dict(health=deepcopy(health),capital=deepcopy(capital))
    async def route(*args):calls.append(args);return {}
    value=LiveRuntime(engine=engine,decision_context_provider=context,
        route_request_provider=route,clock_ms=lambda:frame['available_at_ms'])
    return value,frame,journal,calls


def test_existing_master_shadow_decision_is_durable_without_entering_router(tmp_path):
    value,frame,journal,calls=runtime(tmp_path)
    try:
        result=run(value.observe(frame))
        assert result['proposal']['action']=='ENTER'
        assert result['execution'] is None and calls==[]
        assert journal.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
        assert journal.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==1
        assert journal.verify_audit()
        again=run(value.observe(frame))
        assert again['duplicate'] and again['proposal']==result['proposal']
        assert journal.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==1
    finally:journal.close()


def test_route_is_awaited_only_after_immutable_master_decision(tmp_path):
    value,frame,journal,calls=runtime(tmp_path,mode=Mode.LIVE_PREPARED)
    async def wrong_route(decision,proposal,source):
        assert value._retained(decision)['payload']['proposal']==proposal
        assert journal.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
        return dict(side='BUY',decision_id=decision,mint='wrong',amount_in=1)
    value.route_request_provider=wrong_route
    try:
        with pytest.raises(ValueError,match='frozen_Master'):
            run(value.observe(frame))
        assert journal.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==1
        assert journal.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
    finally:journal.close()


def test_live_requires_policy_approval_and_cannot_execute_synthetic_frames(tmp_path):
    value,frame,journal,calls=runtime(tmp_path,mode=Mode.LIVE_ENABLED)
    try:
        with pytest.raises(ValueError,match='policy_approval'):
            run(value.observe(frame))
        frame['id']+='-second'
        value.approved_policy_sha256=value.core.policy_sha256
        with pytest.raises(ValueError,match='synthetic_frames'):
            run(value.observe(frame))
        assert calls==[]
    finally:journal.close()


def test_future_history_stale_frame_and_reused_id_fail_closed(tmp_path):
    value,frame,journal,calls=runtime(tmp_path)
    try:
        with pytest.raises(ValueError,match='nonprior'):
            run(value.observe(frame,[deepcopy(frame)]))
        stale=deepcopy(frame);stale['available_at_ms']-=5001
        with pytest.raises(ValueError,match='stale'):
            run(value.observe(stale))
        run(value.observe(frame))
        frame['features']['price_usd']*=2
        with pytest.raises(ValueError,match='identity_reused'):
            run(value.observe(frame))
        assert calls==[]
    finally:journal.close()


def test_actual_scanner_context_does_not_invent_authority_health_or_capital(tmp_path):
    journal=ExecutionJournal(tmp_path/'context.sqlite')
    engine=ExecutionEngine(journal=journal,rpc=FakeRpc())
    scanner=ScannerHealth(require_observations=True,clock_ms=lambda:1000,monotonic_ms=lambda:1000)
    context=JournalDecisionContext(engine,scanner,clock_ms=lambda:1000)
    try:
        value=run(context())
        assert value['capital'] is None
        assert value['health']['allow_new_entries'] is False
        assert value['health']['observed_at_ms'] is None
        scanner.observe_rpc(True);scanner.observe_websocket('subscribed')
        value=run(context())
        assert value['capital'] is None
        assert value['health']['observed_at_ms']==1000
    finally:journal.close()
