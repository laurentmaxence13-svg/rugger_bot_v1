import asyncio
import json
import sqlite3
import time
import unittest
from unittest.mock import patch
from bot.analyser import paper_engine as pe
from bot.analyser.paper_trader import setup, MarketQuote

class AuditTests(unittest.TestCase):
    def database(self):
        con=sqlite3.connect(':memory:')
        con.execute('CREATE TABLE launch_candidates (id INTEGER PRIMARY KEY, protocol TEXT, signature TEXT UNIQUE, slot INTEGER, block_time INTEGER, detected_at TEXT, mint TEXT, deployer_candidate TEXT, detection_latency_ms INTEGER, status TEXT, pool_state TEXT)')
        setup(con)
        pe.ensure_signal_status_schema(con)
        now=int(time.time())
        con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,detected_at,mint,deployer_candidate,status,pool_state) VALUES (?,?,?,?,?,?,?,?,?)',('ray','tx',1,now-20,'now','Mint123','Creator123','creator_identified','Pool123'))
        return con,now
    def test_missing_price_creates_audited_safe_rejection(self):
        con,now=self.database()
        async def missing(*args,**kwargs):return None
        async def no_dex(*args,**kwargs):return None,0
        with patch.object(pe,'fetch_onchain_quote',missing),patch.object(pe,'fetch_quote',no_dex):
            messages,*_=asyncio.run(pe.collect_once(con,None,[],now,strategy_mode='shadow_final'))
        data=json.loads(con.execute('SELECT report_json FROM paper_mint_audit').fetchone()[0])
        self.assertEqual(data['decision_finale'],'REJET_PROVISOIRE')
        self.assertIsNone(data['prix_usd'])
        self.assertIsNone(data['score'])
        self.assertTrue(any('DECISION=REJET_PROVISOIRE' in m for m in messages))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0],0)
    def test_real_quote_creates_full_score_audit(self):
        con,now=self.database()
        async def quote(*args,**kwargs):return MarketQuote(100,0.001,'Pool123')
        with patch.object(pe,'fetch_onchain_quote',quote):
            asyncio.run(pe.collect_once(con,None,[],now,strategy_mode='shadow_final'))
        data=json.loads(con.execute('SELECT report_json FROM paper_mint_audit').fetchone()[0])
        self.assertEqual(data['prix_usd'],0.001)
        self.assertEqual(data['liquidite_usd'],100)
        self.assertIsNotNone(data['score'])
        self.assertEqual(data['decision_finale'],'REJET')
if __name__=='__main__': unittest.main()
