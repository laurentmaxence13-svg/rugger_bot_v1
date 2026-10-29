"""Synthetic scanner/ledger integration; never starts a real scanner."""
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bot.analyser import paper_engine as pe
from bot.analyser import paper_trader as pt
from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID as PROGRAM


NOW = 1000
QUOTE = pt.MarketQuote(20000, 1, 'pair', quote_source='dex_market')


def database(path=':memory:'):
    con = sqlite3.connect(path, isolation_level=None, timeout=0)
    pt.setup(con)
    pe.ensure_signal_status_schema(con)
    pe.ensure_audit_schema(con)
    con.execute('CREATE TABLE launch_candidates(id INTEGER PRIMARY KEY, mint, '
                'deployer_candidate, block_time, status, pool_state)')
    con.execute("INSERT INTO launch_candidates VALUES(1,'mint','creator',980,'creator_identified',NULL)")
    con.execute('CREATE TABLE scanner_backfill_state(program_id PRIMARY KEY, '
                'history_status,reason,ws_state,checked_at,cursor_signature,cursor_slot)')
    con.execute('CREATE TABLE scanner_tx_recovery(signature PRIMARY KEY,slot)')
    return con


def state(con, history='caught_up', ws='subscribed', checked=NOW, reason=None):
    con.execute('INSERT OR REPLACE INTO scanner_backfill_state VALUES(?,?,?,?,?,?,?)',
                (PROGRAM, history, reason, ws, checked, 'anchor', 7))
    con.execute("INSERT OR REPLACE INTO scanner_tx_recovery VALUES('anchor',7)")


def args(db, **overrides):
    values = dict(db=db, model=None, poll=15, report=None, max_open=3,
                  max_entries_day=20, max_daily_loss=10, max_candidates=10,
                  max_age=7200, cache_refresh=60, no_live_behavior=True,
                  rpc_interval=2.5, behavior_max_tx=10, min_liquidity=1000,
                  shadow_baseline=False, shadow_final=True, capital_sol=10,
                  position_pct=10, session_seconds=1, session_report=None,
                  no_scanner=False)
    values.update(overrides)
    return SimpleNamespace(**values)


async def cycle(con, guard=None, now=NOW, quote=QUOTE, during=None, **kwargs):
    async def fetch(*a, **k):
        await asyncio.sleep(0)
        if during:
            during()
        return quote, 0
    with patch.object(pe, 'fetch_quote', fetch), patch.object(pe.time, 'time', return_value=now):
        return await pe.collect_once(con, None, [], now, strategy_mode='shadow_final',
                                     entry_guard=guard, **kwargs)


def permission(con):
    return con.execute('SELECT enter,entry_allowed FROM paper_decisions ORDER BY id DESC LIMIT 1').fetchone()


def test_reproduced_decision_must_include_scanner_refusal():
    with closing(database()) as con:
        asyncio.run(cycle(con, lambda: False))
        assert permission(con) == (1, 0)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


def test_reproduced_live_degraded_supervised_scanner_must_deny(tmp_path):
    db = tmp_path / 'synthetic.db'
    with closing(database(db)) as con:
        seen = []
        async def scanner(**kwargs):
            state(con, 'degraded', reason='synthetic')
            await asyncio.Event().wait()
        async def engine(*a, **kwargs):
            await cycle(con, kwargs['entry_guard'])
            seen.append(permission(con))
        with patch('bot.main.run', scanner), patch.object(pe, 'run', engine), \
                patch.object(pe.time, 'time', return_value=NOW):
            asyncio.run(pe.run_with_scanner(args(db)))
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
        assert seen == [(1, 0)]


@pytest.fixture
def guarded(tmp_path):
    db = tmp_path / 'synthetic.db'
    with closing(database(db)) as con:
        task = SimpleNamespace(stopped=False, cancelling_now=False)
        task.done = lambda: task.stopped
        task.cancelling = lambda: int(task.cancelling_now)
        task.get_name = lambda: 'synthetic-child'
        task.scanner_health = pe.ScannerHealth()
        task.scanner_health.tasks.append(task)  # Test double for a healthy monitored child.
        with patch.object(pe.time, 'time', return_value=NOW-1):
            guard = pe._ScannerEntryGuard(db, task)
        state(con)
        yield con, guard, task


def test_healthy_actual_entry(guarded):
    con, guard, _ = guarded
    messages, _, _ = asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 1)
    assert con.execute('SELECT status,position_sol FROM paper_trades').fetchone() == ('open', 1.0)
    assert con.execute('SELECT status FROM paper_signal_status').fetchone() == ('TRADE_PAPER_OUVERT',)
    assert any(m.startswith('ENTRY ') for m in messages)
    assert pt.paper_capital(con) == (10, 10)


@pytest.mark.parametrize('history,ws,reason', [
    ('degraded', 'subscribed', 'synthetic'), ('caught_up', 'disconnected', None),
    ('caught_up', 'subscription_refused', None), ('catching_up', 'subscribed', None),
    ('uninitialized', 'subscribed', None),
    ('baseline', 'subscribed', 'bootstrap_recent_window_only'),
    ('unknown', 'subscribed', None), ('caught_up', 'unknown', None),
    ('caught_up', 'subscribed', 'unresolved_gap'),
])
def test_unhealthy_observations_continue_without_entry(guarded, history, ws, reason):
    con, guard, _ = guarded
    state(con, history, ws, reason=reason)
    asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (1,)
    assert con.execute('SELECT status FROM paper_signal_status').fetchone() == ('REJET',)
    assert pt.paper_capital(con) == (10, 10)


@pytest.mark.parametrize('field,value', [
    ('checked_at', 998), ('checked_at', 1001), ('checked_at', None),
    ('checked_at', 'invalid'), ('checked_at', float('inf')),
    ('cursor_signature', None), ('cursor_signature', ''),
    ('cursor_slot', None), ('cursor_slot', -1), ('cursor_slot', 'invalid'),
    ('program_id', 'different_program'),
])
def test_caught_up_needs_coherent_fresh_state(guarded, field, value):
    con, guard, _ = guarded
    con.execute(f'UPDATE scanner_backfill_state SET {field}=?', (value,))
    asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)


@pytest.mark.parametrize('cancel', [False, True])
def test_stopped_or_cancelling_task(guarded, cancel):
    con, guard, task = guarded
    task.stopped, task.cancelling_now = not cancel, cancel
    asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)


@pytest.mark.parametrize('table', ['scanner_backfill_state', 'scanner_tx_recovery'])
def test_missing_table(guarded, table):
    con, guard, _ = guarded
    con.execute(f'DROP TABLE {table}')
    asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)


def test_cursor_receipt_must_match(guarded):
    con, guard, _ = guarded
    con.execute('UPDATE scanner_tx_recovery SET slot=8')
    asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)
    con.execute('DELETE FROM scanner_tx_recovery')
    assert not guard.allows(con)


def test_sqlite_read_error_is_denial(guarded):
    con, guard, _ = guarded
    con.set_authorizer(lambda action, table, *a:
                       sqlite3.SQLITE_DENY if table == 'scanner_backfill_state' else sqlite3.SQLITE_OK)
    try:
        asyncio.run(cycle(con, guard))
        assert permission(con) == (1, 0)
    finally:
        con.set_authorizer(None)


def test_custom_guard_sqlite_exception_is_denial():
    def broken():
        raise sqlite3.OperationalError('synthetic locked')
    with closing(database()) as con:
        asyncio.run(cycle(con, broken))
        assert permission(con) == (1, 0)


def test_status_changes_during_quote_await(guarded):
    con, guard, _ = guarded
    asyncio.run(cycle(con, guard, during=lambda: state(con, 'degraded', reason='during_quote')))
    assert permission(con) == (1, 0)


def test_status_changes_during_behavior_await(guarded):
    con, guard, _ = guarded
    async def refresh(creator):
        await asyncio.sleep(0)
        state(con, 'degraded', reason='during_behavior')
        return False
    asyncio.run(cycle(con, guard, live_fetcher=SimpleNamespace(refresh=refresh)))
    assert permission(con) == (1, 0)


def test_status_changes_before_decision_and_record_quote(guarded):
    con, guard, _ = guarded
    original = pe.decide
    def decide(*a, **k):
        decision = original(*a, **k)
        state(con, 'degraded', reason='before_decision_write')
        return decision
    with patch.object(pe, 'decide', decide):
        asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


@pytest.mark.parametrize('price,exit_reason,pnl', [(1.2, 'TP', .18), (.8, 'SL', -.22)])
def test_degraded_keeps_tp_sl_and_replay_does_not_duplicate_pnl(guarded, price, exit_reason, pnl):
    con, guard, _ = guarded
    asyncio.run(cycle(con, guard))
    state(con, 'degraded', checked=1001, reason='synthetic')
    quote = pt.MarketQuote(20000, price, 'pair', quote_source='dex_market')
    messages, _, _ = asyncio.run(cycle(con, guard, now=1001, quote=quote))
    assert permission(con) == (1, 0)
    status, reason, actual = con.execute('SELECT status,exit_reason,pnl_sol FROM paper_trades').fetchone()
    assert (status, reason) == ('closed', exit_reason)
    assert actual == pytest.approx(pnl)
    assert any(m.startswith('EXIT ') for m in messages)
    assert con.execute('SELECT status FROM paper_signal_status').fetchone() == ('TRADE_PAPER_FERME',)
    capital = pt.paper_capital(con)
    asyncio.run(cycle(con, guard, now=1001, quote=quote))
    asyncio.run(cycle(con, guard, now=1002, quote=quote))
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)
    assert pt.paper_capital(con) == capital
    assert capital[0] == 10
    assert capital[1] == pytest.approx(10+pnl)


def test_financial_denial_is_not_bypassed(guarded):
    con, guard, _ = guarded
    asyncio.run(cycle(con, guard, max_open=0))
    assert permission(con) == (1, 0)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


def test_atomic_financial_recheck_stays_active(guarded):
    con, guard, _ = guarded
    seen = []
    def refuse(con, *a, **k):
        seen.append(con.in_transaction)
        return False
    with patch.object(pt, 'entry_allowed', refuse):
        asyncio.run(cycle(con, guard))
    assert seen == [True]
    assert permission(con) == (1, 1)  # Permission does not promise execution.
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert con.execute('SELECT status FROM paper_signal_status').fetchone() == ('DECISION_ENTRY',)


def test_reconnection_rechecks_without_forcing_strategy(guarded):
    con, guard, _ = guarded
    state(con, 'degraded', reason='disconnect')
    asyncio.run(cycle(con, guard))
    state(con, checked=1001)
    asyncio.run(cycle(con, guard, now=1001,
                      quote=pt.MarketQuote(0, 1, 'pair', quote_source='dex_market')))
    assert permission(con) == (0, 1)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    asyncio.run(cycle(con, guard, now=1002))
    assert permission(con) == (1, 1)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_restart_rejects_persisted_healthy_row_until_new_check(guarded):
    con, guard, task = guarded
    state(con, checked=1001)
    with patch.object(pe.time, 'time', return_value=1001):
        restarted = pe._ScannerEntryGuard(guard.db, task)
        assert not restarted.allows(con)
    with patch.object(pe.time, 'time', return_value=1002):
        assert not restarted.allows(con)
        state(con, checked=1002)
        assert restarted.allows(con)


def test_state_freshness_expires(guarded):
    con, guard, _ = guarded
    with patch.object(pe.time, 'time', return_value=1120):
        assert guard.allows(con)
    asyncio.run(cycle(con, guard, now=1121))
    assert permission(con) == (1, 0)


def test_sqlite_lock_prevents_status_change_between_permission_and_insertion(guarded):
    con, guard, _ = guarded
    original = pe.record_decision
    blocked = []
    def recorded(*a, **k):
        with closing(sqlite3.connect(guard.db, timeout=0, isolation_level=None)) as other:
            assert other.execute('SELECT history_status FROM scanner_backfill_state').fetchone() == ('caught_up',)
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute("UPDATE scanner_backfill_state SET history_status='degraded'")
            blocked.append(True)
        return original(*a, **k)
    with patch.object(pe, 'record_decision', recorded):
        asyncio.run(cycle(con, guard))
    assert blocked == [True]
    assert permission(con) == (1, 1)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_exclusive_lock_does_not_authorize_from_old_state(guarded):
    con, guard, _ = guarded
    con.execute('BEGIN EXCLUSIVE')
    try:
        with patch.object(pe.time, 'time', return_value=NOW):
            assert not guard()
    finally:
        con.rollback()


def test_concurrent_collections_do_not_duplicate_entry(guarded):
    con, guard, _ = guarded
    async def fetch(*a, **k):
        await asyncio.sleep(0)
        return QUOTE, 0
    async def both():
        with patch.object(pe, 'fetch_quote', fetch), patch.object(pe.time, 'time', return_value=NOW):
            await asyncio.gather(*(pe.collect_once(con, None, [], NOW,
                strategy_mode='shadow_final', entry_guard=guard) for _ in range(2)))
    asyncio.run(both())
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)
    assert con.execute('SELECT COUNT(*) FROM paper_decisions').fetchone() == (1,)
    assert pt.paper_capital(con) == (10, 10)


def test_daily_loss_date_guard_stays_fail_closed(guarded):
    con, guard, _ = guarded
    asyncio.run(cycle(con, guard))
    asyncio.run(cycle(con, guard, now=1001,
                      quote=pt.MarketQuote(20000, .8, 'pair', quote_source='dex_market')))
    con.execute('UPDATE paper_trades SET exit_time=NULL')
    con.execute("INSERT INTO launch_candidates VALUES(2,'new','creator',1000,'creator_identified',NULL)")
    before = con.execute('SELECT pnl_sol FROM paper_trades').fetchall(), pt.paper_capital(con)
    asyncio.run(cycle(con, guard, now=1002))
    assert con.execute("SELECT entry_allowed FROM paper_decisions WHERE mint='new'").fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)
    assert (con.execute('SELECT pnl_sol FROM paper_trades').fetchall(), pt.paper_capital(con)) == before


def test_explicit_no_scanner_keeps_standalone_contract(tmp_path):
    with closing(database(tmp_path/'synthetic.db')) as con:
        async def scanner(**kwargs):
            raise AssertionError('Scanner must not start')
        async def engine(*a, **kwargs):
            assert 'entry_guard' not in kwargs
            await cycle(con)
        with patch('bot.main.run', scanner), patch.object(pe, 'run', engine):
            asyncio.run(pe.run_with_scanner(args(tmp_path/'synthetic.db', no_scanner=True)))
        assert permission(con) == (1, 1)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_ledger_error_rolls_back_decision_price_and_entry(guarded):
    con, guard, _ = guarded
    con.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON paper_trades BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic'):
        asyncio.run(cycle(con, guard))
    for table in ('paper_trades', 'paper_decisions', 'paper_prices'):
        assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone() == (0,)
    assert con.execute('SELECT history_status FROM scanner_backfill_state').fetchone() == ('caught_up',)


def test_unreadable_initial_state_requires_subsequent_renewal(guarded):
    con, guard, task = guarded
    state(con, checked=1001)  # Future-dated row from an earlier process.
    with patch.object(pe.time, 'time', return_value=NOW), \
            patch.object(pe._ScannerEntryGuard, '_connect', side_effect=sqlite3.OperationalError('locked')):
        restarted = pe._ScannerEntryGuard(guard.db, task)
    with patch.object(pe.time, 'time', return_value=1002):
        assert not restarted.allows(con)
        assert not restarted.allows(con)
        state(con, checked=1002)
        assert restarted.allows(con)


def test_absent_database_is_never_created_by_guard(tmp_path):
    path = tmp_path / 'absent.db'
    task = SimpleNamespace(done=lambda: False, cancelling=lambda: 0)
    guard = pe._ScannerEntryGuard(path, task)
    assert not guard()
    assert not path.exists()


def test_empty_scanner_state_denies(guarded):
    con, guard, _ = guarded
    con.execute('DELETE FROM scanner_backfill_state')
    asyncio.run(cycle(con, guard))
    assert permission(con) == (1, 0)


def test_task_stops_during_quote_await(guarded):
    con, guard, task = guarded
    asyncio.run(cycle(con, guard, during=lambda: setattr(task, 'stopped', True)))
    assert permission(con) == (1, 0)


def test_healthy_supervised_wiring_uses_current_state(tmp_path):
    db = tmp_path/'synthetic.db'
    with closing(database(db)) as con:
        async def scanner(**kwargs):
            kwargs['health'].tasks.append(asyncio.current_task())
            kwargs['health'].observe_rpc(True)
            kwargs['health'].observe_websocket('subscribed')
            state(con)
            await asyncio.Event().wait()
        async def engine(*a, **kwargs):
            await cycle(con, kwargs['entry_guard'])
        with patch('bot.main.run', scanner), patch.object(pe, 'run', engine), \
                patch.object(pe.time, 'time', return_value=NOW):
            asyncio.run(pe.run_with_scanner(args(db)))
        assert permission(con) == (1, 1)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_locked_database_stops_collection_without_financial_write(guarded):
    con, guard, _ = guarded
    with closing(sqlite3.connect(guard.db, timeout=0, isolation_level=None)) as other:
        other.execute('BEGIN EXCLUSIVE')
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                asyncio.run(cycle(con, guard))
        finally:
            other.rollback()
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM paper_decisions').fetchone() == (0,)
