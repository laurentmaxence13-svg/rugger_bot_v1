"""Strictly read-only, bounded 24 h observer for Raydium LaunchLab + CPMM.

Safety contract (enforced by code and by ``tests/test_observer24h.py``):

* only the RPC methods in ``ALLOWED_METHODS`` (getSignaturesForAddress,
  getTransaction) can be issued (fail-closed);
* no signing, no transaction submission, no import from ``bot.live``;
* the RPC URL (which may embed an API key) is read from an environment
  variable by the CLI, is never stored, logged, or put in an exception;
* hard wall-clock limit (<= 24 h) measured from the *first* start (kept across
  restarts, so a restart can never extend the window) and a persistent request
  quota (kept across restarts); both stop the run, never relax;
* the quota is charged for EVERY HTTP attempt (429 / timeout retries included)
  and persisted BEFORE the attempt, so a crash can only over-count;
* signature enumeration (paged with ``before``/``until``) and transaction
  processing are separate durable steps: signatures are stored in ``pending``
  in the same SQLite transaction as the enumeration cursor, and each processed
  transaction (events + migrations + ``seen`` + pending removal) is one SQLite
  transaction, so a crash can neither lose nor duplicate an event; re-reading
  the same transaction is idempotent on (signature, slot, event_index, pool, kind);
* a transaction that stays unavailable is retried a bounded number of times then
  dead-lettered with an explicit gap; no data is ever invented;
* unknown values stay ``None`` (slippage is never defaulted to 0);
* a LaunchLab->CPMM migration link is NEVER reported ``proven`` by this module:
  the create/migrate/CPMM-initialize discriminators and account layouts are not
  confirmed on mainnet (``DISCRIMINATORS_CONFIRMED = False``), so every such
  row is ``unproven`` with its evidence recorded.

Discriminators of non-trade instructions are Anchor ``sha256("global:<name>")``
values computed here and are NOT yet confirmed against real mainnet
transactions: such events carry ``decoded=False`` and only program, accounts and
a payload hash. This is a documented limitation (see docs/OBSERVER24H.md).
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from bot.market.collector import Budget, JsonRpc, RpcError
from bot.market.launchlab_events import (
    LAUNCHLAB_PROGRAM, EventDecodeError, b58decode, extract_trade_events, _account_keys,
)

CPMM_PROGRAM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
ALLOWED_METHODS = frozenset({'getSignaturesForAddress', 'getTransaction'})
MAX_DURATION_SECONDS = 24 * 3600
SCHEMA_VERSION = 2
MAX_TX_VERSION = 1   # same value as collector.py; NOT demonstrated against the target RPC
PAGE = 1000
MAX_ENUM_PAGES_PER_POLL = 3
MAX_TX_ATTEMPTS = 3          # getTransaction -> None: tries before dead-letter
DISCRIMINATORS_CONFIRMED = False   # B11: no mainnet proof for create/migrate/CPMM-init
WATCHED = (('launchlab', LAUNCHLAB_PROGRAM), ('cpmm', CPMM_PROGRAM))

_disc = lambda name: hashlib.sha256(f'global:{name}'.encode()).digest()[:8]
LAUNCHLAB_CREATE_DISCS = {_disc('initialize'), _disc('initialize_v2')}
LAUNCHLAB_MIGRATE_DISCS = {_disc('migrate_to_cpswap'), _disc('migrate_to_amm')}
CPMM_INIT_DISCS = {_disc('initialize')}

_SECRET_RE = re.compile(r'(api[-_]?key=)[^&\s"\']+|https?://[^\s"\']+', re.I)


def redact(text):
    """Remove URLs and api-key query values from any text before it is logged."""
    return _SECRET_RE.sub(lambda m: (m.group(1) + '<redacted>') if m.group(1) else '<url>', str(text))


class QuotaExhausted(RuntimeError):
    pass


class DisallowedMethod(RuntimeError):
    pass


class AllowlistRpc:
    """Wraps any ``call(method, params)`` client; refuses methods off the allowlist."""

    def __init__(self, inner):
        self._inner = inner

    def call(self, method, params):
        if method not in ALLOWED_METHODS:
            raise DisallowedMethod(f'rpc_method_not_allowed:{method}')
        return self._inner.call(method, params)


@dataclass(frozen=True)
class ObserverConfig:
    db_path: str
    max_duration_seconds: int = MAX_DURATION_SECONDS
    max_requests_total: int = 20000        # persistent across restarts (free-tier guard)
    max_requests_per_poll: int = 200
    poll_interval_seconds: float = 20.0    # see coverage_plan(): 2 s cannot last 24 h
    max_consecutive_failures: int = 8
    backoff_base_seconds: float = 1.0
    backoff_cap_seconds: float = 60.0
    journal_path: str = None
    anchor_without_backfill: bool = True   # False only for fixture replay

    def __post_init__(self):
        if not 0 < self.max_duration_seconds <= MAX_DURATION_SECONDS:
            raise ValueError('max_duration_seconds_must_be_in_(0,86400]')
        if self.max_requests_total <= 0 or self.max_requests_per_poll <= 0:
            raise ValueError('request_limits_must_be_positive')
        if not math.isfinite(self.poll_interval_seconds) or self.poll_interval_seconds < 0:
            raise ValueError('poll_interval_must_be_finite_and_non_negative')


def coverage_plan(cfg, programs=len(WATCHED)):
    """Pure cost model: can the cadence + quota plausibly cover the whole window?

    Fixed cost = one getSignaturesForAddress head request per program per poll.
    Everything else (extra enumeration pages, getTransaction, retry attempts) shares
    the remaining pool. The real provider credit quota is UNKNOWN to this code and is
    deliberately not modelled: ``max_requests_total`` must be set by the owner.
    """
    interval = max(cfg.poll_interval_seconds, 1e-9)
    polls = int(cfg.max_duration_seconds // interval)
    head = polls * programs
    pool = cfg.max_requests_total - head
    hours = cfg.max_duration_seconds / 3600.0
    return {'polls': polls, 'head_requests': head, 'shared_pool_requests': max(pool, 0),
            'shared_pool_per_hour': round(max(pool, 0) / hours, 1),
            'covers_window': head < cfg.max_requests_total,
            'hours_until_quota_if_idle': round(cfg.max_requests_total / (programs / interval) / 3600.0, 2)}


def check_coverage(cfg, min_shared_fraction=0.5):
    """Refuse cadences that burn more than (1 - min_shared_fraction) of the quota idle."""
    plan = coverage_plan(cfg)
    if plan['head_requests'] > cfg.max_requests_total * (1 - min_shared_fraction):
        raise ValueError(
            f"cadence_exceeds_quota:idle_head_requests={plan['head_requests']}"
            f"_of_total={cfg.max_requests_total}")
    return plan


SCHEMA = '''
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  signature TEXT NOT NULL, slot INTEGER NOT NULL, event_index INTEGER NOT NULL,
  pool TEXT NOT NULL, kind TEXT NOT NULL, program TEXT NOT NULL,
  recv_utc TEXT NOT NULL, chain_time INTEGER, causality TEXT NOT NULL,
  decoded INTEGER NOT NULL, slippage_bps REAL, slippage_status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(signature, slot, event_index, pool, kind));
CREATE TABLE IF NOT EXISTS gaps(
  id INTEGER PRIMARY KEY AUTOINCREMENT, recv_utc TEXT NOT NULL, address TEXT NOT NULL,
  reason TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS migrations(
  signature TEXT NOT NULL, instruction_index TEXT NOT NULL, launchlab_pool TEXT NOT NULL,
  cpmm_pool TEXT, slot INTEGER NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL,
  PRIMARY KEY(signature, instruction_index, launchlab_pool));
CREATE TABLE IF NOT EXISTS pending(
  signature TEXT PRIMARY KEY, address TEXT NOT NULL, slot INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS seen(signature TEXT PRIMARY KEY, outcome TEXT NOT NULL);
'''


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _parse_utc(text):
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


class Journal:
    """Append-only JSON-lines log. Every field is redacted; never holds a URL or key."""

    def __init__(self, path):
        self._path = path

    def write(self, event, **fields):
        if not self._path:
            return
        row = {'t': _utc(datetime.now(timezone.utc)), 'event': event}
        row.update({k: redact(v) if isinstance(v, str) else v for k, v in fields.items()})
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())


def _decode_instruction_events(result, signature, slot, recv, chain_time, causality):
    """Non-trade LaunchLab/CPMM instructions -> normalised rows + migration candidates."""
    meta = result.get('meta') or {}
    if meta.get('err') is not None:
        return [], []
    keys = _account_keys(result)
    message = result['transaction']['message']
    instructions = [(f'o{n}', ix) for n, ix in enumerate(message.get('instructions') or [])]
    for group in meta.get('innerInstructions') or []:
        for n, ix in enumerate(group.get('instructions') or []):
            instructions.append((f"i{group.get('index')}.{n}", ix))
    found = {'create': [], 'migrate': [], 'cpmm_init': []}
    for ix_key, ix in instructions:
        index = ix.get('programIdIndex')
        program = ix.get('programId')
        if program is None and isinstance(index, int) and 0 <= index < len(keys):
            program = keys[index]
        if program not in (LAUNCHLAB_PROGRAM, CPMM_PROGRAM):
            continue
        try:
            data = b58decode(ix.get('data', ''))
        except EventDecodeError:
            continue
        disc = data[:8]
        accounts = [keys[i] for i in ix.get('accounts', []) if isinstance(i, int) and i < len(keys)]
        row = {'program': program, 'accounts': accounts, 'ix': ix_key,
               'discriminator_status': 'unconfirmed',
               'payload_sha256': hashlib.sha256(data).hexdigest()}
        if program == LAUNCHLAB_PROGRAM and disc in LAUNCHLAB_CREATE_DISCS:
            found['create'].append(row)
        elif program == LAUNCHLAB_PROGRAM and disc in LAUNCHLAB_MIGRATE_DISCS:
            found['migrate'].append(row)
        elif program == CPMM_PROGRAM and disc in CPMM_INIT_DISCS:
            found['cpmm_init'].append(row)
    events, migrations = [], []

    def add(kind, idx, pool, row):
        events.append({'signature': signature, 'slot': slot, 'event_index': idx, 'pool': pool,
                       'kind': kind, 'program': row['program'], 'recv_utc': recv,
                       'chain_time': chain_time, 'causality': causality, 'decoded': 0,
                       'slippage_bps': None, 'slippage_status': 'unknown',
                       'payload_json': json.dumps(row, sort_keys=True)})

    for i, row in enumerate(found['create']):
        # pool account position inside initialize is unverified: pool id left unknown
        add('launchlab_create', i, 'unknown', row)
    for i, row in enumerate(found['cpmm_init']):
        add('cpmm_init', i, 'unknown', row)
    for i, row in enumerate(found['migrate']):
        add('launchlab_migrate', i, 'unknown', row)
    for row in found['migrate']:
        # No LaunchLab/CPMM pool id is claimed (layouts unconfirmed on mainnet) => the link is
        # never 'proven'. The key includes the instruction position so several migrate
        # instructions of one transaction cannot overwrite each other.
        evidence = ('cpmm_init_same_tx_ids_unconfirmed' if found['cpmm_init']
                    else 'no_cpmm_init_in_same_tx')
        migrations.append({'signature': signature, 'instruction_index': row['ix'],
                           'launchlab_pool': 'unknown', 'cpmm_pool': None, 'slot': slot,
                           'status': 'unproven', 'evidence': evidence})
    return events, migrations


def normalise_transaction(result, recv_utc):
    """Return (events, migrations) for one raw getTransaction result. Pure function."""
    if not isinstance(result, dict) or 'transaction' not in result:
        raise EventDecodeError('not_a_transaction_result')
    signature = result['transaction']['signatures'][0]
    slot = result['slot']
    chain_time = result.get('blockTime')
    if chain_time is None:
        causality = 'chain_time_unknown'
    elif _parse_utc(recv_utc).timestamp() + 1 < chain_time:
        causality = 'violation_recv_before_chain'
    else:
        causality = 'ok'
    events = []
    try:
        for t in extract_trade_events(result):
            events.append({
                'signature': signature, 'slot': slot, 'event_index': t.event_index,
                'pool': t.pool, 'kind': f'launchlab_trade_{t.side.lower()}',
                'program': LAUNCHLAB_PROGRAM, 'recv_utc': recv_utc, 'chain_time': chain_time,
                'causality': causality, 'decoded': 1,
                'slippage_bps': None, 'slippage_status': 'unknown',
                'payload_json': json.dumps({
                    'amount_in': t.amount_in, 'amount_out': t.amount_out,
                    'total_fee': t.total_fee, 'pool_status': t.pool_status,
                    'real_base_after': t.real_base_after, 'real_quote_after': t.real_quote_after,
                    'violations': list(t.violations)}, sort_keys=True)})
    except EventDecodeError:
        raise
    more, migrations = _decode_instruction_events(result, signature, slot, recv_utc,
                                                  chain_time, causality)
    return events + more, migrations


class PersistentBudget:
    """Durable per-attempt request budget.

    ``JsonRpc.call`` invokes ``charge()`` before EVERY HTTP attempt (first try and each
    429/timeout retry), so the persisted counter equals the number of attempts started.
    The counter is written before the attempt: a crash can over-count, never under-count,
    and it is never reset by a restart.
    """

    def __init__(self, observer, max_calls):
        self._obs, self.max_calls = observer, max_calls

    @property
    def used(self):
        return self._obs.requests_used()

    def charge(self):
        o = self._obs
        if o.requests_used() >= self.max_calls:
            raise QuotaExhausted('quota_total_exhausted')
        if o._poll_used >= o.cfg.max_requests_per_poll:
            raise QuotaExhausted('quota_per_poll_exhausted')
        o._set('requests_total', o.requests_used() + 1)
        o._poll_used += 1


class Observer:
    def __init__(self, config, rpc, *, clock=lambda: datetime.now(timezone.utc),
                 sleep=time.sleep, stop=lambda: False):
        self.cfg = config
        self.rpc = AllowlistRpc(rpc)
        self._clock, self._sleep, self._stop = clock, sleep, stop
        self._poll_used = 0
        self.budget = PersistentBudget(self, config.max_requests_total)
        # A real HTTP client charges per attempt through its ``budget``; a client without one
        # (fixture / fake) is charged once per call.
        self._rpc_charges_attempts = hasattr(rpc, 'budget')
        if self._rpc_charges_attempts:
            rpc.budget = self.budget
        self.journal = Journal(config.journal_path)
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(config.db_path, isolation_level=None)
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('PRAGMA synchronous=FULL')
        self.con.executescript(SCHEMA)

    def close(self):
        self.con.close()

    # -- persistent state -------------------------------------------------------
    def _get(self, key, default=None):
        row = self.con.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def _set(self, key, value):
        self.con.execute('INSERT OR REPLACE INTO state(key,value) VALUES(?,?)', (key, str(value)))

    def _del(self, key):
        self.con.execute('DELETE FROM state WHERE key=?', (key,))

    def requests_used(self):
        return int(self._get('requests_total', 0))

    def _gap(self, address, reason, detail=''):
        self.con.execute('INSERT INTO gaps(recv_utc,address,reason,detail) VALUES(?,?,?,?)',
                         (_utc(self._clock()), address, reason, redact(detail)))
        self.journal.write('gap', address=address, reason=reason, detail=detail)

    def _atomic(self, work):
        """Run ``work`` inside ONE SQLite transaction (all or nothing)."""
        self.con.execute('BEGIN IMMEDIATE')
        try:
            work()
            self.con.execute('COMMIT')
        except BaseException:
            try:
                self.con.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise

    def _call(self, method, params):
        if not self._rpc_charges_attempts:
            self.budget.charge()
        return self.rpc.call(method, params)

    # -- lifecycle ----------------------------------------------------------------
    def start(self):
        version = self._get('schema_version')
        if version is not None and version != str(SCHEMA_VERSION):
            raise ValueError(f'observer_db_schema_mismatch:{version}')
        if self._get('start_utc') is None:
            now = self._clock()
            self._set('start_utc', _utc(now))
            self._set('deadline_utc', _utc(now + timedelta(seconds=self.cfg.max_duration_seconds)))
            self._set('schema_version', SCHEMA_VERSION)
            self.journal.write('start', start_utc=self._get('start_utc'))
        else:
            self.journal.write('resume', start_utc=self._get('start_utc'))

    def expired(self):
        return self._clock() >= _parse_utc(self._get('deadline_utc'))

    def pending_count(self):
        return self.con.execute('SELECT COUNT(*) FROM pending').fetchone()[0]

    def run(self):
        """Poll until deadline, stop request, quota exhaustion or persistent outage."""
        self.start()
        failures = 0
        reason = 'running'
        while True:
            if self._stop():
                reason = 'stopped_by_request'
                break
            if self.expired():
                reason = 'deadline_reached'
                break
            try:
                self.poll_once()
                failures = 0
            except QuotaExhausted:
                reason = 'quota_exhausted'
                break
            except RpcError as exc:
                failures += 1
                self._gap('*', 'rpc_unavailable', str(exc))
                if failures >= self.cfg.max_consecutive_failures:
                    reason = 'network_unavailable'
                    break
                self._sleep(min(self.cfg.backoff_cap_seconds,
                                self.cfg.backoff_base_seconds * 2 ** (failures - 1)))
                continue
            self._sleep(self.cfg.poll_interval_seconds)
        backlog = self.pending_count()
        if backlog:
            self._gap('*', 'backlog_unprocessed_at_stop', f'{backlog}_signatures_pending')
        self._set('final_reason', reason)
        self.journal.write('stop', reason=reason, requests=self.requests_used(), pending=backlog)
        return reason

    # -- one poll -----------------------------------------------------------------
    def poll_once(self):
        """Enumerate new signatures (durably), then fetch transactions round-robin.

        Programs are visited in a rotating order so a LaunchLab backlog cannot starve CPMM.
        Exhausting the per-poll budget ends the poll quietly; the total budget raises.
        """
        self._poll_used = 0
        n = len(WATCHED)
        offset = int(self._get('rr', 0)) % n
        self._set('rr', (offset + 1) % n)
        order = WATCHED[offset:] + WATCHED[:offset]
        try:
            for _, address in order:
                for _ in range(MAX_ENUM_PAGES_PER_POLL):
                    if not self._enumerate(address):
                        break
            tried = set()
            progressed = True
            while progressed:
                progressed = False
                for _, address in order:
                    row = self.con.execute(
                        'SELECT signature FROM pending WHERE address=? ORDER BY attempts, slot, '
                        'signature', (address,)).fetchall()
                    signature = next((r[0] for r in row if r[0] not in tried), None)
                    if signature is None:
                        continue
                    tried.add(signature)
                    progressed = True
                    self._process(address, signature)
        except QuotaExhausted as exc:
            if str(exc) == 'quota_total_exhausted':
                raise

    def _enumerate(self, address):
        """One page of signature discovery. Returns True while older pages remain.

        ``cursor`` (newest signature fully ENUMERATED) only moves when the whole range
        between the previous cursor and the newest signature has been paged through, so a
        busy program (> PAGE signatures per interval) is never silently skipped.
        """
        cursor = self._get(f'cursor:{address}')
        before = self._get(f'enum_before:{address}')
        newest = self._get(f'enum_newest:{address}')
        anchoring = cursor is None and self.cfg.anchor_without_backfill
        options = {'limit': 1 if anchoring else PAGE, 'commitment': 'finalized'}
        if cursor:
            options['until'] = cursor
        if before:
            options['before'] = before
        rows = self._call('getSignaturesForAddress', [address, options]) or []
        if anchoring:
            if rows:
                def anchor():
                    self._set(f'cursor:{address}', rows[0]['signature'])
                    self._gap(address, 'start_anchor_no_backfill', rows[0]['signature'])
                self._atomic(anchor)
            return False
        full = len(rows) >= PAGE
        top = newest or (rows[0]['signature'] if rows else None)

        def commit():
            for r in rows:
                if r.get('err') is not None:
                    continue
                if self.con.execute('SELECT 1 FROM seen WHERE signature=?',
                                    (r['signature'],)).fetchone():
                    continue
                self.con.execute('INSERT OR IGNORE INTO pending(signature,address,slot) '
                                 'VALUES(?,?,?)', (r['signature'], address, r.get('slot') or 0))
            if full:
                self._set(f'enum_newest:{address}', top)
                self._set(f'enum_before:{address}', rows[-1]['signature'])
            else:
                if top:
                    self._set(f'cursor:{address}', top)
                self._del(f'enum_newest:{address}')
                self._del(f'enum_before:{address}')
        self._atomic(commit)
        return full

    def _process(self, address, signature):
        result = self._call('getTransaction', [signature, {
            'encoding': 'json', 'maxSupportedTransactionVersion': MAX_TX_VERSION,
            'commitment': 'finalized'}])
        if result is None:
            attempts = self.con.execute('SELECT attempts FROM pending WHERE signature=?',
                                        (signature,)).fetchone()[0] + 1

            def unavailable():
                if attempts >= MAX_TX_ATTEMPTS:
                    self.con.execute('DELETE FROM pending WHERE signature=?', (signature,))
                    self.con.execute('INSERT OR REPLACE INTO seen VALUES(?,?)',
                                     (signature, 'dead_letter'))
                    self._gap(address, 'transaction_unavailable_dead_letter',
                              f'{signature}:attempts={attempts}')
                else:
                    self.con.execute('UPDATE pending SET attempts=? WHERE signature=?',
                                     (attempts, signature))
                    self._gap(address, 'transaction_unavailable',
                              f'{signature}:attempt={attempts}')
            self._atomic(unavailable)
            return
        self._store(address, signature, result)

    def _store(self, address, signature, result):
        recv = _utc(self._clock())
        try:
            events, migrations = normalise_transaction(result, recv)
            outcome, undecodable = 'stored', None
        except (EventDecodeError, KeyError, TypeError, IndexError) as exc:
            events, migrations = [], []
            outcome, undecodable = 'undecodable', type(exc).__name__

        def commit():
            for e in events:
                self.con.execute(
                    'INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (e['signature'], e['slot'], e['event_index'], e['pool'], e['kind'],
                     e['program'], e['recv_utc'], e['chain_time'], e['causality'], e['decoded'],
                     e['slippage_bps'], e['slippage_status'], e['payload_json']))
            for m in migrations:
                self.con.execute('INSERT OR IGNORE INTO migrations VALUES(?,?,?,?,?,?,?)',
                                 (m['signature'], m['instruction_index'], m['launchlab_pool'],
                                  m['cpmm_pool'], m['slot'], m['status'], m['evidence']))
            if undecodable:
                self._gap(address, 'undecodable', f'{signature}:{undecodable}')
            self.con.execute('INSERT OR REPLACE INTO seen VALUES(?,?)', (signature, outcome))
            self.con.execute('DELETE FROM pending WHERE signature=?', (signature,))   # same tx
        self._atomic(commit)

    def summary(self):
        q = lambda sql: self.con.execute(sql).fetchone()[0]
        return {'start_utc': self._get('start_utc'), 'deadline_utc': self._get('deadline_utc'),
                'requests_total': self.requests_used(), 'events': q('SELECT COUNT(*) FROM events'),
                'gaps': q('SELECT COUNT(*) FROM gaps'), 'pending': q('SELECT COUNT(*) FROM pending'),
                'dead_letter': q("SELECT COUNT(*) FROM seen WHERE outcome='dead_letter'"),
                'final_reason': self._get('final_reason')}


def build_parser():
    p = argparse.ArgumentParser(description='Read-only 24 h LaunchLab + CPMM observer.')
    p.add_argument('--mode', choices=('dry-run', 'fixture', 'live-readonly'), default='dry-run')
    p.add_argument('--db', default='observer24h.db')
    p.add_argument('--journal', default=None)
    p.add_argument('--hours', type=float, default=24.0)
    p.add_argument('--max-requests', type=int, default=20000,
                   help='total HTTP attempts incl. retries; set from the REAL provider quota')
    p.add_argument('--max-requests-per-poll', type=int, default=200)
    p.add_argument('--poll-interval', type=float, default=20.0)
    p.add_argument('--rpc-env', default='HELIUS_RPC_URL',
                   help='NAME of the env var holding the RPC URL (never the URL itself)')
    p.add_argument('--fixture-dir', default=None)
    p.add_argument('--i-understand-this-uses-network', action='store_true')
    return p


def page_signatures(order, slots, params):
    """Shared fake of getSignaturesForAddress paging (newest first, before/until/limit)."""
    opts = params[1]
    rows = []
    started = not opts.get('before')
    for s in order:
        if not started:
            started = s == opts['before']
            continue
        if s == opts.get('until'):
            break
        rows.append({'signature': s, 'slot': slots[s], 'err': None})
        if len(rows) >= opts.get('limit', PAGE):
            break
    return rows


class _FixtureRpc:
    """Replays a directory of getTransaction JSON files: no network."""

    def __init__(self, directory):
        self.txs = {}
        for path in sorted(Path(directory).glob('*.json')):
            result = json.loads(path.read_text()).get('result')
            self.txs[result['transaction']['signatures'][0]] = result
        self.order = sorted(self.txs, key=lambda s: self.txs[s]['slot'], reverse=True)

    def call(self, method, params):
        if method == 'getSignaturesForAddress':
            if params[0] != LAUNCHLAB_PROGRAM:
                return []
            return page_signatures(self.order, {s: t['slot'] for s, t in self.txs.items()}, params)
        if method == 'getTransaction':
            return self.txs.get(params[0])
        raise DisallowedMethod(method)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if not math.isfinite(args.hours) or args.hours <= 0:
            raise ValueError('hours_must_be_finite_and_positive')
        cfg = ObserverConfig(db_path=args.db, journal_path=args.journal,
                             max_duration_seconds=int(args.hours * 3600),
                             max_requests_total=args.max_requests,
                             max_requests_per_poll=args.max_requests_per_poll,
                             poll_interval_seconds=args.poll_interval)
    except ValueError as exc:
        print(f'invalid arguments: {exc}', file=sys.stderr)
        return 2
    if args.mode == 'dry-run':
        print(json.dumps({'mode': 'dry-run', 'network': False, 'db': cfg.db_path,
                          'max_duration_seconds': cfg.max_duration_seconds,
                          'max_requests_total': cfg.max_requests_total,
                          'allowed_methods': sorted(ALLOWED_METHODS),
                          'watched': dict(WATCHED), 'coverage': coverage_plan(cfg)}, indent=2))
        return 0
    if args.mode == 'fixture':
        if not args.fixture_dir:
            print('--fixture-dir required', file=sys.stderr)
            return 2
        rpc = _FixtureRpc(args.fixture_dir)
        cfg = ObserverConfig(**{**cfg.__dict__, 'poll_interval_seconds': 0.0,
                                'anchor_without_backfill': False})
    else:
        if not args.i_understand_this_uses_network:
            print('live-readonly needs --i-understand-this-uses-network', file=sys.stderr)
            return 2
        try:
            check_coverage(cfg)
        except ValueError as exc:
            print(f'refused: {exc}', file=sys.stderr)
            return 2
        url = os.environ.get(args.rpc_env)
        if not url:
            print(f'env var {args.rpc_env} is not set', file=sys.stderr)
            return 2
        rpc = JsonRpc(url, Budget(cfg.max_requests_total))   # budget replaced by Observer's
    stop = {'now': False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.__setitem__('now', True))
    obs = Observer(cfg, rpc, stop=lambda: stop['now'])
    try:
        if args.mode == 'fixture':
            obs.start()
            obs.poll_once()
            obs.poll_once()
            obs._set('final_reason', 'fixture_done')
        else:
            obs.run()
        print(json.dumps(obs.summary(), indent=2))
    finally:
        obs.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
