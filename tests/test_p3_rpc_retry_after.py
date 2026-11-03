"""RPC throttle receipts preserve server cooldown evidence without retrying."""
import asyncio
import json

import pytest

from bot.p3 import collect
from test_p3_collection import Transport
from test_p3_quotes import Response


def receipt(headers, monkeypatch=None):
    transport = Transport(posts=[Response(status=429, headers=headers)])
    session = collect.ReadOnlySession(transport, 1)
    events = []
    if monkeypatch is not None:
        clock = iter((2000, 1000))
        monkeypatch.setattr(collect, 'now_ms', lambda: next(clock))
    result, _, _, outcome = asyncio.run(collect._rpc(session,
        lambda kind, **record: events.append(dict(kind=kind, **record)), 'getSlot', []))
    assert result is None and outcome == 'error'
    assert len(transport.calls) == session.requests_used == len(events) == 1
    assert events[0]['reason'] == 'http_429'
    assert events[0]['payload']['http_status'] == 429
    return events[0]['payload']


@pytest.mark.parametrize('header,seconds', [('120', 120), ('0', 0), (' 7 ', 7)])
def test_rpc_429_preserves_exact_delay_seconds_without_retry(header, seconds):
    payload = receipt({'Retry-After': header})
    assert payload['retry_after_seconds'] == seconds
    assert type(payload['retry_after_seconds']) is int
    assert payload['retry_after_status'] == 'delay_seconds'


@pytest.mark.parametrize('header', ['-1', '2.5', 'NaN', '1e9', '２',
                                     'api_key=synthetic-do-not-store', 'x'*300])
def test_malformed_retry_after_is_unknown_and_not_retained_verbatim(header):
    payload = receipt({'Retry-After': header})
    assert payload['retry_after_seconds'] is None
    assert payload['retry_after_status'] == 'invalid'
    assert 'synthetic-do-not-store' not in json.dumps(payload)


def test_missing_retry_after_is_explicitly_unknown():
    payload = receipt({})
    assert payload['retry_after_seconds'] is None
    assert payload['retry_after_status'] == 'missing'


def test_http_date_uses_server_date_even_when_client_clock_regresses(monkeypatch):
    payload = receipt({'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT',
                       'Date': 'Wed, 21 Oct 2015 07:27:30 GMT'}, monkeypatch)
    assert payload['retry_after_seconds'] == 30
    assert payload['retry_after_status'] == 'http_date'
    assert payload['retry_after_date_utc'] == '2015-10-21T07:28:00+00:00'
    assert payload['retry_after_reference_date_utc'] == '2015-10-21T07:27:30+00:00'
    assert payload['requested_at_ms'] == 2000 and payload['received_at_ms'] == 1000


@pytest.mark.parametrize('server_date', [None, 'not-a-date'])
def test_http_date_without_usable_server_reference_never_infers_client_cooldown(server_date):
    headers = {'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT'}
    if server_date is not None:
        headers['Date'] = server_date
    payload = receipt(headers)
    assert payload['retry_after_seconds'] is None
    assert payload['retry_after_status'] == 'http_date_reference_unknown'


def test_elapsed_http_date_has_known_zero_remaining_delay():
    payload = receipt({'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT',
                       'Date': 'Wed, 21 Oct 2015 07:28:30 GMT'})
    assert payload['retry_after_seconds'] == 0
    assert payload['retry_after_status'] == 'http_date'
