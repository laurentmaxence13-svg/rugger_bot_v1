"""Read-only, size-specific Raydium quote observations for PAPER data capture.

A route quote is an estimate, never an executed fill or a promise of a future
exit. This module has no transaction construction, signing or submission path.
The caller owns its anonymous aiohttp session. The collectors route configured
proxies explicitly, with trust_env=False, no cookies/netrc and no hidden retries.
"""
import asyncio
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit, urlunsplit

import aiohttp


SOL_MINT = 'So11111111111111111111111111111111111111112'
RAYDIUM_QUOTE_URL = 'https://transaction-v1.raydium.io/compute/swap-base-in'
_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_UINT64_MAX = (1 << 64) - 1
_MAX_ERROR_BODY_BYTES = 65_536
_SENSITIVE_KEYS = {
    'apikey', 'authorization', 'proxyauthorization', 'password', 'secret',
    'privatekey', 'secretkey', 'clientsecret', 'seed', 'mnemonic',
    'accesstoken', 'refreshtoken', 'bearertoken',
}


def _mint(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}', value):
        raise ValueError('Invalid public mint address')
    number = 0
    for character in value:
        number = number * 58 + _BASE58.index(character)
    size = len(value) - len(value.lstrip('1')) + (number.bit_length() + 7) // 8
    if size != 32:
        raise ValueError('Mint address must encode 32 bytes')
    return value


def _atomic(value, *, zero=False):
    if type(value) is int:
        amount = value
    elif isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        amount = int(value)
    else:
        raise ValueError('Invalid atomic token amount')
    if amount < (0 if zero else 1) or amount > _UINT64_MAX:
        raise ValueError('Atomic token amount is outside uint64 bounds')
    return str(amount)


def _decimal_text(value, *, nonnegative=True):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite() or (nonnegative and number < 0):
        return None
    return str(number)


def _sanitized(value):
    """Keep public response evidence without credentials or authenticated URLs."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub(r'[^a-z0-9]', '', str(key).lower())
            result[str(key)] = '[REDACTED]' if normalized in _SENSITIVE_KEYS else _sanitized(item)
        return result
    if isinstance(value, list):
        return [_sanitized(item) for item in value]
    if isinstance(value, str) and '://' in value:
        try:
            url = urlsplit(value)
            if url.scheme in ('http', 'https', 'ws', 'wss'):
                if url.username or url.password or url.query or url.fragment:
                    return '[REDACTED_URL]'
                return urlunsplit((url.scheme, url.netloc, url.path, '', ''))
        except ValueError:
            return '[REDACTED_URL]'
    if isinstance(value, float) and not math.isfinite(value):
        return '[NONFINITE]'
    return value


async def _retain_error_body(response, envelope):
    """Bound error-body retention without treating HTTP errors as quotes.

    The digest covers the complete HTTP body after transport decompression,
    before JSON sanitization. Oversize bodies have no complete-body digest.
    Text that cannot be parsed as JSON is never written to the journal.
    """
    raw = bytearray()
    try:
        while len(raw) <= _MAX_ERROR_BODY_BYTES:
            chunk = await response.content.read(min(8192, _MAX_ERROR_BODY_BYTES+1-len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        envelope['response_body_bytes_observed'] = len(raw)
        if len(raw) > _MAX_ERROR_BODY_BYTES:
            envelope['response_body_status'] = 'over_limit'
            return
        envelope['response_body_sha256'] = hashlib.sha256(raw).hexdigest()
        try:
            envelope['raw_payload'] = _sanitized(json.loads(raw))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            envelope['response_body_status'] = 'non_json'
        else:
            envelope['response_body_status'] = 'json_retained'
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError, ValueError, TypeError):
        # Preserve the already observed status; do not retry or echo an exception.
        envelope['response_body_status'] = 'read_failed'
        envelope['response_body_bytes_observed'] = len(raw)
    except asyncio.CancelledError:
        envelope['response_body_status'] = 'read_cancelled'
        envelope['response_body_bytes_observed'] = len(raw)
        raise


class RaydiumQuoteClient:
    def __init__(self, session, *, clock_ms=None, monotonic_ns=None, timeout_seconds=8):
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0):
            raise ValueError('Invalid quote timeout')
        self.session = session
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_ns = monotonic_ns or time.monotonic_ns
        self.timeout_seconds = timeout_seconds

    async def quote(self, input_mint, output_mint, amount_atomic, slippage_bps=100):
        input_mint, output_mint = _mint(input_mint), _mint(output_mint)
        amount = _atomic(amount_atomic)
        if input_mint == output_mint:
            raise ValueError('A quote requires distinct mints')
        if type(slippage_bps) is not int or not 0 <= slippage_bps <= 10_000:
            raise ValueError('Invalid quote slippage basis points')
        requested = self.clock_ms()
        started = self.monotonic_ns()
        envelope = {
            'provider': 'raydium_trade_api',
            'requested_at_ms': requested,
            'received_at_ms': None,
            'latency_ms': None,
            'source_slot': None,
            'source_time_ms': None,
            'outcome': 'error',
            'reason': None,
            'input_mint': input_mint,
            'output_mint': output_mint,
            'input_amount_atomic': amount,
            'actual_input_amount_atomic': None,
            'output_amount_atomic': None,
            'min_output_amount_atomic': None,
            'slippage_bps': slippage_bps,
            'route': [],
            'fee_details': {
                'route_fees': [],
                'network_fee_lamports': None,
                'priority_fee_lamports': None,
                'account_creation_lamports': None,
                'total_cost_known': False,
                'additional_costs_must_not_duplicate_route_fees': True,
            },
            'price_impact_pct': None,
            'liquidity_snapshot': {
                'reserves': None,
                'executable_depth_for_requested_size': None,
                'basis': 'not_provided_by_route_quote',
            },
            'raw_payload': None,
            'response_body_status': 'not_read',
            'response_body_sha256': None,
            'response_body_bytes_observed': None,
            'http_status': None,
            'retry_after_seconds': None,
            'quality_flags': [],
            'quote_kind': 'size_specific_route_estimate',
            'execution_guaranteed': False,
            'executable_confirmed': False,
        }
        try:
            async with self.session.get(
                    RAYDIUM_QUOTE_URL,
                    params={'inputMint': input_mint, 'outputMint': output_mint,
                            'amount': amount, 'slippageBps': str(slippage_bps),
                            'txVersion': 'V0'},
                    timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                    allow_redirects=False) as response:
                envelope['http_status'] = response.status
                if not 200 <= response.status < 300:
                    envelope['outcome'] = 'unavailable'
                    envelope['reason'] = 'http_' + str(response.status)
                    retry = _decimal_text(response.headers.get('Retry-After'))
                    seconds = float(retry) if retry is not None else None
                    envelope['retry_after_seconds'] = seconds if seconds is not None and math.isfinite(seconds) else None
                    await _retain_error_body(response, envelope)
                else:
                    payload = await response.json(content_type=None)
                    envelope['raw_payload'] = _sanitized(payload)
                    envelope['response_body_status'] = 'json_retained'
                    self._parse(payload, envelope)
        except asyncio.CancelledError as error:
            # The caller persists this whitelist before re-raising. Never attach
            # response bodies, exception text, headers or partially parsed routes.
            status = envelope['http_status']
            error.capture_quote_metadata = {
                'http_status': status if type(status) is int and 100 <= status <= 599 else None,
                'retry_after_seconds': envelope['retry_after_seconds'],
                'response_body_status': envelope['response_body_status'],
                'response_body_sha256': envelope['response_body_sha256'],
                'response_body_bytes_observed': envelope['response_body_bytes_observed'],
            }
            if type(requested) is int and requested >= 0:
                error.capture_quote_metadata['requested_at_ms'] = requested
            raise
        except asyncio.TimeoutError:
            envelope['outcome'], envelope['reason'] = 'unavailable', 'timeout'
        except (aiohttp.ClientError, OSError):
            envelope['outcome'], envelope['reason'] = 'unavailable', 'transport_error'
        except (ValueError, TypeError, KeyError, InvalidOperation):
            envelope['outcome'], envelope['reason'] = 'error', 'malformed_response'
        received, finished = self.clock_ms(), self.monotonic_ns()
        envelope['received_at_ms'] = received
        if type(requested) is not int or type(received) is not int or requested < 0 or received < requested:
            envelope['outcome'], envelope['reason'] = 'error', 'wall_clock_invalid'
        if type(started) is int and type(finished) is int and finished >= started:
            envelope['latency_ms'] = (finished - started) / 1_000_000
        else:
            envelope['quality_flags'].append('monotonic_latency_unknown')
        source_time = envelope['source_time_ms']
        if source_time is not None and source_time > received:
            envelope['source_time_ms'] = None
            envelope['quality_flags'].append('provider_source_time_invalid')
        if envelope['source_time_ms'] is None:
            envelope['quality_flags'].append('provider_source_time_unknown')
        if envelope['source_slot'] is None:
            envelope['quality_flags'].append('provider_context_slot_unknown')
        envelope['quality_flags'].append('additional_execution_costs_unknown')
        if envelope['outcome'] != 'quoted':
            # Parsing and final clock checks may reject a response after some
            # fields have been decoded. Keep its evidence, but expose no usable
            # quote amounts or fees from a response that did not validate.
            for field in ('actual_input_amount_atomic', 'output_amount_atomic',
                          'min_output_amount_atomic', 'price_impact_pct'):
                envelope[field] = None
            envelope['route'] = []
            envelope['fee_details']['route_fees'] = []
        return envelope

    @staticmethod
    def _parse(payload, result):
        if not isinstance(payload, dict) or type(payload.get('success')) is not bool:
            raise ValueError('Missing provider success status')
        if payload['success'] is False:
            result['outcome'], result['reason'] = 'unavailable', 'provider_rejected'
            return
        data = payload.get('data')
        if not isinstance(data, dict) or data.get('swapType') != 'BaseIn':
            raise ValueError('Provider response is not exact input')
        if (data.get('inputMint') != result['input_mint']
                or data.get('outputMint') != result['output_mint']
                or _atomic(data.get('inputAmount')) != result['input_amount_atomic']
                or type(data.get('slippageBps')) is not int
                or data['slippageBps'] != result['slippage_bps']):
            result['reason'] = 'quote_request_mismatch'
            return
        output = _atomic(data.get('outputAmount'))
        minimum = _atomic(data.get('otherAmountThreshold'), zero=True)
        if int(minimum) > int(output):
            raise ValueError('Minimum output exceeds quoted output')
        route = data.get('routePlan')
        if not isinstance(route, list) or not route:
            result['outcome'], result['reason'] = 'unavailable', 'route_unavailable'
            return
        cursor = result['input_mint']
        fees = []
        for hop in route:
            if not isinstance(hop, dict) or _mint(hop.get('inputMint')) != cursor:
                raise ValueError('Quote route is not contiguous')
            cursor = _mint(hop.get('outputMint'))
            fee_amount = None
            if hop.get('feeAmount') is not None:
                fee_amount = _atomic(hop['feeAmount'], zero=True)
            fees.append({
                'fee_mint': _mint(hop['feeMint']) if hop.get('feeMint') is not None else None,
                'fee_amount_atomic': fee_amount,
                'fee_rate_raw': _decimal_text(hop.get('feeRate')),
                'fee_rate_unit': 'provider_unit_not_converted_to_bps',
            })
        if cursor != result['output_mint']:
            raise ValueError('Quote route ends in another mint')
        result['output_amount_atomic'] = output
        result['min_output_amount_atomic'] = minimum
        result['route'] = _sanitized(route)
        result['fee_details']['route_fees'] = fees
        if any(fee['fee_amount_atomic'] is None or fee['fee_mint'] is None for fee in fees):
            result['quality_flags'].append('route_fee_details_incomplete')
        if data.get('actualInputAmount') is not None:
            actual = _atomic(data['actualInputAmount'])
            if int(actual) > int(result['input_amount_atomic']):
                raise ValueError('Provider actual input exceeds the requested budget')
            result['actual_input_amount_atomic'] = actual
            if actual != result['input_amount_atomic']:
                result['quality_flags'].append('provider_actual_input_adjusted')
        result['price_impact_pct'] = _decimal_text(data.get('priceImpactPct'))
        if result['price_impact_pct'] is None:
            result['quality_flags'].append('price_impact_unknown')
        slot = data.get('contextSlot', payload.get('contextSlot'))
        source_time = data.get('sourceTimeMs', payload.get('sourceTimeMs'))
        result['source_slot'] = slot if type(slot) is int and slot >= 0 else None
        result['source_time_ms'] = source_time if type(source_time) is int and source_time >= 0 else None
        result['outcome'], result['reason'] = 'quoted', None

    async def round_trip(self, token_mint, input_lamports, slippage_bps=100):
        """Observe two current quotes, without assuming a future token exit.

        The sell quote consumes precisely the buy quote's expected token output.
        This is not the amount guaranteed by the buy's slippage threshold, nor a
        position acquired by a transaction. Both quoted amounts are retained.
        """
        token_mint = _mint(token_mint)
        if token_mint == SOL_MINT:
            raise ValueError('Round trip token must differ from SOL')
        buy = await self.quote(SOL_MINT, token_mint, input_lamports, slippage_bps)
        result = {
            'provider': 'raydium_trade_api',
            'buy': buy, 'sell': None,
            'outcome': buy['outcome'],
            'reason': 'buy_quote_unavailable' if buy['outcome'] != 'quoted' else None,
            'position_acquired': False,
            'future_exit_guaranteed': False,
            'execution_guaranteed': False,
            'quoted_round_trip_delta_lamports': None,
            'additional_execution_costs_known': False,
        }
        if buy['outcome'] != 'quoted':
            return result
        sell = await self.quote(token_mint, SOL_MINT, buy['output_amount_atomic'], slippage_bps)
        result['sell'] = sell
        if sell['outcome'] == 'quoted':
            result['outcome'], result['reason'] = 'quoted', None
            result['quoted_round_trip_delta_lamports'] = (
                int(sell['output_amount_atomic']) - int(buy['input_amount_atomic']))
        else:
            result['outcome'], result['reason'] = sell['outcome'], 'sell_quote_unavailable'
        return result
