"""Public inventory quotes on fake transport only; no request leaves the test."""
import asyncio

import pytest

from bot.p3 import inventory_provider as ip
from bot.p3.exit_qualification import inventory_from_buy
from bot.p3.replay import replay_quote_observation
from bot.p3.store import CaptureStore
from test_p3_quotes import Session, Response, quote_payload, SOL_MINT, USDC


class Transport(Session):
    _retry_connection = False


def test_proxy_resolution_cannot_dispatch_after_global_deadline(monkeypatch):
    from bot.p3.collect import RAYDIUM_QUOTE_URL, ReadOnlyPolicyError
    clock = [9.0]
    def delayed_proxy(_url):
        clock[0] = 11.0
        return None
    monkeypatch.setattr(ip.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(ip, '_environment_proxy', delayed_proxy)
    transport = Transport(Response(quote_payload()))
    session = ip._DeadlineQuoteSession(transport, 1, deadline=10.0)
    with pytest.raises(ReadOnlyPolicyError, match='proxy resolution'):
        session.get(RAYDIUM_QUOTE_URL, params={
            'inputMint':SOL_MINT,'outputMint':USDC,'amount':'1000000000',
            'slippageBps':'100','txVersion':'V0'})
    assert transport.calls == []


def call(provider, *, side='buy', amount='1000000000', inventory=None):
    return provider(None, USDC, side=side, amount_atomic=amount,
                    inventory=inventory, decision_at_ms=1000)


def test_exact_buy_and_remaining_sell_use_committed_live_envelopes_and_unknown_fees(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, '_environment_proxy', lambda _url: None)
    transport = Transport(Response(quote_payload()),
        Response(quote_payload(USDC,SOL_MINT,'25000000','990000000','980100000')))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        async def scenario():
            buy = await call(provider)
            sell = await call(provider,side='sell',amount='25000000',
                              inventory={'mint':USDC,'remaining_atomic':'25000000'})
            return buy,sell
        buy,sell = asyncio.run(scenario())
        for context,side in ((buy,'buy'),(sell,'sell')):
            event = context[side+'_observation']
            assert event in store.events()
            assert event['provenance'] == 'live' and event['available_at_ms'] >= event['received_at_ms']
            assert replay_quote_observation(event)['status'] == 'REPLAYED'
            assert context['fees'] is context['token_decimals'] is None
            assert context['acquisition_verified'] is context['execution_verified'] is False
        projected = inventory_from_buy(buy['buy_observation'], token_decimals=None,
            entry_decision_at_ms=buy['buy_observation']['available_at_ms'],max_source_age_ms=5000)
        assert projected['accepted'] is True and projected['source_timing_qualified'] is False
        assert projected['acquired_atomic'] == '25000000'
        assert sell['requested_quantity_atomic'] == '25000000'
        assert [kwargs['params']['amount'] for _,kwargs in transport.calls] == ['1000000000','25000000']
        assert all(kwargs['allow_redirects'] is False for _,kwargs in transport.calls)
        assert provider.requests_used == 2


@pytest.mark.parametrize('status,body,reason', [
    (429,{'error':'quota'},'http_429'),
    (403,{'error':'forbidden'},'http_403'),
    (200,{'success':False,'msg':'INSUFFICIENT_LIQUIDITY'},'provider_rejected'),
    (200,{'success':True,'data':{}},'malformed_response'),
])
def test_first_refusal_or_error_is_retained_and_latches_all_future_requests(tmp_path,status,body,reason):
    transport = Transport(Response(body,status=status,headers={'Retry-After':'2'}),Response(quote_payload()))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        async def scenario():
            first = await call(provider)
            assert await call(provider) is None
            return first
        result = asyncio.run(scenario())
        event = result['buy_observation']
        assert event['reason'] == provider.stopped_reason == reason
        assert event['payload']['retained_sanitized_response'] == body
        assert event['payload']['output_amount_atomic'] is None
        assert provider.requests_used == len(transport.calls) == 1
        assert len(store.events()) == 1


def test_request_limit_is_counted_before_dispatch_and_never_retried(tmp_path):
    transport = Transport(Response(quote_payload()),Response(quote_payload()))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store,max_requests=1)
        async def scenario():
            assert await call(provider) is not None
            assert await call(provider) is None
        asyncio.run(scenario())
        assert provider.requests_used == len(transport.calls) == 1
        assert provider.stopped_reason == 'inventory_quote_request_budget_exhausted'


@pytest.mark.parametrize('budget',[0,21,True,1.5])
def test_invalid_budget_is_refused_before_dispatch(tmp_path,budget):
    transport = Transport()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        with pytest.raises(ValueError):
            ip.NativeInventoryQuoteProvider(transport,store,max_requests=budget)
    assert transport.calls == []


def test_deadline_starts_at_construction_and_expired_provider_never_dispatches(tmp_path,monkeypatch):
    ticks = [10.0]
    monkeypatch.setattr(ip.time,'monotonic',lambda: ticks[0])
    transport = Transport()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        assert provider.deadline_monotonic == 70.0
        ticks[0] = 70.0
        assert asyncio.run(call(provider)) is None
        assert provider.stopped_reason == 'inventory_quote_deadline_exhausted'
    assert transport.calls == []


@pytest.mark.parametrize('policy',[True,None,0])
def test_transport_retry_switch_must_be_explicitly_disabled_before_dispatch(tmp_path,policy):
    transport = Transport()
    transport._retry_connection = policy
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        assert asyncio.run(call(provider)) is None
        assert provider.stopped_reason == 'inventory_quote_transport_retry_policy_unsafe'
    assert transport.calls == []


def test_sell_never_shrinks_or_substitutes_the_persisted_remainder(tmp_path):
    transport = Transport()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        with pytest.raises(ValueError,match='exactly match'):
            asyncio.run(call(provider,side='sell',amount='1',
                inventory={'mint':USDC,'remaining_atomic':'25000000'}))
        assert provider.stopped_reason == 'invalid_inventory_quote_request'
    assert transport.calls == []


def test_cancellation_retains_exact_requested_quantity_then_propagates_and_latches(tmp_path):
    transport = Transport(asyncio.CancelledError('synthetic interruption'))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        async def scenario():
            with pytest.raises(asyncio.CancelledError):
                await call(provider,side='sell',amount='25000000',
                    inventory={'mint':USDC,'remaining_atomic':'25000000'})
            assert await call(provider) is None
        asyncio.run(scenario())
        event, = store.events()
        assert event['outcome'] == 'cancelled'
        assert event['payload']['input_amount_atomic'] == '25000000'
        assert event['payload']['quote_side'] == 'sell'
        assert event['payload']['execution_verified'] is False
        assert provider.requests_used == len(transport.calls) == 1


def test_concurrent_caller_waits_for_first_refusal_before_getting_no_context(tmp_path):
    transport = Transport(Response({'success':False,'msg':'NO_ROUTE'}),Response(quote_payload()))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        async def scenario():
            return await asyncio.gather(call(provider),call(provider))
        first,second = asyncio.run(scenario())
        assert first['buy_observation']['outcome'] == 'unavailable' and second is None
    assert len(transport.calls) == 1


def test_global_deadline_cancels_inflight_quote_retains_receipt_and_never_retries(tmp_path,monkeypatch):
    class HangingResponse(Response):
        async def json(self, **kwargs):
            await asyncio.Event().wait()
    transport = Transport(HangingResponse(quote_payload()))
    real_monotonic = ip.time.monotonic
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        # Construct as though 59.9 seconds of the fixed session budget elapsed;
        # the real loop timer then bounds even a transport ignoring its timeout.
        monkeypatch.setattr(ip.time,'monotonic',lambda: real_monotonic()-59.9)
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        monkeypatch.setattr(ip.time,'monotonic',real_monotonic)
        async def scenario():
            assert await asyncio.wait_for(call(provider),timeout=1) is None
            assert await call(provider) is None
        asyncio.run(scenario())
        event, = store.events()
        assert event['outcome'] == 'cancelled'
        assert event['payload']['input_amount_atomic'] == '1000000000'
        assert provider.stopped_reason == 'inventory_quote_deadline_exhausted'
        assert provider.requests_used == len(transport.calls) == 1
        assert 0 < transport.calls[0][1]['timeout'].total <= .1


def test_unsafe_body_has_only_policy_rejection_receipt_and_stops_provider(tmp_path):
    body = quote_payload()
    body['api_key'] = 'synthetic-never-retain'
    transport = Transport(Response(body))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        result = asyncio.run(call(provider))
        event = result['buy_observation']
        assert event['reason'] == 'unsafe_or_invalid_quote_payload'
        assert event['payload']['retained_sanitized_response'] is None
        assert 'synthetic-never-retain' not in str(event)
        assert provider.stopped_reason == 'unsafe_or_invalid_quote_payload'
        assert asyncio.run(call(provider)) is None
    assert len(transport.calls) == 1


def test_committed_journal_readback_error_latches_before_any_second_request(tmp_path,monkeypatch):
    transport = Transport(Response(quote_payload()),Response(quote_payload()))
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        original_events = store.events
        def fail_readback(**_kwargs):
            raise OSError('synthetic journal readback interruption')
        monkeypatch.setattr(store,'events',fail_readback)
        provider = ip.NativeInventoryQuoteProvider(transport,store)
        async def scenario():
            with pytest.raises(OSError):
                await call(provider)
            assert provider.stopped_reason == 'inventory_quote_persistence_error'
            assert await call(provider) is None
        asyncio.run(scenario())
        assert len(original_events()) == 1
        assert provider.requests_used == len(transport.calls) == 1
