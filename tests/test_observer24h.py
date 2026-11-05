"""Offline tests of the read-only 24 h observer (fake RPC, no network, no secrets)."""
import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from bot.market import observer24h as ob
from bot.market.collector import RpcError
from bot.market.launchlab_events import b58encode

FIXTURES = Path(__file__).parent / 'fixtures' / 'launchlab_trades'
T0 = datetime(2026, 11, 6, 8, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=max(seconds, 0.001))


class FakeRpc:
    def __init__(self, fail=False):
        self.txs = {}
        for path in FIXTURES.glob('*.json'):
            result = json.loads(path.read_text())['result']
            self.txs[result['transaction']['signatures'][0]] = result
        self.order = sorted(self.txs, key=lambda s: self.txs[s]['slot'], reverse=True)
        self.calls, self.fail = [], fail

    def call(self, method, params):
        self.calls.append(method)
        if self.fail:
            raise RpcError(f'{method}:URLError')
        if method == 'getSignaturesForAddress':
            if params[0] != ob.LAUNCHLAB_PROGRAM:
                return []
            until, rows = params[1].get('until'), []
            for s in self.order:
                if s == until:
                    break
                rows.append({'signature': s, 'slot': self.txs[s]['slot'], 'err': None})
            return rows
        if method == 'getTransaction':
            return self.txs[params[0]]
        raise AssertionError(method)


def make(tmp_path, rpc=None, clock=None, **kw):
    clock = clock or Clock()
    cfg = ob.ObserverConfig(db_path=str(tmp_path / 'o.db'), journal_path=str(tmp_path / 'j.jsonl'),
                            anchor_without_backfill=False, **kw)
    return ob.Observer(cfg, rpc or FakeRpc(), clock=clock, sleep=clock.sleep), clock


def count(tmp_path, table='events'):
    con = sqlite3.connect(tmp_path / 'o.db')
    try:
        return con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    finally:
        con.close()


def test_events_are_stored_and_replay_is_idempotent(tmp_path):
    o, _ = make(tmp_path)
    o.start()
    o.poll_once()
    first = count(tmp_path)
    assert first > 0
    # re-store the very same transactions: no duplicate
    for sig, res in o.rpc._inner.txs.items():
        o._store(ob.LAUNCHLAB_PROGRAM, sig, res)
    o.close()
    assert count(tmp_path) == first


def test_restart_resumes_from_cursor_without_refetching(tmp_path):
    rpc = FakeRpc()
    o, clock = make(tmp_path, rpc)
    o.start(); o.poll_once(); o.close()
    before = count(tmp_path)
    tx_calls = rpc.calls.count('getTransaction')
    o2, _ = make(tmp_path, rpc, clock)
    o2.start(); o2.poll_once()
    assert rpc.calls.count('getTransaction') == tx_calls
    assert count(tmp_path) == before
    o2.close()


def test_crash_between_transactions_loses_and_duplicates_nothing(tmp_path):
    rpc = FakeRpc()
    real = rpc.call
    n = {'tx': 0}

    def crashing(method, params):
        if method == 'getTransaction':
            n['tx'] += 1
            if n['tx'] == 3:
                raise KeyboardInterrupt  # simulated hard crash
        return real(method, params)
    rpc.call = crashing
    o, clock = make(tmp_path, rpc)
    o.start()
    with pytest.raises(KeyboardInterrupt):
        o.poll_once()
    o.close()
    rpc.call = real
    o2, _ = make(tmp_path, rpc, clock)
    o2.start(); o2.poll_once(); o2.close()
    ref = tmp_path / 'ref'; ref.mkdir()
    o3, _ = make(ref, FakeRpc())
    o3.start(); o3.poll_once(); o3.close()
    assert count(tmp_path) == count(ref)


def test_deadline_is_fixed_at_first_start_and_survives_restart(tmp_path):
    o, clock = make(tmp_path, max_duration_seconds=100)
    o.start()
    deadline = o._get('deadline_utc')
    o.close()
    clock.now += timedelta(seconds=90)
    o2, _ = make(tmp_path, clock=clock, max_duration_seconds=100)
    o2.start()
    assert o2._get('deadline_utc') == deadline and not o2.expired()
    clock.now += timedelta(seconds=20)
    assert o2.run() == 'deadline_reached'
    o2.close()


def test_duration_above_24h_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        ob.ObserverConfig(db_path='x', max_duration_seconds=24 * 3600 + 1)


def test_quota_exhaustion_is_fail_closed_and_persistent(tmp_path):
    rpc = FakeRpc()
    o, clock = make(tmp_path, rpc, max_requests_total=5)
    assert o.run() == 'quota_exhausted'
    assert o.requests_used() == 5 and len(rpc.calls) == 5
    o.close()
    o2, _ = make(tmp_path, rpc, clock, max_requests_total=5)
    assert o2.run() == 'quota_exhausted'
    assert len(rpc.calls) == 5               # restart cannot reset the quota
    o2.close()


def test_network_down_stops_with_bounded_backoff_and_records_gaps(tmp_path):
    o, clock = make(tmp_path, FakeRpc(fail=True), max_consecutive_failures=4,
                    backoff_base_seconds=1, backoff_cap_seconds=3)
    assert o.run() == 'network_unavailable'
    assert (clock.now - T0).total_seconds() <= 1 + 2 + 3 + 0.1
    assert count(tmp_path, 'gaps') == 4
    o.close()


def test_stop_request_stops_cleanly(tmp_path):
    clock = Clock()
    flag = {'stop': False}
    cfg = ob.ObserverConfig(db_path=str(tmp_path / 'o.db'), anchor_without_backfill=False)
    rpc = FakeRpc()
    o = ob.Observer(cfg, rpc, clock=clock, stop=lambda: flag['stop'],
                    sleep=lambda s: flag.__setitem__('stop', True))
    assert o.run() == 'stopped_by_request'
    assert o.summary()['events'] > 0
    o.close()


def test_slippage_is_never_zero_by_default(tmp_path):
    o, _ = make(tmp_path)
    o.start(); o.poll_once(); o.close()
    con = sqlite3.connect(tmp_path / 'o.db')
    rows = con.execute('SELECT slippage_bps, slippage_status FROM events').fetchall()
    con.close()
    assert rows and all(b is None and s == 'unknown' for b, s in rows)


def test_no_historical_backfill_on_first_live_start(tmp_path):
    clock = Clock()
    cfg = ob.ObserverConfig(db_path=str(tmp_path / 'o.db'))
    rpc = FakeRpc()
    o = ob.Observer(cfg, rpc, clock=clock, sleep=clock.sleep)
    o.start(); o.poll_once()
    assert 'getTransaction' not in rpc.calls and o.summary()['events'] == 0
    o.close()


def test_chain_time_causality_is_flagged(tmp_path):
    res = next(iter(FakeRpc().txs.values()))
    future = dict(res, blockTime=int(T0.timestamp()) + 10_000)
    events, _ = ob.normalise_transaction(future, ob._utc(T0))
    assert events and all(e['causality'] == 'violation_recv_before_chain' for e in events)
    unknown = dict(res, blockTime=None)
    events, _ = ob.normalise_transaction(unknown, ob._utc(T0))
    assert all(e['causality'] == 'chain_time_unknown' for e in events)


def test_migration_not_proven_without_linked_ids():
    tx = {'slot': 1, 'blockTime': 1, 'transaction': {'signatures': ['S'], 'message': {
        'accountKeys': [ob.LAUNCHLAB_PROGRAM, 'A'], 'instructions': [{
            'programIdIndex': 0, 'accounts': [1],
            'data': b58encode(next(iter(ob.LAUNCHLAB_MIGRATE_DISCS)))}]}},
        'meta': {'err': None, 'innerInstructions': []}}
    events, migrations = ob.normalise_transaction(tx, ob._utc(T0))
    assert [e['kind'] for e in events] == ['launchlab_migrate']
    assert migrations and all(m['status'] != 'proven' for m in migrations)


def test_allowlist_blocks_sending_methods():
    guard = ob.AllowlistRpc(FakeRpc())
    for method in ('sendTransaction', 'simulateTransaction', 'requestAirdrop'):
        with pytest.raises(ob.DisallowedMethod):
            guard.call(method, [])


def test_secrets_never_reach_db_journal_or_errors(tmp_path):
    secret = 'SUPERSECRETKEY123'
    url = f'https://mainnet.helius-rpc.com/?api-key={secret}'
    assert secret not in ob.redact(f'failed {url}')
    class Leaky(FakeRpc):
        def call(self, method, params):
            raise RpcError(f'{method}:boom {url}')
    o, _ = make(tmp_path, Leaky(), max_consecutive_failures=2)
    o.run(); o.close()
    blob = (tmp_path / 'j.jsonl').read_bytes() + (tmp_path / 'o.db').read_bytes()
    assert secret.encode() not in blob


def test_module_has_no_signing_or_live_imports():
    src = Path(ob.__file__).read_text()
    tree = ast.parse(src)
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in mods if m.startswith('bot.live') or 'nacl' in m or 'solders' in m]
    assert 'sendTransaction' not in ob.ALLOWED_METHODS
    code = '\n'.join(l for l in src.splitlines() if not l.lstrip().startswith(('#', '"""')))
    for token in ('Keypair', 'signTransaction', 'private_key', 'secret_key'):
        assert token not in code.replace('"""', ''), token


def test_cli_dry_run_and_live_guards(tmp_path, capsys, monkeypatch):
    assert ob.main(['--mode', 'dry-run', '--db', str(tmp_path / 'x.db')]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['network'] is False and not (tmp_path / 'x.db').exists()
    assert ob.main(['--mode', 'live-readonly']) == 2                     # missing ack
    monkeypatch.delenv('HELIUS_RPC_URL', raising=False)
    assert ob.main(['--mode', 'live-readonly', '--i-understand-this-uses-network']) == 2


def test_cli_fixture_mode(tmp_path, capsys):
    rc = ob.main(['--mode', 'fixture', '--fixture-dir', str(FIXTURES), '--db', str(tmp_path / 'f.db')])
    assert rc == 0 and json.loads(capsys.readouterr().out)['events'] > 0
