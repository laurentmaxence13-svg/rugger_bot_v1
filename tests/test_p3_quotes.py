"""Synthetic HTTP observations only: no wallet, transaction or network access."""
import asyncio
from copy import deepcopy
import json

import aiohttp
import pytest

from bot.p3.quotes import RAYDIUM_QUOTE_URL, SOL_MINT, RaydiumQuoteClient


USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'


def quote_payload(input_mint=SOL_MINT, output_mint=USDC, amount='1000000000',
                  output='25000000', minimum='24750000'):
    return {
        'id': 'synthetic-observation', 'success': True, 'version': 'V1',
        'data': {
            'swapType': 'BaseIn', 'inputMint': input_mint, 'inputAmount': amount,
            'actualInputAmount': amount, 'outputMint': output_mint,
            'outputAmount': output, 'otherAmountThreshold': minimum,
            'slippageBps': 100, 'priceImpactPct': '0.0125',
            'routePlan': [{
                'poolId': 'synthetic-pool', 'inputMint': input_mint,
                'outputMint': output_mint, 'feeMint': input_mint,
                'feeAmount': '3000000', 'feeRate': 2500,
            }],
        },
    }


class Response:
    def __init__(self, payload=None, *, status=200, headers=None, error=None):
        self.payload, self.status = payload, status
        self.headers = headers or {}
        self.error = error
        self.closed = False
        self.json_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def json(self, **kwargs):
        self.json_calls += 1
        if self.error is not None:
            raise self.error
        return deepcopy(self.payload)


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        return value


def client(session):
    wall = iter(range(1000, 100_000, 20))
    monotonic = iter(range(1_000_000_000, 100_000_000_000, 6_000_000))
    return RaydiumQuoteClient(session, clock_ms=lambda: next(wall),
                             monotonic_ns=lambda: next(monotonic))


def fetch(session, **kwargs):
    return asyncio.run(client(session).quote(SOL_MINT, USDC, '1000000000', **kwargs))


def test_exact_size_route_and_latency_are_captured_without_claiming_execution():
    response = Response(quote_payload())
    session = Session(response)
    result = fetch(session)
    assert result['outcome'] == 'quoted' and result['reason'] is None
    assert result['input_amount_atomic'] == '1000000000'
    assert result['actual_input_amount_atomic'] == '1000000000'
    assert result['output_amount_atomic'] == '25000000'
    assert result['min_output_amount_atomic'] == '24750000'
    assert result['requested_at_ms'] == 1000 and result['received_at_ms'] == 1020
    assert result['latency_ms'] == 6
    assert result['source_time_ms'] is result['source_slot'] is None
    assert result['execution_guaranteed'] is result['executable_confirmed'] is False
    assert result['price_impact_pct'] == '0.0125'
    assert result['liquidity_snapshot']['executable_depth_for_requested_size'] is None
    assert result['liquidity_snapshot']['basis'] == 'not_provided_by_route_quote'
    assert 'provider_source_time_unknown' in result['quality_flags']
    fees = result['fee_details']
    assert fees['route_fees'][0]['fee_amount_atomic'] == '3000000'
    assert fees['route_fees'][0]['fee_rate_raw'] == '2500'
    assert fees['route_fees'][0]['fee_rate_unit'] == 'provider_unit_not_converted_to_bps'
    assert fees['network_fee_lamports'] is fees['account_creation_lamports'] is None
    assert fees['total_cost_known'] is False
    assert response.closed
    url, options = session.calls[0]
    assert url == RAYDIUM_QUOTE_URL and len(session.calls) == 1
    assert options['params'] == dict(inputMint=SOL_MINT, outputMint=USDC,
                                     amount='1000000000', slippageBps='100', txVersion='V0')
    assert options['allow_redirects'] is False


@pytest.mark.parametrize('amount', [0, -1, True, 1.5, '1.5', '1e9', '+1',
                                    None, 2**64, '１'])
def test_invalid_atomic_amount_never_performs_an_http_request(amount):
    session = Session()
    with pytest.raises(ValueError):
        asyncio.run(client(session).quote(SOL_MINT, USDC, amount))
    assert session.calls == []


@pytest.mark.parametrize('mint', ['not-an-address', '0'*32, '1'*31, 'z'*44])
def test_invalid_mint_never_requests_a_quote(mint):
    session = Session()
    with pytest.raises(ValueError):
        asyncio.run(client(session).quote(SOL_MINT, mint, 1))
    assert session.calls == []


@pytest.mark.parametrize('slippage', [True, -1, 10001, 0.5, '100'])
def test_invalid_slippage_does_not_request_a_quote(slippage):
    session = Session()
    with pytest.raises(ValueError):
        asyncio.run(client(session).quote(SOL_MINT, USDC, 1, slippage))
    assert session.calls == []


@pytest.mark.parametrize('field,value', [
    ('inputMint', TOKEN), ('outputMint', TOKEN), ('inputAmount', '999999999'),
    ('slippageBps', 99), ('slippageBps', True),
])
def test_response_for_another_request_is_never_accepted(field, value):
    payload = quote_payload()
    payload['data'][field] = value
    result = fetch(Session(Response(payload)))
    assert result['outcome'] == 'error' and result['reason'] == 'quote_request_mismatch'
    assert result['output_amount_atomic'] is None


@pytest.mark.parametrize('alter', ['exact_output', 'overflow_output', 'negative_minimum',
                                   'minimum_above_output', 'disconnected_route',
                                   'wrong_route_destination', 'actual_input_above_budget',
                                   'invalid_fee_amount'])
def test_malformed_route_and_amounts_fail_closed(alter):
    payload = quote_payload()
    data = payload['data']
    if alter == 'exact_output':
        data['swapType'] = 'BaseOut'
    elif alter == 'overflow_output':
        data['outputAmount'] = str(2**64)
    elif alter == 'negative_minimum':
        data['otherAmountThreshold'] = '-1'
    elif alter == 'minimum_above_output':
        data['otherAmountThreshold'] = '25000001'
    elif alter == 'disconnected_route':
        data['routePlan'][0]['inputMint'] = TOKEN
    elif alter == 'wrong_route_destination':
        data['routePlan'][0]['outputMint'] = TOKEN
    elif alter == 'actual_input_above_budget':
        data['actualInputAmount'] = '1000000001'
    else:
        data['routePlan'][0]['feeAmount'] = '-1'
    result = fetch(Session(Response(payload)))
    assert result['outcome'] == 'error'
    assert result['execution_guaranteed'] is False


def test_unknown_fees_and_price_impact_remain_unknown():
    payload = quote_payload()
    del payload['data']['routePlan'][0]['feeAmount']
    del payload['data']['routePlan'][0]['feeMint']
    del payload['data']['priceImpactPct']
    result = fetch(Session(Response(payload)))
    assert result['outcome'] == 'quoted'
    assert result['fee_details']['route_fees'][0]['fee_amount_atomic'] is None
    assert result['fee_details']['route_fees'][0]['fee_mint'] is None
    assert result['price_impact_pct'] is None
    assert 'route_fee_details_incomplete' in result['quality_flags']
    assert result['fee_details']['total_cost_known'] is False


def test_two_hop_route_preserves_fee_units_and_order():
    payload = quote_payload()
    payload['data']['routePlan'] = [
        dict(inputMint=SOL_MINT, outputMint=TOKEN, feeMint=SOL_MINT, feeAmount='10'),
        dict(inputMint=TOKEN, outputMint=USDC, feeMint=TOKEN, feeAmount='30'),
    ]
    result = fetch(Session(Response(payload)))
    assert result['outcome'] == 'quoted' and len(result['route']) == 2
    assert [fee['fee_amount_atomic'] for fee in result['fee_details']['route_fees']] == ['10', '30']
    assert result['fee_details']['route_fees'][0]['fee_rate_raw'] is None


@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
def test_http_failure_is_one_visible_attempt_without_retry(status):
    response = Response(status=status, headers={'Retry-After': '2.5'})
    session = Session(response)
    result = fetch(session)
    assert result['outcome'] == 'unavailable' and result['reason'] == 'http_' + str(status)
    assert result['retry_after_seconds'] == 2.5
    assert result['raw_payload'] is None and response.json_calls == 0
    assert len(session.calls) == 1 and response.closed


@pytest.mark.parametrize('failure,reason', [
    (asyncio.TimeoutError(), 'timeout'),
    (aiohttp.ClientConnectionError('must-not-be-logged?api-key=synthetic'), 'transport_error'),
    (OSError('synthetic transport failure'), 'transport_error'),
])
def test_timeout_or_transport_error_has_no_secret_exception_message(failure, reason):
    session = Session(failure)
    result = fetch(session)
    assert result['outcome'] == 'unavailable' and result['reason'] == reason
    assert 'api-key' not in json.dumps(result)
    assert len(session.calls) == 1 and result['received_at_ms'] == 1020


@pytest.mark.parametrize('retry', ['NaN', 'Infinity', '-1', '1e9999', 'Wed, 21 Oct 2015 07:28:00 GMT'])
def test_unusable_retry_after_is_unknown_and_json_safe(retry):
    result = fetch(Session(Response(status=429, headers={'Retry-After': retry})))
    assert result['retry_after_seconds'] is None
    json.dumps(result, allow_nan=False)


def test_invalid_json_response_is_recorded_as_malformed():
    response = Response(error=ValueError('synthetic JSON decoder error'))
    result = fetch(Session(response))
    assert result['outcome'] == 'error' and result['reason'] == 'malformed_response'
    assert response.closed


@pytest.mark.parametrize('payload', [None, [], {}, {'success': 'true'}, {'success': True, 'data': None}])
def test_unknown_provider_shape_never_becomes_a_quote(payload):
    result = fetch(Session(Response(payload)))
    assert result['outcome'] == 'error' and result['output_amount_atomic'] is None


@pytest.mark.parametrize('payload', [
    {'success': False, 'msg': 'synthetic no route'},
    {'success': True, 'data': {**quote_payload()['data'], 'routePlan': []}},
])
def test_explicit_unavailability_has_no_fabricated_output(payload):
    result = fetch(Session(Response(payload)))
    assert result['outcome'] == 'unavailable' and result['output_amount_atomic'] is None


def test_response_evidence_redacts_credentials_and_authenticated_urls():
    payload = quote_payload()
    payload['api_key'] = 'synthetic-secret-one'
    payload['data']['headers'] = {'Authorization': 'synthetic-secret-two'}
    payload['data']['debugUrl'] = 'https://example.invalid/path?api-key=synthetic-secret-three'
    result = fetch(Session(Response(payload)))
    evidence = json.dumps(result)
    assert all(secret not in evidence for secret in (
        'synthetic-secret-one', 'synthetic-secret-two', 'synthetic-secret-three'))
    assert result['outcome'] == 'quoted'


@pytest.mark.parametrize('source,expected,flag', [(1010, 1010, None),
                                               (1030, None, 'provider_source_time_invalid')])
def test_explicit_source_time_is_not_inferred_from_reception(source, expected, flag):
    payload = quote_payload()
    payload['data']['sourceTimeMs'] = source
    payload['data']['contextSlot'] = 123
    result = fetch(Session(Response(payload)))
    assert result['source_time_ms'] == expected
    assert result['source_slot'] == 123
    if flag:
        assert flag in result['quality_flags']


def test_http_date_does_not_become_a_source_quote_timestamp():
    result = fetch(Session(Response(quote_payload(), headers={'Date': 'synthetic-provider-date'})))
    assert result['source_time_ms'] is None


def test_caller_cancellation_is_propagated_instead_of_returning_an_error_quote():
    session = Session(asyncio.CancelledError('synthetic caller stop'))
    with pytest.raises(asyncio.CancelledError):
        fetch(session)
    assert len(session.calls) == 1


def test_round_trip_sells_the_exact_expected_buy_output_and_stays_indicative():
    buy = quote_payload(output='25000000', minimum='24750000')
    sell = quote_payload(USDC, SOL_MINT, '25000000', '970000000', '960300000')
    session = Session(Response(buy), Response(sell))
    result = asyncio.run(client(session).round_trip(USDC, 1_000_000_000))
    assert result['outcome'] == 'quoted'
    assert len(session.calls) == 2
    assert session.calls[1][1]['params']['amount'] == '25000000'
    assert session.calls[1][1]['params']['inputMint'] == USDC
    assert session.calls[1][1]['params']['outputMint'] == SOL_MINT
    assert result['quoted_round_trip_delta_lamports'] == -30_000_000
    assert result['position_acquired'] is result['future_exit_guaranteed'] is False
    assert result['additional_execution_costs_known'] is False
    assert result['buy']['min_output_amount_atomic'] != result['sell']['input_amount_atomic']


def test_missing_buy_stops_before_requesting_a_sell():
    session = Session(Response(status=429))
    result = asyncio.run(client(session).round_trip(USDC, 1_000_000_000))
    assert result['sell'] is None and result['reason'] == 'buy_quote_unavailable'
    assert len(session.calls) == 1


def test_missing_sell_keeps_its_failure_without_inventing_a_zero_loss():
    session = Session(Response(quote_payload()), Response(status=429))
    result = asyncio.run(client(session).round_trip(USDC, 1_000_000_000))
    assert result['reason'] == 'sell_quote_unavailable'
    assert result['outcome'] == 'unavailable'
    assert result['quoted_round_trip_delta_lamports'] is None
    assert result['buy']['outcome'] == 'quoted'
    assert result['sell']['reason'] == 'http_429'


@pytest.mark.parametrize('alter', ['actual_input_above_budget', 'wall_clock_invalid'])
def test_rejected_quote_never_exposes_partially_parsed_amounts_or_fees(alter):
    payload = quote_payload()
    session = Session(Response(payload))
    quote_client = client(session)
    if alter == 'actual_input_above_budget':
        payload['data']['actualInputAmount'] = '1000000001'
    else:
        times = iter([1000, 999])
        quote_client.clock_ms = lambda: next(times)
    result = asyncio.run(quote_client.quote(SOL_MINT, USDC, '1000000000'))
    assert result['outcome'] == 'error'
    assert result['output_amount_atomic'] is None
    assert result['min_output_amount_atomic'] is None
    assert result['actual_input_amount_atomic'] is None
    assert result['route'] == []
    assert result['fee_details']['route_fees'] == []
    assert result['raw_payload'] == payload  # evidence retained for diagnosis
