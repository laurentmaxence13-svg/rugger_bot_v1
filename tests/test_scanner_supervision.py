import asyncio
import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot.analyser import paper_engine as pe


class SupervisionTests(unittest.IsolatedAsyncioTestCase):
    def args(self, **overrides):
        values = dict(db='unused.db', model=None, poll=15, report=None,
                      max_open=3, max_entries_day=20, max_daily_loss=10,
                      max_candidates=10, max_age=7200, cache_refresh=60,
                      no_live_behavior=True, rpc_interval=2.5, behavior_max_tx=10,
                      min_liquidity=1000, shadow_baseline=False, shadow_final=False,
                      capital_sol=10, position_pct=10, session_seconds=1,
                      session_report=None, no_scanner=False)
        values.update(overrides)
        return SimpleNamespace(**values)

    async def scenario(self, scanner_mode, engine_mode):
        cleaned = set()
        guards = []
        async def scanner(**kwargs):
            try:
                if scanner_mode == 'error':
                    raise ValueError('synthetic scanner')
                if scanner_mode == 'return':
                    return
                await asyncio.Event().wait()
            finally:
                cleaned.add('scanner')
        async def engine(*args, **kwargs):
            try:
                if engine_mode == 'error':
                    raise LookupError('synthetic engine')
                if engine_mode == 'return':
                    return
                guards.append(kwargs['entry_guard']())
                await asyncio.Event().wait()
            finally:
                cleaned.add('engine')
        before = asyncio.all_tasks()
        with patch('bot.main.run', scanner), patch.object(pe, 'run', engine):
            if scanner_mode != 'wait':
                with self.assertRaises(RuntimeError):
                    await pe.run_with_scanner(self.args())
                self.assertEqual(guards, [False])
            elif engine_mode == 'error':
                with self.assertRaises(LookupError):
                    await pe.run_with_scanner(self.args())
            elif engine_mode == 'return':
                await pe.run_with_scanner(self.args())
            else:
                task = asyncio.create_task(pe.run_with_scanner(self.args()))
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(cleaned, {'scanner', 'engine'})
        self.assertEqual(asyncio.all_tasks(), before)

    async def test_scanner_exception(self):
        await self.scenario('error', 'wait')

    async def test_scanner_unexpected_return(self):
        await self.scenario('return', 'wait')

    async def test_engine_exception(self):
        await self.scenario('wait', 'error')

    async def test_engine_normal_return(self):
        await self.scenario('wait', 'return')

    async def test_external_cancellation(self):
        await self.scenario('wait', 'wait')

    async def test_no_scanner(self):
        from unittest.mock import AsyncMock
        with patch('bot.main.run', new_callable=AsyncMock) as scanner, \
                patch.object(pe, 'run', new_callable=AsyncMock) as engine:
            await pe.run_with_scanner(self.args(no_scanner=True))
        scanner.assert_not_called()
        engine.assert_awaited_once()
        self.assertNotIn('entry_guard', engine.call_args.kwargs)

    async def test_degraded_sqlite_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'synthetic.db'
            with contextlib.closing(sqlite3.connect(db)) as con, con:
                con.execute('CREATE TABLE scanner_backfill_state(ws_state, history_status)')
                con.execute("INSERT INTO scanner_backfill_state VALUES('disconnected','degraded')")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pe._print_scanner_state(db)
            self.assertIn('ws=disconnected backfill=degraded', out.getvalue())
            self.assertIn('non garantie', out.getvalue())

    async def test_real_engine_final_report_on_cancel(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'synthetic.db'
            report = Path(tmp) / 'report.json'
            entered = asyncio.Event()
            async def collect(*args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
            with patch.object(pe, 'collect_once', collect):
                task = asyncio.create_task(pe.run(db, live_behavior=False,
                    session_seconds=60, session_report=report))
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(json.loads(report.read_text())['capital_end_sol'], 10)
            with contextlib.closing(sqlite3.connect(db, timeout=0)) as con:
                con.execute('BEGIN EXCLUSIVE')

    async def test_no_entry_when_scanner_fails_during_quote(self):
        from bot.analyser.paper_trader import MarketQuote, setup
        with contextlib.closing(sqlite3.connect(':memory:')) as con:
            setup(con)
            pe.ensure_signal_status_schema(con)
            con.execute('CREATE TABLE launch_candidates (mint, deployer_candidate, block_time, status)')
            con.execute("INSERT INTO launch_candidates VALUES ('mint','creator',1000,'creator_identified')")
            alive = True
            async def quote(*args, **kwargs):
                nonlocal alive
                await asyncio.sleep(0)
                alive = False
                return MarketQuote(20000, 1, 'pair'), 0
            with patch.object(pe, 'fetch_quote', quote):
                await pe.collect_once(con, object(), [], 1060,
                    model=pe.shadow_baseline_model(), entry_guard=lambda: alive)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 1)

    async def test_cleanup_timeout_is_explicit(self):
        started = asyncio.Event()
        async def slow_cleanup():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.Event().wait()
        task = asyncio.create_task(slow_cleanup())
        await started.wait()
        with self.assertRaisesRegex(RuntimeError, 'Nettoyage asyncio incomplet'):
            await pe._stop_supervised_tasks((task,), timeout=0.01)
        with self.assertRaises(asyncio.CancelledError):
            await task
