"""Transport refuses every message except the engine's current durable intent."""
import asyncio
import json

from bot.live.submission import BoundSubmissionGuard
from bot.live.safety import Mode
from test_live_engine import configured


def test_transport_guard_requires_exact_writeahead_intent_and_live_authority(tmp_path):
    async def scenario():
        engine,order,rpc,signer,clock=configured(tmp_path)
        guard=BoundSubmissionGuard(engine)
        seen=[]
        async def send(raw):
            seen.append(guard(raw))
            assert not guard(raw[:-1]+bytes([raw[-1]^1]))
            engine.mode=Mode.LIVE_PREPARED
            assert not guard(raw)
            engine.mode=Mode.LIVE_ENABLED
            clock[0]=engine.envelope.expires_at_ms
            assert not guard(raw)
            clock[0]=1200
            assert guard(raw)
            engine.journal.kill('stop_at_actual_payload_boundary',clock[0])
            assert not guard(raw)
            raise TimeoutError('no actual network transmission')
        rpc.send_transaction=send
        decision=json.loads(order.rebuild_request_json)['decision_id']
        try:
            result=await engine.execute(decision,order)
            assert result['state']=='UNCERTAIN'
            assert seen==[True] and engine.journal.killed
            assert not guard(engine.journal.get(decision)['signed_raw'])
        finally:engine.journal.close()
    asyncio.run(scenario())
