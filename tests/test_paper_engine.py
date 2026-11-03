import asyncio
import sqlite3
import unittest
from unittest.mock import patch

from bot.analyser import paper_engine
from bot.analyser.paper_trader import MarketQuote, record_quote, setup


class PaperEngineTests(unittest.TestCase):
    def test_report_is_explicitly_paper_only(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        setup(con)
        report = paper_engine.paper_report(con, 1000, 12)
        self.assertTrue(report['paper_only'])
        self.assertFalse(report['real_orders_enabled'])
        self.assertFalse(report['private_keys_used'])
        self.assertEqual(report['cached_helius_transactions'], 12)

    def test_collect_once_records_quotes_without_model(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        setup(con)
        paper_engine.ensure_signal_status_schema(con)
        con.execute('''CREATE TABLE launch_candidates (
            mint TEXT, deployer_candidate TEXT, block_time INTEGER, status TEXT)''')
        con.execute(
            'INSERT INTO launch_candidates VALUES (?,?,?,?)',
            ('mint', 'creator', 1000, 'creator_identified'),
        )
        con.commit()

        async def fake_quote(_session, _mint, **_kwargs):
            return MarketQuote(20000.0, 1.0, 'pair'), 0

        with patch.object(paper_engine, 'fetch_quote', side_effect=fake_quote), \
                patch.object(paper_engine, 'record_quote', wraps=record_quote) as recorded:
            messages, cooldown, cache_changed = asyncio.run(paper_engine.collect_once(
                con, object(), [], now=1060, model=None, max_age=900,
                max_open=7, max_entries_day=13, max_daily_loss_pct=4))
        self.assertEqual(recorded.call_args.kwargs['max_open'], 7)
        self.assertEqual(recorded.call_args.kwargs['max_entries_day'], 13)
        self.assertEqual(recorded.call_args.kwargs['max_daily_loss_pct'], 4)
        self.assertEqual(cooldown, 0)
        self.assertFalse(cache_changed)
        self.assertTrue(any('PRIX_OK' in str(m) for m in messages))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0], 1)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 0)

    def test_shadow_baseline_creates_only_diagnostic_paper_trade(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        setup(con)
        model = paper_engine.shadow_baseline_model()
        message = record_quote(
            con, 'shadow-mint', 'creator', 1000, 1060,
            (20000.0, 1.0, 'pair'), model,
            strategy_mode='shadow_baseline',
        )
        self.assertIn('ENTRY', message)
        mode = con.execute(
            'SELECT strategy_mode FROM paper_trades WHERE mint=?',
            ('shadow-mint',),
        ).fetchone()[0]
        self.assertEqual(mode, 'shadow_baseline')
        report = paper_engine.paper_report(
            con, 1060, 0, strategy_mode='shadow_baseline'
        )
        self.assertTrue(report['paper_only'])
        self.assertEqual(report['shadow_open_positions'], 1)

    def test_behavior_snapshot_does_not_look_forward(self):
        cached = [(1500, 'sig', {'blockTime': 1500, 'mint': 'mint'})]
        before = paper_engine.behavior_snapshot(cached, 'mint', 'creator', 1000, 1400)
        after = paper_engine.behavior_snapshot(cached, 'mint', 'creator', 1000, 1600)
        self.assertFalse(before['behavior_known'])
        self.assertTrue(after['behavior_known'])


if __name__ == '__main__':
    unittest.main()
