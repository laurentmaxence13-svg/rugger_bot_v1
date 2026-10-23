"""Synthetic quote provenance; no provider or user database is contacted."""
import asyncio
from contextlib import closing, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from bot.analyser import launchlab_onchain as oc
from bot.analyser import paper_engine as pe
from bot.analyser import paper_trader as pt


class ProvenanceTests(unittest.TestCase):
    def connection(self):
        con = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(con.close)
        pt.setup(con)
        return con

    def store(self, con, quote, now=160):
        return pt.record_quote(con, 'mint', 'creator', 100, now, quote, None)

    def metadata(self, con):
        return con.execute('SELECT quote_source,funding_usd FROM paper_prices').fetchone()

    def test_launchlab_collection_to_storage(self):
        pool = dict(status=0, config='config', mint_b=oc.USDC, real_b=2000000,
                    decimals_b=6)
        with patch.object(oc, '_account', new_callable=AsyncMock) as account, \
                patch.object(oc, 'decode_pool', return_value=pool), \
                patch.object(oc, 'price_in_quote', return_value=.25):
            account.side_effect = [(oc.LAUNCHLAB, b'pool'), (oc.LAUNCHLAB, bytes(17))]
            quote = asyncio.run(oc.fetch_onchain_quote(None, 'mint', 'pool'))
        con = self.connection()
        self.store(con, quote)
        self.assertEqual(self.metadata(con), ('launchlab_curve', 2))
        self.assertEqual(con.execute('SELECT price_usd,liquidity_usd,timestamp '
                                     'FROM paper_prices').fetchone(), (.25, 2, 160))
        self.assertIsNone(quote.depth_usd)
        self.assertIsNone(quote.slippage_bps_est)

    def test_dexscreener_collection_to_storage(self):
        pair = dict(chainId='solana', baseToken={'address': 'mint'},
                    pairAddress='pair', priceUsd='1', liquidity={'usd': 10000},
                    pairCreatedAt=1234)
        class Response:
            status = 200
            def raise_for_status(self):
                pass
            async def json(self, **kwargs):
                return [pair]
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Session:
            def get(self, *args, **kwargs):
                return Response()
        quote, _ = asyncio.run(pt.fetch_quote(Session(), 'mint', include_metrics=True))
        con = self.connection()
        self.store(con, quote)
        self.assertEqual(self.metadata(con), ('dex_market', None))
        report = pe.paper_report(con, 200, 0)['quote_provenance']
        self.assertEqual(report['provider_timestamp_known_quotes'], 0)
        self.assertIsNone(report['provider_age_seconds'])

    def test_missing_metadata_rich_and_legacy(self):
        for quote in ((10000, 1, 'pair'), pt.MarketQuote(10000, 1, 'pair')):
            with self.subTest(quote=quote):
                con = self.connection()
                self.store(con, quote)
                self.assertEqual(self.metadata(con), (None, None))

    def test_null_and_zero_are_distinct(self):
        con = self.connection()
        self.store(con, pt.MarketQuote(0, 1, 'pool', quote_source='launchlab_curve', funding_usd=0))
        self.store(con, (0, 1, 'pool'), now=161)
        self.assertEqual(list(con.execute('SELECT funding_usd FROM paper_prices ORDER BY timestamp')),
                         [(0,), (None,)])
        report = pe.paper_report(con, 200, 0)['quote_provenance']
        self.assertEqual(report['funding_known_quotes'], 1)
        self.assertEqual(report['funding_coverage'], .5)

    def test_old_database_migration_on_synthetic_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / 'old.db'
            migrated = Path(tmp) / 'copy.db'
            with closing(sqlite3.connect(original)) as con, con:
                con.execute('''CREATE TABLE paper_prices(mint TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,price_usd REAL NOT NULL,
                    pair_address TEXT NOT NULL,liquidity_usd REAL NOT NULL,
                    PRIMARY KEY(mint,timestamp))''')
                con.execute("INSERT INTO paper_prices VALUES('old',100,1,'pair',10)")
            before = original.read_bytes()
            shutil.copyfile(original, migrated)
            with closing(sqlite3.connect(migrated)) as con:
                self.assertEqual(pe._quote_provenance(con)['unknown_source_quotes'], 1)
                pt.setup(con)
                pt.setup(con)
                self.assertEqual(con.execute('SELECT mint,timestamp,price_usd,pair_address,'
                    'liquidity_usd,quote_source,funding_usd FROM paper_prices').fetchone(),
                    ('old', 100, 1, 'pair', 10, None, None))
                self.store(con, pt.MarketQuote(0, 1, 'pool', quote_source='launchlab_curve', funding_usd=0))
                con.commit()
            with closing(sqlite3.connect(migrated)) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 2)
            self.assertEqual(original.read_bytes(), before)

    def test_duplicate_identical_is_quiet(self):
        con = self.connection()
        quote = pt.MarketQuote(10000, 1, 'pair', quote_source='dex_market')
        self.store(con, quote)
        out = io.StringIO()
        with redirect_stdout(out):
            self.store(con, quote)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 1)

    def test_duplicate_conflicts_keep_first_and_warn(self):
        base = pt.MarketQuote(10000, 1, 'pair', quote_source='dex_market')
        for changed in (replace(base, price_usd=2), replace(base, quote_source='launchlab_curve'),
                        replace(base, funding_usd=0), replace(base, pair_address='other')):
            with self.subTest(changed=changed):
                con = self.connection()
                self.store(con, base)
                out = io.StringIO()
                with redirect_stdout(out):
                    self.store(con, changed)
                self.assertIn('doublon contradictoire', out.getvalue())
                self.assertEqual(con.execute('SELECT price_usd,pair_address,quote_source,funding_usd '
                                             'FROM paper_prices').fetchone(), (1, 'pair', 'dex_market', None))

    def test_invalid_funding_becomes_unknown(self):
        for funding in (float('nan'), float('inf'), float('-inf'), -1):
            with self.subTest(funding=funding):
                con = self.connection()
                self.store(con, pt.MarketQuote(10000, 1, 'pair', funding_usd=funding))
                self.assertEqual(self.metadata(con), (None, None))
                json.dumps(pe.paper_report(con, 200, 0), allow_nan=False)

    def test_invalid_prices_still_rejected(self):
        for price in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(price=price):
                con = self.connection()
                with self.assertRaises(ValueError):
                    self.store(con, pt.MarketQuote(10000, price, 'pair', funding_usd=0))
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 0)

    def test_empty_report(self):
        con = self.connection()
        report = pe.paper_report(con, 200, 0)['quote_provenance']
        self.assertEqual(report['source_counts'], {})
        self.assertEqual(report['funding_coverage'], 0)
        self.assertIsNone(report['provider_age_seconds'])

    def test_source_counts_and_unknown_freshness(self):
        con = self.connection()
        for now, source in enumerate(('launchlab_curve', 'dex_market', None), 160):
            self.store(con, pt.MarketQuote(10000, 1, 'pair', quote_source=source), now)
        report = pe.paper_report(con, 200, 0)['quote_provenance']
        self.assertEqual(report['source_counts'], {'launchlab_curve': 1, 'dex_market': 1, 'unknown': 1})
        self.assertEqual(report['provider_timestamp_unknown_quotes'], 3)
        self.assertEqual(report['provider_age_measurable_quotes'], 0)

    def test_metadata_does_not_change_paper_accounting_or_decisions(self):
        snapshots = []
        for source, funding in ((None, None), ('dex_market', None), ('launchlab_curve', 0)):
            con = self.connection()
            model = pe.shadow_baseline_model()
            messages = []
            for now, price in ((160, 1), (220, 2)):
                messages.append(pt.record_quote(con, 'mint', 'creator', 100, now,
                    pt.MarketQuote(20000, price, 'pair', quote_source=source, funding_usd=funding),
                    model, strategy_mode='shadow_baseline'))
            snapshots.append((messages, list(con.execute('SELECT * FROM paper_trades')),
                              list(con.execute('SELECT * FROM paper_portfolio')),
                              list(con.execute('SELECT * FROM paper_decisions'))))
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0], snapshots[2])
        self.assertEqual(snapshots[0][1][0][-1], 'closed')

    def test_final_engine_decisions_unchanged(self):
        decisions = []
        for source in (None, 'dex_market', 'launchlab_curve'):
            con = self.connection()
            pe.ensure_signal_status_schema(con)
            pe.ensure_audit_schema(con)
            con.execute('CREATE TABLE launch_candidates(mint,deployer_candidate,block_time,status)')
            con.execute("INSERT INTO launch_candidates VALUES('mint','creator',1000,'creator_identified')")
            quote = pt.MarketQuote(20000, 1, 'pair', quote_source=source, funding_usd=20000)
            with patch.object(pe, 'fetch_quote', new_callable=AsyncMock, return_value=(quote, 0)), \
                    patch.object(pe.time, 'time', return_value=1060):
                asyncio.run(pe.collect_once(con, None, [], 1060, strategy_mode='shadow_final'))
            rows = list(con.execute('SELECT * FROM paper_decisions'))
            self.assertEqual(len(rows), 1)
            decisions.append(rows)
        self.assertEqual(decisions[0], decisions[1])
        # LaunchLab already has distinct scoring in the reference strategy.
        # Golden outputs are also exercised against the unmodified base commit.
        self.assertEqual([(rows[0][6], rows[0][8]) for rows in decisions],
                         [(1, 50), (1, 50), (1, 48)])
