"""Bounded, opt-in read-only P3 observations in a separate point-in-time journal."""
import argparse
import asyncio
from decimal import Decimal, InvalidOperation
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

import aiohttp

from bot.analyser.artifacts import atomic_write_json
from bot.p3.quotes import RaydiumQuoteClient, RAYDIUM_QUOTE_URL, SOL_MINT, _mint, _atomic
from bot.p3.store import CaptureStore
from bot.scanner.transaction_parser import find_raydium_launches, RAYDIUM_LAUNCHPAD_PROGRAM_ID

RPC_URL = 'https://api.mainnet-beta.solana.com'
CANONICAL_RPC_URL = 'https://api.mainnet.solana.com'
_PUBLIC_RPC_URLS = frozenset((RPC_URL, CANONICAL_RPC_URL))
FX_URL = 'https://api.dexscreener.com/token-pairs/v1/solana/' + SOL_MINT
USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
_RPC_METHODS = frozenset(('getSlot', 'getSignaturesForAddress', 'getTransaction'))


def now_ms():
    return time.time_ns() // 1_000_000


def _environment_proxy(url):
    """Honor configured routing without aiohttp's implicit netrc lookup."""
    destination = urlsplit(url)
    if proxy_bypass(destination.hostname):
        return None
    return getproxies().get(destination.scheme)


class ReadOnlyPolicyError(ValueError):
    pass


def _registered_rpc_url(value):
    # Exact public URLs only: no credentials, query parameters or redirects.
    if type(value) is not str or value not in _PUBLIC_RPC_URLS:
        raise ReadOnlyPolicyError('Unregistered public RPC endpoint')
    return value


def _rpc_endpoint_kind(value):
    if value == CANONICAL_RPC_URL:
        return 'canonical'
    return 'historical_alias' if value == RPC_URL else 'unregistered'


class ReadOnlySession:
    """Restrict both destinations and operations; count attempts before transport."""
    def __init__(self, session, max_requests=8, *, proxy_resolver=None, rpc_url=RPC_URL):
        if type(max_requests) is not int or not 1 <= max_requests <= 20:
            raise ValueError('Request budget must be between 1 and 20')
        self.session, self.max_requests, self.requests_used = session, max_requests, 0
        self.proxy_resolver = proxy_resolver
        # Selection is explicit and must be registered by the caller before
        # capture. Failures never switch endpoints or consume a hidden retry.
        self._rpc_url = _registered_rpc_url(rpc_url)

    @property
    def rpc_url(self):
        """The endpoint selected before capture; changing it requires a new session."""
        return self._rpc_url

    def _take(self):
        if self.requests_used >= self.max_requests:
            raise ReadOnlyPolicyError('read_only_request_budget_exhausted')
        self.requests_used += 1

    def get(self, url, **kwargs):
        if url not in (RAYDIUM_QUOTE_URL, FX_URL):
            raise ReadOnlyPolicyError('GET destination is outside the capture policy')
        if kwargs.get('headers') or kwargs.get('auth') or kwargs.get('cookies'):
            raise ReadOnlyPolicyError('Authenticated market requests are not configured')
        params = kwargs.get('params') or {}
        expected = {'inputMint', 'outputMint', 'amount', 'slippageBps', 'txVersion'}
        if ((url == FX_URL and params)
                or (url == RAYDIUM_QUOTE_URL and set(params) != expected)):
            raise ReadOnlyPolicyError('Unexpected quote query parameters')
        self._take()
        kwargs['allow_redirects'] = False
        if self.proxy_resolver is not None:
            kwargs['proxy'] = self.proxy_resolver(url)
        return self.session.get(url, **kwargs)

    def post(self, url, *, json=None, **kwargs):
        if (url != self.rpc_url or not isinstance(json, dict)
                or json.get('method') not in _RPC_METHODS):
            raise ReadOnlyPolicyError('RPC method is outside the read-only capture policy')
        if kwargs.get('headers') or kwargs.get('auth') or kwargs.get('cookies'):
            raise ReadOnlyPolicyError('Authenticated market requests are not configured')
        self._take()
        kwargs['allow_redirects'] = False
        if self.proxy_resolver is not None:
            kwargs['proxy'] = self.proxy_resolver(url)
        return self.session.post(url, json=json, **kwargs)


def _http_date(value):
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(not 32 <= ord(character) <= 126 for character in value)):
        raise ValueError('Invalid HTTP date')
    # IMF-fixdate / obsolete RFC850 both end in GMT. The other HTTP-date
    # representation is asctime, whose timezone is implicitly GMT.
    asctime = re.fullmatch(r'[A-Z][a-z]{2} [A-Z][a-z]{2} [ 0-9][0-9] '
                          r'[0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}', value)
    if not value.endswith(' GMT') and not asctime:
        raise ValueError('HTTP date requires GMT')
    parsed = parsedate_to_datetime(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _retry_after_receipt(headers):
    """Retain parsed cooldown evidence only, never arbitrary response headers.

    HTTP delay-seconds are exact nonnegative integers. HTTP-date is relative
    to the server's Date header; a missing reference remains unknown rather
    than using a possibly skewed client clock. This does not schedule a retry.
    """
    result = {'retry_after_seconds': None, 'retry_after_status': 'missing',
              'retry_after_date_utc': None, 'retry_after_reference_date_utc': None}
    value = headers.get('Retry-After')
    if value is None:
        return result
    result['retry_after_status'] = 'invalid'
    if type(value) is not str or len(value) > 128:
        return result
    value = value.strip()
    if re.fullmatch(r'[0-9]{1,64}', value):
        result.update(retry_after_seconds=int(value), retry_after_status='delay_seconds')
        return result
    try:
        target = _http_date(value)
    except (ValueError, TypeError, OverflowError):
        return result
    result.update(retry_after_date_utc=target.isoformat(),
                  retry_after_status='http_date_reference_unknown')
    try:
        reference = _http_date(headers.get('Date'))
    except (ValueError, TypeError, OverflowError):
        return result
    delay = target-reference
    result.update(retry_after_seconds=max(0, delay.days*86400+delay.seconds),
                  retry_after_reference_date_utc=reference.isoformat(),
                  retry_after_status='http_date')
    return result


async def _rpc(session, append, method, params, *, rpc_url=None):
    request_id = str(uuid.uuid4())
    started, mono = now_ms(), time.monotonic_ns()
    outcome, reason, result, status = 'error', None, None, None
    error_code, cancelled = None, None
    transport_error_type = None
    retry = {'retry_after_seconds': None, 'retry_after_status': 'not_received',
             'retry_after_date_utc': None, 'retry_after_reference_date_utc': None}
    selected_url = getattr(session, 'rpc_url', RPC_URL)
    target_url = selected_url if rpc_url is None else rpc_url
    try:
        _registered_rpc_url(selected_url)
        _registered_rpc_url(target_url)
        if target_url != selected_url:
            raise ReadOnlyPolicyError('RPC endpoint differs from explicit session selection')
        async with session.post(target_url, json={
                'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
                timeout=aiohttp.ClientTimeout(total=8)) as response:
            status = response.status
            retry = _retry_after_receipt(response.headers)
            if status != 200:
                reason = 'http_' + str(status)
            else:
                payload = await response.json(content_type=None)
                if (not isinstance(payload, dict) or payload.get('jsonrpc') != '2.0'
                        or type(payload.get('id')) is not int or payload['id'] != 1):
                    reason = 'invalid_rpc_envelope'
                elif payload.get('error') is not None:
                    reason = 'rpc_error'
                    error = payload['error']
                    code = error.get('code') if isinstance(error, dict) else None
                    error_code = code if type(code) is int else None
                elif 'result' not in payload:
                    reason = 'missing_rpc_result'
                else:
                    result, outcome = payload['result'], 'observed'
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as error:
        reason = 'transport_or_timeout'
        transport_error_type = type(error).__name__
    except ReadOnlyPolicyError:
        reason = 'request_budget_or_policy_rejection'
    except (ValueError, TypeError):
        reason = 'invalid_or_disallowed_response'
    except asyncio.CancelledError as error:
        reason, cancelled = 'capture_cancelled', error
    received = now_ms()
    append('request', received_at_ms=received, outcome=outcome, reason=reason,
           request_id=request_id, payload={
               'provider': 'solana_public_mainnet', 'rpc_method': method,
               'endpoint_kind': _rpc_endpoint_kind(target_url),
               'requested_at_ms': started, 'received_at_ms': received,
               'latency_ms': (time.monotonic_ns() - mono) / 1_000_000,
               'http_status': status, 'rpc_error_code': error_code, **retry,
               **({'transport_error_type':transport_error_type} if transport_error_type else {})})
    if cancelled is not None:
        raise cancelled
    return result, received, request_id, outcome


def capture_transaction(append, tx, *, signature, slot, received_at_ms, request_id=None):
    """Retain failed/missing/unclassified transactions and every verified creation."""
    if tx is None:
        append('transaction', received_at_ms=received_at_ms, source_slot=slot,
               signature=signature, request_id=request_id, outcome='missing',
               reason='transaction_unavailable_at_receipt', payload={'result': None})
        return []
    source = tx.get('blockTime') if isinstance(tx, dict) else None
    source_ms = source * 1000 if type(source) is int else None
    envelope = dict(received_at_ms=received_at_ms, source_time_ms=source_ms,
                    source_slot=slot, signature=signature, request_id=request_id)
    if (not isinstance(tx, dict) or not isinstance(tx.get('meta'), dict)
            or 'err' not in tx['meta'] or not isinstance(tx.get('transaction'), dict)
            or not isinstance(tx['transaction'].get('message'), dict)):
        append('transaction', **envelope, outcome='failed', reason='invalid_transaction_shape',
               payload={'response_representation_sha256':
                        hashlib.sha256(json.dumps(tx, sort_keys=True).encode()).hexdigest()})
        return []
    try:
        transaction_id = append('transaction', **envelope, outcome='observed',
                                payload={'raw_transaction': tx})
    except ValueError:
        # Untrusted program logs may contain credential-shaped text. Preserve a
        # failure receipt and digest instead of leaking that body or losing it silently.
        digest = hashlib.sha256(json.dumps(tx, sort_keys=True).encode()).hexdigest()
        append('transaction', **envelope, outcome='failed', reason='unsafe_or_invalid_raw_payload',
               payload={'response_representation_sha256': digest})
        return []
    if tx.get('slot') is not None and (type(tx['slot']) is not int or tx['slot'] != slot):
        append('candidate_decision', **envelope, outcome='rejected',
               reason='signature_transaction_slot_mismatch',
               payload={'transaction_observation_id': transaction_id})
        return []
    if tx['meta'].get('err') is not None:
        append('candidate_decision', **envelope, outcome='rejected',
               reason='chain_transaction_failed', payload={'transaction_observation_id': transaction_id})
        return []
    try:
        launches = find_raydium_launches(tx)
    except (ValueError, TypeError, KeyError, AttributeError):
        append('candidate_decision', **envelope, outcome='rejected',
               reason='conflicting_or_invalid_launch_identity',
               payload={'transaction_observation_id': transaction_id})
        return []
    if not launches:
        append('candidate_decision', **envelope, outcome='rejected',
               reason='no_verified_launch_instruction',
               payload={'transaction_observation_id': transaction_id})
    for launch in launches:
        append('launch', **envelope, mint=launch['mint'], outcome='observed',
               payload={**launch, 'transaction_observation_id': transaction_id})
        append('candidate_decision', **envelope, mint=launch['mint'],
               outcome='not_evaluated', reason='risk_permissions_and_execution_unverified',
               payload={'transaction_observation_id': transaction_id,
                        'entry_permitted': False, 'real_orders_enabled': False})
    return launches


async def capture_fx(session, append):
    started, mono = now_ms(), time.monotonic_ns()
    outcome, reason, value = 'unavailable', None, None
    pairs = None
    try:
        async with session.get(FX_URL, timeout=aiohttp.ClientTimeout(total=8)) as response:
            if response.status != 200:
                reason = 'http_' + str(response.status)
            else:
                pairs = await response.json(content_type=None)
                candidates = []
                for pair in pairs if isinstance(pairs, list) else []:
                    if not isinstance(pair, dict):
                        continue
                    base, reserves = pair.get('baseToken'), pair.get('liquidity')
                    if (not isinstance(base, dict) or base.get('address') != SOL_MINT
                            or not isinstance(reserves, dict)):
                        continue
                    try:
                        rate = Decimal(str(pair.get('priceUsd')))
                        liquidity = Decimal(str(reserves.get('usd', 0)))
                        if rate.is_finite() and rate > 0 and liquidity.is_finite() and liquidity >= 0:
                            candidates.append((liquidity, str(pair.get('pairAddress') or ''), rate))
                    except (InvalidOperation, ValueError, TypeError):
                        continue
                if candidates:
                    liquidity, pair, rate = max(candidates)
                    outcome = 'indicative'
                    value = {'base_currency': 'SOL', 'quote_currency': 'USD',
                             'rate': str(rate), 'pair_address': pair,
                             'liquidity_usd': str(liquidity)}
                else:
                    reason = 'no_valid_sol_usd_display_price'
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
        reason = 'transport_or_timeout'
    except (ValueError, TypeError):
        reason = 'invalid_or_disallowed_response'
    received = now_ms()
    payload = {'provider': 'dexscreener', 'requested_at_ms': started,
               'latency_ms': (time.monotonic_ns()-mono)/1_000_000,
               'display_observation': value, 'provider_source_time_known': False,
               'eligible_for_strict_fx_conversion': False}
    try:
        append('fx', received_at_ms=received, outcome=outcome, reason=reason, payload=payload)
    except ValueError:
        payload['display_observation'] = None
        payload['response_representation_sha256'] = hashlib.sha256(
            json.dumps(pairs, sort_keys=True).encode()).hexdigest()
        append('fx', received_at_ms=received, outcome='unavailable',
               reason='unsafe_or_invalid_fx_payload', payload=payload)


def _record_quote(append, quote, side, request_id):
    # Retain normalized evidence and a hash of the sanitized raw response.
    # Raw untrusted response extensions cannot inject credentials into the journal.
    payload = {key: value for key, value in quote.items() if key != 'raw_payload'}
    # Preserve the sanitized public body needed to replay normalization. The
    # store still rejects forbidden fields and retains an explicit error receipt.
    payload['retained_sanitized_response'] = quote.get('raw_payload')
    payload['sanitized_response_retained'] = quote.get('raw_payload') is not None
    raw = json.dumps(quote.get('raw_payload'), sort_keys=True, allow_nan=False)
    payload['sanitized_response_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    payload['quote_side'] = side
    envelope = dict(received_at_ms=quote['received_at_ms'],
                    source_time_ms=quote['source_time_ms'], source_slot=quote['source_slot'],
                    mint=quote['output_mint'] if side == 'buy' else quote['input_mint'],
                    request_id=request_id)
    try:
        append('quote_attempt', **envelope, outcome=quote['outcome'],
               reason=quote['reason'], payload=payload)
    except ValueError:
        # Sanitized extensions can still violate the journal policy (including
        # redacted credential keys). Retain a receipt without those extensions.
        append('quote_attempt', **envelope, outcome='error',
               reason='unsafe_or_invalid_quote_payload',
               payload={'provider': 'raydium_trade_api', 'quote_side': side,
                        'sanitized_response_sha256': payload['sanitized_response_sha256'],
                        'retained_sanitized_response': None,
                        'sanitized_response_retained': False,
                        'original_quote_outcome': quote['outcome'],
                        'original_quote_reason': quote['reason'],
                        'response_body_status': 'rejected_by_journal_policy',
                        'response_body_sha256': quote.get('response_body_sha256'),
                        'response_body_bytes_observed': quote.get('response_body_bytes_observed'),
                        'requested_at_ms': quote['requested_at_ms'],
                        'received_at_ms': quote['received_at_ms'],
                        'latency_ms': quote['latency_ms'], 'http_status': quote['http_status'],
                        'slippage_bps': quote['slippage_bps'],
                        'input_mint': quote['input_mint'], 'output_mint': quote['output_mint'],
                        'input_amount_atomic': quote['input_amount_atomic'],
                        'execution_guaranteed': False, 'executable_confirmed': False})
        return False
    return True


async def _quote_with_cancellation_receipt(client, append, input_mint, output_mint,
                                         amount, side, request_id, slippage_bps=100):
    """Retain an interrupted attempt before propagating cancellation.

    A cancelled request has no observed output, even if the provider may have
    received it. Keep the side, exact requested size and local timing only.
    """
    requested, monotonic = now_ms(), time.monotonic_ns()
    try:
        return await client.quote(input_mint, output_mint, amount, slippage_bps)
    except asyncio.CancelledError as error:
        received = now_ms()
        metadata = getattr(error, 'capture_quote_metadata', {})
        # Only our client's explicit receipt whitelist crosses this boundary.
        # Cancellation remains cancellation, including a known HTTP error whose
        # body was interrupted by the campaign deadline.
        retained = {key: metadata[key] for key in (
            'http_status', 'retry_after_seconds', 'response_body_status',
            'response_body_sha256', 'response_body_bytes_observed', 'requested_at_ms')
            if isinstance(metadata, dict) and key in metadata}
        append('quote_attempt', received_at_ms=received,
               mint=output_mint if side == 'buy' else input_mint,
               outcome='cancelled', reason='capture_cancelled', request_id=request_id,
               payload={'provider': 'raydium_trade_api', 'quote_side': side,
                        'input_mint': input_mint, 'output_mint': output_mint,
                        'input_amount_atomic': str(amount), 'requested_at_ms': requested,
                        'received_at_ms': received, 'slippage_bps': slippage_bps,
                        'latency_ms': (time.monotonic_ns()-monotonic)/1_000_000,
                        'position_acquired': False, 'execution_verified': False, **retained})
        raise


async def collect_snapshot(store, session, *, signature_limit=5, max_transactions=2,
                           quote_mint=None, input_lamports=1_000_000_000,
                           slippage_bps=100, provenance='live'):
    """A bounded sample, never an exhaustive live scanner or strategy activation."""
    if type(signature_limit) is not int or not 1 <= signature_limit <= 20:
        raise ValueError('Signature sample limit must be between 1 and 20')
    if type(max_transactions) is not int or not 0 <= max_transactions <= 10:
        raise ValueError('Transaction fetch limit must be between 0 and 10')
    amount = _atomic(input_lamports)
    if quote_mint is not None:
        _mint(quote_mint)
        if quote_mint == SOL_MINT:
            raise ValueError('Quote target must differ from SOL')
    if type(slippage_bps) is not int or not 0 <= slippage_bps <= 10000:
        raise ValueError('Invalid slippage assumption')
    run_id = str(uuid.uuid4())
    def append(kind, **record):
        return store.append(kind, provenance=provenance, **record)
    append('gap', received_at_ms=now_ms(), outcome='open',
           reason='bounded_bootstrap_without_independent_reference',
           payload={'gap_id': run_id, 'global_coverage_known': False})
    slot, _, _, _ = await _rpc(session, append, 'getSlot', [{'commitment': 'confirmed'}])
    page, received, request_id, outcome = await _rpc(
        session, append, 'getSignaturesForAddress',
        [RAYDIUM_LAUNCHPAD_PROGRAM_ID, {'limit': signature_limit, 'commitment': 'confirmed'}])
    fetched = 0
    if outcome == 'observed' and isinstance(page, list) and len(page) <= signature_limit:
        for row in page:
            if (not isinstance(row, dict) or not isinstance(row.get('signature'), str)
                    or not row['signature'] or type(row.get('slot')) is not int
                    or row['slot'] < 0 or 'err' not in row):
                append('gap', received_at_ms=received, outcome='open',
                       reason='invalid_signature_page_row',
                       payload={'gap_id': run_id + '-invalid-row'})
                continue
            # The manifest retains every sampled signature, even ones not fetched.
            if row['err'] is not None or fetched >= max_transactions:
                source = row.get('blockTime')
                append('transaction', received_at_ms=received, source_slot=row['slot'],
                       source_time_ms=source*1000 if type(source) is int else None,
                       signature=row['signature'], outcome='chain_failed' if row['err'] is not None else 'unavailable',
                       reason='signature_has_chain_error' if row['err'] is not None else 'bounded_fetch_budget',
                       payload={'signature_row': row})
                continue
            tx, tx_received, tx_request, _ = await _rpc(
                session, append, 'getTransaction',
                [row['signature'], {'commitment': 'confirmed', 'encoding': 'jsonParsed',
                                    'maxSupportedTransactionVersion': 1}])
            launches = capture_transaction(append, tx, signature=row['signature'], slot=row['slot'],
                                           received_at_ms=tx_received, request_id=tx_request)
            for launch in launches:
                if launch['mint'] != quote_mint:
                    append('quote_attempt', received_at_ms=now_ms(), mint=launch['mint'],
                           signature=row['signature'], outcome='not_attempted',
                           reason='outside_bounded_quote_sample',
                           payload={'quote_side': 'buy_and_sell',
                                    'requested_notional_lamports': amount,
                                    'network_request_attempted': False})
            fetched += 1
    else:
        append('gap', received_at_ms=received, outcome='open', reason='signature_page_unavailable',
               payload={'gap_id': run_id + '-page'})
    await capture_fx(session, append)
    if quote_mint is not None:
        client, quote_request = RaydiumQuoteClient(session), str(uuid.uuid4())
        buy = await _quote_with_cancellation_receipt(
            client, append, SOL_MINT, quote_mint, amount, 'buy', quote_request, slippage_bps)
        buy_recorded = _record_quote(append, buy, 'buy', quote_request)
        if buy['outcome'] == 'quoted' and buy_recorded:
            sell = await _quote_with_cancellation_receipt(
                client, append, quote_mint, SOL_MINT, buy['output_amount_atomic'],
                'sell', quote_request, slippage_bps)
            _record_quote(append, sell, 'sell', quote_request)
        else:
            append('quote_attempt', received_at_ms=now_ms(), mint=quote_mint,
                   outcome='not_attempted', reason='buy_quote_unavailable',
                   request_id=quote_request, payload={'quote_side': 'sell', 'input_amount_atomic': None})
    append('checkpoint', received_at_ms=now_ms(), outcome='bounded_sample_complete',
           payload={'run_id': run_id, 'observed_slot': slot if type(slot) is int else None,
                    'fetched_transactions': fetched, 'signature_page_limit': signature_limit,
                    'coverage_complete': False, 'position_acquired': False})
    report = store.quality_report()
    report.update(run_id=run_id, requests_used=session.requests_used,
                  max_requests=session.max_requests, real_orders_enabled=False,
                  collector='bounded_rpc_snapshot_not_a_live_universe',
                  quote_target=quote_mint, input_lamports=amount)
    return report


async def _capture(args):
    with CaptureStore(args.db) as store:
        async with aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as transport:
            session = ReadOnlySession(transport, args.max_requests, proxy_resolver=_environment_proxy)
            try:
                # aiohttp has no public no-retry option. Its internal GET retry
                # would otherwise bypass the attempt budget. Fail closed if the
                # supported transport no longer exposes this switch.
                if type(getattr(transport, '_retry_connection', None)) is not bool:
                    raise ReadOnlyPolicyError('Unsupported transport retry policy')
                transport._retry_connection = False
                return await asyncio.wait_for(collect_snapshot(
                    store, session, signature_limit=args.signature_limit,
                    max_transactions=args.max_transactions, quote_mint=args.quote_mint,
                    input_lamports=args.input_lamports, slippage_bps=args.slippage_bps), timeout=40)
            except (asyncio.TimeoutError, ReadOnlyPolicyError):
                store.append('gap', received_at_ms=now_ms(), outcome='open',
                             reason='capture_budget_or_deadline_exhausted',
                             payload={'gap_id': str(uuid.uuid4())})
                report = store.quality_report()
                report.update(requests_used=session.requests_used,
                              max_requests=session.max_requests, real_orders_enabled=False)
                return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('collect', 'validate'))
    parser.add_argument('--db', type=Path, required=True, help='Separate P3 journal; existing PAPER DB is refused')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--network', action='store_true', help='Explicit opt-in to bounded free public read-only requests')
    parser.add_argument('--max-requests', type=int, default=8)
    parser.add_argument('--signature-limit', type=int, default=5)
    parser.add_argument('--max-transactions', type=int, default=2)
    parser.add_argument('--quote-mint', help='Public target mint; not automatically inferred from future/surviving tokens')
    parser.add_argument('--input-lamports', type=int, default=1_000_000_000)
    parser.add_argument('--slippage-bps', type=int, default=100)
    args = parser.parse_args()
    if args.output.suffix.lower() != '.json' or args.output.resolve() == args.db.resolve():
        parser.error('Use a separate .json output, never the capture database')
    if args.command == 'collect':
        if not args.network:
            parser.error('collect requires --network; no automatic market access')
        report = asyncio.run(_capture(args))
    else:
        with CaptureStore(args.db, readonly=True) as store:
            report = store.quality_report()
    atomic_write_json(args.output, report, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({'records': report['records'], 'p3_go': report['p3_go'],
                      'economic_validation': report['economic_validation']}, sort_keys=True))


if __name__ == '__main__':
    main()
