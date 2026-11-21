"""Pre-registered, strategy-free LaunchLab baseline census (PAPER ONLY).

Every index identity first seen after a baseline poll is enrolled while the
window is open, without price, volume, score or quote-currency selection. Each
creation is then observed on a fixed schedule after its creation time. Late,
missing, refused, throttled or interrupted observations are terminal outcomes:
never retried, imputed or dropped. No order, wallet, signature or ledger.

The protocol is frozen in code and in a committed JSON file; the owner's quota
lives in a separate committed authorization that references the protocol hash.
Nothing here runs on import. Network access needs --network and both files.
"""
import argparse
import asyncio
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

import aiohttp

from bot.analyser.artifacts import atomic_write_json
from bot.p3 import campaign as cp
from bot.p3 import collect
from bot.p3.collect import RPC_URL, ReadOnlyPolicyError, _environment_proxy, _record_quote
from bot.p3.evidence import _publish_new, export_capture, verify_bundle
from bot.p3.launchlab import addresses_from_pool
from bot.p3.quotes import RAYDIUM_QUOTE_URL, SOL_MINT, RaydiumQuoteClient
from bot.p3.store import CaptureStore

RPC = 'solana_public_rpc'
QUOTE = 'raydium_trade_api'
INDEX = 'raydium_launch_index'
PROVIDERS = (RPC, QUOTE, INDEX)
_PROVIDER_BY_URL = {RPC_URL: RPC, RAYDIUM_QUOTE_URL: QUOTE, cp.INDEX_URL: INDEX}
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_REVISION = re.compile(r'[0-9a-f]{40}\Z')
CENSUS_SCHEMA = 'p3-launchlab-census-run-v1'
AUTHORIZATION_SCHEMA = 'p3-launchlab-census-authorization-v1'

# Frozen protocol. The committed JSON must equal this plus registered_at_ms;
# any change is a NEW protocol, never an edit of this one.
PROTOCOL_V1 = {
    'schema': 'p3-launchlab-census-protocol-v1',
    'protocol_id': 'launchlab-baseline-census-001',
    'mode': 'paper_only_observation_no_orders_no_wallet_no_signing_no_ledger',
    'strategy_free': True,
    'universe': {
        'source': 'raydium_launch_mint_index_get_list_sort_new',
        'unit': 'index_identity_mint_with_its_pool',
        'baseline_rule': 'valid_identities_in_first_successful_poll_are_pre_window_never_enrolled',
        'enrollment_rule': 'every_valid_identity_first_seen_after_baseline_while_enrollment_open',
        'late_listing_rule': 'creation_claim_older_than_window_start_minus_grace_is_pre_window',
        'late_listing_grace_ms': 120000,
        'quote_currency_filter': 'none_all_quote_currencies_enrolled',
        'price_volume_score_filter': 'none',
        'identity_conflict_rule': 'same_mint_with_other_pool_recorded_never_enrolled',
        'poll_interval_ms': 15000,
        'max_rows_per_poll': 100,
        'continuity_rule': 'successful_poll_must_overlap_previous_successful_poll_or_return_fewer_than_cap_rows',
        'independent_reference': None,
        'coverage_of_all_launchlab_creations': 'unknown_no_independent_creation_reference',
    },
    'window': {
        'start': 'receipt_time_of_first_successful_baseline_poll',
        'enrollment_closes_at_first_of': [
            'authorized_max_enrollment_duration_elapsed', 'authorized_max_creations_enrolled',
            'request_quota_reservation_insufficient', 'index_quota_exhausted',
            'provider_throttle_stop', 'discovery_unavailable_stop'],
        'observation_end': 'every_scheduled_task_terminal_or_run_deadline',
        'run_deadline_after_enrollment_close_ms': 4080000,
        'authorization_caps': {'max_enrollment_duration_ms': 43200000, 'max_creations': 1000},
    },
    'schedule': {
        'anchor': 'index_creation_claim_ms_if_positive_and_not_after_receipt_else_first_receipt_ms',
        'state_offsets_ms': [60000, 300000, 900000, 3600000],
        'tolerance_ms': [30000, 60000, 90000, 180000],
        'never_dispatch_before_due': True,
        'buy_offset_ms': 60000,
        'buy_sizes_lamports': [500000000, 1000000000],
        'sell_offsets_ms': [300000, 900000, 3600000],
        'sell_quantity': 'expected_output_atomic_of_plus60_provider_buy_quote_of_same_size',
        'slippage_bps': 100,
        'same_due_order': ['state', 'buy', 'sell'],
        'verification_due': 'at_enrollment_deadline_run_deadline',
        'retries': 0,
        'execution': 'sequential_single_dispatcher',
        'ready_task_priority': 'earliest_deadline_first_then_due_kind_creation_size',
        'discovery_priority': 'after_ready_tasks',
    },
    'creation_verification': {
        'signature_limit': 1000, 'max_supported_transaction_version': 1,
        'transaction_selection': 'oldest_successful_signature_in_received_page',
        'commitment': 'confirmed',
    },
    'transport': {
        'methods': {
            'solana_public_rpc': ['getSignaturesForAddress', 'getTransaction',
                                  'getMultipleAccounts', 'getBlockTime'],
            'raydium_trade_api': ['GET compute/swap-base-in'],
            'raydium_launch_index': ['GET get/list sort=new'],
        },
        'anonymous': True, 'redirects': False, 'wire_retries': False,
        'request_timeout_ms': 8000,
        'token_bucket_interval_ms': {'solana_public_rpc': 500, 'raydium_trade_api': 1000,
                                     'raydium_launch_index': 5000},
        'token_bucket_burst': {'solana_public_rpc': 3, 'raydium_trade_api': 1,
                               'raydium_launch_index': 1},
        'reserved_requests_per_creation': {'solana_public_rpc': 14, 'raydium_trade_api': 8},
        'authorization_caps': {'solana_public_rpc': 20000, 'raydium_trade_api': 10000,
                               'raydium_launch_index': 3000},
    },
    'stop_rules': {
        'throttle_http_statuses': [403, 429],
        'backoff_min_ms': 30000, 'retry_after_cap_ms': 600000,
        'enrollment_stop_throttles': 3, 'enrollment_stop_window_ms': 600000,
        'abort_total_throttles': 10,
        'discovery_stop_consecutive_failures': 40,
    },
    'checkpoint': {
        'segment_max_records': 2000, 'segment_max_bytes': 8388608,
        'segment_max_duration_ms': 1800000,
        'export': 'closed_segment_to_portable_bundle_then_separate_anchor_before_next_segment',
        'archive': 'operator_commits_bundles_anchors_and_run_identity_after_run_never_sqlite',
    },
    'resume': {
        'identity': 'same_run_dir_protocol_authorization_and_source_revision_required',
        'interrupted_segment': 'closed_exported_and_anchored_before_new_segment',
        'in_flight_task': 'terminal_interrupted_in_flight_never_retried',
        'expired_tasks': 'terminal_missed_run_interrupted',
        'request_accounting': 'last_persisted_cumulative_plus_one_operation_allowance',
        'interruption': 'open_gap_never_closed',
        'provider_backoff': 'restored_from_journaled_throttle_events',
    },
    'analysis': {
        'population': 'all_enrolled_creations',
        'primary_return': 'plus900_provider_sell_expected_output_lamports_over_plus60_buy_input_lamports_minus_one',
        'primary_buy_input': 'provider_actual_input_if_reported_else_requested',
        'primary_costs': 'gross_excludes_network_priority_and_account_costs',
        'secondary_return': 'local_curve_plus60_counterfactual_buy_quantity_sold_against_observed_plus900_state',
        'secondary_evidence_profile': 'published_metadata_v1',
        'missingness': 'every_enrolled_creation_counted_in_exactly_one_category_per_size',
        'quantiles': ['0', '0.1', '0.25', '0.5', '0.75', '0.9', '1'],
        'quantile_method': 'nearest_rank_on_exact_rationals',
        'histogram_edges': ['-1', '-0.9', '-0.5', '-0.2', '-0.05', '0', '0.05', '0.2',
                            '0.5', '1', '3'],
        'sellable_exit': 'provider_sell_quote_outcome_quoted_by_offset_and_size',
        'denominators': ['all_enrolled', 'plus60_buy_quoted', 'sell_dispatched'],
        'state_change_vs_plus60': 'real_b_and_spot_ratio_vs_plus60_by_offset_unavailable_pairs_counted',
        'death_label': 'none_inferred_only_observable_categories_reported',
        'detection_latency': 'verified_creation_block_time_to_first_local_price_available_at',
        'first_local_price': 'earliest_decodable_pool_reserve_state_or_quoted_provider_buy',
        'decimal_places': 9,
        'economic_verdict': 'not_part_of_census',
    },
    'out_of_scope': ['decide', 'tp_sl', 'position_sizing', 'paper_ledger', 'currency_convention',
                     'thresholds', 'strategy_comparison'],
}

COMPLETENESS = {
    'complete_raw_replay': False,
    'index_original_body': 'not_retained; identity_claim_fields_of_every_row_and_digest',
    'raw_accounts': 'retained_when_response_available_and_evidence_policy_allows',
    'raw_transactions': 'retained_when_fetched_and_evidence_policy_allows',
    'signature_pages': 'retained_up_to_registered_limit_when_evidence_policy_allows',
    'quote_bodies': 'sanitized_provider_response_retained_when_evidence_policy_allows',
    'refused_bodies': 'digest_and_failure_receipt_only',
    'sqlite_journal': 'local_only_never_archived',
    'provider_redistribution_rights': 'not_certified_for_public_or_commercial_distribution',
    'storage_scope': 'private_internal_evidence_of_authorized_public_reads',
}

_KIND_ORDER = {'verify': 0, 'state': 1, 'buy': 2, 'sell': 3}
_TASK_MAX = {'verify': {RPC: 2}, 'state': {RPC: 3}, 'buy': {QUOTE: 1}, 'sell': {QUOTE: 1}}
_ALLOWANCE = {RPC: 3, QUOTE: 1, INDEX: 1}


class CensusPolicyError(ValueError):
    """The run is not covered by the frozen protocol and owner authorization."""


class ProviderBackoffError(ReadOnlyPolicyError):
    pass


def _strict_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_strict_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(map(_strict_equal, left, right))
    return left == right


def sha256_of(value):
    return hashlib.sha256(cp.canonical(value)).hexdigest()


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def validate_protocol(protocol, *, now_ms=None):
    if type(protocol) is not dict or set(protocol) != set(PROTOCOL_V1) | {'registered_at_ms'}:
        raise CensusPolicyError('Unexpected census protocol schema')
    if any(not _strict_equal(protocol[key], value) for key, value in PROTOCOL_V1.items()):
        raise CensusPolicyError('Unsupported census protocol')
    now = collect.now_ms() if now_ms is None else now_ms
    if not _int(protocol['registered_at_ms'], 1, now - 1):
        raise CensusPolicyError('Protocol must be registered before use')
    return sha256_of(protocol)


def validate_authorization(authorization, protocol, *, now_ms=None):
    """Owner quota for one frozen protocol; nulls, spend or signing are refused."""
    protocol_hash = validate_protocol(protocol, now_ms=now_ms)
    keys = {'schema', 'protocol_sha256', 'approved_by', 'approved_at_ms',
            'max_enrollment_duration_ms', 'max_creations', 'request_budgets',
            'spend_authorized', 'subscriptions_authorized', 'wallet_or_signing_authorized',
            'network_scope'}
    if type(authorization) is not dict or set(authorization) != keys:
        raise CensusPolicyError('Unexpected census authorization schema')
    now = collect.now_ms() if now_ms is None else now_ms
    caps = PROTOCOL_V1['window']['authorization_caps']
    budget_caps = PROTOCOL_V1['transport']['authorization_caps']
    budgets = authorization['request_budgets']
    reserve = PROTOCOL_V1['transport']['reserved_requests_per_creation']
    if (authorization['schema'] != AUTHORIZATION_SCHEMA
            or authorization['protocol_sha256'] != protocol_hash
            or type(authorization['approved_by']) is not str
            or not 1 <= len(authorization['approved_by'].strip()) <= 80
            or not _int(authorization['approved_at_ms'], protocol['registered_at_ms'], now - 1)
            or not _int(authorization['max_enrollment_duration_ms'], 60000,
                        caps['max_enrollment_duration_ms'])
            or not _int(authorization['max_creations'], 1, caps['max_creations'])
            or authorization['network_scope'] != 'anonymous_public_reads_listed_in_protocol'):
        raise CensusPolicyError('Census authorization is incomplete or outside the protocol')
    for flag in ('spend_authorized', 'subscriptions_authorized', 'wallet_or_signing_authorized'):
        if authorization[flag] is not False:
            raise CensusPolicyError('Census never authorizes spend, subscriptions, wallets or signing')
    if (type(budgets) is not dict or set(budgets) != set(PROVIDERS)
            or any(not _int(budgets[p], 1, budget_caps[p]) for p in PROVIDERS)):
        raise CensusPolicyError('Request budgets must be explicit positive integers within caps')
    if budgets[INDEX] < 2 or budgets[RPC] < reserve[RPC] or budgets[QUOTE] < reserve[QUOTE]:
        raise CensusPolicyError('Authorized quota cannot observe even one creation')
    return sha256_of(authorization)


def preregistration_sha256(protocol_hash, authorization_hash):
    return sha256_of({'protocol_sha256': protocol_hash, 'authorization_sha256': authorization_hash})


def git_preflight(repo_root, files):
    """Require committed, unmodified pre-registration files and census code."""
    root = Path(repo_root).resolve()

    def git(*args):
        try:
            done = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True,
                                  timeout=30, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise CensusPolicyError('git is required to prove pre-registration') from error
        return done.returncode, done.stdout
    code, head = git('rev-parse', 'HEAD')
    head = head.strip()
    if code != 0 or _REVISION.fullmatch(head) is None:
        raise CensusPolicyError('Pre-registration requires a committed git revision')
    relative = []
    for file in files:
        path = Path(file).resolve()
        if not path.is_relative_to(root):
            raise CensusPolicyError('Pre-registration files must live in the repository')
        relative.append(path.relative_to(root).as_posix())
    for item in relative:
        if git('ls-files', '--error-unmatch', '--', item)[0] != 0:
            raise CensusPolicyError('Pre-registration file is not committed')
    code, status = git('status', '--porcelain', '--', *relative, 'bot/p3')
    if code != 0 or status.strip():
        raise CensusPolicyError('Pre-registration files or census code differ from the commit')
    return head


def _read_json(path, limit=1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise CensusPolicyError('Expected a small regular JSON file')
    return json.loads(path.read_text(encoding='utf-8'))


class _Dispatch:
    """Async context deferring the transport call until the census admits it."""
    def __init__(self, owner, method, url, kwargs):
        self._owner, self._method, self._url, self._kwargs = owner, method, url, kwargs
        self._provider = _PROVIDER_BY_URL[url]
        self._context = None

    async def __aenter__(self):
        self._owner._admit(self._provider)
        transport = self._owner._transport
        call = transport.get if self._method == 'GET' else transport.post
        self._context = call(self._url, **self._kwargs)
        response = await self._context.__aenter__()
        self._owner._observe(self._provider, response)
        return response

    async def __aexit__(self, *exc):
        if self._context is None:
            return False
        return await self._context.__aexit__(*exc)


class _Deferred:
    def __init__(self, owner):
        self._owner = owner

    def get(self, url, **kwargs):
        return _Dispatch(self._owner, 'GET', url, kwargs)

    def post(self, url, **kwargs):
        return _Dispatch(self._owner, 'POST', url, kwargs)


class CensusSession(cp.CampaignSession):
    """Campaign destination/method policy with owner per-provider budgets.

    The 20-request cap of the bounded campaigns is replaced, deliberately and
    only here, by explicit authorized budgets. Each attempt is counted before
    transport. A token bucket bounds rate; the dispatcher waits for tokens
    BEFORE a task so measured request latencies exclude local pacing. 403/429
    starts a provider backoff; no response is ever retried.
    """
    def __init__(self, transport, budgets, *, clock_ms, monotonic_ms, used=None,
                 proxy_resolver=None):
        if set(budgets) != set(PROVIDERS):
            raise CensusPolicyError('Budgets must name every census provider')
        self._transport = transport
        self.session = _Deferred(self)
        self.proxy_resolver = proxy_resolver
        self._deadline_ns = None
        self.budgets = dict(budgets)
        self.used = {provider: 0 for provider in PROVIDERS}
        self.used.update(used or {})
        self.max_requests = sum(self.budgets.values())
        self.requests_used = sum(self.used.values())
        self._clock, self._monotonic = clock_ms, monotonic_ms
        transport_rules = PROTOCOL_V1['transport']
        self._interval = transport_rules['token_bucket_interval_ms']
        self._burst = transport_rules['token_bucket_burst']
        start = monotonic_ms()
        self._tokens = {p: float(self._burst[p]) for p in PROVIDERS}
        self._refilled = {p: start for p in PROVIDERS}
        self._backoff_until = {p: start for p in PROVIDERS}
        self.throttles = []

    def _take(self):
        # Parent validation calls this before dispatch; counting happens in
        # _admit, still strictly before the transport is touched.
        self.check_deadline()

    def _refill(self, provider, now):
        elapsed = max(0, now - self._refilled[provider])
        self._tokens[provider] = min(float(self._burst[provider]),
                                     self._tokens[provider] + elapsed / self._interval[provider])
        self._refilled[provider] = now

    def remaining(self, provider):
        return self.budgets[provider] - self.used[provider]

    def backoff_remaining_ms(self, provider):
        return max(0, self._backoff_until[provider] - self._monotonic())

    def wait_for_tokens_ms(self, provider, need):
        now = self._monotonic()
        self._refill(provider, now)
        missing = need - self._tokens[provider]
        return 0 if missing <= 0 else math.ceil(missing * self._interval[provider])

    def restore_backoff(self, throttles):
        """Re-apply journaled 403/429 backoffs that have not yet elapsed."""
        now, wall = self._monotonic(), self._clock()
        for entry in throttles:
            remaining = entry['observed_at_ms'] + entry['backoff_ms'] - wall
            if remaining > 0:
                provider = entry['provider']
                self._backoff_until[provider] = max(self._backoff_until[provider], now + remaining)

    def _admit(self, provider):
        self.check_deadline()
        now = self._monotonic()
        if now < self._backoff_until[provider]:
            raise ProviderBackoffError('provider_backoff_active')
        if self.used[provider] >= self.budgets[provider]:
            raise ReadOnlyPolicyError('read_only_request_budget_exhausted')
        self._refill(provider, now)
        if self._tokens[provider] < 1:
            raise ReadOnlyPolicyError('local_rate_limit_not_awaited')
        self._tokens[provider] -= 1
        self.used[provider] += 1
        self.requests_used += 1

    def _observe(self, provider, response):
        status = getattr(response, 'status', None)
        rules = PROTOCOL_V1['stop_rules']
        if status not in rules['throttle_http_statuses']:
            return
        headers = getattr(response, 'headers', None) or {}
        raw = headers.get('Retry-After') if hasattr(headers, 'get') else None
        retry = int(raw) if isinstance(raw, str) and raw.isdigit() else None
        backoff = max(rules['backoff_min_ms'],
                      min(rules['retry_after_cap_ms'], (retry or 0) * 1000))
        self._backoff_until[provider] = max(self._backoff_until[provider],
                                            self._monotonic() + backoff)
        self.throttles.append({'provider': provider, 'http_status': status,
                               'retry_after_seconds': retry, 'backoff_ms': backoff,
                               'observed_at_ms': self._clock()})


def _identity(value):
    return cp._address(value)


def census_rows(payload):
    """Identity claims of every received row, in order, without any selection."""
    data = payload.get('data') if type(payload) is dict else None
    rows = data.get('rows') if type(data) is dict else None
    if type(payload) is not dict or payload.get('success') is not True or type(rows) is not list:
        raise ValueError('Invalid index response')
    cap = PROTOCOL_V1['universe']['max_rows_per_poll']
    records, inputs, seen = [], [], set()
    for index, raw in enumerate(rows[:cap]):
        row = raw if type(raw) is dict else {}
        quote = row.get('mintB') if type(row.get('mintB')) is dict else {}
        mint, pool = _identity(row.get('mint')), _identity(row.get('poolId'))
        claim = row.get('createAt')
        record = {
            'index': index, 'mint': mint, 'pool': pool,
            'config_claim': _identity(row.get('configId')),
            'quote_mint_claim': _identity(quote.get('address')),
            'creator_claim': _identity(row.get('creator')),
            'creation_time_claim_ms': claim if type(claim) is int and claim > 0 else None,
            'row_representation_sha256': cp.digest(raw),
        }
        if mint is None or pool is None or mint == SOL_MINT:
            record['row_status'] = 'invalid_identity'
        elif mint in seen:
            record['row_status'] = 'duplicate_in_response'
        else:
            record['row_status'] = 'valid'
            seen.add(mint)
        records.append(record)
        if type(raw) is dict:
            kept = {key: raw[key] for key in ('mint', 'poolId', 'configId', 'creator', 'createAt')
                    if key in raw}
            kept['mintB'] = {'address': quote.get('address')} if type(raw.get('mintB')) is dict else raw.get('mintB')
            inputs.append(kept)
        else:
            inputs.append(raw)
    return records, {'success': True, 'data': {'rows': inputs}}, len(rows)


def task_id(seq, kind, offset=None, size=None):
    return '%05d:%s:%s:%s' % (seq, kind, '-' if offset is None else offset,
                              '-' if size is None else size)


def creation_tasks(seq, anchor_ms, enrolled_at_ms, run_deadline_ms):
    schedule = PROTOCOL_V1['schedule']
    tolerance = dict(zip(schedule['state_offsets_ms'], schedule['tolerance_ms']))
    tasks = [dict(task_id=task_id(seq, 'verify'), seq=seq, kind='verify', offset_ms=None,
                  size_lamports=None, due_at_ms=enrolled_at_ms, deadline_at_ms=run_deadline_ms)]
    for offset in schedule['state_offsets_ms']:
        due = anchor_ms + offset
        tasks.append(dict(task_id=task_id(seq, 'state', offset), seq=seq, kind='state',
                          offset_ms=offset, size_lamports=None, due_at_ms=due,
                          deadline_at_ms=due + tolerance[offset]))
    for size in schedule['buy_sizes_lamports']:
        offset = schedule['buy_offset_ms']
        tasks.append(dict(task_id=task_id(seq, 'buy', offset, size), seq=seq, kind='buy',
                          offset_ms=offset, size_lamports=size, due_at_ms=anchor_ms + offset,
                          deadline_at_ms=anchor_ms + offset + tolerance[offset]))
    for offset in schedule['sell_offsets_ms']:
        for size in schedule['buy_sizes_lamports']:
            tasks.append(dict(task_id=task_id(seq, 'sell', offset, size), seq=seq, kind='sell',
                              offset_ms=offset, size_lamports=size,
                              due_at_ms=anchor_ms + offset,
                              deadline_at_ms=anchor_ms + offset + tolerance[offset]))
    return tasks


def _sort_key(task, ready_at=None):
    # ready_at only differs from due_at after a deferral for backoff/tokens.
    return (task['due_at_ms'] if ready_at is None else ready_at, _KIND_ORDER[task['kind']],
            task['seq'], task['size_lamports'] or 0, task['task_id'])


def load_segments(run_dir, run):
    """Verify every anchored bundle and its segment links; return ordered events."""
    root = Path(run_dir)
    anchors = sorted((root / 'anchors').glob('*.json')) if (root / 'anchors').is_dir() else []
    events, previous_tail = [], None
    for expected, path in enumerate(anchors, 1):
        anchor = _read_json(path)
        if (type(anchor) is not dict or anchor.get('segment') != expected
                or path.name != '%06d.json' % expected or not _HEX64.fullmatch(str(anchor.get('tail_hash')))):
            raise CensusPolicyError('Census anchors are not a contiguous segment sequence')
        bundle = verify_bundle(root / 'bundles' / ('%06d' % expected), expected_tail=anchor['tail_hash'])
        if (bundle['records'] != anchor.get('records')
                or bundle['plan_sha256'] != run['preregistration_sha256']
                or bundle['compressed_sha256'] != anchor.get('compressed_sha256')):
            raise CensusPolicyError('Census bundle does not match its anchor or pre-registration')
        segment = bundle['events']
        opened = segment[0] if segment else None
        if (opened is None or opened['kind'] != 'checkpoint' or opened['outcome'] != 'segment_opened'
                or opened['payload'].get('segment') != expected
                or opened['payload'].get('run_id') != run['run_id']
                or opened['payload'].get('previous_tail_hash') != previous_tail
                or opened['payload'].get('preregistration_sha256') != run['preregistration_sha256']):
            raise CensusPolicyError('Census segment link is broken')
        closed = segment[-1]
        if closed['kind'] != 'checkpoint' or closed['outcome'] != 'segment_closed':
            raise CensusPolicyError('Census segment was not closed before export')
        for event in segment:
            events.append(dict(event, segment=expected))
        previous_tail = anchor['tail_hash']
    return events, previous_tail, len(anchors)


def replay(events):
    """Reconstruct census state from journal events only (resume and analysis)."""
    state = {'started': None, 'universe': {}, 'conflicts': [], 'creations': [], 'started_tasks': {},
             'terminal': {}, 'polls': [], 'enrollment_closed': None, 'throttles': [],
             'cumulative_requests': None, 'complete': None, 'resumes': [],
             'baseline_keys': None, 'last_success_keys': None, 'last_success_count': None,
             'open_discovery_gap': None, 'consecutive_poll_failures': 0, 'segments_opened': 0}
    for event in events:
        if event['kind'] != 'checkpoint':
            continue
        outcome, payload = event['outcome'], event['payload']
        if outcome == 'segment_opened':
            state['segments_opened'] += 1
        elif outcome == 'census_started':
            state['started'] = payload
        elif outcome == 'census_resumed':
            state['resumes'].append(payload)
        elif outcome == 'census_universe_row':
            state['universe'][payload['mint']] = payload
        elif outcome == 'census_identity_conflict':
            state['conflicts'].append(payload)
        elif outcome == 'census_enrolled':
            state['creations'].append(payload)
        elif outcome == 'census_task_started':
            state['started_tasks'][payload['task_id']] = payload
        elif outcome == 'census_task':
            state['terminal'][payload['task_id']] = dict(payload, segment=event['segment'])
            state['cumulative_requests'] = payload['cumulative_requests']
        elif outcome == 'census_poll':
            state['polls'].append(dict(payload, segment=event['segment']))
            state['cumulative_requests'] = payload['cumulative_requests']
            if payload['outcome'] == 'observed':
                state['last_success_keys'] = payload['valid_mints']
                state['last_success_count'] = payload['rows_received']
                state['consecutive_poll_failures'] = 0
                if payload['continuity'] == 'baseline':
                    state['baseline_keys'] = payload['valid_mints']
            else:
                state['consecutive_poll_failures'] += 1
            state['open_discovery_gap'] = payload['open_discovery_gap']
        elif outcome == 'census_enrollment_closed':
            state['enrollment_closed'] = payload
        elif outcome == 'census_throttle':
            state['throttles'].append(payload)
        elif outcome == 'census_complete':
            state['complete'] = payload
    return state


class CensusRun:
    """One census run directory: identity, segments, bundles and anchors."""

    def __init__(self, run_dir, *, transport, run, protocol, authorization, clock_ms=None,
                 monotonic_ms=None, sleep=None, store_clock_ms=None, provenance='live',
                 limits=None, proxy_resolver=None):
        self.root = Path(run_dir)
        self.run, self.protocol, self.authorization = run, protocol, authorization
        self.clock = clock_ms or collect.now_ms
        self.monotonic = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.sleep = sleep or asyncio.sleep
        self.store_clock = store_clock_ms
        self.provenance = provenance
        checkpoint = PROTOCOL_V1['checkpoint']
        # Offline tests may shrink segment limits; the effective values are
        # journaled and the report flags any deviation from the protocol.
        self.limits = dict(limits or {key: checkpoint[key] for key in
                                      ('segment_max_records', 'segment_max_bytes',
                                       'segment_max_duration_ms')})
        self.transport = transport
        self.proxy_resolver = proxy_resolver
        self.session = None
        self.store = None
        self.segment = 0
        self.segment_records = 0
        self.segment_opened_at = None
        self.previous_tail = None
        self.current = None
        self.creations = {}
        self.order = []
        self.heap = []
        self.terminal = set()
        self.universe = {}
        self.enrollment_open = True
        self.close_reason = None
        self.window_start = None
        self.window_end = None
        self.run_deadline = None
        self.next_poll_at = None
        self.poll_seq = 0
        self.last_success_keys = None
        self.last_success_count = None
        self.open_discovery_gap = None
        self.consecutive_poll_failures = 0
        self.throttles_logged = 0
        self.all_throttles = []
        self.export_failures = []

    # -- journal ---------------------------------------------------------
    def append(self, kind, **event):
        identity = self.store.append(kind, provenance=self.provenance, **event)
        self.segment_records += 1
        if self.current is not None:
            self.current.append({'id': identity, 'kind': kind, 'outcome': event.get('outcome'),
                                 'event': event})
        return identity

    def _checkpoint(self, outcome, payload, mint=None):
        return self.append('checkpoint', received_at_ms=self.clock(), outcome=outcome,
                           mint=mint, payload=payload)

    def _gap(self, reason, gap_id=None, *, outcome='open', mint=None, detail=None):
        gap_id = gap_id or str(uuid.uuid4())
        payload = {'gap_id': gap_id}
        if detail is not None:
            payload['detail'] = detail
        self.append('gap', received_at_ms=self.clock(), outcome=outcome, reason=reason,
                    mint=mint, payload=payload)
        return gap_id

    def _open_segment(self):
        self.segment += 1
        (self.root / 'segments').mkdir(parents=True, exist_ok=True)
        path = self.root / 'segments' / ('%06d.sqlite' % self.segment)
        if path.exists():
            raise CensusPolicyError('Refusing to reuse a census segment path')
        self.store = CaptureStore(path, clock_ms=self.store_clock)
        self.segment_records = 0
        self.segment_opened_at = self.clock()
        self._checkpoint('segment_opened', {
            'census_schema': CENSUS_SCHEMA, 'run_id': self.run['run_id'], 'segment': self.segment,
            'previous_tail_hash': self.previous_tail,
            'protocol_sha256': self.run['protocol_sha256'],
            'authorization_sha256': self.run['authorization_sha256'],
            'preregistration_sha256': self.run['preregistration_sha256'],
            'source_revision': self.run['source_revision']})
        for failure in self.export_failures:
            self._gap('segment_export_failed', detail=failure)
        self.export_failures = []

    def _segment_path(self, number):
        return self.root / 'segments' / ('%06d.sqlite' % number)

    def _export(self, number, tail, records):
        destination = self.root / 'bundles' / ('%06d' % number)
        (self.root / 'bundles').mkdir(parents=True, exist_ok=True)
        if destination.exists():
            try:
                manifest = verify_bundle(destination, expected_tail=tail)
            except ValueError:
                # Never erase an interrupted export; keep it beside the new one.
                destination.rename(destination.with_name(destination.name + '.partial-%d' % self.clock()))
                manifest = None
        else:
            manifest = None
        if manifest is None:
            export_capture(self._segment_path(number), destination,
                           run_id='%s-seg%06d' % (self.run['run_id'], number),
                           source_revision=self.run['source_revision'], completeness=COMPLETENESS,
                           plan_sha256=self.run['preregistration_sha256'])
            manifest = verify_bundle(destination, expected_tail=tail)
        if manifest['records'] != records:
            raise CensusPolicyError('Exported census segment record count mismatch')
        anchors = self.root / 'anchors'
        anchors.mkdir(parents=True, exist_ok=True)
        anchor_path = anchors / ('%06d.json' % number)
        anchor = {'segment': number, 'run_id': self.run['run_id'], 'tail_hash': tail,
                  'records': records, 'compressed_sha256': manifest['compressed_sha256'],
                  'uncompressed_sha256': manifest['uncompressed_sha256']}
        if anchor_path.exists():
            if _read_json(anchor_path) != anchor:
                raise CensusPolicyError('Existing census anchor disagrees with its segment')
        else:
            _publish_new(anchor_path, cp.canonical(anchor) + b'\n')
        self.previous_tail = tail

    def _close_segment(self, reason):
        self._checkpoint('segment_closed', {'segment': self.segment, 'reason': reason})
        tail = self.store.verify_integrity()
        records = self.segment_records
        self.store.close()
        self.store = None
        try:
            self._export(self.segment, tail, records)
        except (ValueError, OSError) as error:
            self.previous_tail = tail
            self.export_failures.append({'segment': self.segment,
                                         'error': type(error).__name__})

    def _maybe_rotate(self):
        if (self.segment_records >= self.limits['segment_max_records']
                or self._segment_path(self.segment).stat().st_size >= self.limits['segment_max_bytes']
                or self.clock() - self.segment_opened_at >= self.limits['segment_max_duration_ms']):
            self._close_segment('checkpoint_cadence')
            self._open_segment()

    # -- accounting -------------------------------------------------------
    def _outstanding(self):
        reserved = {provider: 0 for provider in PROVIDERS}
        for _, _, task in self.heap:
            for provider, count in _TASK_MAX[task['kind']].items():
                reserved[provider] += count
        return reserved

    def _reservable(self):
        outstanding = self._outstanding()
        reserve = PROTOCOL_V1['transport']['reserved_requests_per_creation']
        return all(self.session.remaining(p) - outstanding[p] >= reserve[p] for p in reserve)

    def _cumulative(self):
        return dict(self.session.used)

    def _log_throttles(self):
        while self.throttles_logged < len(self.session.throttles):
            entry = self.session.throttles[self.throttles_logged]
            self.throttles_logged += 1
            self.all_throttles.append(entry)
            self._checkpoint('census_throttle', entry)

    # -- lifecycle --------------------------------------------------------
    def _close_enrollment(self, reason):
        if not self.enrollment_open:
            return
        self.enrollment_open = False
        self.close_reason = reason
        self.next_poll_at = None
        self.run_deadline = min(self.run_deadline, self.clock()
                                + PROTOCOL_V1['window']['run_deadline_after_enrollment_close_ms'])
        self._checkpoint('census_enrollment_closed', {
            'reason': reason, 'enrolled': len(self.order), 'closed_at_ms': self.clock(),
            'run_deadline_ms': self.run_deadline})

    def _terminal(self, task, status, *, reason=None, result=None, requests=None,
                  dispatched_at=None, evidence=()):
        payload = {'task_id': task['task_id'], 'seq': task['seq'], 'kind': task['kind'],
                   'offset_ms': task['offset_ms'], 'size_lamports': task['size_lamports'],
                   'due_at_ms': task['due_at_ms'], 'deadline_at_ms': task['deadline_at_ms'],
                   'dispatched_at_ms': dispatched_at, 'finished_at_ms': self.clock(),
                   'status': status, 'reason': reason, 'result': result,
                   'evidence_ids': list(evidence),
                   'requests': requests or {p: 0 for p in PROVIDERS},
                   'cumulative_requests': self._cumulative()}
        self.terminal.add(task['task_id'])
        self._checkpoint('census_task', payload, mint=self.creations[task['seq']]['mint'])

    def _check_stop_rules(self):
        rules = PROTOCOL_V1['stop_rules']
        now = self.clock()
        if len(self.all_throttles) >= rules['abort_total_throttles']:
            self._close_enrollment('provider_throttle_stop')
            while self.heap:
                _, _, task = heapq.heappop(self.heap)
                self._terminal(task, 'aborted', reason='throttle_abort')
            return
        recent = [t for t in self.all_throttles
                  if now - t['observed_at_ms'] <= rules['enrollment_stop_window_ms']]
        if self.enrollment_open and len(recent) >= rules['enrollment_stop_throttles']:
            self._close_enrollment('provider_throttle_stop')
        if (self.enrollment_open and self.consecutive_poll_failures
                >= rules['discovery_stop_consecutive_failures']):
            self._close_enrollment('discovery_unavailable_stop')
        if self.enrollment_open and self.session.remaining(INDEX) < 1:
            self._close_enrollment('index_quota_exhausted')
        if self.enrollment_open and self.window_end is not None and now >= self.window_end:
            self._close_enrollment('authorized_max_enrollment_duration_elapsed')

    # -- discovery and enrollment ---------------------------------------
    async def _poll(self):
        self.poll_seq += 1
        dispatched = self.clock()
        self.next_poll_at = dispatched + PROTOCOL_V1['universe']['poll_interval_ms']
        wait = self.session.wait_for_tokens_ms(INDEX, 1)
        if wait:
            await self.sleep(wait / 1000)
        self.current = []
        payload, received = await cp._discover(self.session, self.append)
        try:
            records, replay_input, total = census_rows(payload)
        except ValueError:
            self.consecutive_poll_failures += 1
            if self.open_discovery_gap is None and self.window_start is not None:
                self.open_discovery_gap = self._gap('discovery_poll_failed_continuity_unknown')
            self._checkpoint('census_poll', {
                'poll_seq': self.poll_seq, 'outcome': 'failed', 'dispatched_at_ms': dispatched,
                'received_at_ms': received, 'rows_received': None, 'valid_mints': None,
                'continuity': 'not_established', 'first_seen': [],
                'open_discovery_gap': self.open_discovery_gap,
                'evidence_ids': [item['id'] for item in self.current],
                'cumulative_requests': self._cumulative()})
            self.current = None
            return
        self.consecutive_poll_failures = 0
        evidence = {'rows': records, 'received_row_count': total,
                    'response_representation_sha256': cp.digest(payload),
                    'index_is_creation_proof': False, 'pagination_verified': False,
                    'irrelevant_metadata_omitted': True, 'poll_seq': self.poll_seq}
        try:
            cp._safe_json(replay_input)
        except ValueError:
            evidence['selection_input_retained'] = False
            self._gap('census_index_input_rejected_by_evidence_policy')
        else:
            evidence.update(selection_input_retained=True, replay_selection_input=replay_input)
        discovery_id = self.append('discovery', received_at_ms=received, outcome='observed',
                                   payload=evidence)
        valid = [r for r in records if r['row_status'] == 'valid']
        keys = [r['mint'] for r in valid]
        cap = PROTOCOL_V1['universe']['max_rows_per_poll']
        first_seen = []
        if self.window_start is None:
            continuity = 'baseline'
            self.window_start = received
            self.window_end = received + self.authorization['max_enrollment_duration_ms']
            self.run_deadline = (self.window_end
                                 + PROTOCOL_V1['window']['run_deadline_after_enrollment_close_ms'])
            for record in valid:
                self._universe(record, 'pre_window_baseline', received, discovery_id)
        else:
            if set(keys) & set(self.last_success_keys or ()) or total < cap:
                continuity = 'established'
                if self.open_discovery_gap is not None:
                    self._gap('discovery_poll_failed_continuity_unknown',
                              self.open_discovery_gap, outcome='closed')
                    self.open_discovery_gap = None
            else:
                continuity = 'overflow_possible'
                if self.open_discovery_gap is None:
                    self.open_discovery_gap = self._gap('discovery_continuity_not_established')
            # Oldest first so a stop rule never favours the newest listings.
            new = [r for r in valid if r['mint'] not in self.universe]
            new.sort(key=lambda r: (r['creation_time_claim_ms'] is None,
                                    r['creation_time_claim_ms'] or 0, -r['index']))
            for record in new:
                first_seen.append(record['mint'])
                self._consider(record, received, discovery_id)
            for record in valid:
                known = self.universe.get(record['mint'])
                if known is not None and known['pool'] != record['pool']:
                    self._checkpoint('census_identity_conflict', {
                        'mint': record['mint'], 'known_pool': known['pool'],
                        'other_pool': record['pool'], 'poll_seq': self.poll_seq})
        self.last_success_keys, self.last_success_count = keys, total
        if total > cap:
            self._gap('census_index_exceeds_retention_cap')
        self._checkpoint('census_poll', {
            'poll_seq': self.poll_seq, 'outcome': 'observed', 'dispatched_at_ms': dispatched,
            'received_at_ms': received, 'rows_received': total, 'valid_mints': keys,
            'continuity': continuity, 'first_seen': first_seen,
            'open_discovery_gap': self.open_discovery_gap,
            'evidence_ids': [item['id'] for item in self.current],
            'cumulative_requests': self._cumulative()})
        self.current = None

    def _universe(self, record, disposition, received, discovery_id, extra=None):
        payload = dict(record, disposition=disposition, first_seen_poll_seq=self.poll_seq,
                       first_seen_received_at_ms=received, first_seen_segment=self.segment,
                       discovery_observation_id=discovery_id, **(extra or {}))
        self.universe[record['mint']] = payload
        self._checkpoint('census_universe_row', payload, mint=record['mint'])

    def _consider(self, record, received, discovery_id):
        claim = record['creation_time_claim_ms']
        grace = PROTOCOL_V1['universe']['late_listing_grace_ms']
        if claim is not None and claim < self.window_start - grace:
            return self._universe(record, 'pre_window_late_listed', received, discovery_id)
        if self.enrollment_open and len(self.order) >= self.authorization['max_creations']:
            self._close_enrollment('authorized_max_creations_enrolled')
        if self.enrollment_open and not self._reservable():
            self._close_enrollment('request_quota_reservation_insufficient')
        if not self.enrollment_open:
            return self._universe(record, 'not_enrolled_after_stop:' + self.close_reason,
                                  received, discovery_id)
        seq = len(self.order) + 1
        if claim is not None and claim <= received:
            anchor, basis = claim, 'index_creation_claim'
        else:
            anchor, basis = received, 'first_receipt_claim_missing_or_after_receipt'
        tasks = creation_tasks(seq, anchor, received, self.run_deadline)
        self._universe(record, 'enrolled', received, discovery_id, {'seq': seq})
        creation = {'seq': seq, 'mint': record['mint'], 'pool': record['pool'],
                    'creator_claim': record['creator_claim'], 'anchor_ms': anchor,
                    'anchor_basis': basis, 'enrolled_at_ms': received, 'addresses': None,
                    'last_slot': None, 'buy_quantity': {}}
        self.creations[seq] = creation
        self.order.append(seq)
        self._checkpoint('census_enrolled', dict(
            {key: creation[key] for key in ('seq', 'mint', 'pool', 'creator_claim', 'anchor_ms',
                                            'anchor_basis', 'enrolled_at_ms')},
            tasks=tasks, poll_seq=self.poll_seq), mint=record['mint'])
        for task in tasks:
            if task['deadline_at_ms'] < received:
                self._terminal(task, 'missed', reason='detected_after_tolerance')
            else:
                heapq.heappush(self.heap, (_sort_key(task), task['task_id'], task))
        if len(self.order) >= self.authorization['max_creations']:
            self._close_enrollment('authorized_max_creations_enrolled')

    # -- observation tasks -------------------------------------------------
    async def _execute(self, task):
        creation = self.creations[task['seq']]
        provider = next(iter(_TASK_MAX[task['kind']]))
        need = _TASK_MAX[task['kind']][provider]
        now = self.clock()
        if now > task['deadline_at_ms']:
            return self._terminal(task, 'missed', reason='dispatch_after_tolerance')
        if task['kind'] == 'sell' and creation['buy_quantity'].get(task['size_lamports']) is None:
            return self._terminal(task, 'not_attempted', reason='no_plus60_buy_quantity')
        backoff = self.session.backoff_remaining_ms(provider)
        wait = max(backoff, self.session.wait_for_tokens_ms(provider, need))
        if wait:
            # Re-queue instead of blocking the single dispatcher; never early.
            if now + wait > task['deadline_at_ms']:
                return self._terminal(task, 'missed', reason='provider_backoff' if backoff
                                      else 'local_rate_limit_backlog')
            heapq.heappush(self.heap, (_sort_key(task, now + wait), task['task_id'], task))
            return None
        if self.session.remaining(provider) < need:
            return self._terminal(task, 'not_attempted', reason='request_quota_exhausted')
        dispatched = self.clock()
        self._checkpoint('census_task_started', dict(task, dispatched_at_ms=dispatched),
                         mint=creation['mint'])
        before = self._cumulative()
        self.current = []
        handler = {'verify': self._verify, 'state': self._state,
                   'buy': self._quote, 'sell': self._quote}[task['kind']]
        result = await handler(task, creation)
        requests = {p: self.session.used[p] - before[p] for p in PROVIDERS}
        evidence, self.current = [item['id'] for item in self.current], None
        self._terminal(task, 'completed', result=result, requests=requests,
                       dispatched_at=dispatched, evidence=evidence)

    def _row(self, creation):
        return {'mint': creation['mint'], 'pool': creation['pool'],
                'creator_claim': creation['creator_claim']}

    async def _verify(self, task, creation):
        rules = PROTOCOL_V1['creation_verification']
        verified = await cp._creation(self.session, self.append, self._row(creation),
                                      signature_limit=rules['signature_limit'],
                                      max_supported_transaction_version=rules['max_supported_transaction_version'])
        result = {'creation_verified': verified}
        matched = [item['event'] for item in self.current
                   if item['kind'] == 'checkpoint' and item['outcome'] == 'creation_matched']
        if verified and matched:
            detail = matched[-1]['payload']
            slots = [item['event'].get('source_slot') for item in self.current
                     if item['kind'] == 'transaction' and item['outcome'] == 'observed'
                     and item['event'].get('signature') == detail['signature']]
            result.update(signature=detail['signature'], creator=detail['creator'],
                          index_creator_matches=detail['index_creator_matches'],
                          creation_block_time_ms=detail['creation_block_time_ms'],
                          creation_slot=slots[-1] if slots else None)
        return result

    async def _state(self, task, creation):
        period = 'census_offset_%d' % task['offset_ms']
        discovered_now = False
        minimum = creation['last_slot']
        if creation['addresses'] is None:
            result, received, request, _ = await collect._rpc(
                self.session, self.append, 'getMultipleAccounts',
                [[creation['pool']], {'encoding': 'base64', 'commitment': 'confirmed'}])
            slot, values = cp._bank(result, 1)
            try:
                self.append('pool_snapshot', received_at_ms=received, mint=creation['mint'],
                            source_slot=slot, request_id=request, outcome='address_discovery',
                            payload={'raw_rpc_result': result, 'period': period})
            except ValueError:
                self.append('pool_snapshot', received_at_ms=received, mint=creation['mint'],
                            outcome='error', reason='unsafe_or_invalid_address_snapshot',
                            payload={'period': period,
                                     'response_representation_sha256': cp.digest(result)})
                return {'state_status': 'address_graph_unavailable',
                        'reason': 'unsafe_or_invalid_address_snapshot'}
            if values is None:
                return {'state_status': 'address_bank_unavailable'}
            if values[0] is None:
                return {'state_status': 'pool_account_absent', 'context_slot': slot}
            try:
                creation['addresses'] = addresses_from_pool(values[0], creation['mint'],
                                                            creation['pool'])
            except (ValueError, TypeError):
                return {'state_status': 'address_graph_unavailable',
                        'reason': 'pool_layout_or_identity_unsupported', 'context_slot': slot}
            discovered_now = True
            minimum = slot if minimum is None else max(minimum, slot)
        snapshot = await cp._snapshot(self.store, self.session, self.append, self._row(creation),
                                      creation['addresses'], minimum or 0, period)
        if snapshot is None:
            return {'state_status': 'bank_unavailable', 'addresses_discovered_now': discovered_now,
                    'addresses': creation['addresses']}
        creation['last_slot'] = snapshot['context_slot']
        return {'state_status': 'observed', 'addresses_discovered_now': discovered_now,
                'addresses': creation['addresses'],
                **{key: snapshot[key] for key in ('context_slot', 'received_at_ms', 'available_at_ms',
                                                  'analysis_at_ms', 'source_time_ms',
                                                  'snapshot_observation_id')}}

    async def _quote(self, task, creation):
        side, size = task['kind'], task['size_lamports']
        request_id = str(uuid.uuid4())
        client = RaydiumQuoteClient(self.session, clock_ms=self.clock)
        if side == 'buy':
            input_mint, output_mint, amount = SOL_MINT, creation['mint'], size
        else:
            input_mint, output_mint = creation['mint'], SOL_MINT
            amount = creation['buy_quantity'][size]
        quote = await cp._quote_with_cancellation_receipt(client, self.append, input_mint,
                                                          output_mint, amount, side, request_id)
        recorded = _record_quote(self.append, quote, side, request_id)
        if side == 'buy' and recorded and quote['outcome'] == 'quoted':
            creation['buy_quantity'][size] = quote['output_amount_atomic']
        return {'quote_side': side, 'request_id': request_id, 'recorded': recorded,
                'outcome': quote['outcome'], 'reason': quote['reason'],
                'http_status': quote['http_status'], 'input_amount_atomic': quote['input_amount_atomic'],
                'actual_input_amount_atomic': quote['actual_input_amount_atomic'],
                'output_amount_atomic': quote['output_amount_atomic'],
                'received_at_ms': quote['received_at_ms']}

    # -- main loop --------------------------------------------------------
    async def _loop(self):
        while True:
            self._check_stop_rules()
            now = self.clock()
            if self.run_deadline is not None and now >= self.run_deadline:
                self._close_enrollment('run_deadline')
                while self.heap:
                    _, _, task = heapq.heappop(self.heap)
                    self._terminal(task, 'missed', reason='run_deadline')
                break
            task_due = self.heap[0][0][0] if self.heap else None
            poll_due = self.next_poll_at if self.enrollment_open else None
            if poll_due is not None and poll_due <= now:
                backoff = self.session.backoff_remaining_ms(INDEX)
                if backoff:
                    self.next_poll_at = poll_due = now + backoff
            if task_due is None and poll_due is None:
                break
            target = min(value for value in (task_due, poll_due) if value is not None)
            if target > now:
                limit = self.run_deadline if self.run_deadline is not None else target
                await self.sleep(max(1, min(target, limit) - now) / 1000)
                continue
            if task_due is not None and task_due <= now:
                await self._execute(self._pop_ready(now))
            else:
                await self._poll()
            self._log_throttles()
            self._maybe_rotate()

    def _pop_ready(self, now):
        # Earliest deadline first among READY tasks: verification (run-deadline
        # bound) never displaces an offset observation that is about to expire.
        ready = [entry for entry in self.heap if entry[0][0] <= now]
        chosen = min(ready, key=lambda entry: (entry[2]['deadline_at_ms'], entry[0]))
        self.heap.remove(chosen)
        heapq.heapify(self.heap)
        return chosen[2]

    async def _finish(self):
        self._log_throttles()
        self._checkpoint('census_complete', {
            'enrolled': len(self.order), 'close_reason': self.close_reason,
            'terminal_tasks': len(self.terminal), 'requests_used': self._cumulative(),
            'request_budgets': dict(self.session.budgets),
            'position_acquired': False, 'real_orders_enabled': False})
        self._close_segment('census_complete')
        return {'run_id': self.run['run_id'], 'enrolled': len(self.order),
                'close_reason': self.close_reason, 'segments': self.segment,
                'requests_used': self._cumulative(), 'export_failures': self.export_failures,
                'real_orders_enabled': False}

    def _initial_horizon(self):
        # Before the baseline exists; replaced by window end + observation tail.
        return (self.authorization['max_enrollment_duration_ms']
                + PROTOCOL_V1['window']['run_deadline_after_enrollment_close_ms']
                + PROTOCOL_V1['universe']['poll_interval_ms'] * 4)

    def _make_session(self, used=None):
        self.session = CensusSession(self.transport, self.authorization['request_budgets'],
                                     clock_ms=self.clock, monotonic_ms=self.monotonic,
                                     used=used, proxy_resolver=self.proxy_resolver)

    async def start(self):
        self._make_session()
        self._open_segment()
        self._checkpoint('census_started', {
            'run': self.run, 'protocol': self.protocol, 'owner_quota_approval': self.authorization,
            'effective_limits': self.limits, 'data_kind': self.provenance})
        self.next_poll_at = self.clock()
        self.run_deadline = self.clock() + self._initial_horizon()
        await self._loop()
        return await self._finish()

    async def resume(self):
        """Close/export the interrupted segment, rebuild state, never retry."""
        # Identity first: nothing in the run directory is touched for another run.
        if read_run(self.root) != self.run:
            raise CensusPolicyError('Resume requires the run identity stored in the run directory')
        segments = sorted((self.root / 'segments').glob('*.sqlite'))
        anchored = len(list((self.root / 'anchors').glob('*.json'))) if (self.root / 'anchors').is_dir() else 0
        if not segments or len(segments) not in (anchored, anchored + 1):
            raise CensusPolicyError('Census run directory is not resumable')
        if [p.name for p in segments] != ['%06d.sqlite' % n for n in range(1, len(segments) + 1)]:
            raise CensusPolicyError('Census segments are not contiguous')
        load_segments(self.root, self.run)  # verify every closed segment first
        if len(segments) == anchored + 1:
            number = len(segments)
            with CaptureStore(segments[-1], clock_ms=self.store_clock) as store:
                events = store.events()
                if not events:
                    raise CensusPolicyError('Interrupted census segment is empty')
                last = events[-1]
                if not (last['kind'] == 'checkpoint' and last['outcome'] == 'segment_closed'):
                    store.append('checkpoint', received_at_ms=self.clock(), outcome='segment_closed',
                                 provenance=self.provenance,
                                 payload={'segment': number, 'reason': 'interrupted_closed_on_resume'})
                tail = store.verify_integrity()
                records = len(store.events())
            self.segment = number
            self._export(number, tail, records)
        events, self.previous_tail, self.segment = load_segments(self.root, self.run)
        state = replay(events)
        if state['complete'] is not None:
            raise CensusPolicyError('Census run is already complete')
        self._restore(state)
        used = {p: (state['cumulative_requests'] or {}).get(p, 0) + _ALLOWANCE[p] for p in PROVIDERS}
        self._make_session(used)
        self.session.restore_backoff(self.all_throttles)
        self._open_segment()
        resumed_at = self.clock()
        in_flight = [tid for tid in state['started_tasks'] if tid not in state['terminal']]
        self._checkpoint('census_resumed', {
            'resume_index': len(state['resumes']) + 1, 'resumed_at_ms': resumed_at,
            'last_available_at_ms': events[-1]['available_at_ms'],
            'assumed_requests_used': used, 'allowance': dict(_ALLOWANCE),
            'in_flight_tasks': in_flight})
        self._gap('run_interrupted', detail={'last_available_at_ms': events[-1]['available_at_ms'],
                                             'resumed_at_ms': resumed_at})
        if self.run_deadline is None:
            # Interrupted before any baseline: a new baseline is taken on resume.
            self.run_deadline = resumed_at + self._initial_horizon()
        pending = []
        for task in self.heap:
            if task['task_id'] in in_flight:
                self._terminal(task, 'interrupted_in_flight', reason='run_interrupted')
            elif task['deadline_at_ms'] < resumed_at:
                self._terminal(task, 'missed', reason='run_interrupted')
            else:
                pending.append((_sort_key(task), task['task_id'], task))
        heapq.heapify(pending)
        self.heap = pending
        if self.enrollment_open:
            self.next_poll_at = resumed_at
        await self._loop()
        return await self._finish()

    def _restore(self, state):
        started = state['started']
        if started is None or started['run'] != self.run:
            raise CensusPolicyError('Census journal does not belong to this run identity')
        self.limits = started['effective_limits']
        self.universe = dict(state['universe'])
        self.window_start = None
        baseline = [p for p in state['polls'] if p['continuity'] == 'baseline']
        if baseline:
            self.window_start = baseline[0]['received_at_ms']
            self.window_end = self.window_start + self.authorization['max_enrollment_duration_ms']
        after_close = PROTOCOL_V1['window']['run_deadline_after_enrollment_close_ms']
        self.run_deadline = None if self.window_end is None else self.window_end + after_close
        closed = state['enrollment_closed']
        if closed is not None:
            self.enrollment_open = False
            self.close_reason = closed['reason']
            self.run_deadline = closed['run_deadline_ms']
        # Skip one number: a poll in flight at the crash may have journaled it.
        self.poll_seq = max([p['poll_seq'] for p in state['polls']] or [0]) + 1
        self.last_success_keys = state['last_success_keys']
        self.last_success_count = state['last_success_count']
        self.open_discovery_gap = state['open_discovery_gap']
        self.consecutive_poll_failures = state['consecutive_poll_failures']
        self.all_throttles = list(state['throttles'])
        for enrolled in state['creations']:
            creation = {key: enrolled[key] for key in ('seq', 'mint', 'pool', 'creator_claim',
                                                       'anchor_ms', 'anchor_basis', 'enrolled_at_ms')}
            creation.update(addresses=None, last_slot=None, buy_quantity={})
            self.creations[creation['seq']] = creation
            self.order.append(creation['seq'])
            for task in enrolled['tasks']:
                terminal = state['terminal'].get(task['task_id'])
                if terminal is None:
                    self.heap.append(task)
                    continue
                self.terminal.add(task['task_id'])
                result = terminal.get('result') or {}
                if task['kind'] == 'state' and result.get('addresses'):
                    creation['addresses'] = result['addresses']
                if task['kind'] == 'state' and type(result.get('context_slot')) is int:
                    creation['last_slot'] = max(creation['last_slot'] or 0, result['context_slot'])
                if (task['kind'] == 'buy' and result.get('recorded')
                        and result.get('outcome') == 'quoted'):
                    creation['buy_quantity'][task['size_lamports']] = result['output_amount_atomic']


def _new_run_identity(protocol_hash, authorization_hash, source_revision, started_at):
    return {'schema': CENSUS_SCHEMA, 'run_id': 'census-' + uuid.uuid4().hex[:16],
            'protocol_sha256': protocol_hash, 'authorization_sha256': authorization_hash,
            'preregistration_sha256': preregistration_sha256(protocol_hash, authorization_hash),
            'source_revision': source_revision, 'created_at_ms': started_at}


def prepare_run_dir(run_dir, run):
    root = Path(run_dir)
    if root.exists() or root.is_symlink():
        raise CensusPolicyError('A new census needs a new run directory')
    root.mkdir(parents=True)
    _publish_new(root / 'run.json', cp.canonical(run) + b'\n')


def read_run(run_dir):
    run = _read_json(Path(run_dir) / 'run.json')
    if type(run) is not dict or run.get('schema') != CENSUS_SCHEMA:
        raise CensusPolicyError('Unexpected census run identity')
    return run


async def _network(command, args, protocol, authorization, run, run_dir):
    async with aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as transport:
        if type(getattr(transport, '_retry_connection', None)) is not bool:
            raise ReadOnlyPolicyError('Unsupported transport retry policy')
        transport._retry_connection = False
        census = CensusRun(run_dir, transport=transport, run=run, protocol=protocol,
                           authorization=authorization, proxy_resolver=_environment_proxy)
        return await (census.start() if command == 'run' else census.resume())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'resume'):
        item = sub.add_parser(name)
        item.add_argument('--protocol', type=Path, required=True)
        item.add_argument('--authorization', type=Path, required=True)
        item.add_argument('--run-dir', type=Path, required=True)
        item.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
        item.add_argument('--network', action='store_true')
    hashes = sub.add_parser('hash')
    hashes.add_argument('--protocol', type=Path, required=True)
    hashes.add_argument('--authorization', type=Path)
    args = parser.parse_args(argv)
    protocol = _read_json(args.protocol)
    protocol_hash = validate_protocol(protocol)
    if args.command == 'hash':
        result = {'protocol_sha256': protocol_hash}
        if args.authorization is not None:
            authorization_hash = validate_authorization(_read_json(args.authorization), protocol)
            result.update(authorization_sha256=authorization_hash,
                          preregistration_sha256=preregistration_sha256(protocol_hash, authorization_hash))
        print(json.dumps(result, sort_keys=True))
        return result
    if not args.network:
        parser.error('Explicit --network is required; no automatic market access')
    authorization = _read_json(args.authorization)
    authorization_hash = validate_authorization(authorization, protocol)
    revision = git_preflight(args.repo, (args.protocol, args.authorization))
    if args.run_dir.resolve().is_relative_to(args.repo.resolve()):
        parser.error('Keep the run directory (and its SQLite segments) outside the repository')
    if args.command == 'run':
        run = _new_run_identity(protocol_hash, authorization_hash, revision, collect.now_ms())
        prepare_run_dir(args.run_dir, run)
    else:
        run = read_run(args.run_dir)
        if (run['protocol_sha256'], run['authorization_sha256'], run['source_revision']) != (
                protocol_hash, authorization_hash, revision):
            raise CensusPolicyError('Resume requires the same protocol, authorization and revision')
    summary = asyncio.run(_network(args.command, args, protocol, authorization, run, args.run_dir))
    print(json.dumps(summary, sort_keys=True))
    return summary


if __name__ == '__main__':
    main()
