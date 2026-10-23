"""First-observation consistency, with synthetic SQLite and mocked collectors."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

from bot.analyser import paper_engine as pe
from bot.analyser import paper_trader as pt


MODEL = dict(creator_scores={'c': .1}, fallback_score=0, cost_bps=200,
             tp_pct=10, sl_pct=10)
QUOTE = pt.MarketQuote(20000, 1, 'pair', quote_source='dex_market')


class ConsistencyTests(unittest.TestCase):
    def connection(self, isolation=None):
        con = sqlite3.connect(':memory:', isolation_level=isolation)
        self.addCleanup(con.close)
        pt.setup(con)
        return con

    def record(self, con, quote=QUOTE, now=160, model=MODEL, **kwargs):
        return pt.record_quote(con, 'mint', 'c', 100, now, quote, model, **kwargs)

    def snapshot(self, con):
        return tuple(list(con.execute('SELECT * FROM ' + table)) for table in
                     ('paper_prices', 'paper_trades', 'paper_portfolio', 'paper_decisions'))

    def conflicts(self, con):
        return con.execute('SELECT COALESCE(SUM(rejected_observations),0) '
                           'FROM paper_quote_conflicts').fetchone()[0]

    def engine_db(self, isolation=None):
        con = self.connection(isolation)
        con.execute('CREATE TABLE launch_candidates(mint,deployer_candidate,block_time,status)')
        con.execute("INSERT INTO launch_candidates VALUES('mint','c',100,'creator_identified')")
        pe.ensure_signal_status_schema(con)
        pe.ensure_audit_schema(con)
        con.commit()
        return con

    def collect(self, con, quote=QUOTE, now=160):
        with patch.object(pe, 'fetch_quote', new_callable=AsyncMock, return_value=(quote, 0)), \
                patch.object(pe.time, 'time', return_value=now):
            return asyncio.run(pe.collect_once(con, None, [], now, strategy_mode='shadow_final'))

    def test_identical_quote_idempotent_including_forced_exit(self):
        con = self.connection()
        self.assertIn('ENTRY', self.record(con))
        before = self.snapshot(con)
        self.assertIsNone(self.record(con, force_exit_reason='TEST'))
        self.assertEqual(self.snapshot(con), before)
        self.assertEqual(self.conflicts(con), 0)

    def test_conflicting_new_entry_rejected(self):
        con = self.connection()
        self.record(con, model=None)
        before = self.snapshot(con)
        self.assertIsNone(self.record(con, replace(QUOTE, price_usd=2)))
        self.assertEqual(self.snapshot(con), before)
        self.assertEqual(self.conflicts(con), 1)

    def test_identical_replay_does_not_create_entry(self):
        con = self.connection()
        self.record(con, model=None)
        self.assertIsNone(self.record(con))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)

    def test_source_funding_liquidity_and_unknown_conflicts(self):
        for changed in (replace(QUOTE, quote_source='launchlab_curve', funding_usd=20000),
                        replace(QUOTE, funding_usd=0), replace(QUOTE, liquidity_usd=0),
                        replace(QUOTE, quote_source=None), replace(QUOTE, volume_5m_usd=0)):
            with self.subTest(quote=changed):
                con = self.connection()
                self.record(con)
                before = self.snapshot(con)
                self.record(con, changed)
                self.assertEqual(self.snapshot(con), before)
                self.assertEqual(self.conflicts(con), 1)

    def test_tp_sl_conflict_does_not_change_open_position_or_pnl(self):
        for price in (2, .5):
            with self.subTest(price=price):
                con = self.connection()
                self.record(con)
                before = self.snapshot(con)
                self.record(con, replace(QUOTE, price_usd=price))
                self.assertEqual(self.snapshot(con), before)
                self.assertEqual(pt.paper_capital(con), (10, 10))
                self.assertEqual(con.execute('SELECT peak_price,last_price,status FROM paper_trades').fetchone(),
                                 (1, 1, 'open'))

    def test_distinct_seconds_tp_sl_and_no_double_pnl(self):
        for price, reason, capital in ((2, 'TP', 10.98), (.5, 'SL', 9.48)):
            with self.subTest(price=price):
                con = self.connection()
                self.record(con)
                quote = replace(QUOTE, price_usd=price)
                self.assertIn('reason=' + reason, self.record(con, quote, now=161))
                before = self.snapshot(con)
                self.record(con, quote, now=161)
                self.record(con, replace(quote, price_usd=3), now=161)
                self.assertEqual(self.snapshot(con), before)
                self.assertAlmostEqual(pt.paper_capital(con)[1], capital)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 2)

    def test_engine_conflict_never_builds_features_or_decides(self):
        for changed in (replace(QUOTE, price_usd=2),
                        replace(QUOTE, quote_source='launchlab_curve', funding_usd=20000)):
            with self.subTest(quote=changed):
                con = self.engine_db()
                self.record(con, model=None)
                before = self.snapshot(con)
                with patch.object(pe, 'build_features', side_effect=AssertionError('features on conflict')), \
                        patch.object(pe, 'decide', side_effect=AssertionError('decision on conflict')):
                    self.collect(con, changed)
                self.assertEqual(self.snapshot(con), before)
                self.assertEqual(self.conflicts(con), 1)

    def test_engine_identical_repeat_has_one_decision_and_trade(self):
        con = self.engine_db()
        self.collect(con)
        before = self.snapshot(con)
        self.collect(con)
        self.assertEqual(self.snapshot(con), before)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_decisions').fetchone()[0], 1)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)

    def test_historical_null_provenance_is_not_enriched_or_used(self):
        con = self.engine_db()
        con.execute("INSERT INTO paper_prices(mint,timestamp,price_usd,pair_address,liquidity_usd) "
                    "VALUES('mint',160,1,'pair',20000)")
        before = self.snapshot(con)
        self.collect(con)
        self.assertEqual(self.snapshot(con), before)
        report = pe.paper_report(con, 160, 0)['quote_provenance']
        self.assertEqual(report['unknown_source_quotes'], 1)
        self.assertEqual(report['rejected_conflicting_observations'], 1)
        self.assertFalse(report['conflict_history_complete'])

    def test_sqlite_failure_rolls_back_decision_quote_entry_and_capital(self):
        for isolation in (None, ''):
            with self.subTest(isolation=isolation):
                con = self.engine_db(isolation)
                before = self.snapshot(con)
                con.executescript('''CREATE TRIGGER fail_entry AFTER INSERT ON paper_trades
                    BEGIN SELECT RAISE(ABORT,'synthetic entry failure'); END;''')
                with self.assertRaises(sqlite3.IntegrityError):
                    self.collect(con)
                self.assertEqual(self.snapshot(con), before)

    def test_conflict_counter_failure_rolls_back(self):
        con = self.connection()
        self.record(con)
        before = self.snapshot(con)
        con.executescript('''CREATE TRIGGER fail_conflict AFTER INSERT ON paper_quote_conflicts
            BEGIN SELECT RAISE(ABORT,'synthetic conflict failure'); END;''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(con, replace(QUOTE, price_usd=2))
        self.assertEqual(self.snapshot(con), before)
        self.assertEqual(self.conflicts(con), 0)
        self.assertFalse(con.in_transaction)

    def test_caller_rollback_includes_conflict_counter(self):
        con = self.connection()
        self.record(con)
        before = self.snapshot(con)
        con.execute('BEGIN')
        self.record(con, replace(QUOTE, price_usd=2))
        self.assertEqual(self.conflicts(con), 1)
        con.rollback()
        self.assertEqual(self.conflicts(con), 0)
        self.assertEqual(self.snapshot(con), before)

    def test_concurrent_conflicting_entries_share_first_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'synthetic.db'
            with closing(sqlite3.connect(db, isolation_level=None)) as con:
                pt.setup(con)
            barrier = threading.Barrier(2)
            def worker(price):
                with closing(sqlite3.connect(db, isolation_level=None, timeout=5)) as con:
                    barrier.wait(timeout=5)
                    return self.record(con, replace(QUOTE, price_usd=price))
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(worker, (1, 2)))
            self.assertEqual(sum(bool(result and result.startswith('ENTRY')) for result in results), 1)
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute('SELECT price_usd FROM paper_prices').fetchone()[0],
                                 con.execute('SELECT entry_price FROM paper_trades').fetchone()[0])
                self.assertEqual(self.conflicts(con), 1)
                self.assertEqual(pt.paper_capital(con), (10, 10))

    def test_report_without_conflict_table(self):
        con = self.connection()
        con.execute('DROP TABLE paper_quote_conflicts')
        report = pe.paper_report(con, 160, 0)['quote_provenance']
        self.assertEqual(report['rejected_conflicting_observations'], 0)
        self.assertFalse(report['conflict_history_complete'])

    def test_engine_close_failure_rolls_back_whole_observation(self):
        con = self.engine_db()
        self.collect(con)
        before = self.snapshot(con)
        con.executescript('''CREATE TRIGGER fail_capital AFTER UPDATE ON paper_portfolio
            BEGIN SELECT RAISE(ABORT,'synthetic capital failure'); END;''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.collect(con, replace(QUOTE, price_usd=2), now=161)
        self.assertEqual(self.snapshot(con), before)
        self.assertEqual(pt.paper_capital(con), (10, 10))

    def test_private_record_quote_also_serializes_before_history_write(self):
        con = self.connection()
        self.record(con)
        before = self.snapshot(con)
        pt._record_quote(con, 'mint', 'c', 100, 160,
                         replace(QUOTE, price_usd=2), MODEL)
        self.assertEqual(self.snapshot(con), before)
        self.assertEqual(self.conflicts(con), 1)
        self.assertFalse(con.in_transaction)

    def test_concurrent_engine_features_decisions_and_entry_are_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'synthetic.db'
            with closing(sqlite3.connect(db, isolation_level=None)) as con:
                pt.setup(con)
                pe.ensure_signal_status_schema(con)
                pe.ensure_audit_schema(con)
                con.execute('CREATE TABLE launch_candidates(mint,deployer_candidate,block_time,status)')
                con.execute("INSERT INTO launch_candidates VALUES('mint','c',100,'creator_identified')")
            barrier = threading.Barrier(2)
            async def fake_quote(session, *args, **kwargs):
                barrier.wait(timeout=5)
                return session, 0
            def worker(price):
                with closing(sqlite3.connect(db, isolation_level=None, timeout=5)) as con:
                    asyncio.run(pe.collect_once(con, replace(QUOTE, price_usd=price), [], 160,
                                                strategy_mode='shadow_final'))
            with patch.object(pe, 'fetch_quote', fake_quote), \
                    patch.object(pe.time, 'time', return_value=160), ThreadPoolExecutor(2) as pool:
                list(pool.map(worker, (1, 2)))
            with closing(sqlite3.connect(db)) as con:
                price = con.execute('SELECT price_usd FROM paper_prices').fetchone()[0]
                self.assertEqual(list(con.execute('SELECT price_usd FROM paper_decisions')), [(price,)])
                self.assertEqual(list(con.execute('SELECT entry_price FROM paper_trades')), [(price,)])
                self.assertEqual(self.conflicts(con), 1)
