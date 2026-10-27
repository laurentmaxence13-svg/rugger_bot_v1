"""Explicit anonymous RPC selection; fake transports only, no network access."""
import asyncio

import pytest

from bot.p3 import collect, campaign
from test_p3_collection import Transport, rpc
from test_p3_quotes import Response

CANONICAL = 'https://api.mainnet.solana.com'


@pytest.mark.parametrize('session_class', [collect.ReadOnlySession, campaign.CampaignSession])
def test_explicit_canonical_endpoint_is_used_and_other_registered_alias_is_refused(session_class):
    transport = Transport(posts=[rpc(123)])
    session = session_class(transport, rpc_url=CANONICAL)
    receipts = []
    result, _, _, outcome = asyncio.run(collect._rpc(
        session, lambda kind, **e: receipts.append(e), 'getTransaction', ['synthetic']))
    assert result == 123 and outcome == 'observed'
    assert receipts[0]['payload']['endpoint_kind'] == 'canonical'
    assert len(transport.calls) == session.requests_used == 1
    assert transport.calls[0][1] == CANONICAL
    assert transport.calls[0][2]['allow_redirects'] is False
    with pytest.raises(collect.ReadOnlyPolicyError):
        session.post(collect.RPC_URL, json={'jsonrpc':'2.0','id':1,'method':'getTransaction','params':[]})
    assert len(transport.calls) == session.requests_used == 1


@pytest.mark.parametrize('session_class', [collect.ReadOnlySession, campaign.CampaignSession])
def test_legacy_default_keeps_historical_alias_and_refuses_automatic_canonical_fallback(session_class):
    transport = Transport(posts=[Response(status=403)])
    session = session_class(transport)
    receipts = []
    result, _, _, outcome = asyncio.run(collect._rpc(
        session, lambda kind, **e: receipts.append(e), 'getTransaction', ['synthetic']))
    assert result is None and outcome == 'error'
    assert receipts[0]['payload']['endpoint_kind'] == 'historical_alias'
    assert receipts[0]['reason'] == 'http_403'
    assert len(transport.calls) == session.requests_used == 1
    assert transport.calls[0][1] == collect.RPC_URL
    with pytest.raises(collect.ReadOnlyPolicyError):
        session.post(CANONICAL, json={'jsonrpc':'2.0','id':1,'method':'getTransaction','params':[]})
    assert len(transport.calls) == 1


@pytest.mark.parametrize('session_class', [collect.ReadOnlySession, campaign.CampaignSession])
@pytest.mark.parametrize('endpoint', ['https://rpc.example.invalid', CANONICAL+'?api-key=synthetic',
                                      'https://name:synthetic@api.mainnet.solana.com', CANONICAL+'/'])
def test_unregistered_or_parameterized_endpoint_is_rejected_before_transport(session_class, endpoint):
    transport = Transport()
    with pytest.raises(collect.ReadOnlyPolicyError):
        session_class(transport, rpc_url=endpoint)
    assert transport.calls == []


def test_direct_rpc_helper_cannot_bypass_url_validation_or_session_selection():
    class UnguardedTransport:
        def post(self, *args, **kwargs):
            raise AssertionError('Unknown endpoint must never reach transport')
    receipts = []
    result, _, _, outcome = asyncio.run(collect._rpc(UnguardedTransport(),
        lambda kind, **e: receipts.append(e), 'getTransaction', [],
        rpc_url='https://rpc.example.invalid?api-key=synthetic'))
    assert result is None and outcome == 'error'
    assert receipts[0]['payload']['endpoint_kind'] == 'unregistered'
    assert 'api-key' not in str(receipts)
    transport = Transport()
    session = collect.ReadOnlySession(transport, rpc_url=CANONICAL)
    result, _, _, outcome = asyncio.run(collect._rpc(session,
        lambda kind, **e: receipts.append(e), 'getTransaction', [], rpc_url=collect.RPC_URL))
    assert result is None and outcome == 'error'
    assert session.requests_used == 0 and transport.calls == []
