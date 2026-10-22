import asyncio
import sqlite3
import time
import unittest
from unittest.mock import patch

from bot.analyser import paper_engine as pe
from bot.analyser.paper_trader import MarketQuote, setup


class PaperPipelineTests(unittest.TestCase):
    def make_db(self):
        con = sqlite3.connect(':memory:')
        con.execute('''CREATE TABLE launch_candidates(
          id INTEGER PRIMARY KEY, protocol TEXT, signature TEXT UNIQUE,
          slot INTEGER, block_time INTEGER, detected_at TEXT, mint TEXT,
          deployer_candidate TEXT, detection_latency_ms INTEGER, status TEXT)''')
        setup(con)
        pe.ensure_signal_status_schema(con)
        return con

    def seed(self, con, age=70):
        now = int(time.time())
        mint = 'MintTest111111111111111111111111111111111'
        con.execute('''INSERT INTO launch_candidates(
          protocol,signature,slot,block_time,detected_at,mint,
          deployer_candidate,status) VALUES(?,?,?,?,?,?,?,?)''',
          ('ray','sig',1,now-age,'x',mint,'Creator1','creator_identified'))
        return now, mint

    def test_unindexed_mint_gets_explicit_status(self):
        con = self.make_db(); now, mint = self.seed(con)
        async def noquote(*args, **kwargs): return None, 0
        with patch.object(pe, 'fetch_quote', noquote):
            asyncio.run(pe.collect_once(
                con, None, [], now, live_fetcher=None,
                strategy_mode='shadow_final', min_liquidity=1000))
        status = con.execute(
            'SELECT status FROM paper_signal_status WHERE mint=?',(mint,)
        ).fetchone()[0]
        self.assertEqual(status, 'PRIX_NON_INDEXE')

    def test_low_liquidity_reaches_decision_and_reject(self):
        con = self.make_db(); now, mint = self.seed(con)
        async def quote(*args, **kwargs):
            return MarketQuote(100.0, 0.001, 'pair'), 0
        with patch.object(pe, 'fetch_quote', quote):
            asyncio.run(pe.collect_once(
                con, None, [], now, live_fetcher=None,
                strategy_mode='shadow_final', min_liquidity=1000))
        self.assertEqual(con.execute(
            'SELECT COUNT(*) FROM paper_decisions').fetchone()[0], 1)
        self.assertEqual(con.execute(
            'SELECT status FROM paper_signal_status WHERE mint=?',(mint,)
        ).fetchone()[0], 'REJET')


if __name__ == '__main__':
    unittest.main()
