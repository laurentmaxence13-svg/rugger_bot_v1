import asyncio
import sqlite3
import struct
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.analyser import launchlab_onchain as oc
from bot.database.db import Database


def key(seed):
    return oc.b58encode(bytes([seed]) * 32)


class OnchainTests(unittest.TestCase):
    def make_pool(self):
        mint = key(4)
        data = bytearray(320)
        data[17:21] = bytes([0, 6, 9, 1])
        struct.pack_into('<6Q', data, 21, 1000000000, 800000000, 800000000, 3000000000, 400000000, 1000000000)
        data[141:173] = bytes([3])*32
        data[205:237] = bytes([4])*32
        data[237:269] = bytes([5])*32
        pool = oc.decode_pool(bytes(data), mint)
        self.assertIsNotNone(pool)
        self.assertEqual(pool['config'], key(3))
        self.assertIsNone(oc.decode_pool(bytes(data), key(6)))
        self.assertAlmostEqual(oc.price_in_quote(pool, 0), 0.01)
        self.assertAlmostEqual(oc.price_in_quote(pool, 2), (800000000 * 400000000 / (1 << 64)) * .001)
        self.assertIsNone(oc.price_in_quote(pool, 3))
        return mint, bytes(data)

    def test_decode_curve_and_reject_wrong_mint(self):
        self.make_pool()

    def test_quote_from_verified_pool(self):
        mint, data = self.make_pool()
        pool = oc.decode_pool(data, mint)
        pool['mint_b'] = oc.USDC
        with patch.object(oc, 'decode_pool', return_value=pool), patch.object(oc, '_account') as mock:
            async def accounts(_session, address):
                if address == 'pool':
                    return oc.LAUNCHLAB, data
                return oc.LAUNCHLAB, bytes(16) + bytes([0])
            mock.side_effect = accounts
            quote = asyncio.run(oc.fetch_onchain_quote(None, mint, 'pool'))
        self.assertIsNotNone(quote)
        self.assertGreater(quote.price_usd, 0)
        self.assertEqual(quote.pair_address, 'pool')

    def test_database_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.db'
            with closing(sqlite3.connect(path)) as con:
                con.execute('''CREATE TABLE launch_candidates (
                  id INTEGER PRIMARY KEY, protocol TEXT NOT NULL,
                  signature TEXT UNIQUE, slot INTEGER NOT NULL, block_time INTEGER,
                  detected_at TEXT NOT NULL, mint TEXT, deployer_candidate TEXT,
                  detection_latency_ms INTEGER, status TEXT NOT NULL)''')
            db = Database(path)
            self.assertTrue(db.save_candidate(protocol='ray',signature='tx',slot=1,
                block_time=1,detected_at='x',mint='m',deployer_candidate='d',
                detection_latency_ms=1,status='creator_identified',pool_state='pool'))
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT pool_state FROM launch_candidates').fetchone()[0], 'pool')

if __name__ == '__main__':
    unittest.main()
