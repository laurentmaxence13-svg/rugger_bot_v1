"""Adversarial prospective-run guards, on synthetic transport only."""
import asyncio

import pytest

from bot.p3 import prospective_campaign as prospective
from bot.p3.campaign import CampaignSession
from bot.p3.store import CaptureStore
from test_p3_campaign import indexed, payload
from test_p3_collection import Transport, rpc
from test_p3_launchlab import fixture, encode
from test_p3_quotes import Response, quote_payload, SOL_MINT, USDC


def plan():
    return dict(prospective.FIXED, registered_at_ms=1, source_revision='a'*40)


def fixture_transport(*quote_responses):
    accounts, addresses=fixture()
    source=Transport(posts=[rpc({'context':{'slot':10},'value':[accounts[addresses['pool']]]}),rpc([])],
                     gets=[Response(payload(indexed())),*quote_responses])
    source._retry_connection=False
    return source,addresses


def fake_bank(monkeypatch):
    calls=[]
    async def grouped(store,session,append,rows,graphs,minimum_slot,phase):
        calls.append(phase)
        return max(10,minimum_slot),{row['mint']:{'analysis':{}} for row in rows}
    async def no_sleep(_delay):
        return None
    monkeypatch.setattr(prospective,'_grouped_snapshot',grouped)
    monkeypatch.setattr(prospective.asyncio,'sleep',no_sleep)
    return calls


def test_discovery_throttle_preserves_receipt_and_produces_zero_candidate_report(tmp_path):
    transport=Transport(gets=[Response(status=429,headers={'Retry-After':'30'})])
    transport._retry_connection=False
    session=CampaignSession(transport,20)
    with CaptureStore(tmp_path/'throttled.sqlite') as store:
        report=asyncio.run(prospective.collect_prospective(store,session,plan(),provenance='synthetic'))
        events=store.events()
        assert events[-1]['outcome']=='prospective_closed'
        assert events[-1]['payload']['stop_reason']=='source_error_after_persisted_receipt'
        requests=store.events(kind='request')
        assert len(requests)==1 and requests[0]['payload']['http_status']==429
        assert report['selected_corpus_size']==0
        assert report['qualified_economic_quote_scenarios']==0
    assert session.requests_used==len(transport.calls)==1


@pytest.mark.parametrize('source_failure',[OSError('synthetic connection failure'),asyncio.TimeoutError()])
def test_buy_transport_error_stops_global_schedule_after_persisted_receipt(tmp_path,monkeypatch,source_failure):
    grouped=fake_bank(monkeypatch)
    transport,_=fixture_transport(Response(error=source_failure))
    session=CampaignSession(transport,20)
    with CaptureStore(tmp_path/'buy-error.sqlite') as store:
        asyncio.run(prospective.collect_prospective(store,session,plan(),provenance='synthetic'))
        attempts=[e for e in store.events(kind='quote_attempt') if e['payload'].get('provider')=='raydium_trade_api']
        assert len(attempts)==1 and attempts[0]['outcome']=='unavailable'
        assert store.events()[-1]['payload']['stop_reason']=='source_error_after_persisted_receipt'
    assert grouped==['initial']
    # Index, pool roots, failed quote; no signature/fee-reference RPC afterwards.
    assert len(transport.calls)==session.requests_used==3


def test_partial_diagnostic_transport_error_stops_before_followup_and_fee_lookup(tmp_path,monkeypatch):
    grouped=fake_bank(monkeypatch)
    _,addresses=fixture()
    buy=quote_payload(output_mint=addresses['mint_a'])
    transport,_=fixture_transport(Response(buy),Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'}),
                                  Response(error=OSError('synthetic partial response reset')))
    session=CampaignSession(transport,20)
    with CaptureStore(tmp_path/'partial-error.sqlite') as store:
        asyncio.run(prospective.collect_prospective(store,session,plan(),provenance='synthetic'))
        attempts=[e for e in store.events(kind='quote_attempt') if e['payload'].get('provider')=='raydium_trade_api']
        assert len(attempts)==3
        assert attempts[-1]['payload']['exit_scope']=='partial_diagnostic'
        assert attempts[-1]['reason']=='transport_error'
        assert store.events()[-1]['payload']['stop_reason']=='source_error_after_persisted_receipt'
    assert grouped==['initial']
    assert len(transport.calls)==session.requests_used==5


def test_native_sol_prefix_ignores_out_of_scope_row_before_duplicate_filtering():
    first=indexed()
    wrong_quote=dict(first,mintB={'address':USDC})
    other=[indexed(mint=encode(bytes([n])*32),pool=encode(bytes([n+10])*32)) for n in (20,21,22)]
    retained,selected,total=prospective.select_prefix(payload(wrong_quote,first,*other))
    assert total==5 and len(selected)==3
    assert [row['index'] for row in selected]==[1,2,3]
    assert retained[0]['selection_reason']=='invalid_or_outside_native_SOL_scope'
    assert retained[-1]['selection_reason']=='outside_fixed_prefix'


def test_malformed_grouped_account_bank_stops_before_fee_reference(tmp_path):
    accounts,addresses=fixture()
    transport=Transport(posts=[
        rpc({'context':{'slot':10},'value':[accounts[addresses['pool']]]}),
        rpc({'context':{'slot':11},'value':[]}),  # Wrong length for seven requested accounts.
        rpc([])], gets=[Response(payload(indexed()))])
    transport._retry_connection=False
    session=CampaignSession(transport,20)
    with CaptureStore(tmp_path/'bad-bank.sqlite') as store:
        asyncio.run(prospective.collect_prospective(store,session,plan(),provenance='synthetic'))
        banks=store.events(kind='pool_snapshot')
        assert banks[-1]['payload']['raw_rpc_result']=={'context':{'slot':11},'value':[]}
        assert store.events()[-1]['payload']['stop_reason']=='source_error_after_persisted_receipt'
    assert len(transport.calls)==session.requests_used==3


def test_native_quote_uses_last_global_attempt_without_resetting_rpc_budget(tmp_path):
    import time
    from bot.p3.inventory_provider import NativeInventoryQuoteProvider
    transport=Transport(posts=[rpc(10) for _ in range(19)],gets=[Response(quote_payload())])
    transport._retry_connection=False
    session=CampaignSession(transport,20)
    session._deadline_ns=time.monotonic_ns()+60_000_000_000
    for _ in range(19):
        session.post(prospective.RPC_URL,json={'jsonrpc':'2.0','id':1,'method':'getBlockTime','params':[10]})
    with CaptureStore(tmp_path/'shared-budget.sqlite') as store:
        def append(kind,**event):
            return store.append(kind,provenance='synthetic',**event)
        reader=prospective.NativeInventoryQuoteProvider(transport,store,shared_session=session,
            append=append,stop_on_provider_rejection=False,max_requests=20)
        async def run():
            args=dict(side='buy',amount_atomic='1000000000',inventory=None,decision_at_ms=1)
            first=await reader(None,USDC,**args)
            assert first is not None
            assert await reader(None,USDC,**args) is None
        asyncio.run(run())
        assert len(store.events(kind='quote_attempt'))==1
    assert len(transport.calls)==session.requests_used==reader.requests_used==20
    assert reader.stopped_reason=='inventory_quote_request_budget_exhausted'


def test_shared_session_endpoint_must_match_preregistered_source_before_any_wire(tmp_path):
    from bot.p3.collect import CANONICAL_RPC_URL
    transport=Transport(gets=[Response(status=429)])
    transport._retry_connection=False
    session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL)
    with CaptureStore(tmp_path/'wrong-source.sqlite') as store:
        with pytest.raises(ValueError,match='endpoint'):
            asyncio.run(prospective.collect_prospective(store,session,plan(),provenance='synthetic'))
        assert store.events()==[]
    assert session.requests_used==len(transport.calls)==0
