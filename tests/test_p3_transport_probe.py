"""Diagnostic failures use fake context managers, never live HTTPS requests."""
import asyncio
import json

import aiohttp
import pytest

from bot.p3 import transport


@pytest.mark.parametrize('failure',[
    OSError('private diagnostic text'),
    aiohttp.ConnectionTimeoutError('private connect text'),
    aiohttp.SocketTimeoutError('private read text'),
    aiohttp.ClientSSLError(None, OSError('private TLS text')),
    aiohttp.ClientProxyConnectionError(None, OSError('private proxy text')),
    301, 401, 402, 403, 407, 429, 451, 500,
])
def test_diagnostic_stops_after_first_failure_without_reading_a_body_or_retry(monkeypatch,failure):
    calls=[];events=[]
    class Response:
        status=failure
        async def __aenter__(self):
            if isinstance(failure,Exception):raise failure
            return self
        async def __aexit__(self,*args):pass
        async def json(self,*args,**kwargs):pytest.fail('Diagnostic read a market body')
        async def read(self,*args,**kwargs):pytest.fail('Diagnostic read a market body')
    class Session:
        _retry_connection=True
        def __init__(self,**kwargs):
            assert kwargs['trust_env'] is False
            assert kwargs['timeout'].total==4
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def head(self,url,**kwargs):
            assert self._retry_connection is False
            assert kwargs==dict(proxy='http://managed.invalid:8080',allow_redirects=False)
            calls.append(url);return Response()
    monkeypatch.setattr(transport.aiohttp,'ClientSession',Session)
    monkeypatch.setattr(transport,'connector',lambda *args,**kwargs:None)
    asyncio.run(transport.probe_https_origins(['https://first.invalid/','https://second.invalid/'],
        'http://managed.invalid:8080',transport.PhaseRecorder(events.append)))
    assert calls==['https://first.invalid/']
    assert events[-1]['phase']=='diagnostic_stopped'
    assert 'private' not in json.dumps(events)


def test_010_plan_is_distinct_and_quotes_cannot_be_resized():
    from bot.p3.active_cohort_campaign import make_plan,make_plan_010,validate_plan
    old=make_plan(registered_at_ms=1,source_revision='a'*40)
    new=make_plan_010(registered_at_ms=1,source_revision='a'*40)
    assert validate_plan(old)!=validate_plan(new)
    assert new['control_id']=='P3-010'
    assert new['acquisition']==old['acquisition']
    assert new['comparison']['resizing_provider_quotes'] is False
    new['transport']['phase_timeouts_seconds']['connect']=10
    with pytest.raises(ValueError,match='Exact'):validate_plan(new)


def test_phase_policy_applies_to_all_campaign_requests_without_changing_old_default():
    from bot.p3.campaign import CampaignSession,INDEX_URL
    from bot.p3.collect import CANONICAL_RPC_URL
    from bot.p3.quotes import RAYDIUM_QUOTE_URL
    from test_p3_collection import Transport
    from test_p3_quotes import Response
    for phased in (False,True):
        fake=Transport(gets=[Response({}),Response({})],posts=[Response({})])
        session=CampaignSession(fake,20,rpc_url=CANONICAL_RPC_URL,bounded_phases=phased)
        session.get(INDEX_URL,params={'sort':'new'},timeout=aiohttp.ClientTimeout(total=8))
        session.post(CANONICAL_RPC_URL,json=dict(jsonrpc='2.0',id=1,method='getBlockTime',params=[1]),timeout=aiohttp.ClientTimeout(total=8))
        session.get(RAYDIUM_QUOTE_URL,params=dict(inputMint='a',outputMint='b',amount='1',slippageBps='100',txVersion='V0'),timeout=aiohttp.ClientTimeout(total=8))
        assert session.requests_used==3
        for method,url,options in fake.calls:
            timeout=options['timeout']
            assert timeout.total==8
            assert timeout.connect==(4 if phased else None)
            assert timeout.sock_connect==(3 if phased else None)
            assert timeout.sock_read==(4 if phased else None)


@pytest.mark.parametrize('actual',[None,'http://different.invalid:8080'])
def test_010_rejects_missing_or_inconsistent_proxy_before_journal_creation(tmp_path,monkeypatch,actual):
    from bot.p3 import collect,active_cohort_campaign as active
    monkeypatch.setattr(collect,'_environment_proxy',lambda url:actual)
    monkeypatch.setattr(transport.Path,'read_text',lambda self:json.dumps(dict(http_proxy='http://managed.invalid:8080')))
    def forbidden(*args,**kwargs):pytest.fail('Unsafe route created capture/transport')
    monkeypatch.setattr(active,'CaptureStore',forbidden)
    with pytest.raises(ValueError,match='Configured managed proxy'):
        asyncio.run(active._capture(active.make_plan_010(registered_at_ms=1,source_revision='a'*40),tmp_path/'never.sqlite'))


def test_every_source_has_the_frozen_managed_proxy_route(monkeypatch):
    from bot.p3 import collect
    monkeypatch.setattr(collect,'_environment_proxy',lambda url:'http://managed.invalid:8080')
    origins=['https://first.invalid/','https://second.invalid/']
    routes=transport.managed_proxy_routes(origins,policy=dict(http_proxy='http://managed.invalid:8080'))
    assert routes==dict.fromkeys(origins,'http://managed.invalid:8080')
