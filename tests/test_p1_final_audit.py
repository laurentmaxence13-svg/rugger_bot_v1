"""P1 scanner/temporal safety and raw transaction-date provenance regressions.

Corrected properties are asserted positively, including refusal of saved-date fallback.
Only synthetic databases, prices, settings and scanner child tasks are used.
"""
import asyncio
from contextlib import closing
import csv
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot import main as scanner
from bot.analyser import paper_engine as pe, research_pipeline as research, behavior_pipeline as behavior
from bot.analyser.paper_trader import MarketQuote, setup, ensure_paper_portfolio
from bot.analyser.final_decision_engine import Decision
from bot.database.db import Database
from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID as PROGRAM
from test_complete_launch_export import payload


@pytest.fixture
def research_db(tmp_path):
    db = tmp_path / 'synthetic.db'
    Database(db)
    pe.ensure_schema(db)
    with closing(sqlite3.connect(db, isolation_level=None)) as con:
        setup(con)
        pe.ensure_signal_status_schema(con)
        pe.ensure_audit_schema(con)
        ensure_paper_portfolio(con, 10, 1000)
        yield db, con, tmp_path


def corpus(con, tmp, count=50, *, tied=True):
    if tied:
        tx = payload([(f'm{i:03}', 'creator', f'pool{i:03}') for i in range(count)], 1000)
        con.execute('INSERT INTO research_tx_cache VALUES(?,?,1,?)', ('shared-transaction', json.dumps(tx), 'synthetic'))
    else:
        for i in range(count):
            tx = payload([(f'm{i:03}', 'creator', f'pool{i:03}')], 1000 + i * 10)
            con.execute('INSERT INTO research_tx_cache VALUES(?,?,1,?)', (f'sig{i:03}', json.dumps(tx), 'synthetic'))
    price_path = tmp / 'synthetic-prices.csv'
    with price_path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['mint', 'timestamp', 'price_usd'])
        for i in range(count):
            when = 1000 if tied else 1000 + i * 10
            for delay, price in ((60, 1), (300, 1.05), (900, 1.1), (3660, 1.2)):
                writer.writerow([f'm{i:03}', when + delay, price])
    return price_path


def test_same_transaction_timestamp_cannot_cross_train_test(research_db):
    db, con, tmp = research_db
    prices = corpus(con, tmp)
    before = list(con.iterdump())
    events = research.verified_launches(db)
    split = int(len(events) * .7)
    assert {e[1] for e in events[:split]} & {e[1] for e in events[split:]} == {'shared-transaction'}
    with pytest.raises(ValueError, match='Observations complètes insuffisantes'):
        research.backtest(db, prices)  # No disjoint boundary: never relax 30/15 minima.
    assert list(con.iterdump()) == before


def test_future_training_labels_are_rejected(research_db):
    db, con, tmp = research_db
    prices = corpus(con, tmp, count=60, tied=False)
    with pytest.raises(ValueError, match='purges temporelles'):
        research.backtest(db, prices)  # All candidate training outcomes are still in the future.


def test_creator_prior_return_is_causal(research_db):
    db, con, tmp = research_db
    prices = corpus(con, tmp)
    seen = []
    original = behavior._causal_creator_mean
    def causal(*args):
        value = original(*args)
        seen.append(value)
        return value
    with patch.object(behavior, '_causal_creator_mean', causal):
        result = behavior.behavior_backtest(db, prices)
    assert result['status'] == 'insufficient_data'
    assert len(seen) == 50 and all(value is None for value in seen)


def test_saved_date_fallback_cannot_override_missing_entry_provenance(research_db):
    db, con, tmp = research_db
    tx = payload([('a', 'creator', 'pool')], None)
    con.execute('INSERT INTO research_tx_cache VALUES(?,?,1,?)', ('legacy-sig', json.dumps(tx), 'synthetic'))
    con.execute('INSERT INTO research_launches(signature,creator,mint,block_time,updated_at) '
                'VALUES(?,?,?,?,?)', ('legacy-sig', 'creator', 'a', 980, 'synthetic'))
    con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,detected_at,'
                'mint,deployer_candidate,status,pool_state) VALUES(?,?,?,?,?,?,?,?,?)',
                ('ray', 'legacy-sig:a', 1, 980, '1970-01-01T00:16:30+00:00',
                 'a', 'creator', 'creator_identified', 'pool'))
    assert research.verified_launches(db) == []
    assert pe.recent_candidates(con, 1100) == []
    report = pe.paper_report(con, 1100, 0)
    assert report['launch_time_diagnostics']['undated_mints'] == 1
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


def error_graph(error):
    found, pending = [], [error]
    while pending:
        item = pending.pop()
        if item is None or any(item is old for old in found):
            continue
        found.append(item)
        pending.extend((item.__cause__, item.__context__))
        pending.extend(e for _, e in getattr(item, 'paper_failures', ()))
    return found


class RPC:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


def settings(db):
    return SimpleNamespace(db_path=db, rpc_url='synthetic://unused', ws_url='synthetic://unused',
                           raydium_launchpad_program_id=PROGRAM)


@pytest.mark.parametrize('publication_fails', [False, True])
def test_internal_scanner_failure_denies_entry_during_cleanup(research_db, publication_fails):
    db, con, tmp = research_db
    con.execute('CREATE TABLE scanner_backfill_state(program_id PRIMARY KEY, history_status,'
                'reason,ws_state,checked_at,cursor_signature,cursor_slot)')
    con.execute('INSERT INTO scanner_backfill_state VALUES(?,?,?,?,?,?,?)',
                (PROGRAM, 'caught_up', None, 'subscribed', 999, 'anchor', 7))
    con.execute('CREATE TABLE scanner_tx_recovery(signature PRIMARY KEY,slot)')
    con.execute("INSERT INTO scanner_tx_recovery VALUES('anchor',7)")
    con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,detected_at,'
                'mint,deployer_candidate,status) VALUES(?,?,?,?,?,?,?,?)',
                ('ray', 'candidate', 1, 980, '1970-01-01T00:16:30+00:00',
                 'mint', 'creator', 'creator_identified'))
    failure = RuntimeError('synthetic internal backfill failure')
    publication_error = sqlite3.OperationalError('synthetic publication failure')
    async def scenario():
        now = 1000
        ready, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Backfill:
            def __init__(self, *args):
                pass
            async def run(self):
                nonlocal now
                await ready.wait()
                now = 1001
                con.execute('UPDATE scanner_backfill_state SET checked_at=1001')
                raise failure
            async def on_state(self, message):
                if publication_fails:
                    raise publication_error
                con.execute("UPDATE scanner_backfill_state SET ws_state='disconnected',history_status='degraded'")
        async def recovery(*args, **kwargs):
            ready.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                draining.set()
                await release.wait()  # Deliberately delayed, finite, synthetic cleanup.
        original_getenv = pe.os.getenv
        before = asyncio.all_tasks()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()), \
                patch.object(scanner, 'TransactionRecovery'), \
                patch.object(scanner, 'ProgramBackfill', Backfill), \
                patch.object(scanner, 'recover_transactions', recovery), \
                patch.object(scanner, 'stream_program_logs', return_value=object()), \
                patch.object(pe.time, 'time', side_effect=lambda: now), \
                patch.object(pe.os, 'getenv', side_effect=lambda name, default=None:
                             PROGRAM if name == 'RAYDIUM_LAUNCHPAD_PROGRAM_ID' else original_getenv(name, default)):
            task = asyncio.create_task(scanner.run(db_path=db))
            guard = pe._ScannerEntryGuard(db, task)
            await draining.wait()
            try:
                assert not task.done() and not task.cancelling()
                assert guard() is False  # Failed child is latched before parent's cleanup completes.
                con.execute("UPDATE scanner_backfill_state SET history_status='caught_up',ws_state='subscribed',checked_at=1001")
                assert guard() is False  # Fresh SQL cannot reset an in-memory failure.
                decision = Decision(enter=True, score=56, reasons=('synthetic',), risk_flags=(),
                    tp_pct=10, sl_pct=8, hold_seconds=300, trailing_stop_pct=None, cost_bps=200)
                with patch.object(pe, 'fetch_quote', AsyncMock(return_value=(MarketQuote(20000, .001, 'pair'), 0))), \
                        patch.object(pe, 'decide', return_value=decision):
                    await pe.collect_once(con, None, [], now, strategy_mode='shadow_final', entry_guard=guard)
                assert con.execute('SELECT entry_allowed FROM paper_decisions').fetchone() == (0,)
                assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
            finally:
                release.set()
                with pytest.raises(RuntimeError) as raised:
                    await task
                assert raised.value is failure
                if publication_fails:
                    assert publication_error in error_graph(raised.value)
            assert not guard()
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_scanner_secondary_cleanup_error_is_preserved(research_db):
    db, con, tmp = research_db
    primary, secondary = RuntimeError('backfill failed'), ValueError('recovery close failed')
    async def scenario():
        ready = asyncio.Event()
        class Backfill:
            def __init__(self, *args):
                pass
            async def run(self):
                await ready.wait()
                raise primary
            async def on_state(self, message):
                pass
        async def recovery(*args, **kwargs):
            ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                raise secondary
        before = asyncio.all_tasks()
        with patch.object(scanner, 'get_settings', return_value=settings(db)), \
                patch.object(scanner, 'SolanaRPC', return_value=RPC()), \
                patch.object(scanner, 'TransactionRecovery'), \
                patch.object(scanner, 'ProgramBackfill', Backfill), \
                patch.object(scanner, 'recover_transactions', recovery), \
                patch.object(scanner, 'stream_program_logs', return_value=object()):
            with pytest.raises(RuntimeError) as raised:
                await scanner.run(db_path=db)
        assert raised.value is primary
        assert secondary in error_graph(raised.value)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())
