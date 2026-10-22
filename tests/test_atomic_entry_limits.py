"""Direct PAPER calls must enforce limits under the insertion transaction."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from bot.analyser import paper_trader


MODEL = {'creator_scores': {'c': .1}, 'fallback_score': 0, 'cost_bps': 0}


class BarrierConnection(sqlite3.Connection):
    barrier = None
    attempting = None

    def execute(self, sql, parameters=()):
        if sql == 'BEGIN IMMEDIATE' and self.attempting is not None:
            self.attempting.set()
        if sql == 'BEGIN IMMEDIATE' and self.barrier is not None:
            self.barrier.wait(timeout=5)
        return super().execute(sql, parameters)


class AtomicEntryLimitTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(self.con.close)
        paper_trader.setup(self.con)

    def enter(self, mint, now=160, **limits):
        return paper_trader.record_quote(self.con, mint, 'c', now-60, now,
                                        (10000, 1, 'pair'), MODEL, **limits)

    def close(self, mint, price=1, now=200, **limits):
        return paper_trader.record_quote(self.con, mint, 'c', 100, now,
                                        (10000, price, 'pair'), MODEL,
                                        force_exit_reason='TEST', **limits)

    def test_direct_calls_enforce_default_open_limit(self):
        for mint in ('a', 'b', 'c'):
            self.assertIn('ENTRY ', self.enter(mint))
        self.assertIsNone(self.enter('fourth'))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 3)

    def test_configured_open_limit_is_not_replaced_by_default(self):
        for i in range(5):
            self.assertIn('ENTRY ', self.enter(str(i), max_open=5))
        self.assertIsNone(self.enter('sixth', max_open=5))

    def test_zero_limits_deny_entries(self):
        self.assertIsNone(self.enter('open-zero', max_open=0))
        self.assertIsNone(self.enter('day-zero', max_entries_day=0))

    def test_daily_entries_include_closed_positions(self):
        for mint in ('a', 'b'):
            self.assertIn('ENTRY ', self.enter(mint, max_entries_day=2))
            self.assertIn('EXIT ', self.close(mint))
        self.assertIsNone(self.enter('third', max_entries_day=2))

    def test_default_daily_entry_limit_cannot_be_bypassed(self):
        for i in range(20):
            self.assertIn('ENTRY ', self.enter(str(i)))
            self.close(str(i))
        self.assertIsNone(self.enter('twenty-first'))

    def test_daily_loss_boundary_and_configured_threshold(self):
        self.enter('loss', position_pct=20)
        self.close('loss', price=.5)  # exactly -1 SOL, -10% of initial 10 SOL
        self.assertEqual(paper_trader.paper_capital(self.con), (10, 9))
        self.assertIsNone(self.enter('default-denied', now=201))
        self.assertIsNone(self.enter('strict-denied', now=201, max_daily_loss_pct=9))
        self.assertIn('ENTRY ', self.enter('configured-allowed', now=201, max_daily_loss_pct=12))

    def test_loss_uses_closure_day_not_entry_day(self):
        self.enter('overnight', position_pct=20)
        self.close('overnight', price=.5, now=86401)
        self.assertIsNone(self.enter('today', now=86460))
        self.assertIn('ENTRY ', self.enter('tomorrow', now=172860))

    def test_advisory_permission_does_not_bypass_later_realized_loss(self):
        self.enter('loss', position_pct=20)
        self.assertTrue(paper_trader.entry_allowed(self.con, 160))
        self.close('loss', price=.5)
        self.assertIsNone(self.enter('stale-permission', now=201, allow_entry=True))

    def test_closures_remain_allowed_when_entry_limits_are_exhausted(self):
        self.enter('a')
        self.assertIn('EXIT ', self.close('a', max_open=0, max_entries_day=0,
                                         max_daily_loss_pct=.01, allow_entry=False))
        self.assertIsNone(self.enter('blocked', max_open=0))

    def test_limits_are_checked_in_caller_transaction(self):
        self.con.execute('BEGIN')
        self.enter('a', max_open=1)
        self.assertIsNone(self.enter('b', max_open=1))
        self.assertTrue(self.con.in_transaction)
        self.con.rollback()
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)

    def test_check_and_insert_share_the_same_transaction(self):
        original = paper_trader.entry_allowed
        observed = []

        def checked(con, now, **limits):
            observed.append((con.in_transaction, limits))
            return original(con, now, **limits)

        with patch.object(paper_trader, 'entry_allowed', side_effect=checked):
            self.enter('a', max_open=7, max_entries_day=13, max_daily_loss_pct=4)
        self.assertEqual(observed, [(True, {'max_open': 7, 'max_entries_day': 13,
                                           'max_daily_loss_pct': 4})])

    def test_concurrent_entries_cannot_both_take_last_slot(self):
        for limits in ({'max_open': 1}, {'max_open': 10, 'max_entries_day': 1}):
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'synthetic.db'
                with closing(sqlite3.connect(path, isolation_level=None)) as seed:
                    paper_trader.setup(seed)
                barrier = threading.Barrier(2)

                def worker(mint):
                    with closing(sqlite3.connect(path, isolation_level=None, timeout=5,
                                                 factory=BarrierConnection)) as con:
                        con.barrier = barrier
                        return paper_trader.record_quote(con, mint, 'c', 100, 160,
                                                         (10000, 1, 'pair'), MODEL, **limits)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    tasks = [pool.submit(worker, mint) for mint in ('a', 'b')]
                    messages = [task.result(timeout=10) for task in tasks]
                self.assertEqual(sum(m is not None for m in messages), 1)
                with closing(sqlite3.connect(path)) as check:
                    self.assertEqual(check.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)

    def test_entry_waiting_for_loss_closure_rechecks_daily_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.db'
            with closing(sqlite3.connect(path, isolation_level=None)) as seed:
                paper_trader.setup(seed)
                paper_trader.record_quote(seed, 'loss', 'c', 100, 160,
                                          (10000, 1, 'pair'), MODEL, position_pct=20)
            loss_written = threading.Event()
            entry_attempting = threading.Event()

            def close_worker():
                with closing(sqlite3.connect(path, isolation_level=None, timeout=5)) as con:
                    con.execute('BEGIN IMMEDIATE')
                    paper_trader.record_quote(con, 'loss', 'c', 100, 200,
                                              (10000, .5, 'pair'), MODEL,
                                              force_exit_reason='TEST')
                    loss_written.set()
                    if not entry_attempting.wait(timeout=5):
                        raise AssertionError('entry did not attempt its transaction')
                    con.commit()

            def entry_worker():
                if not loss_written.wait(timeout=5):
                    raise AssertionError('closure did not write the loss')
                with closing(sqlite3.connect(path, isolation_level=None, timeout=5,
                                             factory=BarrierConnection)) as con:
                    con.attempting = entry_attempting
                    return paper_trader.record_quote(con, 'new', 'c', 100, 201,
                                                     (10000, 1, 'pair'), MODEL)

            with ThreadPoolExecutor(max_workers=2) as pool:
                closing_task = pool.submit(close_worker)
                entering_task = pool.submit(entry_worker)
                closing_task.result(timeout=10)
                self.assertIsNone(entering_task.result(timeout=10))
            with closing(sqlite3.connect(path)) as check:
                self.assertEqual(paper_trader.paper_capital(check), (10, 9))
                self.assertEqual(check.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)
