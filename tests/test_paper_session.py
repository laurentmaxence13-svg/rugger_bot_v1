import sqlite3
import tempfile
import unittest
from pathlib import Path
from bot.analyser.paper_trader import setup, ensure_paper_portfolio
from bot.analyser.paper_engine import _session_summary

class PaperSessionTests(unittest.TestCase):
    def test_summary_is_scoped_to_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 's.db'
            con = sqlite3.connect(db)
            setup(con); ensure_paper_portfolio(con, 10.0, 1000)
            # one old trade must not pollute the new session
            con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,exit_time,exit_price,net_return,cost_bps,strategy_mode,position_sol,pnl_sol,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ('old','c',1,10,1,20,1.1,.08,200,'shadow_final',1,.08,'closed'))
            con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,exit_time,exit_price,net_return,cost_bps,strategy_mode,position_sol,pnl_sol,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ('new','c',1000,1010,1,1020,1.2,.18,200,'shadow_final',1,.18,'closed'))
            con.execute("INSERT INTO paper_decisions(mint,creator,signal_time,decision_time,strategy_mode,enter,entry_allowed,score,reasons_json,risk_flags_json,prior_launches,behavior_known,dev_sales,relay_transfers,bundle_transactions,bundle_wallets,liquidity_usd,price_usd,quote_count,hold_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ('new','c',1000,1005,'shadow_final',1,1,70,'[]','[]',1,1,0,0,0,0,9000,1e-5,1,3600))
            # Realized capital must include both synthetic closed trades.
            con.execute('UPDATE paper_portfolio SET realized_capital_sol=10.26')
            con.commit()
            s = _session_summary(con, 1000, 1100)
            self.assertEqual(s['entries'], 1)
            self.assertEqual(s['closed_trades'], 1)
            self.assertAlmostEqual(s['pnl_sol'], .18)
            self.assertEqual(s['decisions'], 1)
            con.close()

if __name__ == '__main__': unittest.main()
