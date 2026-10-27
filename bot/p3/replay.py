"""Semantic quote replay from retained evidence, without network or ingestion.

The original availability timestamps remain evidence; replay does not make a
historical quote executable or certify provider authenticity or execution.
"""
import asyncio
from copy import deepcopy
import hashlib
import json

from bot.p3.quotes import RaydiumQuoteClient


_QUOTE_FIELDS = ('outcome', 'reason', 'input_mint', 'output_mint', 'input_amount_atomic',
                 'actual_input_amount_atomic', 'output_amount_atomic',
                 'min_output_amount_atomic', 'slippage_bps', 'route', 'fee_details',
                 'price_impact_pct', 'source_slot', 'source_time_ms', 'quality_flags',
                 'execution_guaranteed', 'executable_confirmed')


def replay_quote_observation(event):
    """Check a retained sanitized body against its original normalization.

    HTTP errors are checked as unavailable diagnostics, never passed to the quote
    parser. Missing bodies remain missing, including unsafe-policy fallbacks.
    HTTP-200 bodies use the normalizer with a strictly in-memory session and
    original wall times. Local latency is not remeasured or asserted anew.
    """
    payload = event.get('payload')
    if (event.get('kind') != 'quote_attempt' or not isinstance(payload, dict)
            or payload.get('provider') != 'raydium_trade_api'):
        raise ValueError('Not a retained provider quote observation')
    raw = payload.get('retained_sanitized_response')
    if raw is None:
        return {'status': 'MISSING_BODY', 'execution_verified': False}
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if digest != payload.get('sanitized_response_sha256'):
        raise ValueError('Retained sanitized quote digest mismatch')
    status = payload.get('http_status')
    if type(status) is not int:
        raise ValueError('Retained quote has no HTTP status')
    if not 200 <= status < 300:
        amounts = ('actual_input_amount_atomic', 'output_amount_atomic', 'min_output_amount_atomic')
        valid_rejection = (event.get('outcome') == 'unavailable'
                           and event.get('reason') == 'http_' + str(status))
        invalid_clock = (event.get('outcome') == 'error' and event.get('reason') == 'wall_clock_invalid')
        if (not (valid_rejection or invalid_clock)
                or any(payload.get(key) is not None for key in amounts)
                or payload.get('route')
                or payload.get('fee_details', {}).get('route_fees')):
            raise ValueError('HTTP error exposed a usable quote or inconsistent refusal')
        return {'status': 'HTTP_ERROR_RETAINED', 'http_status': status,
                'outcome': event['outcome'], 'reason': event['reason'], 'execution_verified': False}

    class RetainedResponse:
        status = payload['http_status']
        headers = {}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def json(self, **kwargs):
            return deepcopy(raw)

    class OfflineSession:
        def get(self, *args, **kwargs):
            return RetainedResponse()

    times = iter((payload['requested_at_ms'], payload['received_at_ms']))
    # Only presence/absence of monotonic timing affects the normalization flags.
    # The actual measured latency and availability stay original evidence.
    ticks = iter((0, 0 if payload.get('latency_ms') is not None else -1))
    client = RaydiumQuoteClient(OfflineSession(), clock_ms=lambda: next(times),
                               monotonic_ns=lambda: next(ticks))
    replay = asyncio.run(client.quote(payload['input_mint'], payload['output_mint'],
        payload['input_amount_atomic'], payload['slippage_bps']))
    if any(replay[key] != payload.get(key) for key in _QUOTE_FIELDS):
        raise ValueError('Quote normalization replay differs from retained result')
    if replay['outcome'] != event.get('outcome') or replay['reason'] != event.get('reason'):
        raise ValueError('Quote event outcome disagrees with normalization')
    return {'status': 'REPLAYED', 'http_status': status,
            'outcome': replay['outcome'], 'reason': replay['reason'], 'execution_verified': False}
