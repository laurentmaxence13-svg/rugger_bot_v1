"""Deterministic full-pipeline PAPER validation. No network, orders or wallet."""
import asyncio
import sqlite3
import time
import unittest
from unittest.mock import patch

from bot.analyser import paper_engine as pe
from bot.analyser.final_decision_engine import Decision
from bot.analyser.paper_trader import MarketQuote, paper_capital, record_quote, setup


class ShadowFinalEntryFlowTests(unittest.TestCase):
    @staticmethod
    def decision(enter):
        return Decision(
            enter=enter, score=56.0 if enter else 20.0,
            reasons=('test_selection',) if enter else (),
            risk_flags=() if enter else ('vente_developpeur',),
            tp_pct=10.0, sl_pct=8.0, hold_seconds=300,
            trailing_stop_pct=None, cost_bps=200,
        )

    @staticmethod
    def db(now):
        con = sqlite3.connect(':memory:')
        con.execute('''CREATE TABLE launch_candidates (
            id INTEGER PRIMARY KEY, protocol TEXT, signature TEXT UNIQUE,
            slot INTEGER, block_time INTEGER, detected_at TEXT, mint TEXT,
            deployer_candidate TEXT, detection_latency_ms INTEGER,
            status TEXT, pool_state TEXT)''')
        setup(con)
        pe.ensure_signal_status_schema(con)
        con.execute('''INSERT INTO launch_candidates(
            protocol,signature,slot,block_time,detected_at,mint,
            deployer_candidate,status,pool_state)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            ('ray', 'sig-123', 1, now-20, 'now', 'test_mint',
             'test_creator', 'creator_identified', None))
        return con

    def test_approved_at_20_seconds_opens_and_closes_with_realized_pnl(self):
        start = int(time.time())
        con = self.db(start)
        clock = {'now': start}
        quotes = [MarketQuote(16000.0, 0.001, 'test_pool'),
                  MarketQuote(16000.0, 0.00120, 'test_pool')]

        async def fetch_quote(*args, **kwargs):
            return quotes.pop(0), 0

        try:
            with patch.object(pe, 'fetch_quote', fetch_quote), \
                 patch.object(pe, 'decide', return_value=self.decision(True)), \
                 patch.object(pe.time, 'time', side_effect=lambda: clock['now']):
                messages, _, _ = asyncio.run(pe.collect_once(
                    con, None, [], start, strategy_mode='shadow_final',
                    initial_capital_sol=10.0, position_pct=10.0))
                row = con.execute('''SELECT status,entry_time,entry_price,position_sol
                                     FROM paper_trades WHERE mint='test_mint' ''').fetchone()
                self.assertIsNotNone(row, messages)
                self.assertEqual(row[0], 'open')
                self.assertEqual(row[1], start)
                self.assertAlmostEqual(row[2], 0.001)
                self.assertAlmostEqual(row[3], 1.0)
                self.assertTrue(any('TRADE_PAPER_OUVERT' in message for message in messages), messages)
                self.assertEqual(con.execute('''SELECT enter,entry_allowed,score
                    FROM paper_decisions ORDER BY id DESC LIMIT 1''').fetchone(), (1,1,56.0))
                clock['now'] += 20
                messages, _, _ = asyncio.run(pe.collect_once(
                    con, None, [], clock['now'], strategy_mode='shadow_final',
                    initial_capital_sol=10.0, position_pct=10.0))
            trade = con.execute('''SELECT status,exit_reason,net_return,pnl_sol
                                   FROM paper_trades WHERE mint='test_mint' ''').fetchone()
            self.assertEqual(trade[0], 'closed')
            self.assertEqual(trade[1], 'TP')
            self.assertAlmostEqual(trade[2], 0.18)
            self.assertAlmostEqual(trade[3], 0.18)
            self.assertEqual(paper_capital(con), (10.0, 10.18))
            self.assertTrue(any('TRADE_PAPER_FERME' in message for message in messages), messages)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 1)
        finally:
            con.close()

    def test_rejected_decision_never_opens(self):
        con = sqlite3.connect(':memory:')
        setup(con)
        try:
            bad = self.decision(False).to_paper_model()
            msg = record_quote(con, 'rejected', 'c', 100, 120,
                               MarketQuote(16000, .001, 'pool'), bad,
                               strategy_mode='shadow_final')
            self.assertIsNone(msg)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)
        finally:
            con.close()

    def test_paper_risk_limits_override_approved_decision(self):
        con = sqlite3.connect(':memory:')
        setup(con)
        try:
            approved = self.decision(True).to_paper_model()
            msg = record_quote(con, 'blocked', 'c', 100, 120,
                               MarketQuote(16000, .001, 'pool'), approved,
                               allow_entry=False, strategy_mode='shadow_final')
            self.assertIsNone(msg)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)
        finally:
            con.close()

    def test_legacy_model_keeps_original_entry_window(self):
        con = sqlite3.connect(':memory:')
        setup(con)
        try:
            legacy = {'creator_scores': {}, 'fallback_score': 0.75}
            msg = record_quote(con, 'early', 'c', 100, 120,
                               MarketQuote(16000, .001, 'pool'), legacy,
                               strategy_mode='validated')
            self.assertIsNone(msg)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)
        finally:
            con.close()


if __name__ == '__main__':
    unittest.main()
