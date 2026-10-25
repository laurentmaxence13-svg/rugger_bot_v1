"""Synthetic SOL reservations, including concurrent SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from bot.analyser.paper_trader import record_quote, setup, paper_capital


MODEL = {'creator_scores': {'c': .1}, 'fallback_score': 0, 'cost_bps': 0}


class EntryConnection(sqlite3.Connection):
    fail_after_entry = False
    barrier = None

    def execute(self, sql, parameters=()):
        if sql == 'BEGIN IMMEDIATE' and self.barrier is not None:
            self.barrier.wait(timeout=5)
        cursor = super().execute(sql, parameters)
        if self.fail_after_entry and sql.startswith('INSERT OR IGNORE INTO paper_trades'):
            raise RuntimeError('injected failure after reservation')
        return cursor


class PaperCapitalReservationTests(unittest.TestCase):
    def connection(self):
        con = sqlite3.connect(':memory:', isolation_level=None, factory=EntryConnection)
        self.addCleanup(con.close)
        setup(con)
        return con

    def enter(self, con, mint, pct=10, now=160):
        return record_quote(con, mint, 'c', 100, now, (10000, 1, 'pair'), MODEL,
                            position_pct=pct, max_open=100, max_entries_day=100,
                            max_daily_loss_pct=None)

    def close(self, con, mint, price=1):
        return record_quote(con, mint, 'c', 100, 200, (10000, price, 'pair'), MODEL,
                            force_exit_reason='TEST')

    def committed(self, con):
        return con.execute("SELECT COALESCE(SUM(position_sol),0) FROM paper_trades "
                           "WHERE status='open'").fetchone()[0]

    def test_free_capital_not_total_capital_controls_entry(self):
        con = self.connection()
        self.assertIn('ENTRY ', self.enter(con, 'a', 60))
        self.assertIsNone(self.enter(con, 'b', 60))
        self.assertEqual(self.committed(con), 6)
        self.assertEqual(paper_capital(con), (10, 10))
        # A new allocation attempt needs a new observation, not an identical replay.
        self.assertIn('ENTRY ', self.enter(con, 'b', 40, now=161))
        self.assertEqual(self.committed(con), 10)
        self.assertIsNone(self.enter(con, 'c'))

    def test_default_allocation_cannot_exceed_available_sol(self):
        con = self.connection()
        for i in range(10):
            self.assertIn('ENTRY ', self.enter(con, str(i)))
        self.assertIsNone(self.enter(con, 'eleventh'))
        self.assertEqual(self.committed(con), 10)

    def test_ten_sol_is_initial_capital_not_ceiling(self):
        con = self.connection()
        self.enter(con, 'gain', 100)
        self.close(con, 'gain', 2)
        self.assertEqual(paper_capital(con), (10, 20))
        self.assertIn('ENTRY ', self.enter(con, 'a', 50))
        self.assertIn('ENTRY ', self.enter(con, 'b', 50))
        self.assertEqual(self.committed(con), 20)
        self.assertIsNone(self.enter(con, 'c', 50))

    def test_closure_releases_reservation_and_updates_free_capital(self):
        for price, capital in ((1, 10), (.5, 7), (2, 16)):
            with self.subTest(price=price):
                con = self.connection()
                self.enter(con, 'a', 60)
                self.enter(con, 'b', 40)
                self.close(con, 'a', price)
                self.assertEqual(paper_capital(con)[1], capital)
                self.assertEqual(self.committed(con), 4)
                # Preserve allocation: do not shrink a requested 60% position.
                msg = self.enter(con, 'next', 60)
                self.assertEqual(msg is not None, capital * .6 <= capital - 4)

    def test_repeated_entry_does_not_reserve_twice(self):
        con = self.connection()
        self.enter(con, 'a', 60)
        self.assertIsNone(self.enter(con, 'a', 60))
        self.assertEqual(self.committed(con), 6)

    def test_insert_failure_rolls_back_initialization_and_reservation(self):
        con = self.connection()
        con.fail_after_entry = True
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.enter(con, 'a')
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 0)
        self.assertEqual(paper_capital(con), (None, None))
        self.assertFalse(con.in_transaction)

    def test_outer_transaction_preserved_on_success_and_failure(self):
        con = self.connection()
        self.enter(con, 'a', 60)
        con.execute('BEGIN')
        con.execute("UPDATE paper_trades SET creator='outer'")
        self.enter(con, 'b', 40)
        self.assertTrue(con.in_transaction)
        con.rollback()
        self.assertEqual(self.committed(con), 6)
        con.execute('BEGIN')
        con.execute("UPDATE paper_trades SET creator='outer'")
        con.fail_after_entry = True
        with self.assertRaises(RuntimeError):
            self.enter(con, 'c', 40)
        self.assertTrue(con.in_transaction)
        self.assertEqual(self.committed(con), 6)
        self.assertEqual(con.execute('SELECT creator FROM paper_trades').fetchone()[0], 'outer')
        con.rollback()

    def test_invalid_open_sizes_block_new_reservations(self):
        for size in (None, 0, -1, float('nan'), float('inf'), float('-inf'), 'bad'):
            with self.subTest(size=size):
                con = self.connection()
                self.enter(con, 'a')
                con.execute('UPDATE paper_trades SET position_sol=?', (size,))
                with self.assertRaises(ValueError):
                    self.enter(con, 'b')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)
                self.assertEqual(paper_capital(con), (10, 10))

    def test_missing_or_unreconciled_portfolio_is_not_recreated(self):
        for sql in ('DELETE FROM paper_portfolio',
                    'UPDATE paper_portfolio SET realized_capital_sol=20'):
            with self.subTest(sql=sql):
                con = self.connection()
                self.enter(con, 'a')
                con.execute(sql)
                with self.assertRaises(ValueError):
                    self.enter(con, 'b')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)

    def test_overcommitted_history_blocks_entries_but_not_closure(self):
        con = self.connection()
        self.enter(con, 'a')
        con.execute('UPDATE paper_trades SET position_sol=11')
        self.assertIsNone(self.enter(con, 'b'))
        self.assertIn('EXIT ', self.close(con, 'a'))
        self.assertEqual(self.committed(con), 0)

    def test_negative_equity_does_not_allow_reservation(self):
        con = self.connection()
        self.enter(con, 'a', 100)
        record_quote(con, 'a', 'c', 100, 200, (10000, 0, 'pair'),
                     {**MODEL, 'cost_bps': 200}, force_exit_reason='TEST')
        self.assertLess(paper_capital(con)[1], 0)
        self.assertIsNone(self.enter(con, 'b'))

    def test_invalid_portfolio_and_allocation_values_are_rejected(self):
        for value in (float('inf'), float('-inf'), 'bad'):
            with self.subTest(capital=value):
                con = self.connection()
                self.enter(con, 'a')
                con.execute('UPDATE paper_portfolio SET realized_capital_sol=?', (value,))
                with self.assertRaises(ValueError):
                    self.enter(con, 'b')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)
        for value in (None, -1, float('nan'), float('inf')):
            with self.subTest(allocation=value):
                con = self.connection()
                with self.assertRaises(ValueError):
                    self.enter(con, 'a', value)
                self.assertEqual(self.committed(con), 0)
                self.assertEqual(paper_capital(con), (None, None))

    def test_incomplete_closed_pnl_blocks_new_reservation(self):
        con = self.connection()
        self.enter(con, 'a')
        con.execute("UPDATE paper_trades SET status='closed',exit_time=180")
        with self.assertRaisesRegex(ValueError, 'historical pnl_sol'):
            self.enter(con, 'b')
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)

    def test_stale_caller_snapshot_cannot_overreserve(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.db'
            with closing(sqlite3.connect(path, isolation_level=None)) as outer:
                outer.execute('PRAGMA journal_mode=WAL')
                setup(outer)
                self.enter(outer, 'seed', 40)
                outer.execute('BEGIN')
                outer.execute('SELECT * FROM paper_portfolio').fetchall()
                with closing(sqlite3.connect(path, isolation_level=None)) as other:
                    self.enter(other, 'other', 60)
                with self.assertRaises(sqlite3.OperationalError):
                    self.enter(outer, 'stale', 60)
                self.assertTrue(outer.in_transaction)
                outer.rollback()
                self.assertIsNone(self.enter(outer, 'retry', 60))
                self.assertEqual(self.committed(outer), 10)

    def test_concurrent_entries_share_the_last_available_capital(self):
        for same_mint in (False, True):
            with self.subTest(same_mint=same_mint), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'synthetic.db'
                with closing(sqlite3.connect(path, isolation_level=None)) as seed:
                    setup(seed)
                    self.enter(seed, 'seed', 40)
                barrier = threading.Barrier(2)

                def worker(mint):
                    with closing(sqlite3.connect(path, isolation_level=None, timeout=5,
                                                 factory=EntryConnection)) as con:
                        con.barrier = barrier
                        return self.enter(con, mint, 60)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    tasks = [pool.submit(worker, mint) for mint in ('a', 'a' if same_mint else 'b')]
                    messages = [task.result(timeout=10) for task in tasks]
                self.assertEqual(sum(msg is not None for msg in messages), 1)
                with closing(sqlite3.connect(path)) as check:
                    self.assertEqual(self.committed(check), 10)
                    self.assertEqual(paper_capital(check), (10, 10))
