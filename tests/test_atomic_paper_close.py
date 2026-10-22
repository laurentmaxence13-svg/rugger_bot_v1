"""Synthetic PAPER ledgers only, including independent SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest

from bot.analyser.paper_trader import record_quote, setup, paper_capital


MODEL = {'creator_scores': {'c': .1}, 'fallback_score': 0, 'cost_bps': 200}


class FailingConnection(sqlite3.Connection):
    fail_after_capital = False

    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if self.fail_after_capital and sql.startswith('UPDATE paper_portfolio SET realized_capital_sol='):
            raise RuntimeError('injected failure after capital write')
        return result


class ConcurrentConnection(sqlite3.Connection):
    barrier = None

    def execute(self, sql, parameters=()):
        cursor = super().execute(sql, parameters)
        if self.barrier is not None and sql.startswith('SELECT 1 FROM paper_trades'):
            row = cursor.fetchone()
            cursor.close()
            self.barrier.wait(timeout=5)
            return SimpleNamespace(fetchone=lambda: row)
        return cursor


class AtomicPaperCloseTests(unittest.TestCase):
    def connection(self, isolation=None):
        con = sqlite3.connect(':memory:', isolation_level=isolation, factory=FailingConnection)
        self.addCleanup(con.close)
        setup(con)
        self.seed(con)
        if con.in_transaction:
            con.commit()
        return con

    def seed(self, con, mint='a'):
        record_quote(con, mint, 'c', 100, 160, (10000, 1, 'pair'), MODEL)

    def close(self, con, mint='a', price=1.2, now=200, model=None):
        return record_quote(con, mint, 'c', 100, now, (10000, price, 'pair'),
                            MODEL if model is None else model, force_exit_reason='TEST')

    def assert_open_unchanged(self, con):
        self.assertEqual(con.execute("SELECT status,pnl_sol,exit_time,capital_after_sol "
                                     "FROM paper_trades WHERE mint='a'").fetchone(),
                         ('open', None, None, None))
        self.assertEqual(paper_capital(con), (10, 10))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices WHERE timestamp=200').fetchone()[0], 0)

    def test_autocommit_and_repeated_close(self):
        con = self.connection()
        self.assertIn('EXIT ', self.close(con))
        self.assertFalse(con.in_transaction)
        self.assertAlmostEqual(paper_capital(con)[1], 10.18)
        self.assertIsNone(self.close(con))
        self.assertAlmostEqual(paper_capital(con)[1], 10.18)

    def test_rollback_after_both_financial_writes(self):
        con = self.connection()
        con.fail_after_capital = True
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.close(con)
        self.assert_open_unchanged(con)
        self.assertFalse(con.in_transaction)
        con.fail_after_capital = False
        self.assertIn('EXIT ', self.close(con))
        self.assertAlmostEqual(paper_capital(con)[1], 10.18)

    def test_caller_transaction_is_not_committed(self):
        for isolation in (None, ''):
            with self.subTest(isolation=isolation):
                con = self.connection(isolation)
                con.execute('BEGIN')
                con.execute("UPDATE paper_trades SET creator='outer' WHERE mint='a'")
                self.close(con)
                self.assertTrue(con.in_transaction)
                con.rollback()
                self.assert_open_unchanged(con)
                self.assertEqual(con.execute("SELECT creator FROM paper_trades").fetchone()[0], 'c')

    def test_savepoint_failure_preserves_caller_work(self):
        con = self.connection('')
        con.execute("UPDATE paper_trades SET creator='outer' WHERE mint='a'")
        con.fail_after_capital = True
        with self.assertRaises(RuntimeError):
            self.close(con)
        self.assertTrue(con.in_transaction)
        self.assert_open_unchanged(con)
        self.assertEqual(con.execute('SELECT creator FROM paper_trades').fetchone()[0], 'outer')
        con.commit()
        self.assertEqual(con.execute('SELECT status FROM paper_trades').fetchone()[0], 'open')

    def test_status_transition_must_update_one_row(self):
        con = self.connection()
        con.execute("CREATE TRIGGER ignore_close BEFORE UPDATE OF status ON paper_trades "
                    "BEGIN SELECT RAISE(IGNORE); END")
        with self.assertRaisesRegex(RuntimeError, 'transition'):
            self.close(con)
        self.assert_open_unchanged(con)

    def test_portfolio_update_must_update_one_row(self):
        con = self.connection()
        con.execute("CREATE TRIGGER ignore_capital BEFORE UPDATE ON paper_portfolio "
                    "BEGIN SELECT RAISE(IGNORE); END")
        with self.assertRaisesRegex(RuntimeError, 'portfolio update'):
            self.close(con)
        self.assert_open_unchanged(con)

    def test_invalid_position_is_not_zero_pnl(self):
        for size in (None, 0, -1, float('nan'), float('inf'), float('-inf'), 'invalid'):
            with self.subTest(size=size):
                con = self.connection()
                con.execute('UPDATE paper_trades SET position_sol=?', (size,))
                with self.assertRaises(ValueError):
                    self.close(con)
                self.assert_open_unchanged(con)

    def test_invalid_prices_and_costs(self):
        for value in (None, -1, float('nan'), float('inf'), float('-inf')):
            with self.subTest(price=value):
                con = self.connection()
                with self.assertRaises((ValueError, TypeError, sqlite3.IntegrityError)):
                    self.close(con, price=value)
                self.assert_open_unchanged(con)
            with self.subTest(cost=value):
                con = self.connection()
                with self.assertRaises(ValueError):
                    self.close(con, model={**MODEL, 'cost_bps': value})
                self.assert_open_unchanged(con)

    def test_invalid_entry_price(self):
        for value in (0, -1, float('inf'), 'invalid'):
            with self.subTest(value=value):
                con = self.connection()
                con.execute('UPDATE paper_trades SET entry_price=?', (value,))
                with self.assertRaises(ValueError):
                    self.close(con)
                self.assert_open_unchanged(con)

    def test_missing_or_unreconciled_portfolio(self):
        for statement in ('DELETE FROM paper_portfolio',
                          'UPDATE paper_portfolio SET realized_capital_sol=11',
                          "UPDATE paper_portfolio SET realized_capital_sol='invalid'"):
            with self.subTest(statement=statement):
                con = self.connection()
                con.execute(statement)
                before = con.execute('SELECT * FROM paper_portfolio').fetchall()
                with self.assertRaises(ValueError):
                    self.close(con)
                self.assertEqual(con.execute('SELECT * FROM paper_portfolio').fetchall(), before)
                self.assertEqual(con.execute('SELECT status,pnl_sol FROM paper_trades').fetchone(), ('open', None))

    def test_nonfinite_result_rolls_back(self):
        con = self.connection()
        con.execute('UPDATE paper_trades SET position_sol=1e308')
        with self.assertRaises(ValueError):
            self.close(con, price=1e308)
        self.assert_open_unchanged(con)

    def test_existing_closure_fields_on_open_trade_are_rejected(self):
        for field in ('pnl_sol', 'exit_time', 'capital_after_sol'):
            with self.subTest(field=field):
                con = self.connection()
                con.execute(f'UPDATE paper_trades SET {field}=1')
                with self.assertRaisesRegex(ValueError, 'closure accounting'):
                    self.close(con)
                self.assertEqual(paper_capital(con), (10, 10))
                self.assertEqual(con.execute(f'SELECT status,{field} FROM paper_trades').fetchone(), ('open', 1))

    def test_incomplete_historical_pnl_blocks_accounting(self):
        con = self.connection()
        self.seed(con, 'b')
        con.execute("UPDATE paper_trades SET status='closed',exit_time=180 WHERE mint='b'")
        with self.assertRaisesRegex(ValueError, 'historical pnl_sol'):
            self.close(con)
        self.assert_open_unchanged(con)

    def test_stale_caller_snapshot_fails_without_partial_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.db'
            with closing(sqlite3.connect(path, isolation_level=None)) as outer:
                outer.execute('PRAGMA journal_mode=WAL')
                setup(outer)
                self.seed(outer)
                self.seed(outer, 'b')
                outer.execute('BEGIN')
                outer.execute('SELECT * FROM paper_portfolio').fetchall()
                with closing(sqlite3.connect(path, isolation_level=None)) as other:
                    self.close(other, 'b')
                with self.assertRaises(sqlite3.OperationalError):
                    self.close(outer)
                self.assertTrue(outer.in_transaction)
                outer.rollback()
                self.assertEqual(outer.execute("SELECT status,pnl_sol FROM paper_trades WHERE mint='a'").fetchone(), ('open', None))
                self.assertAlmostEqual(paper_capital(outer)[1], 10.18)
                self.assertIn('EXIT ', self.close(outer))
                self.assertAlmostEqual(paper_capital(outer)[1], 10.36)

    def test_extreme_loss_preserves_full_liability(self):
        con = self.connection()
        con.execute('UPDATE paper_trades SET position_sol=10')
        self.close(con, price=0)
        pnl, capital = con.execute('SELECT pnl_sol,capital_after_sol FROM paper_trades').fetchone()
        self.assertAlmostEqual(pnl, -10.2)
        self.assertAlmostEqual(capital, -.2)
        self.assertAlmostEqual(paper_capital(con)[1], 10 + pnl)
        self.assertIsNone(self.close(con, price=0))
        self.assertAlmostEqual(paper_capital(con)[1], -.2)

    def test_concurrent_closures(self):
        for same_mint in (True, False):
            with self.subTest(same_mint=same_mint), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'synthetic.db'
                con = sqlite3.connect(path, isolation_level=None)
                setup(con)
                self.seed(con)
                if not same_mint:
                    self.seed(con, 'b')
                con.close()
                barrier = threading.Barrier(2)

                def worker(mint):
                    local = sqlite3.connect(path, isolation_level=None, timeout=5,
                                            factory=ConcurrentConnection)
                    local.barrier = barrier
                    try:
                        return self.close(local, mint)
                    finally:
                        local.close()

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(worker, mint) for mint in ('a', 'a' if same_mint else 'b')]
                    results = [f.result(timeout=10) for f in futures]
                with closing(sqlite3.connect(path)) as check:
                    count = 1 if same_mint else 2
                    self.assertEqual(sum(r is not None for r in results), count)
                    self.assertEqual(check.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'").fetchone()[0], count)
                    self.assertAlmostEqual(paper_capital(check)[1], 10 + count * .18)
                    total = check.execute('SELECT SUM(pnl_sol) FROM paper_trades').fetchone()[0]
                    self.assertAlmostEqual(paper_capital(check)[1], 10 + total)
