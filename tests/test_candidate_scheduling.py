"""Fair collection scheduling on synthetic SQLite; no external services."""
import asyncio
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bot.analyser import paper_engine as pe
from bot.analyser import paper_trader as pt


MODEL = dict(creator_scores={'creator': .1}, fallback_score=0,
             cost_bps=200, tp_pct=10, sl_pct=10)
QUOTE = pt.MarketQuote(20000, 1, 'pair', quote_source='dex_market')


class CandidateSchedulingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic.db'
        self.con = self.connect()
        self.addCleanup(lambda: self.con.close())

    def connect(self):
        con = sqlite3.connect(self.path, isolation_level=None)
        pt.setup(con)
        con.execute('''CREATE TABLE IF NOT EXISTS launch_candidates (
            id INTEGER PRIMARY KEY, mint TEXT, deployer_candidate TEXT,
            block_time INTEGER, status TEXT)''')
        pe.ensure_signal_status_schema(con)
        pe.ensure_audit_schema(con)
        return con

    def seed(self, count, prefix='m', start=1000):
        mints = [f'{prefix}{i:03}' for i in range(count)]
        self.con.executemany('INSERT INTO launch_candidates '
                             '(mint,deployer_candidate,block_time,status) '
                             "VALUES(?,'creator',?,'creator_identified')",
                             [(mint, start + i) for i, mint in enumerate(mints)])
        return mints

    def opened(self, count):
        mints = self.seed(count, prefix='open', start=900)
        for mint in mints:
            pt.record_quote(self.con, mint, 'creator', 900, 1000, QUOTE, MODEL,
                            max_open=count)
        return mints

    async def cycle(self, now=1100, limit=10, result=None, error=None, **kwargs):
        seen = []

        async def fetch(_session, mint, **_kwargs):
            seen.append(mint)
            if error:
                raise error
            return result, 0

        with patch.object(pe, 'fetch_quote', fetch), \
                patch.object(pe.time, 'time', return_value=now):
            await pe.collect_once(self.con, None, [], now,
                                  max_candidates=limit, **kwargs)
        return seen

    async def test_twelve_candidates_all_seen_in_two_cycles(self):
        expected = set(self.seed(12))
        first = await self.cycle()
        second = await self.cycle(now=1101)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(second), 10)
        self.assertEqual(set(first + second), expected)
        self.assertEqual(second[:2], ['m001', 'm000'])

    async def test_twenty_five_candidates_fifo_over_three_cycles(self):
        expected = set(self.seed(25))
        cycles = [await self.cycle(now=1100 + i) for i in range(3)]
        self.assertEqual([len(c) for c in cycles], [10, 10, 10])
        self.assertEqual(set(sum(cycles, [])), expected)
        self.assertEqual(cycles[2][:5], ['m004', 'm003', 'm002', 'm001', 'm000'])

    async def test_open_positions_first_every_cycle_with_spare_capacity(self):
        positions = self.opened(3)
        waiting = set(self.seed(12))
        first = await self.cycle()
        second = await self.cycle(now=1101)
        self.assertEqual(first[:3], positions)
        self.assertEqual(second[:3], positions)
        self.assertEqual(set(first + second) - set(positions), waiting)
        self.assertEqual((len(first), len(second)), (10, 10))

    async def test_overloaded_open_positions_and_candidates_both_progress(self):
        positions = set(self.opened(4))
        waiting = set(self.seed(3))
        cycles = [await self.cycle(now=1100 + i, limit=2) for i in range(4)]
        self.assertTrue(all(len(c) == 2 and c[0] in positions and c[1] in waiting
                            for c in cycles))
        self.assertEqual({c[0] for c in cycles}, positions)
        self.assertEqual({c[1] for c in cycles}, waiting)

    async def test_one_slot_alternates_lanes_across_restart(self):
        positions = set(self.opened(2))
        waiting = set(self.seed(2))
        cycles = []
        for i in range(4):
            cycles.append(await self.cycle(now=1100 + i, limit=1))
            self.con.close()
            self.con = self.connect()
        self.assertEqual(set(cycles[0] + cycles[2]), positions)
        self.assertEqual(set(cycles[1] + cycles[3]), waiting)

    async def test_priority_tp_exits_do_not_starve_waiting_candidates(self):
        positions = set(self.opened(3))
        waiting = set(self.seed(25))
        higher = pt.MarketQuote(20000, 2, 'pair', quote_source='dex_market')
        first = await self.cycle(result=higher, model=MODEL, entry_guard=lambda: False)
        self.assertEqual(set(first[:3]), positions)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'").fetchone()[0], 3)
        self.assertAlmostEqual(pt.paper_capital(self.con)[1], 12.94)
        seen = first + await self.cycle(now=1101) + await self.cycle(now=1102)
        self.assertTrue(waiting <= set(seen))

    async def test_arrivals_join_after_existing_waiters(self):
        self.seed(12)
        await self.cycle()
        newcomers = set(self.seed(3, prefix='new', start=1050))
        second = await self.cycle(now=1101)
        self.assertEqual(second[:2], ['m001', 'm000'])
        third = await self.cycle(now=1102)
        self.assertTrue(newcomers <= set(second + third))

    async def test_continuous_arrivals_cannot_overtake_waiting_mints(self):
        original = set(self.seed(6))
        seen = set()
        for i in range(6):
            if i:
                self.seed(3, prefix=f'new{i}', start=1050)
            seen.update(await self.cycle(now=1100 + i, limit=1))
        self.assertEqual(seen, original)

    async def test_expired_and_future_candidates_not_scheduled(self):
        self.seed(12)
        self.seed(1, prefix='future', start=2000)
        self.seed(1, prefix='invalid', start=1000)
        self.con.execute("UPDATE launch_candidates SET status='not_launch' WHERE mint='invalid000'")
        await self.cycle(max_age=100)
        second = await self.cycle(now=1101, max_age=100)
        self.assertIn('m001', second)
        self.assertNotIn('m000', second)
        self.assertNotIn('future000', second)
        self.assertNotIn('invalid000', second)
        third = await self.cycle(now=2000, max_age=100)
        self.assertEqual(third, ['future000'])

    async def test_duplicate_mint_consumes_one_slot(self):
        mints = self.seed(3)
        self.con.execute("INSERT INTO launch_candidates(mint,deployer_candidate,block_time,status) "
                         "VALUES('m002','creator',1002,'creator_identified')")
        seen = await self.cycle()
        self.assertEqual(seen, list(reversed(mints)))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_collection_schedule').fetchone()[0], 3)

    async def test_restart_keeps_unserved_candidates_at_front(self):
        expected = set(self.seed(12))
        first = await self.cycle()
        self.con.close()
        self.con = self.connect()
        second = await self.cycle(now=1101)
        self.assertEqual(second[:2], ['m001', 'm000'])
        self.assertEqual(set(first + second), expected)

    async def test_no_eligible_candidates(self):
        self.seed(1, start=1)
        self.assertEqual(await self.cycle(max_age=100), [])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_collection_schedule').fetchone()[0], 0)

    async def test_missing_prices_do_not_pin_front_of_queue(self):
        expected = set(self.seed(12))
        seen = await self.cycle(result=None)
        seen += await self.cycle(now=1101, result=None)
        self.assertEqual(set(seen), expected)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 0)

    async def test_exception_advances_only_attempted_mint(self):
        self.seed(3)
        with self.assertRaises(TimeoutError):
            await self.cycle(limit=2, error=TimeoutError())
        self.con.close()
        self.con = self.connect()
        self.assertEqual(await self.cycle(now=1101, limit=2), ['m001', 'm000'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)

    async def test_cancellation_after_attempt_is_durable(self):
        self.seed(3)
        started = asyncio.Event()

        async def fetch(*_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

        with patch.object(pe, 'fetch_quote', fetch):
            task = asyncio.create_task(pe.collect_once(self.con, None, [], 1100, max_candidates=2))
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.con.close()
        self.con = self.connect()
        self.assertEqual(await self.cycle(now=1101, limit=2), ['m001', 'm000'])

    async def test_tp_sl_and_replays_do_not_duplicate_financial_events(self):
        self.seed(2, start=1000)
        await self.cycle(result=QUOTE, model=MODEL)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 2)
        prices = {'m000': 2, 'm001': .5}

        async def fetch(_session, mint, **_kwargs):
            return pt.MarketQuote(20000, prices[mint], 'pair', quote_source='dex_market'), 0

        with patch.object(pe, 'fetch_quote', fetch), patch.object(pe.time, 'time', return_value=1101):
            await pe.collect_once(self.con, None, [], 1101, model=MODEL)
        self.assertEqual(self.con.execute('SELECT mint,exit_reason FROM paper_trades ORDER BY mint').fetchall(),
                         [('m000', 'TP'), ('m001', 'SL')])
        self.assertAlmostEqual(pt.paper_capital(self.con)[1], 10.46)
        for now in (1101, 1102):
            await self.cycle(now=now, result=QUOTE, model=MODEL)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 2)
        self.assertAlmostEqual(pt.paper_capital(self.con)[1], 10.46)

    async def test_under_capacity_keeps_recent_order_each_cycle(self):
        for count in (1, 5, 10):
            with self.subTest(count=count):
                self.con.execute('DELETE FROM launch_candidates')
                expected = list(reversed(self.seed(count, prefix=f'n{count}')))
                self.assertEqual(await self.cycle(), expected)
                self.assertEqual(await self.cycle(now=1101), expected)

    async def test_tied_times_have_deterministic_order_and_dedup(self):
        for mint in ('c', 'a', 'b', 'a'):
            self.con.execute("INSERT INTO launch_candidates(mint,deployer_candidate,block_time,status) "
                             "VALUES(?,'creator',1000,'creator_identified')", (mint,))
        self.assertEqual(await self.cycle(limit=2), ['a', 'b'])
        self.assertEqual(await self.cycle(now=1101, limit=2), ['c', 'a'])

    async def test_schedule_changes_rollback_with_caller_transaction(self):
        self.seed(3)
        pe._scheduled_candidates(self.con, 1100, 7200, 2)
        before = self.con.execute('SELECT * FROM paper_collection_schedule ORDER BY turn').fetchall()
        self.con.execute('BEGIN')
        pe._mark_collection_attempt(self.con, 'm002', 'candidate')
        self.con.rollback()
        self.assertEqual(self.con.execute('SELECT * FROM paper_collection_schedule ORDER BY turn').fetchall(), before)


if __name__ == '__main__':
    unittest.main()
