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
        self.calls, self.fail, self.missing = [], fail, set()

    def call(self, method, params):
        self.calls.append(method)
        if self.fail:
            raise RpcError(f'{method}:URLError')
        if method == 'getSignaturesForAddress':
            if params[0] != ob.LAUNCHLAB_PROGRAM:
                return []
            return ob.page_signatures(self.order, {s: t['slot'] for s, t in self.txs.items()},
                                      params)
        if method == 'getTransaction':
            if params[0] in self.missing:
                return None
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


def _docstring_nodes(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = n.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def test_module_has_no_signing_or_live_code_ast():
    """AST-level: no signing/sending identifier, attribute, import or RPC-method literal."""
    import re
    banned = re.compile(r'(?i)^(send|sign(?!al|ature)|simulate|requestairdrop|keypair|private_?key|secret_?key'
                        r'|nacl|solders|ed25519)')
    rpc_like = re.compile(r'^(get|send|sign|simulate|request)[A-Z]\w+$')
    tree = ast.parse(Path(ob.__file__).read_text())
    docs = _docstring_nodes(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names = [n.id]
        elif isinstance(n, ast.Attribute):
            names = [n.attr]
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            names = [n.name]
        elif isinstance(n, ast.arg):
            names = [n.arg]
        elif isinstance(n, ast.keyword):
            names = [n.arg or '']
        elif isinstance(n, ast.alias):
            names = [n.name.split('.')[-1], n.name.split('.')[0]]
        elif isinstance(n, ast.ImportFrom):
            names = [(n.module or '').split('.')[0]] + ([(n.module or '').split('.')[1]]
                                                       if (n.module or '').count('.') else [])
            assert 'live' not in (n.module or '').split('.'), n.module
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            names = [n.value]
            if rpc_like.match(n.value):
                assert n.value in ob.ALLOWED_METHODS, n.value
        else:
            continue
        for name in names:
            assert not banned.match(name), name
    assert ob.ALLOWED_METHODS == frozenset({'getSignaturesForAddress', 'getTransaction'})


def test_allowed_methods_is_exact_and_getslot_removed():
    assert 'getSlot' not in ob.ALLOWED_METHODS
    with pytest.raises(ob.DisallowedMethod):
        ob.AllowlistRpc(FakeRpc()).call('getSlot', [])


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


# ---------------------------------------------------------------- B1 : per-attempt budget
class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_429():
    import urllib.error
    return urllib.error.HTTPError('https://rpc.invalid/', 429, 'x', {}, None)


def _real_rpc(seq):
    """JsonRpc over a scripted opener: items are '429' or a result value."""
    import itertools
    from bot.market.collector import Budget, JsonRpc
    calls = []
    it = iter(seq)

    def opener(request, timeout=None):
        calls.append(1)
        item = next(it)
        if item == '429':
            raise _http_429()
        if item == 'crash':
            raise KeyboardInterrupt
        return _Resp({'jsonrpc': '2.0', 'id': 1, 'result': item})
    return JsonRpc('https://rpc.invalid/', Budget(1), min_interval=0, sleep=lambda s: None,
                   opener=opener), calls


def test_b1_every_http_attempt_incl_429_retries_is_counted(tmp_path):
    rpc, calls = _real_rpc(['429', '429', '429', []])
    o, _ = make(tmp_path, rpc)
    assert o._call('getSignaturesForAddress', ['A', {}]) == []
    assert len(calls) == 4 and o.requests_used() == 4          # retry x3 + success = 4
    o.close()


def test_b1_budget_survives_restart_and_stays_exhausted(tmp_path):
    rpc, calls = _real_rpc(['429', 'crash'])
    o, clock = make(tmp_path, rpc, max_requests_total=3)
    with pytest.raises(KeyboardInterrupt):
        o._call('getSignaturesForAddress', ['A', {}])
    assert o.requests_used() == 2                               # charged BEFORE the attempt
    o.close()
    rpc2, calls2 = _real_rpc([[]])
    o2, _ = make(tmp_path, rpc2, clock, max_requests_total=3)
    assert o2.requests_used() == 2                              # not reset
    o2._call('getSignaturesForAddress', ['A', {}])
    assert o2.requests_used() == 3
    with pytest.raises(ob.QuotaExhausted):
        o2._call('getSignaturesForAddress', ['A', {}])
    assert len(calls2) == 1                                     # no HTTP attempt past the quota
    o2.close()


def test_b1_retries_cannot_exceed_total_quota_midway(tmp_path):
    rpc, calls = _real_rpc(['429'] * 10)
    o, _ = make(tmp_path, rpc, max_requests_total=3)
    with pytest.raises(ob.QuotaExhausted):
        o._call('getTransaction', ['S', {}])
    assert len(calls) == 3 and o.requests_used() == 3
    o.close()


# ---------------------------------------------------------------- B2 : cadence vs quota
def test_b2_old_two_second_cadence_cannot_cover_24h():
    cfg = ob.ObserverConfig(db_path='x', poll_interval_seconds=2.0)
    plan = ob.coverage_plan(cfg)
    assert plan['head_requests'] == 2 * 43200 and not plan['covers_window']
    assert plan['hours_until_quota_if_idle'] < 6
    with pytest.raises(ValueError, match='cadence_exceeds_quota'):
        ob.check_coverage(cfg)


def test_b2_default_cadence_leaves_a_shared_pool():
    plan = ob.check_coverage(ob.ObserverConfig(db_path='x'))
    assert plan['covers_window'] and plan['head_requests'] == 2 * 4320
    assert plan['shared_pool_requests'] == 20000 - 8640


def test_b2_24h_clock_simulation_idle_program_reaches_deadline(tmp_path):
    class Idle:
        calls = 0

        def call(self, method, params):
            Idle.calls += 1
            return []
    o, clock = make(tmp_path, Idle())
    assert o.run() == 'deadline_reached'
    assert 8600 <= o.requests_used() <= 8700 and o.requests_used() == Idle.calls
    assert (clock.now - T0).total_seconds() >= 24 * 3600
    o.close()


# ---------------------------------------------------------------- B3 / B4 : pagination, fairness
class SynthRpc:
    """Per-program signature lists (newest first) + transactions cloned from a fixture."""

    def __init__(self, lists, tx_template=None):
        self.lists, self.tx, self.calls = lists, tx_template, []

    def call(self, method, params):
        self.calls.append((method, params[0]))
        if method == 'getSignaturesForAddress':
            order = self.lists.get(params[0], [])
            return ob.page_signatures(order, {s: int(s[1:]) for s in order}, params)
        import copy
        t = copy.deepcopy(self.tx)
        t['transaction']['signatures'] = [params[0]]
        t['slot'] = int(params[0][1:])
        return t


def _template():
    return next(iter(FakeRpc().txs.values()))


def test_b3_more_than_1000_signatures_are_all_enumerated_without_skip(tmp_path):
    order = [f'L{n}' for n in range(2500, 0, -1)]
    rpc = SynthRpc({ob.LAUNCHLAB_PROGRAM: order})
    o, _ = make(tmp_path, rpc)
    o.start()
    pages = 0
    while o._enumerate(ob.LAUNCHLAB_PROGRAM):
        pages += 1
    assert pages == 2 and o.pending_count() == 2500
    assert o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') == 'L2500'
    assert o._get(f'enum_before:{ob.LAUNCHLAB_PROGRAM}') is None       # enumeration closed
    # a second burst of 1200 new signatures: stops exactly at the old cursor, nothing skipped
    rpc.lists[ob.LAUNCHLAB_PROGRAM] = [f'L{n}' for n in range(3700, 0, -1)]
    while o._enumerate(ob.LAUNCHLAB_PROGRAM):
        pass
    assert o.pending_count() == 3700 and o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') == 'L3700'
    assert count(tmp_path, 'gaps') == 0
    o.close()


def test_b3_cursor_does_not_move_while_enumeration_is_unfinished(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, 'PAGE', 3)
    rpc = SynthRpc({ob.LAUNCHLAB_PROGRAM: [f'L{n}' for n in range(10, 0, -1)]})
    o, _ = make(tmp_path, rpc)
    o.start()
    assert o._enumerate(ob.LAUNCHLAB_PROGRAM) is True
    assert o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') is None and o.pending_count() == 3
    o.close()
    o2, _ = make(tmp_path, rpc)               # crash/restart: continues from the stored page
    o2.start()
    while o2._enumerate(ob.LAUNCHLAB_PROGRAM):
        pass
    assert o2.pending_count() == 10 and o2._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') == 'L10'
    o2.close()


def test_b3_full_page_fixture_replay_matches_unpaginated(tmp_path, monkeypatch):
    ref = tmp_path / 'ref'; ref.mkdir()
    r, _ = make(ref, FakeRpc()); r.start(); r.poll_once(); r.close()
    monkeypatch.setattr(ob, 'PAGE', 2)         # fixtures span several full pages
    o, _ = make(tmp_path, FakeRpc())
    o.start(); o.poll_once(); o.poll_once()
    assert o.pending_count() == 0 and count(tmp_path) == count(ref) > 0
    assert count(tmp_path, 'gaps') == 0
    o.close()


def test_b4_launchlab_backlog_cannot_starve_cpmm(tmp_path):
    tx = _template()
    rpc = SynthRpc({ob.LAUNCHLAB_PROGRAM: [f'L{n}' for n in range(40, 0, -1)],
                    ob.CPMM_PROGRAM: ['C102', 'C101']}, tx)
    o, _ = make(tmp_path, rpc, max_requests_per_poll=8)
    o.start()
    o.poll_once()
    left = {a: o.con.execute('SELECT COUNT(*) FROM pending WHERE address=?', (a,)).fetchone()[0]
            for a in (ob.LAUNCHLAB_PROGRAM, ob.CPMM_PROGRAM)}
    assert left[ob.CPMM_PROGRAM] == 0                      # served in the very first poll
    assert 30 < left[ob.LAUNCHLAB_PROGRAM] < 40            # and LaunchLab still progresses
    assert o.requests_used() <= 8
    o.close()


# ---------------------------------------------------------------- B5 : missing transactions
def test_b5_unavailable_transaction_is_bounded_then_dead_lettered(tmp_path):
    rpc = FakeRpc()
    bad = rpc.order[1]
    rpc.missing = {bad}
    o, _ = make(tmp_path, rpc)
    o.start()
    for _ in range(6):
        o.poll_once()
    tries = [c for c in rpc.calls if c == 'getTransaction']
    assert o.pending_count() == 0
    assert o.con.execute('SELECT outcome FROM seen WHERE signature=?', (bad,)).fetchone()[0] \
        == 'dead_letter'
    reasons = [r[0] for r in o.con.execute('SELECT reason FROM gaps')]
    assert reasons.count('transaction_unavailable') == ob.MAX_TX_ATTEMPTS - 1
    assert reasons.count('transaction_unavailable_dead_letter') == 1
    assert len(tries) == len(rpc.order) - 1 + ob.MAX_TX_ATTEMPTS      # exactly 3 tries for `bad`
    assert o.con.execute('SELECT COUNT(*) FROM events WHERE signature=?', (bad,)).fetchone()[0] == 0
    assert count(tmp_path) > 0                                         # others not blocked
    o.close()


# ---------------------------------------------------------------- B6 / B8 / B11 : migrations
def _tx(instructions, keys):
    return {'slot': 5, 'blockTime': 5, 'transaction': {'signatures': ['SIG'], 'message': {
        'accountKeys': keys, 'instructions': instructions}},
        'meta': {'err': None, 'innerInstructions': []}}


def _ix(program_index, disc, accounts=(2,)):
    return {'programIdIndex': program_index, 'accounts': list(accounts), 'data': b58encode(disc)}


MIG = next(iter(ob.LAUNCHLAB_MIGRATE_DISCS))
INIT = next(iter(ob.CPMM_INIT_DISCS))
KEYS = [ob.LAUNCHLAB_PROGRAM, ob.CPMM_PROGRAM, 'ACC']


def test_b6_two_migrate_instructions_in_one_tx_do_not_collide(tmp_path):
    tx = _tx([_ix(0, MIG), _ix(0, MIG, (2, 2)), _ix(1, INIT)], KEYS)
    events, migrations = ob.normalise_transaction(tx, ob._utc(T0))
    assert len(migrations) == 2
    assert {m['instruction_index'] for m in migrations} == {'o0', 'o1'}
    assert all(m['status'] == 'unproven' and m['cpmm_pool'] is None
               and m['launchlab_pool'] == 'unknown'
               and m['evidence'] == 'cpmm_init_same_tx_ids_unconfirmed' for m in migrations)
    o, _ = make(tmp_path)
    o.start()
    o._store(ob.LAUNCHLAB_PROGRAM, 'SIG', tx)
    assert count(tmp_path, 'migrations') == 2
    o._store(ob.LAUNCHLAB_PROGRAM, 'SIG', tx)           # replay: idempotent
    assert count(tmp_path, 'migrations') == 2
    o.close()


def test_b6_migrate_alone_is_unproven_with_no_link_evidence():
    _, migrations = ob.normalise_transaction(_tx([_ix(0, MIG)], KEYS), ob._utc(T0))
    assert [(m['status'], m['evidence']) for m in migrations] == [('unproven', 'no_cpmm_init_in_same_tx')]


def test_b6_inner_instructions_get_distinct_keys():
    tx = _tx([_ix(0, MIG)], KEYS)
    tx['meta']['innerInstructions'] = [{'index': 0, 'instructions': [_ix(0, MIG)]}]
    _, migrations = ob.normalise_transaction(tx, ob._utc(T0))
    assert {m['instruction_index'] for m in migrations} == {'o0', 'i0.0'}


def test_b8_discriminator_mismatch_yields_nothing_and_events_stay_unconfirmed():
    assert ob.DISCRIMINATORS_CONFIRMED is False
    wrong = _tx([_ix(1, MIG), _ix(0, b'\x00' * 8), _ix(1, b'\xff' * 8)], KEYS)   # crossed / unknown discs
    events, migrations = ob.normalise_transaction(wrong, ob._utc(T0))
    assert events == [] and migrations == []
    ok = _tx([_ix(0, MIG), _ix(1, INIT)], KEYS)
    events, _ = ob.normalise_transaction(ok, ob._utc(T0))
    assert {e['kind'] for e in events} == {'launchlab_migrate', 'cpmm_init'}
    for e in events:
        assert e['decoded'] == 0 and e['pool'] == 'unknown' and e['slippage_bps'] is None
        assert json.loads(e['payload_json'])['discriminator_status'] == 'unconfirmed'
    assert 'proven' not in {m['status'] for m in ob.normalise_transaction(ok, ob._utc(T0))[1]}


# ---------------------------------------------------------------- B7 : atomicity / anchor
class _FailOnCommit:
    def __init__(self, con):
        self._c = con

    def execute(self, sql, *a):
        if sql == 'COMMIT':
            raise sqlite3.OperationalError('disk I/O error (simulated)')
        return self._c.execute(sql, *a)

    def close(self):
        self._c.close()


def test_b7_failure_between_insert_and_commit_rolls_everything_back(tmp_path):
    o, _ = make(tmp_path)
    o.start()
    o._enumerate(ob.LAUNCHLAB_PROGRAM)
    sig = o.rpc._inner.order[0]
    pending_before = o.pending_count()
    real = o.con
    o.con = _FailOnCommit(real)
    with pytest.raises(sqlite3.OperationalError):
        o._store(ob.LAUNCHLAB_PROGRAM, sig, o.rpc._inner.txs[sig])
    o.con = real
    assert count(tmp_path) == 0 and count(tmp_path, 'seen') == 0       # nothing half-written
    assert o.pending_count() == pending_before                          # still to be retried
    o._store(ob.LAUNCHLAB_PROGRAM, sig, o.rpc._inner.txs[sig])           # retry succeeds
    assert count(tmp_path) > 0 and o.pending_count() == pending_before - 1
    o.close()


def test_b7_failure_during_enumeration_commit_leaves_cursor_and_pending_untouched(tmp_path):
    o, _ = make(tmp_path)
    o.start()
    real = o.con
    o.con = _FailOnCommit(real)
    with pytest.raises(sqlite3.OperationalError):
        o._enumerate(ob.LAUNCHLAB_PROGRAM)
    o.con = real
    assert o.pending_count() == 0 and o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') is None


def test_b7_anchor_with_empty_page_sets_nothing_then_anchors_when_rows_appear(tmp_path):
    rpc = SynthRpc({}, _template())
    clock = Clock()
    cfg = ob.ObserverConfig(db_path=str(tmp_path / 'o.db'))        # anchoring ON
    o = ob.Observer(cfg, rpc, clock=clock, sleep=clock.sleep)
    o.start(); o.poll_once()
    assert o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') is None and count(tmp_path, 'gaps') == 0
    assert 'getTransaction' not in [m for m, _ in rpc.calls]
    rpc.lists[ob.LAUNCHLAB_PROGRAM] = ['L9', 'L8']
    o.poll_once()
    assert o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') == 'L9' and o.pending_count() == 0
    assert [r[0] for r in o.con.execute('SELECT reason FROM gaps')] == ['start_anchor_no_backfill']
    o.close()


# ---------------------------------------------------------------- B10 : CLI hygiene
@pytest.mark.parametrize('args', [['--hours', '0'], ['--hours', 'nan'], ['--hours', '-1'],
                                  ['--hours', '25'], ['--max-requests', '0'],
                                  ['--poll-interval', '-1']])
def test_b10_invalid_cli_values_give_clean_exit_code(tmp_path, capsys, args):
    rc = ob.main(['--mode', 'dry-run', '--db', str(tmp_path / 'x.db')] + args)
    assert rc == 2 and 'invalid arguments' in capsys.readouterr().err


def test_b10_live_refuses_cadence_that_cannot_cover_the_window(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('HELIUS_RPC_URL', 'https://rpc.invalid/')       # never contacted
    rc = ob.main(['--mode', 'live-readonly', '--i-understand-this-uses-network',
                  '--poll-interval', '2', '--db', str(tmp_path / 'x.db')])
    assert rc == 2 and 'cadence_exceeds_quota' in capsys.readouterr().err
    assert not (tmp_path / 'x.db').exists()


def test_b10_deleting_the_db_resets_window_and_quota_documented(tmp_path):
    o, clock = make(tmp_path); o.start(); o._set('requests_total', 7); o.close()
    (tmp_path / 'o.db').unlink()
    o2, _ = make(tmp_path, clock=clock)
    assert o2.requests_used() == 0               # known limitation, see docs/OBSERVER24H.md
    o2.close()


def test_b10_old_schema_db_is_refused(tmp_path):
    o, _ = make(tmp_path); o.start(); o._set('schema_version', 1); o.close()
    o2, _ = make(tmp_path)
    with pytest.raises(ValueError, match='schema_mismatch'):
        o2.start()
    o2.close()
