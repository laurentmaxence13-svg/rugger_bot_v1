"""Strictly read-only, bounded 24 h observer for Raydium LaunchLab + CPMM.

Safety contract (enforced by code and by ``tests/test_observer24h.py``):

* only the RPC methods in ``ALLOWED_METHODS`` can be issued (fail-closed);
* no signing, no transaction submission, no import from ``bot.live``;
* the RPC URL (which may embed an API key) is read from an environment
  variable by the CLI, is never stored, logged, or put in an exception;
* hard wall-clock limit (<= 24 h) measured from the *first* start (kept across
  restarts, so a restart can never extend the window) and a persistent request
  quota (kept across restarts); both stop the run, never relax;
* events and the cursor are written in ONE SQLite transaction, so a crash can
  neither lose nor duplicate an event; re-reading the same transaction is
  idempotent on (signature, slot, event_index, pool, kind);
* unknown values stay ``None`` (slippage is never defaulted to 0);
* a migration is reported ``proven`` only when one successful transaction
  contains the LaunchLab migrate instruction AND the CPMM pool initialisation
  and both pool identifiers are linked; otherwise ``unproven``.

Discriminators of non-trade instructions are Anchor ``sha256("global:<name>")``
values computed here and are NOT yet confirmed against real mainnet
transactions: such events carry ``decoded=False`` and only program, accounts and
a payload hash. This is a documented limitation (see docs/OBSERVER24H.md).
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from bot.market.collector import Budget, BudgetExhausted, JsonRpc, RpcError
from bot.market.launchlab_events import (
    LAUNCHLAB_PROGRAM, EventDecodeError, b58decode, extract_trade_events, _account_keys,
)

CPMM_PROGRAM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
ALLOWED_METHODS = frozenset({'getSignaturesForAddress', 'getTransaction', 'getSlot'})
MAX_DURATION_SECONDS = 24 * 3600
SCHEMA_VERSION = 1
MAX_TX_VERSION = 1
PAGE = 1000
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
    poll_interval_seconds: float = 2.0
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
  launchlab_pool TEXT NOT NULL, cpmm_pool TEXT, signature TEXT NOT NULL, slot INTEGER NOT NULL,
  status TEXT NOT NULL, PRIMARY KEY(signature, launchlab_pool));
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
    instructions = list(message.get('instructions') or [])
    for group in meta.get('innerInstructions') or []:
        instructions.extend(group.get('instructions') or [])
    found = {'create': [], 'migrate': [], 'cpmm_init': []}
    for ix in instructions:
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
        row = {'program': program, 'accounts': accounts,
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
        linked = found['cpmm_init'] and row['accounts']
        # Proof needs a LaunchLab pool id AND a CPMM pool id; the account layout of the
        # migrate instruction is not yet confirmed, so no pool id is claimed => unproven.
        migrations.append({'launchlab_pool': 'unknown', 'cpmm_pool': None,
                           'signature': signature, 'slot': slot,
                           'status': 'unproven' if not linked else 'unproven_ids_unconfirmed'})
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


class Observer:
    def __init__(self, config, rpc, *, clock=lambda: datetime.now(timezone.utc),
                 sleep=time.sleep, stop=lambda: False):
        self.cfg = config
        self.rpc = AllowlistRpc(rpc)
        self._clock, self._sleep, self._stop = clock, sleep, stop
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

    def requests_used(self):
        return int(self._get('requests_total', 0))

    def _gap(self, address, reason, detail=''):
        self.con.execute('INSERT INTO gaps(recv_utc,address,reason,detail) VALUES(?,?,?,?)',
                         (_utc(self._clock()), address, reason, redact(detail)))
        self.journal.write('gap', address=address, reason=reason, detail=detail)

    def _call(self, method, params, poll_used):
        """Quota is charged BEFORE the call and persisted, so a crash cannot undercount."""
        if self.requests_used() >= self.cfg.max_requests_total:
            raise QuotaExhausted('quota_total_exhausted')
        if poll_used[0] >= self.cfg.max_requests_per_poll:
            raise QuotaExhausted('quota_per_poll_exhausted')
        self._set('requests_total', self.requests_used() + 1)
        poll_used[0] += 1
        return self.rpc.call(method, params)

    # -- lifecycle ----------------------------------------------------------------
    def start(self):
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
            except QuotaExhausted as exc:
                if str(exc) == 'quota_total_exhausted':
                    reason = 'quota_exhausted'
                    break
            except (RpcError, BudgetExhausted) as exc:
                failures += 1
                self._gap('*', 'rpc_unavailable', str(exc))
                if failures >= self.cfg.max_consecutive_failures:
                    reason = 'network_unavailable'
                    break
                self._sleep(min(self.cfg.backoff_cap_seconds,
                                self.cfg.backoff_base_seconds * 2 ** (failures - 1)))
                continue
            self._sleep(self.cfg.poll_interval_seconds)
        self._set('final_reason', reason)
        self.journal.write('stop', reason=reason, requests=self.requests_used())
        return reason

    def poll_once(self):
        poll_used = [0]
        for name, address in WATCHED:
            cursor = self._get(f'cursor:{address}')
            options = {'limit': PAGE, 'commitment': 'finalized'}
            if cursor:
                options['until'] = cursor
            rows = self._call('getSignaturesForAddress', [address, options], poll_used) or []
            if not cursor and self.cfg.anchor_without_backfill:
                # first run: no historical backfill; anchor on the newest signature only
                if rows:
                    self._set(f'cursor:{address}', rows[0]['signature'])
                    self._gap(address, 'start_anchor_no_backfill', rows[0]['signature'])
                continue
            if len(rows) >= PAGE:
                self._gap(address, 'page_full_possible_loss',
                          f'newest_page_of_{PAGE}_may_not_connect_to_cursor')
            for row in reversed(rows):                       # oldest first -> contiguous prefix
                if row.get('err') is not None:
                    self._advance(address, row['signature'])
                    continue
                result = self._call('getTransaction', [row['signature'], {
                    'encoding': 'json', 'maxSupportedTransactionVersion': MAX_TX_VERSION,
                    'commitment': 'finalized'}], poll_used)
                if result is None:
                    self._gap(address, 'transaction_unavailable', row['signature'])
                    return                                   # cursor not advanced: retry later
                self._store(address, row['signature'], result)

    def _advance(self, address, signature):
        self._set(f'cursor:{address}', signature)

    def _store(self, address, signature, result):
        recv = _utc(self._clock())
        try:
            events, migrations = normalise_transaction(result, recv)
        except (EventDecodeError, KeyError, TypeError, IndexError) as exc:
            events, migrations = [], []
            self._gap(address, 'undecodable', f'{signature}:{type(exc).__name__}')
        self.con.execute('BEGIN IMMEDIATE')
        try:
            for e in events:
                self.con.execute(
                    'INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (e['signature'], e['slot'], e['event_index'], e['pool'], e['kind'],
                     e['program'], e['recv_utc'], e['chain_time'], e['causality'], e['decoded'],
                     e['slippage_bps'], e['slippage_status'], e['payload_json']))
            for m in migrations:
                self.con.execute('INSERT OR IGNORE INTO migrations VALUES(?,?,?,?,?)',
                                 (m['launchlab_pool'], m['cpmm_pool'], m['signature'],
                                  m['slot'], m['status']))
            self._advance(address, signature)      # same transaction as the events
            self.con.execute('COMMIT')
        except BaseException:
            self.con.execute('ROLLBACK')
            raise

    def summary(self):
        q = lambda sql: self.con.execute(sql).fetchone()[0]
        return {'start_utc': self._get('start_utc'), 'deadline_utc': self._get('deadline_utc'),
                'requests_total': self.requests_used(), 'events': q('SELECT COUNT(*) FROM events'),
                'gaps': q('SELECT COUNT(*) FROM gaps'),
                'final_reason': self._get('final_reason')}


def build_parser():
    p = argparse.ArgumentParser(description='Read-only 24 h LaunchLab + CPMM observer.')
    p.add_argument('--mode', choices=('dry-run', 'fixture', 'live-readonly'), default='dry-run')
    p.add_argument('--db', default='observer24h.db')
    p.add_argument('--journal', default=None)
    p.add_argument('--hours', type=float, default=24.0)
    p.add_argument('--max-requests', type=int, default=20000)
    p.add_argument('--max-requests-per-poll', type=int, default=200)
    p.add_argument('--rpc-env', default='HELIUS_RPC_URL',
                   help='NAME of the env var holding the RPC URL (never the URL itself)')
    p.add_argument('--fixture-dir', default=None)
    p.add_argument('--i-understand-this-uses-network', action='store_true')
    return p


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
            until = params[1].get('until')
            rows = []
            for s in self.order:
                if s == until:
                    break
                rows.append({'signature': s, 'slot': self.txs[s]['slot'], 'err': None})
            return rows
        if method == 'getTransaction':
            return self.txs.get(params[0])
        raise DisallowedMethod(method)


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = ObserverConfig(db_path=args.db, journal_path=args.journal,
                         max_duration_seconds=int(args.hours * 3600),
                         max_requests_total=args.max_requests,
                         max_requests_per_poll=args.max_requests_per_poll)
    if args.mode == 'dry-run':
        print(json.dumps({'mode': 'dry-run', 'network': False, 'db': cfg.db_path,
                          'max_duration_seconds': cfg.max_duration_seconds,
                          'max_requests_total': cfg.max_requests_total,
                          'allowed_methods': sorted(ALLOWED_METHODS),
                          'watched': dict(WATCHED)}, indent=2))
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
        url = os.environ.get(args.rpc_env)
        if not url:
            print(f'env var {args.rpc_env} is not set', file=sys.stderr)
            return 2
        rpc = JsonRpc(url, Budget(cfg.max_requests_total))
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
