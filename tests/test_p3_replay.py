"""Offline quote semantics survive portable export; no provider/network access."""
import asyncio
from copy import deepcopy

import pytest

from bot.p3.collect import _record_quote
from bot.p3.evidence import export_capture, verify_bundle
from bot.p3.replay import replay_quote_observation
from bot.p3.store import CaptureStore
from test_p3_quotes import client, Session, Response, quote_payload, SOL_MINT, USDC


@pytest.mark.parametrize('status,body,expected', [
    (200, quote_payload(), 'REPLAYED'),
    (200, {'success': False, 'msg': 'ROUTE_NOT_FOUND'}, 'REPLAYED'),
    (429, quote_payload(), 'HTTP_ERROR_RETAINED'),
])
def test_quote_semantics_replay_after_export_without_source_database(tmp_path, status, body, expected):
    quote = asyncio.run(client(Session(Response(body, status=status))).quote(SOL_MINT, USDC, '1000000000'))
    source = tmp_path/'source.sqlite'
    with CaptureStore(source) as store:
        def append(kind, **event):
            return store.append(kind, provenance='synthetic', **event)
        assert _record_quote(append, quote, 'buy', 'synthetic-request')
        tail = store.verify_integrity()
    export_capture(source, tmp_path/'bundle', run_id='synthetic-quotes', source_revision='a'*40,
                   completeness={'quote_body': 'sanitized_retained'})
    source.unlink()
    event = verify_bundle(tmp_path/'bundle', expected_tail=tail)['events'][0]
    replay = replay_quote_observation(event)
    assert replay['status'] == expected and replay['execution_verified'] is False
    changed = deepcopy(event)
    changed['payload']['output_amount_atomic'] = '999'
    with pytest.raises(ValueError):
        replay_quote_observation(changed)
    changed = deepcopy(event)
    changed['payload']['retained_sanitized_response']['msg'] = 'changed-body'
    with pytest.raises(ValueError, match='digest'):
        replay_quote_observation(changed)


def test_missing_quote_body_is_not_reconstructed_or_claimed_replayed():
    assert replay_quote_observation({'kind': 'quote_attempt', 'payload': {
        'provider': 'raydium_trade_api', 'sanitized_response_sha256': '0'*64,
    }}) == {'status': 'MISSING_BODY', 'execution_verified': False}
