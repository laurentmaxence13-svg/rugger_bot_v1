"""One-attempt RPC health read; synthetic transport, no network or wallet."""
import asyncio

import pytest

from bot.p3 import rpc_health as health
from bot.p3.campaign import CampaignSession
from bot.p3.collect import ReadOnlyPolicyError
from bot.p3.store import CaptureStore
from test_p3_collection import Transport, rpc
from test_p3_launchlab import fixture
from test_p3_quotes import Response


def plan():
    return dict(schema='p3-rpc-health-once-v1', plan_id='health-before-007',
        source_revision=health.BASE_REVISION, source_revision_role='base_before_probe',
        rpc_endpoint=health.RPC_URL, max_requests=1, max_elapsed_ms=5000,
        rpc_method='getMultipleAccounts', addresses=[health.SOL_MINT], encoding='base64',
        commitment='finalized', retry=False,
        success_claim='one_valid_WSOL_mint_read_at_receipt_not_future_quota', registered_at_ms=1)


def test_one_healthy_read_retains_public_account_without_certifying_later_quota(tmp_path):
    accounts, _ = fixture()
    result = {'context': {'slot': 42}, 'value': [accounts[health.SOL_MINT]]}
    transport = Transport(posts=[rpc(result)])
    session = CampaignSession(transport, 1)
    with CaptureStore(tmp_path/'health.sqlite') as store:
        report = asyncio.run(health.probe(store, session, plan(), provenance='synthetic'))
        snapshots = store.events(kind='pool_snapshot')
        assert len(snapshots) == 1 and snapshots[0]['payload']['raw_rpc_result'] == result
        assert all(event['provenance'] == 'synthetic' for event in store.events())
    assert report['healthy_at_receipt'] is True
    assert report['context_slot'] == 42
    assert report['future_quota_certified'] is report['other_rpc_methods_certified'] is False
    assert report['market_or_trade_qualified'] is report['real_orders_enabled'] is False
    assert len(transport.calls) == session.requests_used == report['requests_used'] == 1
    method, url, kwargs = transport.calls[0]
    assert method == 'POST' and url == health.RPC_URL
    assert kwargs['json']['params'] == [[health.SOL_MINT], {'encoding':'base64', 'commitment':'finalized'}]
    assert 0 < kwargs['timeout'].total <= 5
    assert kwargs['allow_redirects'] is False
    with pytest.raises(ReadOnlyPolicyError, match='budget'):
        session.post(url, json=kwargs['json'])
    assert len(transport.calls) == 1


def test_throttle_keeps_retry_after_receipt_and_never_retries(tmp_path):
    transport = Transport(posts=[Response(status=429, headers={'Retry-After':'30'})])
    with CaptureStore(tmp_path/'throttled.sqlite') as store:
        report = asyncio.run(health.probe(store, CampaignSession(transport, 1), plan(),
                                          provenance='synthetic'))
        assert store.events(kind='pool_snapshot') == []
    assert report['healthy_at_receipt'] is False and len(transport.calls) == 1
    receipt = report['request_receipt']
    assert receipt['reason'] == 'http_429'
    assert receipt['payload']['http_status'] == 429
    assert receipt['payload']['retry_after_seconds'] == 30
    assert receipt['payload']['retry_after_status'] == 'delay_seconds'


def test_malformed_success_and_modified_plan_are_not_health_success(tmp_path):
    transport = Transport(posts=[rpc({'context': {'slot': 42}, 'value': [None]})])
    with CaptureStore(tmp_path/'invalid.sqlite') as store:
        report = asyncio.run(health.probe(store, CampaignSession(transport, 1), plan(),
                                          provenance='synthetic'))
        assert store.events(kind='pool_snapshot')[0]['outcome'] == 'rejected'
    assert report['healthy_at_receipt'] is False
    assert report['reason'] == 'invalid_WSOL_mint_response'
    altered = plan()
    altered['max_requests'] = 2
    with pytest.raises(ValueError, match='parameters'):
        health.validate_plan(altered)
