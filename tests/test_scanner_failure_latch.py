"""Fatal scanner health latches, publication failures and staged cleanup only."""
import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bot import main as scanner
from bot.analyser import paper_engine as pe
from bot.scanner.supervision import ScannerHealth
from bot.scanner.tx_recovery import recover_transactions
from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID as PROGRAM
from test_p1_final_audit import research_db, settings, error_graph
from test_scanner_entry_integrity import guarded


def test_nested_receiver_failure_is_latched_before_worker_cleanup():
    async def scenario():
        before = asyncio.all_tasks()
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        primary = RuntimeError('synthetic receiver failed')
        store = SimpleNamespace(lease_seconds=90, claim_due=lambda now: {'signature': 'synthetic'},
                                has_pending=lambda: True)
        async def feed():
            await entered.wait()
            raise primary
            yield  # A synthetic finite async iterator, never a real stream.
        async def fetch(signature):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        health = ScannerHealth()
        parent = health.start_task(recover_transactions(feed(), store, fetch, health=health),
                                   'synthetic-recovery-parent')
        await cleaning.wait()
        assert health.failed and not health.permits_entries()
        assert not parent.done()
        try:
            with pytest.raises(AttributeError):
                health.failed = False
        finally:
            release.set()
            with pytest.raises(RuntimeError) as raised:
                await parent
            assert raised.value is primary
        assert all(task.done() for task in health.tasks)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_cancel_before_monitored_child_starts_closes_its_coroutine():
    async def scenario():
        async def child():
            await asyncio.Event().wait()
        health = ScannerHealth()
        task = health.start_task(child(), 'cancelled-before-start')
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert not health.permits_entries()
    asyncio.run(scenario())


@pytest.mark.parametrize('publication_error', [False, True])
@pytest.mark.parametrize('rpc_error', [False, True])
def test_repeated_main_cancellation_preserves_every_cleanup_failure(research_db, publication_error, rpc_error):
    db, con, tmp = research_db
    state_error = sqlite3.OperationalError('synthetic state publication')
    close_error = ValueError('synthetic RPC close')
    async def scenario():
        before = asyncio.all_tasks()
        started, publishing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        closes = []
        class RPC:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                closes.append(True)
                if rpc_error:
                    raise close_error
        class Backfill:
            def __init__(self, *args):
                pass
            async def run(self):
                started.set()
                await asyncio.Event().wait()
            async def on_state(self, message):
                publishing.set()
                await release.wait()
                if publication_error:
                    raise state_error
        async def recovery(*args, **kwargs):
            await asyncio.Event().wait()
        health = ScannerHealth()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()), \
                patch.object(scanner, 'TransactionRecovery'), \
                patch.object(scanner, 'ProgramBackfill', Backfill), \
                patch.object(scanner, 'recover_transactions', recovery), \
                patch.object(scanner, 'stream_program_logs', return_value=object()):
            task = asyncio.create_task(scanner.run(db_path=db, health=health))
            await started.wait()
            task.cancel('first cancellation')
            await publishing.wait()
            assert health.failed and not task.done()
            assert not pe._ScannerEntryGuard(db, task, health=health).allows(object())
            task.cancel('second cancellation')
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError) as raised:
                await task
        assert raised.value.args == ('first cancellation',)
        errors = error_graph(raised.value)
        if publication_error:
            assert state_error in errors
        if rpc_error:
            assert close_error in errors
        assert closes == [True]
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


@pytest.mark.parametrize('close_fails', [False, True])
def test_partial_rpc_start_is_closed_and_primary_retained(research_db, close_fails):
    db, con, tmp = research_db
    primary, secondary = RuntimeError('RPC initialization after acquisition'), ValueError('RPC close')
    async def scenario():
        calls = []
        class RPC:
            async def __aenter__(self):
                calls.append('acquire')
                raise primary
            async def __aexit__(self, *args):
                calls.append('close')
                if close_fails:
                    raise secondary
        health = ScannerHealth()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()):
            with pytest.raises(RuntimeError) as raised:
                await scanner.run(db_path=db, health=health)
        assert raised.value is primary
        assert calls == ['acquire', 'close']
        assert health.failed
        if close_fails:
            assert secondary in error_graph(raised.value)
    asyncio.run(scenario())


def test_simultaneous_internal_errors_are_all_preserved(research_db):
    db, con, tmp = research_db
    first, second = RuntimeError('backfill'), LookupError('recovery')
    async def scenario():
        release = asyncio.Event()
        class Backfill:
            def __init__(self, *args):
                pass
            async def run(self):
                await release.wait()
                raise first
            async def on_state(self, message):
                pass
        class RPC:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        async def recovery(*args, **kwargs):
            release.set()
            raise second
        health = ScannerHealth()
        before = asyncio.all_tasks()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()), \
                patch.object(scanner, 'TransactionRecovery'), \
                patch.object(scanner, 'ProgramBackfill', Backfill), \
                patch.object(scanner, 'recover_transactions', recovery), \
                patch.object(scanner, 'stream_program_logs', return_value=object()):
            with pytest.raises(RuntimeError) as raised:
                await scanner.run(db_path=db, health=health)
        assert raised.value is first  # Deterministic acquisition order for simultaneous failures.
        assert first in error_graph(raised.value) and second in error_graph(raised.value)
        assert health.failed
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_only_new_supervision_with_renewed_sql_can_restore_permission(research_db):
    db, con, tmp = research_db
    con.execute('CREATE TABLE scanner_backfill_state(program_id PRIMARY KEY,history_status,'
                'reason,ws_state,checked_at,cursor_signature,cursor_slot)')
    con.execute('INSERT INTO scanner_backfill_state VALUES(?,?,?,?,?,?,?)',
                (PROGRAM, 'caught_up', None, 'subscribed', 1000, 'anchor', 7))
    con.execute('CREATE TABLE scanner_tx_recovery(signature PRIMARY KEY,slot)')
    con.execute("INSERT INTO scanner_tx_recovery VALUES('anchor',7)")
    async def scenario():
        health = ScannerHealth()
        health.fail('previous fatal error')
        parent = SimpleNamespace(done=lambda: False, cancelling=lambda: 0)
        with patch.object(pe.time, 'time', return_value=1001):
            old = pe._ScannerEntryGuard(db, parent, health=health)
        con.execute('UPDATE scanner_backfill_state SET checked_at=1001')
        assert not old.allows(con)
        new_health = ScannerHealth()
        child = new_health.start_task(asyncio.Event().wait(), 'healthy-new-child')
        with patch.object(pe.time, 'time', return_value=1001):
            new = pe._ScannerEntryGuard(db, parent, health=new_health)
            assert not new.allows(con)
        con.execute('UPDATE scanner_backfill_state SET checked_at=1002')
        with patch.object(pe.time, 'time', return_value=1002):
            assert new.allows(con)
            assert not old.allows(con)
        child.cancel()
        with pytest.raises(asyncio.CancelledError):
            await child
    asyncio.run(scenario())


def test_fresh_sql_cannot_enable_an_unstarted_health_channel(research_db):
    db, con, tmp = research_db
    parent = SimpleNamespace(done=lambda: False, cancelling=lambda: 0)
    guard = pe._ScannerEntryGuard(db, parent, health=ScannerHealth())
    assert not guard.allows(object())  # No SQLite access can be required to deny here.


def test_transport_failure_is_visible_before_async_socket_close():
    from bot.solana import websocket as ws
    async def scenario():
        before = asyncio.all_tasks()
        closing, release = asyncio.Event(), asyncio.Event()
        primary = ValueError('synthetic bad WebSocket payload')
        class Context:
            async def __aenter__(self):
                return object()
            async def __aexit__(self, *args):
                closing.set()
                await release.wait()
        health = ScannerHealth()
        async def receive():
            async with ws._observed_connection('synthetic://unused',
                    lambda error: health.fail('transport', error)):
                raise primary
        with patch.object(ws.websockets, 'connect', return_value=Context()):
            task = health.start_task(receive(), 'socket-receiver')
            await closing.wait()
            assert health.failed and health.failure_event.is_set() and not task.done()
            release.set()
            with pytest.raises(ValueError) as raised:
                await task
            assert raised.value is primary
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_failed_transport_notification_does_not_replace_original_error():
    from bot.solana import websocket as ws
    primary, secondary = ValueError('payload'), RuntimeError('notification')
    class Context:
        async def __aenter__(self):
            return object()
        async def __aexit__(self, *args):
            pass
    def notification(error):
        raise secondary
    async def scenario():
        with patch.object(ws.websockets, 'connect', return_value=Context()):
            with pytest.raises(ValueError) as raised:
                async with ws._observed_connection('synthetic://unused', notification):
                    raise primary
        assert raised.value is primary and secondary in error_graph(primary)
    asyncio.run(scenario())


def test_live_sql_publication_failure_latches_before_stream_teardown(research_db):
    db, con, tmp = research_db
    primary = sqlite3.OperationalError('synthetic subscribed publication')
    async def scenario():
        before = asyncio.all_tasks()
        closing, release = asyncio.Event(), asyncio.Event()
        class RPC:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Backfill:
            def __init__(self, *args):
                pass
            async def run(self):
                await asyncio.Event().wait()
            async def on_state(self, message):
                if message['state'] == 'subscribed':
                    raise primary
        async def stream(*args, on_state, on_failure):
            try:
                await on_state({'state': 'subscribed'})
            except BaseException:
                closing.set()
                await release.wait()
                raise
            yield
        async def recovery(source, *args, **kwargs):
            await anext(source)
        health = ScannerHealth()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()), \
                patch.object(scanner, 'ProgramBackfill', Backfill), \
                patch.object(scanner, 'TransactionRecovery'), \
                patch.object(scanner, 'recover_transactions', recovery), \
                patch.object(scanner, 'stream_program_logs', stream):
            task = asyncio.create_task(scanner.run(db_path=db, health=health))
            await closing.wait()
            assert health.failed and health.failure_event.is_set()
            assert not pe._ScannerEntryGuard(db, task, health=health).allows(object())
            release.set()
            with pytest.raises(sqlite3.OperationalError) as raised:
                await task
            assert raised.value is primary
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_real_scanner_supervision_requires_fresh_verified_state_then_allows_entry(research_db):
    from bot.analyser.paper_trader import MarketQuote
    from bot.analyser.final_decision_engine import Decision
    from unittest.mock import AsyncMock
    db, con, tmp = research_db
    con.execute('CREATE TABLE scanner_backfill_state(program_id PRIMARY KEY,history_status,'
                'reason,ws_state,checked_at,cursor_signature,cursor_slot)')
    con.execute('INSERT INTO scanner_backfill_state VALUES(?,?,?,?,?,?,?)',
                (PROGRAM, 'caught_up', None, 'subscribed', 999, 'anchor', 7))
    con.execute('CREATE TABLE scanner_tx_recovery(signature PRIMARY KEY,slot)')
    con.execute("INSERT INTO scanner_tx_recovery VALUES('anchor',7)")
    con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,detected_at,'
                'mint,deployer_candidate,status) VALUES(?,?,?,?,?,?,?,?)',
                ('ray', 'candidate', 1, 980, '1970-01-01T00:16:30+00:00',
                 'mint', 'creator', 'creator_identified'))
    async def scenario():
        now = 1000
        fresh = asyncio.Event()
        before = asyncio.all_tasks()
        class RPC:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Backfill:
            def __init__(self, *args):
                pass
            async def run(self):
                nonlocal now
                now = 1001
                con.execute('UPDATE scanner_backfill_state SET checked_at=1001')
                # A renewed SQL cursor alone is no longer transport health.
                task.scanner_health.observe_rpc(True)
                task.scanner_health.observe_websocket('subscribed')
                fresh.set()
                await asyncio.Event().wait()
            async def on_state(self, message):
                con.execute("UPDATE scanner_backfill_state SET ws_state='disconnected'")
        async def recovery(*args, **kwargs):
            await asyncio.Event().wait()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()), \
                patch.object(scanner, 'ProgramBackfill', Backfill), \
                patch.object(scanner, 'TransactionRecovery'), \
                patch.object(scanner, 'recover_transactions', recovery), \
                patch.object(scanner, 'stream_program_logs', return_value=object()), \
                patch.object(pe.time, 'time', side_effect=lambda: now):
            task = asyncio.create_task(scanner.run(db_path=db))
            guard = pe._ScannerEntryGuard(db, task)
            assert not guard.allows(con)  # No channel/verified new state yet.
            await fresh.wait()
            try:
                assert guard.allows(con)
                decision = Decision(enter=True, score=56, reasons=('synthetic',), risk_flags=(),
                    tp_pct=10, sl_pct=8, hold_seconds=300, trailing_stop_pct=None, cost_bps=200)
                with patch.object(pe, 'fetch_quote', AsyncMock(return_value=(MarketQuote(20000, .001, 'pair'), 0))), \
                        patch.object(pe, 'decide', return_value=decision):
                    await pe.collect_once(con, None, [], now, strategy_mode='shadow_final', entry_guard=guard)
                assert con.execute('SELECT status,position_sol FROM paper_trades').fetchone() == ('open', 1)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert not guard.allows(con)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


@pytest.mark.parametrize('price,reason,pnl', [(1.2, 'TP', .18), (.8, 'SL', -.22)])
def test_latched_failure_still_manages_existing_position(guarded, price, reason, pnl):
    from bot.analyser import paper_trader as trader
    from test_scanner_entry_integrity import cycle
    con, guard, task = guarded
    asyncio.run(cycle(con, guard))
    task.scanner_health.fail('synthetic internal failure')
    asyncio.run(cycle(con, guard, now=1001,
        quote=trader.MarketQuote(20000, price, 'pair', quote_source='dex_market')))
    row = con.execute('SELECT status,exit_reason,pnl_sol FROM paper_trades').fetchone()
    assert row[:2] == ('closed', reason) and row[2] == pytest.approx(pnl)
    assert trader.paper_capital(con)[1] == pytest.approx(10 + pnl)
    assert not guard.allows(con)
