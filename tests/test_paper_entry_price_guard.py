"""Entry prices are positive finite numbers; exits may realize total loss."""
import sqlite3
import unittest

from bot.analyser.paper_trader import (
    MarketQuote, choose_quote_details, paper_capital, record_quote, setup,
)


MODEL = {'creator_scores': {'c': .1}, 'fallback_score': 0, 'sl_pct': 10,
         'cost_bps': 200}
INVALID = (0, -1, float('nan'), float('inf'), float('-inf'), None, 'invalid', {}, '1.0')


class PaperEntryPriceGuardTests(unittest.TestCase):
    def connection(self):
        con = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(con.close)
        setup(con)
        return con

    def quote(self, price, rich):
        return MarketQuote(10000, price, 'pair') if rich else (10000, price, 'pair')

    def enter(self, con, price, rich, mode='validated'):
        model = {**MODEL, 'decision_approved': True, 'decision_score': 70}
        return record_quote(con, 'mint', 'c', 100, 160, self.quote(price, rich),
                            model, strategy_mode=mode)

    def test_invalid_prices_rejected_for_both_shapes_and_all_modes(self):
        for mode in ('validated', 'shadow_baseline', 'shadow_final'):
            for rich in (False, True):
                for price in INVALID:
                    with self.subTest(mode=mode, rich=rich, price=price):
                        con = self.connection()
                        with self.assertRaises(ValueError):
                            self.enter(con, price, rich, mode)
                        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)
                        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 0)
                        self.assertEqual(paper_capital(con), (None, None))
                        self.assertFalse(con.in_transaction)

    def test_valid_prices_keep_allocation_and_initial_capital(self):
        for mode in ('validated', 'shadow_baseline', 'shadow_final'):
            for rich in (False, True):
                with self.subTest(mode=mode, rich=rich):
                    con = self.connection()
                    self.assertIn('ENTRY ', self.enter(con, .25, rich, mode))
                    self.assertEqual(con.execute('SELECT entry_price,position_sol FROM paper_trades').fetchone(), (.25, 1))
                    self.assertEqual(paper_capital(con), (10, 10))

    def test_existing_position_closes_at_zero_for_both_shapes(self):
        for rich in (False, True):
            with self.subTest(rich=rich):
                con = self.connection()
                self.enter(con, 1, rich)
                msg = record_quote(con, 'mint', 'c', 100, 200, self.quote(0, rich), MODEL,
                                   allow_entry=False, max_open=0, max_entries_day=0)
                self.assertIn('reason=SL', msg)
                status, price, net, pnl = con.execute(
                    'SELECT status,exit_price,net_return,pnl_sol FROM paper_trades').fetchone()
                self.assertEqual((status, price), ('closed', 0))
                self.assertAlmostEqual(net, -1.02)
                self.assertAlmostEqual(pnl, -1.02)
                self.assertAlmostEqual(paper_capital(con)[1], 8.98)
                self.assertIsNone(record_quote(con, 'mint', 'c', 100, 201, self.quote(0, rich), MODEL))
                self.assertAlmostEqual(paper_capital(con)[1], 8.98)

    def test_invalid_exit_preserves_existing_position_and_capital(self):
        for rich in (False, True):
            for price in INVALID[1:]:
                with self.subTest(rich=rich, price=price):
                    con = self.connection()
                    self.enter(con, 1, rich)
                    with self.assertRaises(ValueError):
                        record_quote(con, 'mint', 'c', 100, 200, self.quote(price, rich), MODEL)
                    self.assertEqual(con.execute('SELECT status,pnl_sol,exit_time FROM paper_trades').fetchone(), ('open', None, None))
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 1)
                    self.assertEqual(paper_capital(con), (10, 10))

    def test_failed_price_guard_preserves_callers_transaction(self):
        con = self.connection()
        self.enter(con, 1, True)
        con.execute('BEGIN')
        con.execute("UPDATE paper_trades SET creator='outer'")
        with self.assertRaises(ValueError):
            record_quote(con, 'new', 'c', 100, 160, self.quote(0, True), MODEL)
        self.assertTrue(con.in_transaction)
        self.assertEqual(con.execute('SELECT creator FROM paper_trades').fetchone()[0], 'outer')
        self.assertEqual(paper_capital(con), (10, 10))
        con.rollback()
        self.assertEqual(con.execute('SELECT creator FROM paper_trades').fetchone()[0], 'c')

    def test_market_pair_rejects_zero_and_other_invalid_prices(self):
        for price in (0, '0', -1, 'invalid', None, float('nan'), float('inf'), float('-inf')):
            with self.subTest(price=price):
                pair = {'chainId': 'solana', 'baseToken': {'address': 'mint'},
                        'pairAddress': 'pair', 'liquidity': {'usd': 10000}, 'priceUsd': price}
                self.assertIsNone(choose_quote_details([pair], 'mint'))
