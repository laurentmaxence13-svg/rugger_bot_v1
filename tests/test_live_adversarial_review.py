"""Independent counter-review regressions, isolated fake services only."""
import asyncio
import json

import pytest

from test_live_engine import configured


def test_persistent_kill_during_last_rpc_await_prevents_submission(tmp_path):
    engine,order,rpc,signer,_=configured(tmp_path)
    original=rpc.get_block_height
    async def interrupted_height():
        value=await original()
        if signer.calls:
            engine.journal.kill('independent-stop-during-final-height',1100)
        return value
    rpc.get_block_height=interrupted_height
    decision=json.loads(order.rebuild_request_json)['decision_id']
    try:
        asyncio.run(engine.execute(decision,order))
    except ValueError:
        pass
    assert engine.journal.killed
    assert not rpc.send_calls,'A persisted kill must gate the final write-ahead submission transition'


@pytest.mark.parametrize('new_clock',[2101,10000])
def test_authorization_and_health_expiry_during_last_rpc_await_prevent_submission(tmp_path,new_clock):
    engine,order,rpc,signer,clock=configured(tmp_path)
    original=rpc.get_block_height
    async def delayed_height():
        value=await original()
        if signer.calls:
            clock[0]=new_clock
        return value
    rpc.get_block_height=delayed_height
    decision=json.loads(order.rebuild_request_json)['decision_id']
    try:
        asyncio.run(engine.execute(decision,order))
    except ValueError:
        pass
    assert not rpc.send_calls,'Final admission must use the clock after the last awaited RPC'
