"""Semantic quote replay from retained evidence, without network or ingestion.

The original availability timestamps remain evidence; replay does not make a
historical quote executable or certify provider authenticity or execution.
"""
from decimal import InvalidOperation
import hashlib
import json

from bot.p3.quotes import RaydiumQuoteClient, _atomic, _mint


_QUOTE_FIELDS = ('outcome', 'reason', 'input_mint', 'output_mint', 'input_amount_atomic',
                 'actual_input_amount_atomic', 'output_amount_atomic',
                 'min_output_amount_atomic', 'slippage_bps', 'route', 'fee_details',
                 'price_impact_pct', 'source_slot', 'source_time_ms', 'quality_flags',
                 'execution_guaranteed', 'executable_confirmed')


def _normalize_retained_body(payload, raw):
    """Replay the pure parser and receipt checks without starting an event loop.

    This deliberately reinitializes normalized fields instead of trusting their
    retained values. Transport, clocks and ingestion are never performed again.
    """
    input_mint, output_mint = _mint(payload['input_mint']), _mint(payload['output_mint'])
    amount = _atomic(payload['input_amount_atomic'])
    slippage = payload['slippage_bps']
    if input_mint == output_mint or type(slippage) is not int or not 0 <= slippage <= 10_000:
        raise ValueError('Invalid retained quote request')
    result = dict(outcome='error', reason=None, input_mint=input_mint,
        output_mint=output_mint, input_amount_atomic=amount,
        actual_input_amount_atomic=None, output_amount_atomic=None,
        min_output_amount_atomic=None, slippage_bps=slippage, route=[],
        fee_details={'route_fees': [], 'network_fee_lamports': None,
                     'priority_fee_lamports': None, 'account_creation_lamports': None,
                     'total_cost_known': False,
                     'additional_costs_must_not_duplicate_route_fees': True},
        price_impact_pct=None, source_slot=None, source_time_ms=None, quality_flags=[],
        execution_guaranteed=False, executable_confirmed=False)
    try:
        RaydiumQuoteClient._parse(raw, result)
    except (ValueError, TypeError, KeyError, InvalidOperation):
        result['outcome'], result['reason'] = 'error', 'malformed_response'
    requested, received = payload['requested_at_ms'], payload['received_at_ms']
    if type(requested) is not int or type(received) is not int or requested < 0 or received < requested:
        result['outcome'], result['reason'] = 'error', 'wall_clock_invalid'
    if payload.get('latency_ms') is None:
        result['quality_flags'].append('monotonic_latency_unknown')
    source = result['source_time_ms']
    if source is not None:
        if type(received) is not int:
            raise ValueError('Retained quote receipt cannot order the source time')
        if source > received:
            result['source_time_ms'] = None
            result['quality_flags'].append('provider_source_time_invalid')
    if result['source_time_ms'] is None:
        result['quality_flags'].append('provider_source_time_unknown')
    if result['source_slot'] is None:
        result['quality_flags'].append('provider_context_slot_unknown')
    result['quality_flags'].append('additional_execution_costs_unknown')
    if result['outcome'] != 'quoted':
        for field in ('actual_input_amount_atomic', 'output_amount_atomic',
                      'min_output_amount_atomic', 'price_impact_pct'):
            result[field] = None
        result['route'] = []
        result['fee_details']['route_fees'] = []
    return result


def replay_quote_observation(event):
    """Check a retained sanitized body against its original normalization.

    HTTP errors are checked as unavailable diagnostics, never passed to the quote
    parser. Missing bodies remain missing, including unsafe-policy fallbacks.
    HTTP-200 bodies use the pure parser and original wall times. This function
    is synchronous and may also be called inside the running PAPER event loop.
    Local latency is not remeasured or asserted anew.
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

    replay = _normalize_retained_body(payload, raw)
    if any(replay[key] != payload.get(key) for key in _QUOTE_FIELDS):
        raise ValueError('Quote normalization replay differs from retained result')
    if replay['outcome'] != event.get('outcome') or replay['reason'] != event.get('reason'):
        raise ValueError('Quote event outcome disagrees with normalization')
    return {'status': 'REPLAYED', 'http_status': status,
            'outcome': replay['outcome'], 'reason': replay['reason'], 'execution_verified': False}
