"""Bounded read-only capture integration with synthetic providers, never network."""
import asyncio
import copy
import hashlib
import json
import sys

import pytest

from bot.p3 import collect
from bot.p3.store import CaptureStore
from test_multiple_launches import transaction, instruction
from test_p3_quotes import Response, quote_payload


class Transport:
    def __init__(self, posts=(), gets=()):
        self.posts, self.gets = iter(posts), iter(gets)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(('POST', url, copy.deepcopy(kwargs)))
        return next(self.posts)

    def get(self, url, **kwargs):
        self.calls.append(('GET', url, copy.deepcopy(kwargs)))
        return next(self.gets)


def rpc(result):
    return Response({'jsonrpc': '2.0', 'id': 1, 'result': result})


def test_bounded_snapshot_keeps_creations_failures_unfetched_and_absent_quotes(tmp_path):
    page = [dict(signature=sig, slot=i, blockTime=100, err=error)
            for i, (sig, error) in enumerate((('multi', None), ('missing', None),
                                               ('failed', {'InstructionError': [0, 'x']}),
                                               ('unfetched', None)), 1)]
    transport = Transport(posts=[rpc(100), rpc(page),
        rpc(transaction(instruction('a'), instruction('b'))), rpc(None)],
        gets=[Response([])])
    session = collect.ReadOnlySession(transport, 8)
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        report = asyncio.run(collect.collect_snapshot(store, session, provenance='synthetic'))
        events = store.events()
        assert {e['mint'] for e in events if e['kind'] == 'launch'} == {'a', 'b'}
        txs = [e for e in events if e['kind'] == 'transaction']
        assert {e['signature'] for e in txs} == {'multi', 'missing', 'failed', 'unfetched'}
        assert next(e for e in txs if e['signature'] == 'missing')['outcome'] == 'missing'
        assert next(e for e in txs if e['signature'] == 'unfetched')['reason'] == 'bounded_fetch_budget'
        assert next(e for e in txs if e['signature'] == 'failed')['outcome'] == 'chain_failed'
        assert all(not e['payload']['entry_permitted'] for e in events
                   if e['kind'] == 'candidate_decision' and e['outcome'] == 'not_evaluated')
        assert report['market_detection_coverage'] is None and report['open_gap_count'] == 1
        assert report['missing_transactions'] == 2
        assert report['p3_go'] is report['real_orders_enabled'] is False
        assert session.requests_used == 5
        assert all(e['provenance'] == 'synthetic' for e in events)
        assert {e['mint'] for e in events if e['kind'] == 'quote_attempt'} == {'a', 'b'}
        assert all(e['reason'] == 'outside_bounded_quote_sample' for e in events
                   if e['kind'] == 'quote_attempt')


def test_buy_is_persisted_before_sell_and_exact_output_is_sell_input(tmp_path):
    buy = quote_payload(output='25000000')
    sell = quote_payload(input_mint=collect.USDC_MINT, output_mint=collect.SOL_MINT,
                         amount='25000000', output='990000000', minimum='980100000')
    path = tmp_path / 'capture.sqlite'
    transport = Transport(posts=[rpc(100), rpc([])], gets=[Response([]), Response(buy)])
    session = collect.ReadOnlySession(transport)
    with CaptureStore(path) as store:
        get = transport.get
        def observe(url, **kwargs):
            if url == collect.RAYDIUM_QUOTE_URL and kwargs['params']['inputMint'] == collect.USDC_MINT:
                quotes = store.events(kind='quote_attempt')
                assert len(quotes) == 1 and quotes[0]['payload']['quote_side'] == 'buy'
                transport.calls.append(('GET', url, copy.deepcopy(kwargs)))
                return Response(sell)
            return get(url, **kwargs)
        transport.get = observe
        report = asyncio.run(collect.collect_snapshot(store, session,
            quote_mint=collect.USDC_MINT, provenance='synthetic'))
        quotes = store.events(kind='quote_attempt')
        assert len(quotes) == 2 and quotes[0]['request_id'] == quotes[1]['request_id']
        assert quotes[1]['payload']['input_amount_atomic'] == quotes[0]['payload']['output_amount_atomic']
        assert quotes[1]['payload']['execution_guaranteed'] is False
        assert quotes[1]['payload']['fee_details']['total_cost_known'] is False
        assert report['unavailable_quotes'] == 0
        assert report['quotes_without_source_time'] == 2
        assert report['p3_go'] is False


def test_failed_buy_leaves_explicit_unattempted_sell(tmp_path):
    transport = Transport(posts=[rpc(100), rpc([])], gets=[Response([]), Response(status=429)])
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        report = asyncio.run(collect.collect_snapshot(store, collect.ReadOnlySession(transport),
            quote_mint=collect.USDC_MINT, provenance='synthetic'))
        quotes = store.events(kind='quote_attempt')
        assert [e['outcome'] for e in quotes] == ['unavailable', 'not_attempted']
        assert quotes[1]['reason'] == 'buy_quote_unavailable'
        assert report['unavailable_quotes'] == 2
        assert len(transport.calls) == 4


@pytest.mark.parametrize('response', [Response(status=429), Response({'jsonrpc':'2.0','id':1,'error':{'code':-32005}}), rpc(None), rpc([{}])])
def test_scan_errors_do_not_become_empty_complete_universe(tmp_path, response):
    transport = Transport(posts=[rpc(100), response], gets=[Response([])])
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        report = asyncio.run(collect.collect_snapshot(store, collect.ReadOnlySession(transport), provenance='synthetic'))
        assert report['open_gap_count'] == 2
        assert report['market_detection_coverage'] is None and report['p3_go'] is False


def test_fx_display_price_keeps_missing_source_time_and_cannot_be_strict_fx(tmp_path):
    pairs = [dict(baseToken={'address':collect.SOL_MINT}, priceUsd='120.0123456789',
                  pairAddress='synthetic-pair', liquidity={'usd':'100000'})]
    transport = Transport(gets=[Response(pairs)])
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        def append(kind, **record):
            return store.append(kind, provenance='synthetic', **record)
        asyncio.run(collect.capture_fx(collect.ReadOnlySession(transport), append))
        event = store.events()[0]
        assert event['outcome'] == 'indicative'
        assert event['source_time_ms'] is None
        assert event['payload']['display_observation']['rate'] == '120.0123456789'
        assert event['payload']['eligible_for_strict_fx_conversion'] is False


@pytest.mark.parametrize('pair', [dict(baseToken='invalid', liquidity={'usd':'1000'}),
                                 dict(baseToken={'address':collect.SOL_MINT}, liquidity=10)])
def test_malformed_fx_fields_leave_explicit_missing_quote_not_an_abort(tmp_path, pair):
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        def append(kind, **record):
            return store.append(kind, provenance='synthetic', **record)
        asyncio.run(collect.capture_fx(collect.ReadOnlySession(Transport(gets=[Response([pair])])), append))
        event = store.events()[0]
        assert event['outcome'] == 'unavailable'
        assert event['reason'] == 'no_valid_sol_usd_display_price'


def test_slot_mismatch_preserves_raw_transaction_but_rejects_identity(tmp_path):
    tx = transaction(instruction())
    tx['slot'] = 99
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        def append(kind, **record):
            return store.append(kind, provenance='synthetic', **record)
        assert collect.capture_transaction(append, tx, signature='s', slot=1,
            received_at_ms=collect.now_ms()) == []
        assert store.events(kind='transaction')[0]['payload']['raw_transaction'] == tx
        assert store.events(kind='candidate_decision')[0]['reason'] == 'signature_transaction_slot_mismatch'
        assert store.events(kind='launch') == []


@pytest.mark.parametrize('change', ['missing_chain_status', 'invalid_message'])
def test_unknown_chain_status_or_message_shape_never_creates_a_launch(tmp_path, change):
    tx = transaction(instruction())
    if change == 'missing_chain_status':
        tx['meta'].pop('err')
    else:
        tx['transaction']['message'] = ['unexpected']
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        def append(kind, **record):
            return store.append(kind, provenance='synthetic', **record)
        assert collect.capture_transaction(append, tx, signature='s', slot=1,
            received_at_ms=collect.now_ms()) == []
        assert store.events()[0]['outcome'] == 'failed'
        assert store.events()[0]['reason'] == 'invalid_transaction_shape'
        assert store.events(kind='launch') == []


def test_invalid_nested_instructions_are_recorded_as_rejected_not_fatal(tmp_path):
    tx = transaction(instruction())
    tx['transaction']['message']['instructions'] = ['invalid-instruction']
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        def append(kind, **record):
            return store.append(kind, provenance='synthetic', **record)
        assert collect.capture_transaction(append, tx, signature='s', slot=1,
            received_at_ms=collect.now_ms()) == []
        assert store.events(kind='transaction')[0]['payload']['raw_transaction'] == tx
        assert store.events(kind='candidate_decision')[0]['reason'] == 'conflicting_or_invalid_launch_identity'


def test_unsafe_program_payload_is_not_leaked_or_silently_discarded(tmp_path):
    tx = transaction(instruction())
    tx['meta']['logMessages'] = ['api_key=synthetic-not-a-real-credential']
    with CaptureStore(tmp_path / 'capture.sqlite') as store:
        def append(kind, **record):
            return store.append(kind, provenance='synthetic', **record)
        assert collect.capture_transaction(append, tx, signature='s', slot=1,
            received_at_ms=collect.now_ms()) == []
        events = store.events()
        assert events[0]['outcome'] == 'failed'
        assert events[0]['reason'] == 'unsafe_or_invalid_raw_payload'
        assert 'response_representation_sha256' in events[0]['payload']
        assert 'synthetic-not-a-real-credential' not in json.dumps(events)


def test_readonly_policy_refuses_financial_methods_redirect_auth_and_budget_before_transport():
    transport = Transport(gets=[Response([])])
    session = collect.ReadOnlySession(transport, 1)
    for method in ('sendTransaction', 'requestAirdrop', 'simulateTransaction'):
        with pytest.raises(collect.ReadOnlyPolicyError):
            session.post(collect.RPC_URL, json={'method':method})
    for url, kwargs in [('https://example.com', {}), (collect.FX_URL, {'auth':'secret'}),
                        (collect.RAYDIUM_QUOTE_URL, {'params':{'api-key':'never-send'}})]:
        with pytest.raises(collect.ReadOnlyPolicyError):
            session.get(url, **kwargs)
    assert not transport.calls and session.requests_used == 0
    session.get(collect.FX_URL, allow_redirects=True)
    assert transport.calls[0][2]['allow_redirects'] is False
    with pytest.raises(collect.ReadOnlyPolicyError):
        session.get(collect.FX_URL)
    assert len(transport.calls) == 1 and session.requests_used == 1


def test_cli_requires_network_opt_in_before_opening_journal(tmp_path, monkeypatch):
    path = tmp_path / 'capture.sqlite'
    monkeypatch.setattr(sys, 'argv', ['collect','collect','--db',str(path),'--output',str(tmp_path/'report.json')])
    with pytest.raises(SystemExit):
        collect.main()
    assert not path.exists()


def test_validator_is_readonly_and_cannot_overwrite_capture(tmp_path, monkeypatch):
    path, output = tmp_path/'capture.sqlite', tmp_path/'report.json'
    with CaptureStore(path) as store:
        store.append('launch', received_at_ms=collect.now_ms(), outcome='observed', provenance='synthetic')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(sys,'argv',['collect','validate','--db',str(path),'--output',str(output)])
    collect.main()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert json.loads(output.read_text())['records'] == 1
    monkeypatch.setattr(sys,'argv',['collect','validate','--db',str(path),'--output',str(path)])
    with pytest.raises(SystemExit):
        collect.main()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
