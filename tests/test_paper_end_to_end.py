"""Deterministic ledger validation; does not claim a live trade."""
import sqlite3
import unittest
from bot.analyser.paper_trader import MarketQuote, record_quote, setup, paper_capital
from bot.analyser.final_decision_engine import Decision

class PaperEndToEndTests(unittest.TestCase):
    def test_entry_exit_and_capital(self):
        con = sqlite3.connect(':memory:')
        try:
            setup(con)
            model = Decision(enter=True, score=75, reasons=(), risk_flags=(),
                             tp_pct=10.0, sl_pct=8.0, hold_seconds=300,
                             trailing_stop_pct=None, cost_bps=200).to_paper_model()
            start = 100000
            entry = record_quote(con, 'mint_test', 'creator_test', start,
                start + 65, MarketQuote(12000, .001, 'pool'), model,
                strategy_mode='shadow_final')
            self.assertTrue(entry and entry.startswith('ENTRY '), entry)
            exit_message = record_quote(con, 'mint_test', 'creator_test', start,
                start + 80, MarketQuote(12000, .0012, 'pool'), model,
                strategy_mode='shadow_final')
            self.assertTrue(exit_message and exit_message.startswith('EXIT '), exit_message)
            row = con.execute('SELECT status,exit_reason,pnl_sol FROM paper_trades WHERE mint=?',
                              ('mint_test',)).fetchone()
            self.assertEqual(row[0], 'closed')
            self.assertEqual(row[1], 'TP')
            self.assertGreater(row[2], 0)
            initial, final = paper_capital(con)
            self.assertGreater(final, initial)
        finally:
            con.close()

if __name__ == '__main__':
    unittest.main()
