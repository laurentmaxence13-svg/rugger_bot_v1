"""Offline adversarial and integration checks of the bounded P3 campaign."""
import asyncio
import copy
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from bot.p3 import campaign as cp
from bot.p3 import collect
from bot.p3.quotes import RAYDIUM_QUOTE_URL, SOL_MINT, RaydiumQuoteClient
from bot.p3.store import CaptureStore
from test_multiple_launches import instruction, transaction
from test_p3_collection import Transport, rpc
from test_p3_launchlab import fixture, encode
from test_p3_quotes import Response, quote_payload


def plan():
    return {
        'schema': 'p3-launchlab-campaign-v1', 'plan_id': 'launchlab-native-sol-001',
        'registered_at_ms': 1, 'sample_size': 2, 'max_requests': 20,
        'max_elapsed_ms': 60_000, 'followup_delay_ms': 15_000,
        'index_sort': 'new', 'max_index_rows': 100, 'signature_limit': 20,
        'transactions_per_pool': 1, 'input_lamports': 1_000_000_000,
        'slippage_bps': 100, 'share_fee_rate_ppm': 0, 'commitment': 'confirmed',
        'selection': 'first_two_valid_unique_SOL_rows_in_response_order',
        'transaction_selection': 'oldest_successful_signature_in_received_page',
        'source_main': '966076c1a8b9a5d83bea74fe53fdad1056ade6dc',
    }


def plan_v2():
    return dict(plan(), schema='p3-launchlab-campaign-v2', plan_id='launchlab-native-sol-002',
                signature_limit=1000, max_supported_transaction_version=1)


def indexed(mint=None, pool=None, **extra):
    _, addresses = fixture()
    return dict(mint=mint or addresses['mint_a'], poolId=pool or addresses['pool'],
                mintB={'address': SOL_MINT}, creator=encode(bytes([8])*32),
                createAt=100_000, **extra)


def payload(*rows):
    return {'success': True, 'data': {'rows': list(rows), 'nextPageId': 'opaque-unfollowed'}}


def append_for(store):
    def append(kind, **event):
        return store.append(kind, provenance='synthetic', **event)
    return append


def bank(accounts, addresses, slot):
    return {'context': {'slot': slot}, 'value': [accounts[address] for address in addresses.values()]}


async def no_sleep(_seconds):
    return None


def test_plan_hash_is_canonical_and_only_exact_registered_protocol_is_allowed():
    declared = plan()
    assert cp.validate_plan(declared) == hashlib.sha256(cp.canonical(declared)).hexdigest()
    reordered = dict(reversed(list(declared.items())))
    assert cp.validate_plan(reordered) == cp.validate_plan(declared)
    for key, changed in [('max_requests', 21), ('sample_size', True),
                         ('index_sort', 'hotToken'), ('registered_at_ms', False),
                         ('share_fee_rate_ppm', 1), ('registered_at_ms', 2**100)]:
        invalid = dict(declared, **{key: changed})
        with pytest.raises(ValueError):
            cp.validate_plan(invalid)
    with pytest.raises(ValueError):
        cp.validate_plan(dict(declared, arbitrary_destination='example.invalid'))


def test_version_two_is_an_explicit_new_plan_and_does_not_rewrite_v1():
    original = plan()
    original_hash = hashlib.sha256(cp.canonical(original)).hexdigest()
    revised = plan_v2()
    assert cp.validate_plan(revised) == hashlib.sha256(cp.canonical(revised)).hexdigest()
    assert cp.validate_plan(original) == original_hash
    assert cp.validate_plan(revised) != original_hash
    assert original['signature_limit'] == 20
    assert 'max_supported_transaction_version' not in original


@pytest.mark.parametrize('key,value', [
    ('schema', 'p3-launchlab-campaign-v1'), ('schema', 'p3-launchlab-campaign-v3'),
    ('plan_id', 'launchlab-native-sol-001'), ('signature_limit', 20),
    ('signature_limit', 999), ('signature_limit', 1000.0), ('signature_limit', '1000'),
    ('max_supported_transaction_version', 0), ('max_supported_transaction_version', 2),
    ('max_supported_transaction_version', True), ('max_supported_transaction_version', 1.0),
    ('max_supported_transaction_version', '1'), ('max_supported_transaction_version', None),
    ('max_requests', 21),
])
def test_version_two_requires_exact_registered_identity_limit_and_transaction_version(key, value):
    invalid = dict(plan_v2(), **{key: value})
    with pytest.raises(ValueError):
        cp.validate_plan(invalid)


def test_transaction_version_field_is_required_only_by_the_new_plan_schema():
    revised = plan_v2()
    del revised['max_supported_transaction_version']
    with pytest.raises(ValueError):
        cp.validate_plan(revised)
    with pytest.raises(ValueError):
        cp.validate_plan(dict(plan(), max_supported_transaction_version=1))


@pytest.mark.parametrize('invalid', [None, [], {}, {'success': 1, 'data': {'rows': []}},
                                   {'success': True, 'data': {'rows': {}}}])
def test_malformed_discovery_is_not_an_empty_complete_universe(invalid):
    with pytest.raises(ValueError, match='Invalid index'):
        cp.select_rows(invalid)


def test_selection_retains_response_order_rejects_duplicates_and_ignores_prices():
    first = indexed(marketCap=0, metadata={'api_key': 'unsafe-fixture'})
    second = indexed(encode(bytes([9])*32), encode(bytes([10])*32), marketCap=1)
    third = indexed(encode(bytes([11])*32), encode(bytes([12])*32), marketCap=10**30)
    non_sol = indexed(encode(bytes([13])*32), encode(bytes([14])*32))
    non_sol['mintB']['address'] = encode(bytes([15])*32)
    rows, chosen, count = cp.select_rows(payload(None, first, copy.deepcopy(first), non_sol,
                                                second, third))
    assert count == len(rows) == 6
    assert [row['mint'] for row in chosen] == [first['mint'], second['mint']]
    assert [row['index'] for row in rows] == list(range(6))
    assert [row['selection_reason'] for row in rows] == [
        'invalid_identity', 'selected_for_observation_only', 'duplicate_mint',
        'outside_native_SOL_scope', 'selected_for_observation_only', 'outside_preregistered_sample']
    assert 'api_key' not in json.dumps(rows) and 'unsafe-fixture' not in json.dumps(rows)
    assert rows[1]['row_representation_sha256'] == cp.digest(first)


def test_retention_cap_is_explicit_and_total_count_preserved():
    rows, selected, count = cp.select_rows(payload(*(indexed() for _ in range(103))))
    assert len(rows) == 100 and count == 103 and len(selected) == 1


def test_same_base_and_quote_currency_is_retained_but_never_selected():
    rows, selected, count = cp.select_rows(payload(indexed(mint=SOL_MINT), indexed()))
    assert count == len(rows) == 2
    assert len(selected) == 1 and selected[0]['mint'] != SOL_MINT
    assert rows[0]['selection_reason'] != 'selected_for_observation_only'


@pytest.mark.parametrize('invalid_first', ['missing_pool', 'non_SOL_quote'])
def test_out_of_scope_row_does_not_poison_later_valid_mint_identity(invalid_first):
    invalid = indexed()
    if invalid_first == 'missing_pool':
        invalid['poolId'] = 'invalid-pool'
    else:
        invalid['mintB']['address'] = encode(bytes([9])*32)
    rows, selected, count = cp.select_rows(payload(invalid, indexed()))
    assert count == 2 and len(selected) == 1
    assert selected[0]['index'] == 1
    assert rows[0]['selection_reason'] in ('invalid_identity', 'outside_native_SOL_scope')


@pytest.mark.parametrize('kwargs', [
    {'headers': {'Authorization': 'fixture'}}, {'auth': 'fixture'},
    {'cookies': {'fixture': 'fixture'}}, {'ssl': False}, {'proxy': 'https://example.invalid'},
    {'allow_redirects': True},
])
def test_discovery_transport_cannot_inject_auth_tls_or_destination_options(kwargs):
    transport = Transport()
    session = cp.CampaignSession(transport)
    with pytest.raises(cp.ReadOnlyPolicyError):
        session.get(cp.INDEX_URL, params={'sort': 'new'}, **kwargs)
    assert transport.calls == [] and session.requests_used == 0


@pytest.mark.parametrize('params', [{}, {'sort': 'hotToken'}, {'sort': 'new', 'page': 2}, None])
def test_discovery_query_does_not_invent_pagination_or_ranking(params):
    transport = Transport()
    session = cp.CampaignSession(transport)
    with pytest.raises(cp.ReadOnlyPolicyError):
        session.get(cp.INDEX_URL, params=params)
    assert transport.calls == []


@pytest.mark.parametrize('method', ['sendTransaction', 'requestAirdrop', 'simulateTransaction',
                                    'getProgramAccounts', 'getTokenAccountsByOwner'])
def test_rpc_financial_and_unregistered_methods_never_reach_transport(method):
    transport = Transport()
    session = cp.CampaignSession(transport)
    with pytest.raises(cp.ReadOnlyPolicyError):
        session.post(cp.RPC_URL, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': []})
    assert transport.calls == [] and session.requests_used == 0


@pytest.mark.parametrize('method', sorted(cp._METHODS))
def test_registered_read_methods_count_attempt_before_transport_and_never_redirect(method):
    transport = Transport(posts=[rpc(None)])
    session = cp.CampaignSession(transport, max_requests=1)
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': []}
    session.post(cp.RPC_URL, json=body)
    assert session.requests_used == 1 and len(transport.calls) == 1
    assert transport.calls[0][2]['allow_redirects'] is False
    with pytest.raises(cp.ReadOnlyPolicyError, match='budget'):
        session.post(cp.RPC_URL, json=body)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('url', ['https://example.invalid', cp.INDEX_URL+'?sort=new',
                                cp.RPC_URL+'/extra', collect.FX_URL])
def test_new_campaign_has_no_unregistered_get_destination(url):
    session = cp.CampaignSession(Transport())
    with pytest.raises(cp.ReadOnlyPolicyError):
        session.get(url, params={'sort': 'new'})
    assert session.requests_used == 0


def test_quote_client_redirect_false_is_compatible_and_exact_amount_reaches_transport():
    _, addresses = fixture()
    response = Response(quote_payload(output_mint=addresses['mint_a']))
    transport = Transport(gets=[response])
    session = cp.CampaignSession(transport)
    quote = asyncio.run(RaydiumQuoteClient(session).quote(SOL_MINT, addresses['mint_a'], 10**9))
    assert quote['outcome'] == 'quoted' and session.requests_used == 1
    assert transport.calls[0][1] == RAYDIUM_QUOTE_URL
    assert transport.calls[0][2]['params']['amount'] == '1000000000'
    assert transport.calls[0][2]['allow_redirects'] is False
    assert quote['execution_guaranteed'] is quote['executable_confirmed'] is False


def test_snapshot_is_committed_before_analysis_and_retains_one_bank_context(tmp_path, monkeypatch):
    accounts, addresses = fixture()
    row = cp.select_rows(payload(indexed()))[1][0]
    result = bank(accounts, addresses, 1234)
    transport = Transport(posts=[rpc(result), rpc(100)])
    session = cp.CampaignSession(transport, 20)
    analyze = cp.analyze_snapshot
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        def checking_analyzer(values, **kwargs):
            events = store.events(kind='pool_snapshot')
            assert len(events) == 1 and events[0]['payload']['raw_rpc_result'] == result
            assert events[0]['source_slot'] == kwargs['context_slot'] == 1234
            with CaptureStore(store.path, readonly=True) as independently_opened:
                assert independently_opened.events(kind='pool_snapshot')[0]['record_hash'] == events[0]['record_hash']
            return analyze(values, **kwargs)
        monkeypatch.setattr(cp, 'analyze_snapshot', checking_analyzer)
        snapshot = asyncio.run(cp._snapshot(store, session, append_for(store), row, addresses, 1200, 'initial'))
        assert snapshot['available_at_ms'] <= snapshot['analysis_at_ms']
        assert snapshot['source_time_ms'] == 100_000 and snapshot['context_slot'] == 1234
        assert transport.calls[0][2]['json']['params'][1]['minContextSlot'] == 1200
        quotes = store.events(kind='quote_attempt')
        assert [q['payload']['quote_side'] for q in quotes] == ['buy', 'sell']
        assert all(q['outcome'] == 'conditional' for q in quotes)
        assert all(q['payload']['position_acquired'] is q['payload']['execution_verified'] is False for q in quotes)


def test_snapshot_replay_preserves_rpc_address_order_across_canonical_json_sorting(tmp_path):
    accounts, addresses = fixture()
    requested = list(addresses.values())
    row = cp.select_rows(payload(indexed()))[1][0]
    transport = Transport(posts=[rpc(bank(accounts, addresses, 1234)), rpc(100)])
    database = tmp_path/'p3.sqlite'
    with CaptureStore(database) as store:
        original = asyncio.run(cp._snapshot(store, cp.CampaignSession(transport, 20),
            append_for(store), row, addresses, 1200, 'initial'))
    with CaptureStore(database, readonly=True) as reopened:
        evidence = reopened.events(kind='pool_snapshot')[0]['payload']
        assert evidence['requested_addresses'] == requested
        assert evidence['requested_addresses'] == transport.calls[0][2]['json']['params'][0]
        # Object-key order changes during canonical serialization. RPC values
        # remain ordered by the request array, never by those sorted role keys.
        assert list(evidence['addresses'].values()) != requested
        values = evidence['raw_rpc_result']['value']
        replayed_accounts = dict(zip(evidence['requested_addresses'], values))
        assert replayed_accounts == accounts
        assert dict(zip(evidence['addresses'].values(), values)) != accounts
        discovered = cp.addresses_from_pool(replayed_accounts[row['pool']], row['mint'], row['pool'])
        assert discovered == addresses
        replayed = cp.analyze_snapshot(replayed_accounts,
            context_slot=evidence['raw_rpc_result']['context']['slot'],
            expected_mint=row['mint'], pool_address=row['pool'], input_lamports=10**9)
        assert replayed == original['analysis']
        assert replayed['conditional_projection'] is not None


@pytest.mark.parametrize('result', [None, {}, {'context': {'slot': True}, 'value': []},
                                   {'context': {'slot': 1234}, 'value': []},
                                   {'context': {'slot': 1000}, 'value': [None]*7}])
def test_missing_malformed_or_older_bank_leaves_gap_and_never_runs_arithmetic(tmp_path, monkeypatch, result):
    _, addresses = fixture()
    row = cp.select_rows(payload(indexed()))[1][0]
    session = cp.CampaignSession(Transport(posts=[rpc(result)]), 20)
    monkeypatch.setattr(cp, 'analyze_snapshot', lambda *_a, **_kw: pytest.fail('invalid bank was analyzed'))
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        snapshot = asyncio.run(cp._snapshot(store, session, append_for(store), row, addresses, 1200, 'initial'))
        assert snapshot is None and store.quality_report()['open_gap_count'] == 1
        assert store.events(kind='pool_snapshot')[0]['outcome'] == 'missing'
        assert session.requests_used == 1


def test_unsafe_snapshot_preserves_digest_and_failure_receipt(tmp_path, monkeypatch):
    accounts, addresses = fixture()
    result = bank(accounts, addresses, 1234)
    result['api_key'] = 'unsafe-synthetic-body'
    session = cp.CampaignSession(Transport(posts=[rpc(result)]), 20)
    row = cp.select_rows(payload(indexed()))[1][0]
    monkeypatch.setattr(cp, 'analyze_snapshot', lambda *_a, **_kw: pytest.fail('unsafe bank was analyzed'))
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        assert asyncio.run(cp._snapshot(store, session, append_for(store), row, addresses, 1200, 'initial')) is None
        event = store.events(kind='pool_snapshot')[0]
        assert event['outcome'] == 'error'
        assert event['payload']['response_representation_sha256'] == cp.digest(result)
        assert 'unsafe-synthetic-body' not in json.dumps(store.events())


def creation_fixture():
    row = cp.select_rows(payload(indexed()))[1][0]
    target = '3'*88
    page = [dict(signature='1'*88, slot=100, err={'InstructionError': [0, 'failed']}),
            dict(signature='2'*88, slot=99, err=None),
            dict(signature=target, slot=98, err=None), {'invalid': 'kept-as-digest'}]
    tx = transaction(instruction(row['mint'], creator=row['creator_claim'], pool=row['pool']))
    tx['slot'] = 98
    tx['transaction']['signatures'] = [target]
    tx['meta']['fee'] = 5000
    return row, page, tx


def test_creation_requires_matching_discriminator_pool_mint_and_requested_signature(tmp_path):
    row, page, tx = creation_fixture()
    transport = Transport(posts=[rpc(page), rpc(tx)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        assert asyncio.run(cp._creation(cp.CampaignSession(transport, 20), append_for(store), row)) is True
        assert transport.calls[1][2]['json']['params'][0] == page[2]['signature']
        assert [e['outcome'] for e in store.events(kind='transaction')] == [
            'chain_failed', 'not_fetched', 'observed', 'invalid_signature_row']
        assert len(store.events(kind='launch')) == 1
        matched = [e for e in store.events(kind='checkpoint') if e['outcome'] == 'creation_matched'][0]
        assert matched['payload']['meta_fee_lamports'] == 5000
        assert matched['payload']['fee_scope'] == 'observed_creation_transaction_not_our_trade'


@pytest.mark.parametrize('signature_limit', [20, 1000])
@pytest.mark.parametrize('maximum_version', [0, 1])
def test_creation_propagates_registered_page_limit_and_supported_transaction_version(tmp_path, signature_limit, maximum_version):
    row, page, tx = creation_fixture()
    tx['version'] = maximum_version
    transport = Transport(posts=[rpc(page), rpc(tx)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        assert asyncio.run(cp._creation(cp.CampaignSession(transport, 20), append_for(store), row,
                                       signature_limit=signature_limit,
                                       max_supported_transaction_version=maximum_version)) is True
        assert transport.calls[0][2]['json']['params'][1]['limit'] == signature_limit
        assert transport.calls[1][2]['json']['params'][1]['maxSupportedTransactionVersion'] == maximum_version
        measured = next(e for e in store.events(kind='checkpoint') if e['outcome'] == 'pool_signature_page')
        assert measured['payload']['retention_limit'] == signature_limit
        assert len(store.events(kind='launch')) == 1


@pytest.mark.parametrize('kwargs', [
    {'signature_limit': value} for value in (None, True, False, 0, 19, 21, 999, 1001, 20.0, '1000')
] + [
    {'max_supported_transaction_version': value} for value in (None, True, False, -1, 2, 1.0, '1')
])
def test_creation_rejects_invalid_limit_or_transaction_version_before_any_request(tmp_path, kwargs):
    row, _, _ = creation_fixture()
    transport = Transport()
    session = cp.CampaignSession(transport, 20)
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        with pytest.raises(ValueError):
            asyncio.run(cp._creation(session, append_for(store), row, **kwargs))
        assert store.events() == []
        assert session.requests_used == 0 and transport.calls == []


@pytest.mark.parametrize('alteration', ['signature', 'pool', 'mint', 'failed', 'missing', 'swap'])
def test_creation_mismatch_failure_or_missing_does_not_verify_creation(tmp_path, alteration):
    row, page, tx = creation_fixture()
    if alteration == 'signature':
        tx['transaction']['signatures'] = ['9'*88]
    elif alteration == 'pool':
        tx['transaction']['message']['instructions'][0]['accounts'][5] = 'wrong-pool'
    elif alteration == 'mint':
        tx['transaction']['message']['instructions'][0]['accounts'][6] = 'wrong-mint'
    elif alteration == 'failed':
        tx['meta']['err'] = {'InstructionError': [0, 'failed']}
    elif alteration == 'missing':
        tx = None
    elif alteration == 'swap':
        tx['transaction']['message']['instructions'] = [instruction(row['mint'], name='sell_exact_in')]
    session = cp.CampaignSession(Transport(posts=[rpc(page), rpc(tx)]), 20)
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        assert asyncio.run(cp._creation(session, append_for(store), row)) is False
        assert store.quality_report()['open_gap_count'] == 1
        assert not any(e['outcome'] == 'creation_matched' for e in store.events())
        if alteration == 'signature':
            assert store.events(kind='launch') == []


def test_oversized_signature_page_is_measured_capped_and_never_fetches_outside_protocol(tmp_path):
    row, _, _ = creation_fixture()
    page = [dict(signature='2'*87+str(index % 8 + 1), slot=100-index,
                 err={'InstructionError': [0, 'failed']}) for index in range(20)]
    page.append(dict(signature='9'*88, slot=80, err=None))
    transport = Transport(posts=[rpc(page)])
    session = cp.CampaignSession(transport, 20)
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        assert asyncio.run(cp._creation(session, append_for(store), row)) is False
        measured = next(e for e in store.events(kind='checkpoint') if e['outcome'] == 'pool_signature_page')
        assert measured['payload']['received_row_count'] == 21
        assert measured['payload']['retention_limit'] == 20
        assert measured['payload']['page_representation_sha256'] == cp.digest(page)
        assert len(store.events(kind='transaction')) == 20
        assert store.quality_report()['open_gap_count'] == 2
        assert session.requests_used == len(transport.calls) == 1


def test_version_two_page_is_retained_up_to_1000_with_explicit_gap_beyond_cap():
    row, _, _ = creation_fixture()
    page = [dict(signature='2'*88, slot=2000-index, err={'InstructionError': [0, 'failed']})
            for index in range(1000)]
    page.append(dict(signature='9'*88, slot=999, err=None))
    session = cp.CampaignSession(Transport(posts=[rpc(page)]), 20)
    receipts = []
    def append(kind, **event):
        receipts.append(dict(kind=kind, **event))
        return len(receipts)
    assert asyncio.run(cp._creation(session, append, row, signature_limit=1000,
                                   max_supported_transaction_version=1)) is False
    measured = next(e for e in receipts if e['kind'] == 'checkpoint')
    assert measured['payload']['received_row_count'] == 1001
    assert measured['payload']['retention_limit'] == 1000
    assert measured['payload']['page_representation_sha256'] == cp.digest(page)
    assert sum(e['kind'] == 'transaction' for e in receipts) == 1000
    assert sum(e['kind'] == 'gap' for e in receipts) == 2
    assert session.requests_used == 1


def test_campaign_integrates_creation_snapshots_rejects_and_quotes_without_a_fill(tmp_path, monkeypatch):
    accounts, addresses = fixture()
    row, page, tx = creation_fixture()
    index = payload(indexed(), None, indexed())
    initial = bank(accounts, addresses, 1234)
    later = bank(accounts, addresses, 1274)
    buy = quote_payload(output_mint=row['mint'], output='25000000')
    sell = quote_payload(input_mint=row['mint'], output_mint=SOL_MINT,
                         amount='25000000', output='980000000', minimum='970200000')
    transport = Transport(posts=[rpc({'context': {'slot': 1230}, 'value': [accounts[row['pool']]]}),
        rpc(initial), rpc(100), rpc(page), rpc(tx), rpc(later), rpc(115)],
        gets=[Response(index), Response(buy), Response(sell)])
    monkeypatch.setattr(cp.asyncio, 'sleep', no_sleep)
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan(), provenance='synthetic'))
        assert report['selected_count'] == report['verified_creations'] == 1
        assert report['discovery_received_rows'] == report['discovery_retained_rows'] == 3
        assert report['manifest']['run']['requests_used'] == len(transport.calls) == 10
        assert report['manifest']['run']['open_gaps'] == 1
        assert report['manifest']['candidates'][0]['coherent_snapshot_count'] == 2
        assert report['manifest']['candidates'][0]['all_account_links_verified'] is False
        assert report['readiness']['p3_go'] is False
        assert report['economic_verdict'] == 'INSUFFICIENT DATA'
        assert report['position_acquired'] is report['real_orders_enabled'] is False
        assert report['market_detection_coverage'] is None
        assert all(e['provenance'] == 'synthetic' for e in store.events())
        provider_quotes = [e for e in store.events(kind='quote_attempt')
                           if e['payload'].get('provider') == 'raydium_trade_api']
        assert len(provider_quotes) == 2
        assert provider_quotes[1]['payload']['input_amount_atomic'] == provider_quotes[0]['payload']['output_amount_atomic']
        assert all(e['payload']['executable_confirmed'] is False for e in provider_quotes)


@pytest.mark.parametrize('response', [Response(status=429), Response(None), Response({'success': True}),
                                     Response(error=ValueError('malformed JSON'))])
def test_campaign_discovery_failure_retains_gap_and_does_not_claim_zero_universe(tmp_path, response):
    transport = Transport(gets=[response])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan(), provenance='synthetic'))
        assert report['selected_count'] == report['verified_creations'] == 0
        assert report['discovery_received_rows'] is None
        assert report['manifest']['run']['open_gaps'] == 2
        assert report['market_detection_coverage'] is None
        assert report['readiness']['p3_go'] is False
        assert len(store.events(kind='request')) == 1


def test_oversized_index_retains_explicit_gap_and_all_100_in_scope_rejections(tmp_path):
    transport = Transport(gets=[Response(payload(*([None]*101)))])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan(), provenance='synthetic'))
        assert report['discovery_received_rows'] == 101
        assert report['discovery_retained_rows'] == 100
        assert report['manifest']['run']['open_gaps'] == 2
        assert len(store.events(kind='candidate_decision')) == 100
        assert any(event['reason'] == 'index_exceeds_retention_cap' for event in store.events(kind='gap'))


def test_deadline_retains_every_selected_candidate_and_sample_exclusion(tmp_path, monkeypatch):
    second = indexed(encode(bytes([9])*32), encode(bytes([10])*32))
    transport = Transport(gets=[Response(payload(indexed(), second, *([None]*98)))])
    async def interrupted_rpc(*_args, **_kwargs):
        raise asyncio.TimeoutError
    monkeypatch.setattr(cp, '_rpc', interrupted_rpc)
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan(), provenance='synthetic'))
        assert report['selected_count'] == len(report['manifest']['candidates']) == 2
        assert report['discovery_received_rows'] == report['discovery_retained_rows'] == 100
        assert report['verified_creations'] == 0
        assert report['manifest']['run']['open_gaps'] == 2
        assert all(c['coherent_snapshot_count'] == 0 for c in report['manifest']['candidates'])
        decisions = store.events(kind='candidate_decision')
        assert len(decisions) == 100
        assert sum(e['outcome'] == 'selected' for e in decisions) == 2
        assert report['readiness']['p3_go'] is False


def test_rpc_429_and_failed_buy_preserve_missing_state_and_absent_sell(tmp_path):
    transport = Transport(posts=[Response(status=429), Response(status=429)],
                          gets=[Response(payload(indexed())), Response(status=429)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan(), provenance='synthetic'))
        assert report['selected_count'] == 1 and report['verified_creations'] == 0
        assert report['manifest']['run']['requests_used'] == len(transport.calls) == 4
        assert report['manifest']['run']['open_gaps'] == 3
        assert report['manifest']['candidates'][0]['coherent_snapshot_count'] == 0
        quotes = store.events(kind='quote_attempt')
        assert [quote['outcome'] for quote in quotes] == ['unavailable', 'not_attempted']
        assert quotes[0]['reason'] == 'http_429'
        assert quotes[1]['reason'] == 'buy_quote_unavailable'


@pytest.mark.parametrize('declared,expected_limit,expected_version', [(plan(), 20, 0), (plan_v2(), 1000, 1)])
def test_campaign_passes_the_declared_lookup_protocol_to_creation(tmp_path, monkeypatch, declared, expected_limit, expected_version):
    lookup_arguments = []
    async def lookup(_session, _append, _row, *, signature_limit, max_supported_transaction_version):
        lookup_arguments.append((signature_limit, max_supported_transaction_version))
        return False
    monkeypatch.setattr(cp, '_creation', lookup)
    transport = Transport(posts=[rpc(None)], gets=[Response(payload(indexed())), Response(status=429)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), declared, provenance='synthetic'))
        assert lookup_arguments == [(expected_limit, expected_version)]
        assert report['manifest']['plan']['schema'] == declared['schema']
        assert report['manifest']['plan']['signature_limit'] == expected_limit
        assert report['verified_creations'] == 0


def test_unsafe_address_discovery_receipt_survives_with_digest_and_no_body_leak(tmp_path):
    accounts, addresses = fixture()
    result = {'context': {'slot': 1230}, 'value': [accounts[addresses['pool']]],
              'api_key': 'unsafe-bootstrap-fixture'}
    transport = Transport(posts=[rpc(result), rpc([])],
                          gets=[Response(payload(indexed())), Response(status=429)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan(), provenance='synthetic'))
        evidence = store.events(kind='pool_snapshot')
        assert len(evidence) == 1 and evidence[0]['outcome'] == 'error'
        assert evidence[0]['reason'] == 'unsafe_or_invalid_address_snapshot'
        assert evidence[0]['payload']['response_representation_sha256'] == cp.digest(result)
        assert 'unsafe-bootstrap-fixture' not in json.dumps(store.events())
        assert report['manifest']['candidates'][0]['coherent_snapshot_count'] == 0
        assert report['verified_creations'] == 0


def test_campaign_refuses_nonempty_journal_and_reused_session_before_network(tmp_path):
    transport = Transport()
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        store.append('checkpoint', received_at_ms=1, outcome='preexisting', provenance='synthetic')
        with pytest.raises(ValueError, match='empty'):
            asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20), plan()))
    with CaptureStore(tmp_path/'fresh.sqlite') as store:
        with pytest.raises(ValueError, match='budget'):
            asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 1), plan()))
    assert transport.calls == []


def test_cli_requires_network_optin_before_any_database_is_created(tmp_path, monkeypatch):
    db, output = tmp_path/'p3.sqlite', tmp_path/'report.json'
    monkeypatch.setattr(sys, 'argv', ['campaign', '--plan', str(tmp_path/'plan.json'),
                                     '--db', str(db), '--output', str(output)])
    with pytest.raises(SystemExit):
        cp.main()
    assert not db.exists() and not output.exists()


@pytest.mark.parametrize('collision', ['registered_plan', 'existing_anchor'])
def test_cli_cannot_overwrite_registered_plan_or_existing_tail_anchor(tmp_path, monkeypatch, collision):
    output = tmp_path/'report.json'
    anchor = output.with_suffix('.anchor.json')
    registered = anchor if collision == 'registered_plan' else tmp_path/'plan.json'
    registered.write_text(json.dumps(plan()))
    if collision == 'existing_anchor':
        anchor.write_text('retained-anchor')
    retained = {path: path.read_bytes() for path in (registered, anchor) if path.exists()}
    async def forbidden_capture(*_args):
        pytest.fail('colliding evidence paths reached the collector')
    monkeypatch.setattr(cp, '_capture', forbidden_capture)
    monkeypatch.setattr(sys, 'argv', ['campaign', '--network', '--plan', str(registered),
                                     '--db', str(tmp_path/'p3.sqlite'), '--output', str(output)])
    with pytest.raises(SystemExit):
        cp.main()
    assert all(path.read_bytes() == value for path, value in retained.items())
    assert not output.exists() and not (tmp_path/'p3.sqlite').exists()


def plan_v3():
    return dict(plan_v2(), schema='p3-launchlab-campaign-v3',
                plan_id='launchlab-retention-sol-003',
                source_main='7ddddb9f73339242fbcb5b9bf10fa329c82fa700',
                source_revision='a'*40, evidence_profile='published_metadata_v1',
                stop_on_source_error=True)


def test_retention_successor_keeps_old_plan_hashes_and_rejects_guard_changes():
    old_hashes = [cp.validate_plan(p) for p in (plan(), plan_v2())]
    assert cp.validate_plan(plan_v3()) not in old_hashes
    for field, value in [('evidence_profile', 'legacy'), ('stop_on_source_error', False),
                         ('source_revision', 'not-a-revision'), ('max_requests', 21)]:
        with pytest.raises(ValueError):
            cp.validate_plan(dict(plan_v3(), **{field: value}))
    assert [cp.validate_plan(p) for p in (plan(), plan_v2())] == old_hashes


def test_new_profile_is_retained_and_replayable_in_snapshot(tmp_path):
    from test_p3_qualification import qualified_fixture
    accounts, addresses = qualified_fixture()
    row = cp.select_rows(payload(indexed(mint=addresses['mint_a'], pool=addresses['pool'])))[1][0]
    transport = Transport(posts=[rpc(bank(accounts, addresses, 1234)), rpc(100)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        snapshot = asyncio.run(cp._snapshot(store, cp.CampaignSession(transport, 20),
            append_for(store), row, addresses, 1200, 'initial',
            evidence_profile='published_metadata_v1'))
        assert snapshot['analysis']['facts']['supply_consistency']['matches'] is True
        retained = store.events(kind='pool_snapshot')[0]['payload']
        assert retained['evidence_profile'] == 'published_metadata_v1'
        replay = cp.analyze_snapshot(dict(zip(retained['requested_addresses'],
            retained['raw_rpc_result']['value'])), context_slot=1234,
            expected_mint=row['mint'], pool_address=row['pool'],
            evidence_profile=retained['evidence_profile'])
        assert replay == snapshot['analysis']


@pytest.mark.parametrize('status', [403, 429, 503])
def test_new_run_stops_after_failed_rpc_receipt_without_further_consumption(tmp_path, status):
    transport = Transport(posts=[Response(status=status)], gets=[Response(payload(indexed()))])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20),
            plan_v3(), provenance='synthetic'))
        assert len(transport.calls) == report['manifest']['run']['requests_used'] == 2
        requests = store.events(kind='request')
        assert requests[-1]['payload']['http_status'] == status
        assert any(e['reason'] == 'campaign_stopped_on_source_error' for e in store.events(kind='gap'))
        assert store.events(kind='quote_attempt') == []
        assert report['economic_verdict'] == 'INSUFFICIENT DATA'


@pytest.mark.parametrize('failure,reason', [
    (asyncio.TimeoutError(), 'timeout'),
    (OSError('synthetic transport failure'), 'transport_error'),
    (ValueError('synthetic invalid response'), 'malformed_response'),
])
def test_retention_run_stops_after_quote_failure_receipt_before_followup(tmp_path, monkeypatch, failure, reason):
    accounts, addresses = fixture()
    row, page, tx = creation_fixture()
    initial = bank(accounts, addresses, 1234)
    later = bank(accounts, addresses, 1274)
    transport = Transport(posts=[
        rpc({'context': {'slot': 1230}, 'value': [accounts[row['pool']]]}),
        rpc(initial), rpc(100), rpc(page), rpc(tx), rpc(later), rpc(115)],
        gets=[Response(payload(indexed())), Response(error=failure)])
    monkeypatch.setattr(cp.asyncio, 'sleep', no_sleep)
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        report = asyncio.run(cp.collect_campaign(store, cp.CampaignSession(transport, 20),
            plan_v3(), provenance='synthetic'))
        assert len(transport.calls) == report['manifest']['run']['requests_used'] == 7
        quotes = [e for e in store.events(kind='quote_attempt')
                  if e['payload'].get('provider') == 'raydium_trade_api']
        assert len(quotes) == 1
        assert quotes[0]['reason'] == reason
        assert quotes[0]['payload']['quote_side'] == 'buy'
        assert quotes[0]['payload']['requested_at_ms'] <= quotes[0]['received_at_ms']
        assert any(e['reason'] == 'campaign_stopped_on_source_error' for e in store.events(kind='gap'))
        assert report['manifest']['candidates'][0]['coherent_snapshot_count'] == 1
        assert report['economic_verdict'] == 'INSUFFICIENT DATA'
