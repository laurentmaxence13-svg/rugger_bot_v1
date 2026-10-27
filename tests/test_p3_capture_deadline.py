"""Focused capture failures: cancellation evidence and a monotonic wire deadline."""
import asyncio
import math

import aiohttp
import pytest

from bot.p3 import campaign as cp, collect
from bot.p3.store import CaptureStore
from test_p3_campaign import indexed, payload, plan_v2
from test_p3_collection import Transport, rpc
from test_p3_quotes import Response


class HangingResponse(Response):
    async def json(self, **kwargs):
        await asyncio.Event().wait()


def test_cancelled_rpc_and_discovery_retain_receipts_before_reraising():
    async def run():
        for method in ('rpc', 'discovery'):
            receipts = []
            transport = Transport(posts=[HangingResponse()], gets=[HangingResponse()])
            session = cp.CampaignSession(transport, 20)
            def append(kind, **event):
                receipts.append(dict(kind=kind, **event))
            operation = (collect._rpc(session, append, 'getBlockTime', [123])
                         if method == 'rpc' else cp._discover(session, append))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(operation, timeout=.01)
            assert session.requests_used == len(transport.calls) == len(receipts) == 1
            receipt = receipts[0]
            assert receipt['kind'] == 'request' and receipt['reason'] == 'capture_cancelled'
            assert receipt['payload']['requested_at_ms'] <= receipt['received_at_ms']
            assert receipt['payload']['latency_ms'] >= 0
    asyncio.run(run())


def test_cancelled_buy_and_sell_retain_side_size_and_request_time():
    class Client:
        async def quote(self, *args):
            await asyncio.Event().wait()
    async def run():
        for side in ('buy', 'sell'):
            receipts = []
            def append(kind, **event):
                receipts.append(dict(kind=kind, **event))
            first, second = ((collect.SOL_MINT, collect.USDC_MINT) if side == 'buy'
                             else (collect.USDC_MINT, collect.SOL_MINT))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(cp._quote_with_cancellation_receipt(
                    Client(), append, first, second, '123456', side, 'paired-request'), timeout=.01)
            assert len(receipts) == 1
            receipt = receipts[0]
            assert receipt['kind'] == 'quote_attempt' and receipt['outcome'] == 'cancelled'
            assert receipt['request_id'] == 'paired-request'
            assert receipt['payload']['quote_side'] == side
            assert receipt['payload']['input_mint'] == first
            assert receipt['payload']['output_mint'] == second
            assert receipt['payload']['input_amount_atomic'] == '123456'
            assert receipt['payload']['requested_at_ms'] <= receipt['received_at_ms']
            assert receipt['payload']['position_acquired'] is False
            assert receipt['payload']['execution_verified'] is False
    asyncio.run(run())


def test_rpc_envelope_rejects_boolean_ids_and_wrong_protocol_version():
    for response in ({'jsonrpc': '2.0', 'id': True, 'result': 123},
                     {'jsonrpc': '1.0', 'id': 1, 'result': 123},
                     {'id': 1, 'result': 123}):
        receipts = []
        def append(kind, **event):
            receipts.append(event)
        session = cp.CampaignSession(Transport(posts=[Response(response)]), 20)
        result, _, _, outcome = asyncio.run(collect._rpc(session, append, 'getBlockTime', [123]))
        assert result is None and outcome == 'error'
        assert receipts[0]['reason'] == 'invalid_rpc_envelope'


def test_wire_deadline_caps_timeout_and_rechecks_after_proxy_resolution(monkeypatch):
    clock = [0]
    monkeypatch.setattr(cp.time, 'monotonic_ns', lambda: clock[0])
    transport = Transport(posts=[rpc(None)])
    session = cp.CampaignSession(transport, 20)
    session._deadline_ns = 60_000_000_000
    clock[0] = 59_750_000_000
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'getBlockTime', 'params': [123]}
    session.post(cp.RPC_URL, json=body, timeout=aiohttp.ClientTimeout(total=8))
    timeout = transport.calls[0][2]['timeout']
    assert timeout.total == .25 and math.isinf(timeout.ceil_threshold)
    clock[0] = 60_000_000_000
    with pytest.raises(cp.ReadOnlyPolicyError, match='deadline'):
        session.post(cp.RPC_URL, json=body)
    with pytest.raises(cp.ReadOnlyPolicyError, match='deadline'):
        session.get(cp.INDEX_URL, params={'sort': 'new'})
    assert session.requests_used == len(transport.calls) == 1

    clock[0] = 0
    def delayed_proxy(_url):
        clock[0] = 61_000_000_000
        return None
    transport = Transport()
    session = cp.CampaignSession(transport, 20, proxy_resolver=delayed_proxy)
    session._deadline_ns = 60_000_000_000
    with pytest.raises(cp.ReadOnlyPolicyError, match='deadline'):
        session.get(cp.INDEX_URL, params={'sort': 'new'})
    assert session.requests_used == len(transport.calls) == 0


def test_synchronous_processing_past_deadline_preserves_selection_without_more_wire(tmp_path, monkeypatch):
    clock = [0]
    monkeypatch.setattr(cp.time, 'monotonic_ns', lambda: clock[0])
    original_discover = cp._discover
    async def delayed_discovery(session, append):
        result = await original_discover(session, append)
        # Model time consumed by synchronous JSON/SQLite processing. asyncio's
        # cooperative timer alone cannot run until that work yields control.
        clock[0] = 61_000_000_000
        return result
    monkeypatch.setattr(cp, '_discover', delayed_discovery)
    transport = Transport(gets=[Response(payload(indexed()))])
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20),
                                                 plan_v2(), provenance='synthetic'))
        assert report['manifest']['run']['requests_used'] == len(transport.calls) == 1
        assert report['selected_count'] == len(report['manifest']['candidates']) == 1
        assert report['manifest']['run']['elapsed_ms'] == 61_000
        assert any(event['reason'] == 'campaign_budget_or_deadline_exhausted'
                   for event in store.events(kind='gap'))
        assert report['readiness']['collection_readiness'] == 'NO-GO'
        assert report['readiness']['p3_go'] is False
