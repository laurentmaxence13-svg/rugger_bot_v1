"""Preregistered, bounded public LaunchLab observations; no order construction.

The index supplies leads, transactions supply creation evidence, and one RPC
bank supplies linked account bytes. Neither a curve projection nor a provider
quote is an executed trade. All evidence goes to a separate P3 journal.
"""
import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
import time
import uuid

import aiohttp

from bot.analyser.artifacts import atomic_write_json
from bot.p3.collect import (RPC_URL, ReadOnlySession, ReadOnlyPolicyError, _rpc,
                            _environment_proxy, now_ms, capture_transaction, _record_quote,
                            _quote_with_cancellation_receipt)
from bot.p3.launchlab import addresses_from_pool, analyze_snapshot, SnapshotEvidenceError
from bot.p3.quotes import SOL_MINT, RAYDIUM_QUOTE_URL, RaydiumQuoteClient, _mint
from bot.p3.readiness import evaluate_readiness
from bot.p3.store import CaptureStore, _safe_json

INDEX_URL = 'https://launch-mint-v1.raydium.io/get/list'
_METHODS = frozenset(('getMultipleAccounts', 'getBlockTime',
                      'getSignaturesForAddress', 'getTransaction'))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    # Digest untrusted JSON without ever echoing its potentially unsafe fields.
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_plan(plan):
    """Versioned fixed instrumentation protocol, not an optimized strategy."""
    required = {
        'schema': 'p3-launchlab-campaign-v1', 'plan_id': 'launchlab-native-sol-001',
        'sample_size': 2, 'max_requests': 20, 'max_elapsed_ms': 60_000,
        'followup_delay_ms': 15_000, 'index_sort': 'new', 'max_index_rows': 100,
        'signature_limit': 20, 'transactions_per_pool': 1,
        'input_lamports': 1_000_000_000, 'slippage_bps': 100,
        'share_fee_rate_ppm': 0, 'commitment': 'confirmed',
        'selection': 'first_two_valid_unique_SOL_rows_in_response_order',
        'transaction_selection': 'oldest_successful_signature_in_received_page',
        'source_main': '966076c1a8b9a5d83bea74fe53fdad1056ade6dc',
    }
    if type(plan) is dict and plan.get('plan_id') == 'launchlab-native-sol-002':
        # Explicit new protocol after observed v1 transactions and a creation
        # outside the first 20 signatures. Never mutate/relabel the original run.
        required.update(schema='p3-launchlab-campaign-v2', plan_id='launchlab-native-sol-002',
                        signature_limit=1000, max_supported_transaction_version=1)
    if type(plan) is dict and plan.get('plan_id') == 'launchlab-retention-sol-003':
        required.update(schema='p3-launchlab-campaign-v3', plan_id='launchlab-retention-sol-003',
                        signature_limit=1000, max_supported_transaction_version=1,
                        evidence_profile='published_metadata_v1', stop_on_source_error=True,
                        source_main='7ddddb9f73339242fbcb5b9bf10fa329c82fa700')
        revision = plan.get('source_revision')
        if type(revision) is not str or re.fullmatch(r'[0-9a-f]{40}', revision) is None:
            raise ValueError('New retention plan requires an exact source revision')
        required['source_revision'] = revision
    if type(plan) is not dict or set(plan) != set(required) | {'registered_at_ms'}:
        raise ValueError('Unexpected preregistered plan schema')
    if any(type(plan[key]) is not type(value) or plan[key] != value
           for key, value in required.items()):
        raise ValueError('Unsupported campaign protocol')
    if type(plan['registered_at_ms']) is not int or not 0 < plan['registered_at_ms'] < now_ms():
        raise ValueError('Plan must be registered before collection')
    return hashlib.sha256(canonical(plan)).hexdigest()


class CampaignSession(ReadOnlySession):
    """Adds only discovery and two account-reading methods to the P3 policy."""
    def __init__(self, session, max_requests=8, *, proxy_resolver=None):
        super().__init__(session, max_requests, proxy_resolver=proxy_resolver)
        self._deadline_ns = None

    def check_deadline(self):
        if self._deadline_ns is not None and time.monotonic_ns() >= self._deadline_ns:
            raise ReadOnlyPolicyError('campaign_deadline_exhausted')

    def _take(self):
        # asyncio timers cannot interrupt SQLite/JSON synchronous work. Check
        # the monotonic deadline again immediately before dispatching a request.
        self.check_deadline()
        super()._take()

    def _limit_timeout(self, kwargs):
        if self._deadline_ns is None:
            return
        self.check_deadline()
        remaining = (self._deadline_ns-time.monotonic_ns())/1_000_000_000
        if remaining <= 0:
            raise ReadOnlyPolicyError('campaign_deadline_exhausted')
        timeout = kwargs.get('timeout')
        if timeout is not None and not isinstance(timeout, aiohttp.ClientTimeout):
            raise ReadOnlyPolicyError('Unexpected campaign timeout configuration')
        total = timeout.total if timeout is not None else None
        kwargs['timeout'] = aiohttp.ClientTimeout(
            total=min(remaining, total) if total is not None and total > 0 else remaining,
            connect=timeout.connect if timeout is not None else None,
            sock_read=timeout.sock_read if timeout is not None else None,
            sock_connect=timeout.sock_connect if timeout is not None else None,
            # aiohttp otherwise rounds timeouts >=5 s to the next second.
            ceil_threshold=float('inf'))

    @staticmethod
    def _anonymous_options(kwargs):
        if set(kwargs) - {'timeout'}:
            raise ReadOnlyPolicyError('Unexpected transport options')

    def get(self, url, **kwargs):
        if url != INDEX_URL:
            # Existing exact Raydium compute policy; no arbitrary destinations.
            if url != RAYDIUM_QUOTE_URL:
                raise ReadOnlyPolicyError('GET destination is outside the campaign policy')
            redirects = kwargs.pop('allow_redirects', False)
            if redirects is not False or set(kwargs) - {'params', 'timeout'}:
                raise ReadOnlyPolicyError('Unexpected transport options')
            params = kwargs.get('params') or {}
            if set(params) != {'inputMint', 'outputMint', 'amount', 'slippageBps', 'txVersion'}:
                raise ReadOnlyPolicyError('Unexpected quote query parameters')
        else:
            params = kwargs.pop('params', None)
            self._anonymous_options(kwargs)
            if params != {'sort': 'new'}:
                raise ReadOnlyPolicyError('Unexpected discovery query')
            kwargs['params'] = params
        kwargs['allow_redirects'] = False
        if self.proxy_resolver is not None:
            kwargs['proxy'] = self.proxy_resolver(url)
        self._limit_timeout(kwargs)
        self._take()
        return self.session.get(url, **kwargs)

    def post(self, url, *, json=None, **kwargs):
        self._anonymous_options(kwargs)
        if (url != RPC_URL or type(json) is not dict
                or set(json) != {'jsonrpc', 'id', 'method', 'params'}
                or json.get('jsonrpc') != '2.0' or type(json.get('id')) is not int
                or json['id'] != 1 or json.get('method') not in _METHODS
                or type(json.get('params')) is not list):
            raise ReadOnlyPolicyError('RPC method is outside the campaign policy')
        kwargs['allow_redirects'] = False
        if self.proxy_resolver is not None:
            kwargs['proxy'] = self.proxy_resolver(url)
        self._limit_timeout(kwargs)
        self._take()
        return self.session.post(url, json=json, **kwargs)


def _address(value):
    try:
        _mint(value)
    except (ValueError, TypeError):
        return None
    return value


def select_rows(payload):
    """Retain every received row, including invalid/unselected rows, in order."""
    data = payload.get('data') if type(payload) is dict else None
    rows = data.get('rows') if type(data) is dict else None
    if type(payload) is not dict or payload.get('success') is not True or type(rows) is not list:
        raise ValueError('Invalid index response')
    retained, selected, seen = [], [], set()
    for index, raw in enumerate(rows[:100]):
        row = raw if type(raw) is dict else {}
        quote = row.get('mintB') if type(row.get('mintB')) is dict else {}
        mint, pool = _address(row.get('mint')), _address(row.get('poolId'))
        source_time = row.get('createAt')
        record = {
            'index': index, 'mint': mint, 'pool': pool,
            'config_claim': _address(row.get('configId')),
            'quote_mint_claim': _address(quote.get('address')),
            'creator_claim': _address(row.get('creator')),
            'creation_time_claim_ms': source_time if type(source_time) is int and source_time > 0 else None,
            'row_representation_sha256': digest(raw),
        }
        if mint is None or pool is None or mint == SOL_MINT:
            reason = 'invalid_identity'
        elif quote.get('address') != SOL_MINT:
            reason = 'outside_native_SOL_scope'
        elif mint in seen:
            reason = 'duplicate_mint'
        elif len(selected) >= 2:
            reason = 'outside_preregistered_sample'
        else:
            reason = 'selected_for_observation_only'
            selected.append(record)
        if mint is not None and mint != SOL_MINT and pool is not None and quote.get('address') == SOL_MINT:
            seen.add(mint)
        record['selection_reason'] = reason
        retained.append(record)
    return retained, selected, len(rows)


async def _discover(session, append):
    started, mono = now_ms(), time.monotonic_ns()
    payload, status, reason, cancelled = None, None, None, None
    try:
        async with session.get(INDEX_URL, params={'sort': 'new'},
                               timeout=aiohttp.ClientTimeout(total=8)) as response:
            status = response.status
            if status == 200:
                payload = await response.json(content_type=None)
            else:
                reason = 'http_' + str(status)
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
        reason = 'transport_or_timeout'
    except (ValueError, TypeError, ReadOnlyPolicyError):
        reason = 'invalid_response_or_policy'
    except asyncio.CancelledError as error:
        reason, cancelled = 'capture_cancelled', error
    received = now_ms()
    append('request', received_at_ms=received, outcome='observed' if payload is not None else 'error',
           reason=reason, payload={'provider': 'raydium_launch_mint_index', 'sort': 'new',
                                  'requested_at_ms': started, 'http_status': status,
                                  'latency_ms': (time.monotonic_ns()-mono)/1_000_000})
    if cancelled is not None:
        raise cancelled
    return payload, received


def _gap(append, reason, *, mint=None):
    append('gap', received_at_ms=now_ms(), outcome='open', reason=reason, mint=mint,
           payload={'gap_id': str(uuid.uuid4())})


def _bank(result, count):
    if type(result) is not dict or type(result.get('context')) is not dict:
        return None, None
    slot, values = result['context'].get('slot'), result.get('value')
    if (type(slot) is not int or not 0 <= slot < 2**63 or type(values) is not list
            or len(values) != count):
        return None, None
    return slot, values


async def _snapshot(store, session, append, row, addresses, minimum_slot, period,
                    *, evidence_profile='legacy'):
    requested_addresses = list(addresses.values())
    result, received, request, _ = await _rpc(session, append, 'getMultipleAccounts',
        [requested_addresses, {'encoding': 'base64', 'commitment': 'confirmed',
                                   'minContextSlot': minimum_slot}])
    slot, values = _bank(result, len(addresses))
    if slot is not None and slot < minimum_slot:
        slot, values = None, None
    try:
        identity = append('pool_snapshot', received_at_ms=received, source_slot=slot,
            mint=row['mint'], request_id=request, outcome='observed' if values is not None else 'missing',
            payload={'period': period, 'addresses': addresses, 'requested_addresses': requested_addresses,
                     'raw_rpc_result': result,
                     'minimum_context_slot': minimum_slot, 'evidence_profile': evidence_profile})
    except ValueError:
        append('pool_snapshot', received_at_ms=received, mint=row['mint'], outcome='error',
               reason='unsafe_or_invalid_snapshot', payload={'period': period,
                       'response_representation_sha256': digest(result)})
        _gap(append, 'snapshot_evidence_rejected', mint=row['mint'])
        return None
    # append has committed before analysis begins; available_at is a precommit
    # ingestion barrier and must not be presented as an exact durability time.
    evidence = next(event for event in store.events() if event['id'] == identity)
    if values is None:
        _gap(append, 'coherent_snapshot_unavailable', mint=row['mint'])
        return None
    source_seconds, _, _, _ = await _rpc(session, append, 'getBlockTime', [slot])
    source = source_seconds * 1000 if type(source_seconds) is int and source_seconds > 0 else None
    analysis_at = now_ms()
    analysis = analyze_snapshot(dict(zip(requested_addresses, values)), context_slot=slot,
        expected_mint=row['mint'], pool_address=row['pool'], input_lamports=1_000_000_000,
        evidence_profile=evidence_profile)
    append('candidate_decision', received_at_ms=analysis_at, source_slot=slot, mint=row['mint'],
           outcome='not_admitted', reason='research_observation_only',
           payload={'snapshot_observation_id': identity, 'analysis_at_ms': analysis_at,
                    'block_time_estimate_ms': source, 'analysis': analysis,
                    'entry_permitted': False})
    projection = analysis['conditional_projection']
    for side in ('buy', 'sell'):
        append('quote_attempt', received_at_ms=analysis_at, source_slot=slot, mint=row['mint'],
            outcome='conditional' if projection is not None else 'unavailable',
            reason='counterfactual_curve_only' if projection is not None else 'unsupported_or_unverified_state',
            payload={'provider': 'local_pinned_sdk_arithmetic', 'quote_side': side,
                     'snapshot_observation_id': identity, 'projection': projection,
                     'blocking_reasons': analysis['blocking_reasons'],
                     'position_acquired': False, 'execution_verified': False})
    return {'context_slot': slot, 'received_at_ms': received,
            'available_at_ms': evidence['available_at_ms'], 'analysis_at_ms': analysis_at,
            'source_time_ms': source, 'coherent': True, 'analysis': analysis,
            'snapshot_observation_id': identity}


async def _creation(session, append, row, *, signature_limit=20, max_supported_transaction_version=0):
    if (type(signature_limit) is not int or signature_limit not in (20, 1000)
            or type(max_supported_transaction_version) is not int
            or max_supported_transaction_version not in (0, 1)):
        raise ValueError('Unsupported explicit creation evidence protocol')
    page, received, request, _ = await _rpc(session, append, 'getSignaturesForAddress',
        [row['pool'], {'limit': signature_limit, 'commitment': 'confirmed'}])
    if type(page) is not list:
        _gap(append, 'pool_signature_page_unavailable', mint=row['mint'])
        return False
    page_evidence = {'received_row_count': len(page), 'page_representation_sha256': digest(page),
                     'retention_limit': signature_limit}
    try:
        _safe_json(page[:signature_limit])
    except ValueError:
        page_evidence['raw_page_retained'] = False
        _gap(append, 'signature_page_body_rejected_by_evidence_policy', mint=row['mint'])
    else:
        page_evidence.update(raw_page_retained=True, raw_signature_page=page[:signature_limit])
    append('checkpoint', received_at_ms=received, mint=row['mint'], outcome='pool_signature_page',
           payload=page_evidence)
    if len(page) > signature_limit:
        _gap(append, 'signature_page_exceeds_retention_cap', mint=row['mint'])
    page = page[:signature_limit]
    valid = [item for item in page if type(item) is dict
             and type(item.get('signature')) is str and 64 <= len(item['signature']) <= 90
             and set(item['signature']) <= set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
             and type(item.get('slot')) is int and 0 <= item['slot'] < 2**63
             and 'err' in item]
    success = [item for item in reversed(valid) if item['err'] is None]
    target = success[0] if success else None
    verified = False
    for index, item in enumerate(page):
        if item not in valid:
            append('transaction', received_at_ms=received, mint=row['mint'], outcome='invalid_signature_row',
                   payload={'row_index': index, 'row_sha256': digest(item)})
        elif item is not target:
            append('transaction', received_at_ms=received, source_slot=item['slot'],
                   signature=item['signature'], mint=row['mint'], request_id=request,
                   outcome='chain_failed' if item['err'] is not None else 'not_fetched',
                   reason='chain_error' if item['err'] is not None else 'bounded_creation_lookup',
                   payload={'row_index': index, 'row_sha256': digest(item)})
        else:
            tx, tx_received, tx_request, _ = await _rpc(session, append, 'getTransaction',
                [item['signature'], {'encoding': 'jsonParsed', 'commitment': 'confirmed',
                                     'maxSupportedTransactionVersion': max_supported_transaction_version}])
            transaction = tx.get('transaction') if type(tx) is dict else None
            signatures = transaction.get('signatures') if type(transaction) is dict else None
            if tx is not None and (type(signatures) is not list or not signatures
                                      or signatures[0] != item['signature']):
                append('transaction', received_at_ms=tx_received, source_slot=item['slot'],
                       signature=item['signature'], mint=row['mint'], outcome='failed',
                       reason='returned_transaction_signature_mismatch',
                       payload={'response_representation_sha256': digest(tx)})
                launches = []
            else:
                launches = capture_transaction(append, tx, signature=item['signature'], slot=item['slot'],
                    received_at_ms=tx_received, request_id=tx_request)
            matching = [launch for launch in launches if launch['mint'] == row['mint']
                        and launch['pool_state'] == row['pool']]
            verified = len(matching) == 1
            if verified:
                append('checkpoint', received_at_ms=now_ms(), mint=row['mint'], outcome='creation_matched',
                    payload={'signature': item['signature'], 'pool': row['pool'],
                             'creator': matching[0]['creator'],
                             'index_creator_matches': matching[0]['creator'] == row['creator_claim'],
                             'creation_block_time_ms': tx.get('blockTime') * 1000
                                 if type(tx.get('blockTime')) is int else None,
                             'meta_fee_lamports': tx.get('meta', {}).get('fee'),
                             'fee_scope': 'observed_creation_transaction_not_our_trade'})
    if not verified:
        _gap(append, 'creation_not_found_in_bounded_page', mint=row['mint'])
    return verified


class CampaignSourceStopped(RuntimeError):
    """Stop a new instrumental run after recording a failed source receipt."""


async def collect_campaign(store, session, plan, *, provenance='live'):
    """Execute exactly one fixed campaign; dependency injection is for offline tests."""
    plan_hash = validate_plan(plan)
    if store.events():
        raise ValueError('Campaign requires a new empty P3 journal')
    if session.max_requests != plan['max_requests'] or session.requests_used != 0:
        raise ValueError('Fresh session must match the registered request budget')
    started, mono = now_ms(), time.monotonic_ns()
    session._deadline_ns = mono + plan['max_elapsed_ms']*1_000_000
    selected, retained, total_rows, candidates, snapshots, addresses = [], [], None, [], {}, {}
    initial_completed_ns = []

    def append(kind, **event):
        identity = store.append(kind, provenance=provenance, **event)
        if plan.get('stop_on_source_error') is True:
            status = event.get('payload', {}).get('http_status')
            reason = event.get('reason') or ''
            # Logical HTTP-200 quote refusal is data, not a transport failure.
            if ((type(status) is int and not 200 <= status < 300)
                    or (kind in ('request', 'quote_attempt') and event.get('outcome') == 'error')
                    or reason in ('timeout', 'transport_error')
                    or reason.startswith('unsafe_or_invalid')):
                raise CampaignSourceStopped('source_error_after_persisted_receipt')
        return identity

    append('checkpoint', received_at_ms=started, outcome='registered_plan',
           payload={'plan': plan, 'plan_sha256': plan_hash})
    _gap(append, 'universe_bootstrap_no_independent_creation_reference')

    async def run():
        nonlocal selected, retained, total_rows
        payload, received = await _discover(session, append)
        try:
            retained, selected, total_rows = select_rows(payload)
        except ValueError:
            _gap(append, 'discovery_unavailable_or_invalid')
            return
        # Retain the exact inputs USED by selection, including malformed rows,
        # without collecting irrelevant social/image URLs or following them.
        inputs = []
        for raw in payload['data']['rows'][:100]:
            if type(raw) is not dict:
                inputs.append(raw)
                continue
            record = {key: raw[key] for key in ('mint', 'poolId', 'configId', 'creator', 'createAt')
                      if key in raw}
            quote = raw.get('mintB')
            record['mintB'] = {'address': quote.get('address')} if type(quote) is dict else quote
            inputs.append(record)
        discovery_evidence = {'rows': retained, 'received_row_count': total_rows,
            'response_representation_sha256': digest(payload), 'index_is_creation_proof': False,
            'pagination_verified': False, 'irrelevant_metadata_omitted': True}
        replay_input = {'success': True, 'data': {'rows': inputs}}
        try:
            _safe_json(replay_input)
        except ValueError:
            discovery_evidence['selection_input_retained'] = False
            _gap(append, 'selection_input_rejected_by_evidence_policy')
        else:
            discovery_evidence.update(selection_input_retained=True, replay_selection_input=replay_input)
        append('discovery', received_at_ms=received, outcome='observed', payload=discovery_evidence)
        if total_rows > 100:
            _gap(append, 'index_exceeds_retention_cap')
        for row in retained:
            append('candidate_decision', received_at_ms=received, mint=row['mint'],
                   outcome='selected' if row in selected else 'rejected_from_capture_sample',
                   reason=row['selection_reason'], payload={'index': row['index'], 'entry_permitted': False})
        for row in selected:
            session.check_deadline()
            mint = row['mint']
            candidate = {'mint': mint, 'creation_verified': False, 'snapshots': [],
                'all_account_links_verified': False, 'account_discriminators_certified': False,
                'native_sol': False, 'token_transfer_restrictions_known': False,
                'exit_liquidity_checked': False, 'fees_complete': False,
                'network_fee_bound_known': False, 'source_clock_bound_known': False,
                'pit_decision_order_verified': False, 'exit_observation_available': False}
            candidates.append(candidate)
            result, pool_received, request, _ = await _rpc(session, append, 'getMultipleAccounts',
                [[row['pool']], {'encoding': 'base64', 'commitment': 'confirmed'}])
            slot, values = _bank(result, 1)
            try:
                append('pool_snapshot', received_at_ms=pool_received, mint=mint, source_slot=slot,
                       request_id=request, outcome='address_discovery', payload={'raw_rpc_result': result})
            except ValueError:
                append('pool_snapshot', received_at_ms=pool_received, mint=mint, outcome='error',
                       reason='unsafe_or_invalid_address_snapshot',
                       payload={'response_representation_sha256': digest(result)})
                _gap(append, 'pool_address_graph_unavailable', mint=mint)
            else:
                try:
                    if values is None:
                        raise SnapshotEvidenceError('pool_account_unavailable')
                    addresses[mint] = addresses_from_pool(values[0], mint, row['pool'])
                except (ValueError, TypeError):
                    _gap(append, 'pool_address_graph_unavailable', mint=mint)
                else:
                    first = await _snapshot(store, session, append, row, addresses[mint], slot, 'initial',
                        evidence_profile=plan.get('evidence_profile', 'legacy'))
                    if first is not None:
                        snapshots.setdefault(mint, []).append(first)
                        initial_completed_ns.append(time.monotonic_ns())
            session.check_deadline()
            candidate['creation_verified'] = await _creation(session, append, row,
                signature_limit=plan['signature_limit'],
                max_supported_transaction_version=plan.get('max_supported_transaction_version', 0))
            client, quote_request = RaydiumQuoteClient(session), str(uuid.uuid4())
            session.check_deadline()
            buy = await _quote_with_cancellation_receipt(
                client, append, SOL_MINT, mint, 1_000_000_000, 'buy', quote_request)
            if _record_quote(append, buy, 'buy', quote_request) and buy['outcome'] == 'quoted':
                session.check_deadline()
                sell = await _quote_with_cancellation_receipt(
                    client, append, mint, SOL_MINT, buy['output_amount_atomic'], 'sell', quote_request)
                _record_quote(append, sell, 'sell', quote_request)
            else:
                append('quote_attempt', received_at_ms=now_ms(), mint=mint, outcome='not_attempted',
                       reason='buy_quote_unavailable', payload={'quote_side': 'sell', 'position_acquired': False})
        if snapshots:
            # Wait from the latest initial receipt; subsequent periods cannot
            # silently be relabelled duplicate readings from the same instant.
            if plan.get('stop_on_source_error') is True:
                # Delay conservatively after initial snapshot analysis/persistence,
                # on a monotonic clock unaffected by UTC corrections.
                since = (time.monotonic_ns()-max(initial_completed_ns))/1_000_000
                delay = max(0, plan['followup_delay_ms']-since)
            else:
                last_received = max(values[0]['received_at_ms'] for values in snapshots.values())
                delay = max(0, plan['followup_delay_ms'] - (now_ms()-last_received))
            await asyncio.sleep(delay/1000)
        for row in selected:
            session.check_deadline()
            previous = snapshots.get(row['mint'], [])
            if previous:
                following = await _snapshot(store, session, append, row, addresses[row['mint']],
                                            previous[0]['context_slot'], 'followup',
                                            evidence_profile=plan.get('evidence_profile', 'legacy'))
                if following is not None:
                    previous.append(following)

    try:
        await asyncio.wait_for(run(), timeout=plan['max_elapsed_ms']/1000)
    except CampaignSourceStopped:
        _gap(append, 'campaign_stopped_on_source_error')
    except (asyncio.TimeoutError, ReadOnlyPolicyError):
        _gap(append, 'campaign_budget_or_deadline_exhausted')
    # Every selected identity survives interruption, including ones not reached.
    for row in selected:
        if not any(candidate['mint'] == row['mint'] for candidate in candidates):
            candidates.append({'mint': row['mint'], 'creation_verified': False})
        candidate = next(candidate for candidate in candidates if candidate['mint'] == row['mint'])
        evidence = snapshots.get(row['mint'], [])
        candidate['snapshots'] = [{key: value for key, value in snapshot.items()
                                  if key not in ('analysis', 'snapshot_observation_id')}
                                 for snapshot in evidence]
        candidate['coherent_snapshot_count'] = len(evidence)
        ages = [s['received_at_ms']-s['source_time_ms'] for s in evidence if s['source_time_ms'] is not None]
        candidate['snapshot_source_age_ms'] = max(ages) if evidence and len(ages) == len(evidence) else None
        candidate['pit_decision_order_verified'] = bool(evidence) and all(
            s['analysis_at_ms'] >= s['available_at_ms'] for s in evidence)
        candidate['native_sol'] = bool(evidence) and all(
            s['analysis']['facts'].get('pool', {}).get('mint_b') == SOL_MINT for s in evidence)
        # PDA authority, discriminators, transfer policies, all-in fees and a
        # genuinely observed later exit are not certified by these probes.
    append('checkpoint', received_at_ms=now_ms(), outcome='bounded_campaign_complete',
           payload={'requests_used': session.requests_used, 'position_acquired': False,
                    'real_orders_enabled': False, 'coverage_complete': False})
    quality = store.quality_report()
    tail = store.verify_integrity()
    manifest = {'data_kind': provenance, 'plan': dict(plan, plan_sha256=plan_hash, started_at_ms=started),
        'run': {'requests_used': session.requests_used, 'elapsed_ms': (time.monotonic_ns()-mono)//1_000_000,
                'anonymous_transport': True, 'wire_retry_disabled': True, 'financial_methods_used': [],
                'integrity_verified': True, 'tail_anchor_verified': False,
                'open_gaps': quality['open_gap_count'], 'selected_count': len(selected),
                'independent_reference_complete': False},
        'candidates': candidates, 'policy': {'max_snapshot_age_ms': 5000}}
    return {'schema': 'p3-launchlab-campaign-report-v1', 'manifest': manifest,
        'readiness': evaluate_readiness(manifest), 'quality': quality, 'tail_hash': tail,
        'discovery_received_rows': total_rows, 'discovery_retained_rows': len(retained),
        'selected_count': len(selected), 'verified_creations': sum(c['creation_verified'] for c in candidates),
        'market_detection_coverage': None, 'position_acquired': False, 'real_orders_enabled': False,
        'economic_verdict': 'INSUFFICIENT DATA'}


async def _capture(plan, database):
    # Persisted journal is exclusive to this run. No netrc, cookie or implicit
    # idempotent GET retry may escape the anonymous wire-attempt budget.
    with CaptureStore(database) as store:
        async with aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as transport:
            if type(getattr(transport, '_retry_connection', None)) is not bool:
                raise ReadOnlyPolicyError('Unsupported transport retry policy')
            transport._retry_connection = False
            session = CampaignSession(transport, plan['max_requests'], proxy_resolver=_environment_proxy)
            return await collect_campaign(store, session, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--network', action='store_true')
    args = parser.parse_args()
    if not args.network:
        parser.error('Explicit --network is required')
    anchor = args.output.with_suffix('.anchor.json')
    paths = [path.resolve() for path in (args.plan, args.db, args.output, anchor)]
    if (len(set(paths)) != 4 or args.db.exists() or args.output.exists() or anchor.exists()
            or args.output.suffix != '.json'):
        parser.error('Use a new separate journal and a new .json report')
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    report = asyncio.run(_capture(plan, args.db))
    atomic_write_json(args.output, report, indent=2, sort_keys=True, allow_nan=False)
    # Retain the tail outside the DB, then reopen the CLOSED journal read-only.
    atomic_write_json(anchor, {'tail_hash': report['tail_hash'],
                              'records': report['quality']['records']}, sort_keys=True)
    with CaptureStore(args.db, readonly=True) as store:
        if store.verify_integrity() != json.loads(anchor.read_text())['tail_hash']:
            raise ValueError('Retained tail anchor mismatch')
    report['manifest']['run']['tail_anchor_verified'] = True
    report['readiness'] = evaluate_readiness(report['manifest'])
    atomic_write_json(args.output, report, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({key: report[key] for key in ('selected_count', 'verified_creations', 'economic_verdict')}))


if __name__ == '__main__':
    main()
