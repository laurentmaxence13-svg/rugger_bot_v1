"""OFFLINE compatibility proof: collector (#184+#191) x decoder/backfill (#189) x PaperLedger.

Signed LaunchLab fixtures -> RPC fake -> Observer (cursor/checkpoint/idempotent store) ->
cross-checked against ``classify_transaction`` and ``run_backfill`` -> ledger contract gap check.
No network, no secret, no real order. Nothing is invented: fields the chain events do not
carry are asserted MISSING, not filled in (see docs/INTEGRATION_COMPAT_202.md).
"""
import copy
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.market import launchlab_program_decoder as D
from bot.market import observer24h as ob
from bot.market.launchlab_events import b58encode
from bot.market.signature_backfill import BackfillError, BackfillState, run_backfill
from bot.p4.live_like_paper_ledger import source_quote

FIXTURES = Path(__file__).parent / 'fixtures' / 'launchlab_trades'
T0 = datetime(2026, 11, 6, 8, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=max(seconds, 0.001))


def load():
    txs = {}
    for p in sorted(FIXTURES.glob('*.json')):
        r = json.loads(p.read_text())['result']
        txs[r['transaction']['signatures'][0]] = r
    return txs


class Rpc:
    def __init__(self, txs, missing=()):
        self.txs, self.missing, self.calls = txs, set(missing), []
        self.order = sorted(txs, key=lambda s: txs[s]['slot'], reverse=True)
        self.slots = {s: t['slot'] for s, t in txs.items()}

    def call(self, method, params):
        self.calls.append(method)
        if method == 'getSignaturesForAddress':
            return ob.page_signatures(self.order, self.slots, params) \
                if params[0] == ob.LAUNCHLAB_PROGRAM else []
        if method == 'getTransaction':
            return None if params[0] in self.missing else self.txs[params[0]]
        raise AssertionError(method)


@pytest.fixture
def observers():
    made = []
    yield made
    for o in made:
        o.con.close()


def make(tmp_path, observers, rpc, clock=None, **kw):
    clock = clock or Clock()
    cfg = ob.ObserverConfig(db_path=str(tmp_path / 'o.db'), anchor_without_backfill=False, **kw)
    o = ob.Observer(cfg, rpc, clock=clock, sleep=clock.sleep)
    observers.append(o)
    o.start()
    return o


def rows(o, sql):
    return o.con.execute(sql).fetchall()


def test_signed_fixture_decode_store_idempotent_matches_decoder(tmp_path, observers):
    txs = load()
    rpc = Rpc(txs)
    o = make(tmp_path, observers, rpc)
    o.poll_once()
    stored = {(r[0], r[1]): r[2] for r in rows(o, 'SELECT signature,kind,decoded FROM events')}
    # decoder #189 and collector #184 agree on every signed fixture: same trades, same side
    for sig, tx in txs.items():
        kinds = {d.kind for d, _, _ in D.classify_transaction(tx)}
        assert kinds == {'buy', 'trade_event'} or kinds == {'sell', 'trade_event'}, sig
        side = 'buy' if 'buy' in kinds else 'sell'
        assert (sig, f'launchlab_trade_{side}') in stored
    assert len(stored) == len(txs) and all(v == 1 for v in stored.values())
    assert o.pending_count() == 0
    n_calls = len(rpc.calls)
    o.poll_once()                               # replay: cursor => nothing new to fetch
    assert rows(o, 'SELECT COUNT(*) FROM events')[0][0] == len(txs)
    assert [c for c in rpc.calls[n_calls:] if c == 'getTransaction'] == []
    # restart on the same DB: checkpoint/cursor survive, still no duplicates
    o2 = make(tmp_path, observers, rpc)
    o2.poll_once()
    assert rows(o2, 'SELECT COUNT(*) FROM events')[0][0] == len(txs)


def test_two_paginations_cover_same_signatures_without_duplicates(tmp_path, observers, monkeypatch):
    txs = load()
    monkeypatch.setattr(ob, 'PAGE', 2)         # force multi-page enumeration (7 txs, pages of 2)
    rpc = Rpc(txs)
    o = make(tmp_path, observers, rpc)
    o.poll_once()
    # per-poll enumeration cap (3 pages x 2) leaves the oldest signature for the NEXT poll;
    # the cursor must not advance past the unfinished range (no silent skip).
    assert len(rows(o, 'SELECT signature FROM seen')) == ob.MAX_ENUM_PAGES_PER_POLL * 2
    assert o._get(f'cursor:{ob.LAUNCHLAB_PROGRAM}') is None
    assert o._get(f'enum_before:{ob.LAUNCHLAB_PROGRAM}') is not None
    o.poll_once()
    assert o._get(f'enum_before:{ob.LAUNCHLAB_PROGRAM}') is None
    seen = {r[0] for r in rows(o, 'SELECT signature FROM seen')}
    st = BackfillState(address=ob.LAUNCHLAB_PROGRAM)
    run_backfill(st, lambda a, before, until, limit: ob.page_signatures(
        rpc.order, rpc.slots, [a, {'before': before, 'until': until, 'limit': limit}]),
        page_size=2, max_pages=10)
    assert st.complete and not st.gap
    assert set(st.seen) == seen == set(txs)    # same set, one entry per signature
    again = len(st.seen)
    run_backfill(st, lambda *a: pytest.fail('complete state must not fetch'))
    assert len(st.seen) == again
    # known semantic differences (documented): backfill abort on non-monotonic slots,
    # observer does not; backfill keeps failed txs apart, observer skips err rows.
    bad = BackfillState(address='x')
    pages = [[{'signature': 'a', 'slot': 5, 'err': None}, {'signature': 'b', 'slot': 9, 'err': None}]]
    with pytest.raises(BackfillError):
        run_backfill(bad, lambda *a: pages.pop(0), page_size=2)


def test_backfill_page_cap_is_a_gap_not_complete():
    txs = load()
    rpc = Rpc(txs)
    st = BackfillState(address=ob.LAUNCHLAB_PROGRAM)
    run_backfill(st, lambda a, b, u, n: ob.page_signatures(rpc.order, rpc.slots,
                 [a, {'before': b, 'until': u, 'limit': n}]), page_size=2, max_pages=2)
    assert not st.complete and st.gap == 'page_cap_reached_before_until'
    assert len(st.seen) == 4


def test_no_lookahead_causality_flag(tmp_path, observers):
    txs = load()
    early = datetime.fromtimestamp(min(t['blockTime'] for t in txs.values()) - 3600, timezone.utc)
    o = make(tmp_path, observers, Rpc(txs), clock=Clock(early))
    o.poll_once()
    assert {r[0] for r in rows(o, 'SELECT causality FROM events')} == {'violation_recv_before_chain'}
    # ledger side: a quote can only be built from causality == 'ok' rows (see adapter below)
    assert all(adapt(r) is None for r in rows(o, 'SELECT causality,payload_json FROM events'))


def test_gaps_and_none_transactions(tmp_path, observers):
    txs = load()
    victim = next(iter(txs))
    no_time = copy.deepcopy(txs)
    for t in no_time.values():
        t['blockTime'] = None
    o = make(tmp_path, observers, Rpc(txs, missing={victim}))
    for _ in range(ob.MAX_TX_ATTEMPTS):
        o.poll_once()
    assert rows(o, "SELECT outcome FROM seen WHERE signature=?".replace('?', f"'{victim}'")) \
        == [('dead_letter',)]
    reasons = {r[0] for r in rows(o, 'SELECT reason FROM gaps')}
    assert {'transaction_unavailable', 'transaction_unavailable_dead_letter'} <= reasons
    assert rows(o, f"SELECT COUNT(*) FROM events WHERE signature='{victim}'")[0][0] == 0
    ev, _ = ob.normalise_transaction(next(iter(no_time.values())), '2026-11-06T08:00:00.000000Z')
    assert {e['causality'] for e in ev} == {'chain_time_unknown'}


def test_quota_is_hard_and_persistent(tmp_path, observers):
    rpc = Rpc(load())
    o = make(tmp_path, observers, rpc, max_requests_total=5)
    with pytest.raises(ob.QuotaExhausted):
        o.poll_once()
    assert len(rpc.calls) <= 5 and o.requests_used() == 5
    n = len(rpc.calls)
    o2 = make(tmp_path, observers, rpc, max_requests_total=5)   # restart cannot reset it
    with pytest.raises(ob.QuotaExhausted):
        o2.poll_once()
    assert len(rpc.calls) == n
    with pytest.raises(ob.DisallowedMethod):
        o2.rpc.call('sendTransaction', [])


def _with_instruction(tx, program, name):
    t = copy.deepcopy(tx)
    keys = t['transaction']['message']['accountKeys']
    keys = [k if isinstance(k, str) else k['pubkey'] for k in keys]
    t['transaction']['message']['instructions'].append(
        {'programIdIndex': keys.index(program), 'accounts': [],
         'data': b58encode(D.anchor_ix(name) + b'\0' * 8)})
    return t


def test_creation_migration_cpmm_unproven_on_both_sides():
    """Synthetic instruction bytes (NOT a real tx): both modules must refuse to call them proven."""
    base = next(iter(load().values()))
    for name in ('initialize', 'migrate_to_cpswap'):
        t = _with_instruction(base, ob.LAUNCHLAB_PROGRAM, name)
        top = [d for d, loc, _ in D.classify_transaction(t) if loc.startswith('top')]
        assert top and top[-1].kind == 'unproven' and top[-1].evidence == D.DERIVED_UNVERIFIED
        ev, mig = ob.normalise_transaction(t, '2026-11-06T08:00:00.000000Z')
        kinds = {e['kind'] for e in ev}
        assert ('launchlab_create' if name == 'initialize' else 'launchlab_migrate') in kinds
        assert all(e['pool'] == 'unknown' for e in ev if e['decoded'] == 0)
        assert all(m['status'] == 'unproven' and m['launchlab_pool'] == 'unknown' for m in mig)
    assert D.link_evidence([])['cpmm_pool'] == 'unproven'
    assert ob.DISCRIMINATORS_CONFIRMED is False


LEDGER_KEYS = {"id", "mint", "pool", "venue", "side", "input_atomic", "output_atomic",
               "source_slot", "available_at_ms", "source_produced_at_ms",
               "source_observation_sha256", "provenance", "network_and_priority_fee_lamports",
               "account_creation_fee_lamports", "failed_attempt_fee_lamports", "migration_proof"}


def adapt(row):
    """Best-effort map observer event -> ledger quote keys. Returns None (fail-closed) when the
    event is not causally ok; otherwise returns ONLY the fields the event really carries."""
    causality, payload = row[0], json.loads(row[1])
    if causality != 'ok':
        return None
    return {'input_atomic': payload['amount_in'], 'output_atomic': payload['amount_out']}


def test_ledger_contract_gap_matrix_is_explicit(tmp_path, observers):
    o = make(tmp_path, observers, Rpc(load()))
    o.poll_once()
    carried = set()
    for r in rows(o, 'SELECT causality,payload_json FROM events'):
        a = adapt(r)
        assert a is not None
        carried |= set(a)
    # from signed events: pool (events.pool), signature, slot, side, venue, amounts are available;
    # the ledger ALSO needs mint, SOL/network/ATA fees, source clock ms, observation sha, proof.
    missing = LEDGER_KEYS - carried - {'id', 'pool', 'venue', 'side', 'source_slot'}
    assert {'mint', 'network_and_priority_fee_lamports', 'account_creation_fee_lamports',
            'failed_attempt_fee_lamports', 'provenance', 'migration_proof'} <= missing
    with pytest.raises(ValueError, match='exact_quote_evidence_required'):
        source_quote(dict(adapt(rows(o, 'SELECT causality,payload_json FROM events')[0]),
                          id='x', pool='p'))
    with sqlite3.connect(':memory:') as con:      # no creator/mint column exists in the store
        con.executescript(ob.SCHEMA)
        cols = {c[1] for c in con.execute('PRAGMA table_info(events)')}
    assert not ({'mint', 'creator', 'sol_leg'} & cols)
