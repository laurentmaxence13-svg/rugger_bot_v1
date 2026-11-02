"""Bounded, resumable, read-only collection of LaunchLab pool trade histories.

Only three JSON-RPC read methods are used: ``getSignaturesForAddress``,
``getTransaction`` and ``getAccountInfo``. Every call is charged against an
explicit budget; the collector stops (and keeps what it has) when the budget
is exhausted. Raw ``getTransaction`` results are archived unmodified so every
derived number can be re-audited offline.

The RPC endpoint URL may embed an API key: it is never logged, stored in an
archive or included in exception messages.
"""
import base64
from dataclasses import dataclass, field
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import urllib.error
import urllib.request

from bot.market.launchlab_events import (
    LAUNCHLAB_PROGRAM, EventDecodeError, b58encode, extract_trade_events,
)
from bot.market.pool_timeline import build_timeline

WSOL_MINT = 'So11111111111111111111111111111111111111112'
POOL_DISCRIMINATOR = hashlib.sha256(b'account:PoolState').digest()[:8]
SIGNATURE_PAGE = 1000
ARCHIVE_VERSION = 1
MAX_TX_VERSION = 1   # Solana v1 transactions are live on mainnet (Nov 2026)


class BudgetExhausted(RuntimeError):
    pass


class RpcError(RuntimeError):
    pass


@dataclass
class Budget:
    max_calls: int
    used: int = 0

    def charge(self):
        if self.used >= self.max_calls:
            raise BudgetExhausted(f'rpc_budget_exhausted:{self.max_calls}')
        self.used += 1


class JsonRpc:
    """Minimal HTTP JSON-RPC client with pacing, 429 back-off and a budget."""

    def __init__(self, url, budget, *, min_interval=0.12, timeout=30, max_retries=4,
                 sleep=time.sleep, clock=time.monotonic, opener=urllib.request.urlopen):
        self._url = url
        self.budget = budget
        self._min_interval = min_interval
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep, self._clock, self._open = sleep, clock, opener
        self._last = None

    def __repr__(self):
        return f'JsonRpc(budget={self.budget.used}/{self.budget.max_calls})'

    def call(self, method, params):
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
        for attempt in range(self._max_retries + 1):
            self.budget.charge()
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            request = urllib.request.Request(self._url, body, {'Content-Type': 'application/json'})
            try:
                with self._open(request, timeout=self._timeout) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < self._max_retries:
                    self._sleep(min(30.0, 2.0 * 2 ** attempt))
                    continue
                raise RpcError(f'{method}:http_{exc.code}') from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                if attempt < self._max_retries:
                    self._sleep(min(30.0, 1.0 * 2 ** attempt))
                    continue
                raise RpcError(f'{method}:{type(exc).__name__}') from None
            if 'error' in payload:
                code = payload['error'].get('code') if isinstance(payload['error'], dict) else None
                if code in (-32005, 429) and attempt < self._max_retries:
                    self._sleep(min(30.0, 2.0 * 2 ** attempt))
                    continue
                raise RpcError(f'{method}:rpc_error_{code}')
            return payload.get('result')
        raise RpcError(f'{method}:retries_exhausted')


def decode_pool_account(data):
    """Minimal LaunchLab PoolState fields needed to classify a pool."""
    if len(data) < 429 or data[:8] != POOL_DISCRIMINATOR:
        raise EventDecodeError('not_a_launchlab_pool_account')

    def key(offset):
        return b58encode(data[offset:offset + 32])

    return {
        'status': data[17], 'decimals_base': data[18], 'decimals_quote': data[19],
        'migrate_type': data[20], 'supply': struct.unpack_from('<Q', data, 21)[0],
        'mint_base': key(205), 'mint_quote': key(237), 'creator': key(333),
    }


def fetch_pool_account(rpc, pool):
    result = rpc.call('getAccountInfo', [pool, {'encoding': 'base64', 'commitment': 'finalized'}])
    value = (result or {}).get('value')
    if not value or value.get('owner') != LAUNCHLAB_PROGRAM:
        raise EventDecodeError('pool_account_missing_or_foreign_owner')
    return decode_pool_account(base64.b64decode(value['data'][0]))


def fetch_signatures(rpc, address, *, max_pages, known_newest=None):
    """All signatures of ``address`` newest-first, stopping at ``known_newest``.

    Returns (signatures, reached_origin). ``reached_origin`` is True only when
    the listing was exhausted, i.e. the address's full history was listed.
    """
    out, before = [], None
    for _ in range(max_pages):
        options = {'limit': SIGNATURE_PAGE, 'commitment': 'finalized'}
        if before:
            options['before'] = before
        page = rpc.call('getSignaturesForAddress', [address, options]) or []
        for row in page:
            if row['signature'] == known_newest:
                return out, False
            out.append(row)
        if len(page) < SIGNATURE_PAGE:
            return out, True
        before = page[-1]['signature']
    return out, False


@dataclass
class PoolArchive:
    pool: str
    account: dict = None
    signatures: list = field(default_factory=list)       # newest first
    signatures_complete: bool = False
    transactions: dict = field(default_factory=dict)     # signature -> raw result

    def to_json(self):
        return {'version': ARCHIVE_VERSION, 'pool': self.pool, 'account': self.account,
                'signatures': self.signatures, 'signatures_complete': self.signatures_complete,
                'transactions': self.transactions}

    @classmethod
    def from_json(cls, data):
        if data.get('version') != ARCHIVE_VERSION:
            raise ValueError('unsupported_archive_version')
        return cls(data['pool'], data.get('account'), data.get('signatures') or [],
                   bool(data.get('signatures_complete')), data.get('transactions') or {})


def archive_path(directory, pool):
    return Path(directory) / f'{pool}.json.gz'


def load_archive(directory, pool):
    path = archive_path(directory, pool)
    if not path.exists():
        return PoolArchive(pool)
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        return PoolArchive.from_json(json.load(handle))


def save_archive(directory, archive):
    path = archive_path(directory, archive.pool)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8') as handle:
        json.dump(archive.to_json(), handle, separators=(',', ':'), sort_keys=True)
    os.replace(temporary, path)


def collect_pool(rpc, pool, directory, *, max_signature_pages=20):
    """Extend the pool's archive as far as the budget allows; always saves."""
    archive = load_archive(directory, pool)
    try:
        if archive.account is None:
            archive.account = fetch_pool_account(rpc, pool)
        newest = archive.signatures[0]['signature'] if archive.signatures else None
        rows, reached = fetch_signatures(rpc, pool, max_pages=max_signature_pages,
                                         known_newest=newest)
        if newest is None:
            archive.signatures, archive.signatures_complete = rows, reached
        else:
            archive.signatures = rows + archive.signatures
        for row in reversed(archive.signatures):                   # oldest first
            if row.get('err') is not None or row['signature'] in archive.transactions:
                continue
            result = rpc.call('getTransaction', [row['signature'], {
                'encoding': 'json', 'maxSupportedTransactionVersion': MAX_TX_VERSION,
                'commitment': 'finalized'}])
            if result is None:
                continue                                           # not yet available; retry later
            archive.transactions[row['signature']] = result
    finally:
        save_archive(directory, archive)
    return archive


def summarize(archive):
    """Timeline and data-quality summary of an archive (no network)."""
    events, undecodable = [], []
    for signature, result in archive.transactions.items():
        try:
            events.extend(e for e in extract_trade_events(result) if e.pool == archive.pool)
        except EventDecodeError as exc:
            undecodable.append((signature, str(exc)))
    timeline = build_timeline(archive.pool, events)
    successful = [r for r in archive.signatures if r.get('err') is None]
    missing = [r['signature'] for r in successful if r['signature'] not in archive.transactions]
    account = archive.account or {}
    times = [e.block_time for e in timeline.events if e.block_time is not None]
    return {
        'pool': archive.pool,
        'quote_is_sol': account.get('mint_quote') == WSOL_MINT,
        'mint_base': account.get('mint_base'), 'creator': account.get('creator'),
        'status_now': account.get('status'),
        'signatures': len(archive.signatures), 'signatures_complete': archive.signatures_complete,
        'transactions_missing': len(missing), 'undecodable': len(undecodable),
        'trades': len(timeline.events), 'gaps': [g.reason for g in timeline.gaps],
        'rejected': len(timeline.rejected),
        'complete': (archive.signatures_complete and not missing and not undecodable
                     and timeline.complete),
        'first_block_time': min(times) if times else None,
        'last_block_time': max(times) if times else None,
        'max_progress_ppm': max((e.state_after().progress_ppm for e in timeline.events), default=0),
    }, timeline
