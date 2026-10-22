import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.analyser import research_pipeline as research
from bot.analyser.paper_trader import (
    choose_quote, eligible_model, entry_allowed, record_quote, setup,
)


class PipelineTests(unittest.TestCase):
    def test_real_dataset_and_insufficient_backtest(self):
        db = Path(__file__).resolve().parents[1] / 'data' / 'rugger_bot.db'
        if not db.exists():
            self.skipTest('base utilisateur absente')
        if len(research.verified_launches(db)) >= 45:
            self.skipTest('base utilisateur assez grande : test historique obsolète')
        with tempfile.TemporaryDirectory() as d:
            n, creators = research.export_dataset(db, Path(d) / 'dataset.csv')
            self.assertGreaterEqual(n, 27)
            self.assertGreaterEqual(creators, 10)
            with self.assertRaisesRegex(ValueError, 'Corpus insuffisant'):
                research.backtest(db, Path(d) / 'unused.csv')

    def test_chronological_train_test_with_future_prices_excluded(self):
        events = [(1000 + i*10000, str(i), f'creator{i % 3}', f'mint{i}', 'pool') for i in range(50)]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'prices.csv'
            with path.open('w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['mint', 'timestamp', 'price_usd'])
                for ts, _, _, mint, _ in events:
                    w.writerow([mint, ts+60, 1])
                    w.writerow([mint, ts+3660, 1.2])
            with patch.object(research, 'verified_launches', return_value=events):
                result = research.backtest(':memory:', path)
            self.assertEqual((result['train'], result['test'], result['selected']), (35, 15, 15))
            self.assertLess(result['train_end'], result['test_start'])
            self.assertAlmostEqual(result['mean_return'], .18)

    def test_paper_no_model_and_idempotent_fill(self):
        con = sqlite3.connect(':memory:')
        setup(con)
        quote = (20000, 1, 'pair')
        self.assertIsNone(record_quote(con, 'mint', 'creator', 1000, 1060, quote, None))
        self.assertEqual(con.execute('select count(*) from paper_trades').fetchone()[0], 0)
        model = {'creator_scores': {'creator': .1}, 'fallback_score': 0}
        self.assertIn('ENTRY', record_quote(con, 'mint', 'creator', 1000, 1070, quote, model))
        self.assertIsNone(record_quote(con, 'mint', 'creator', 1000, 1080, quote, model))
        self.assertIn('EXIT', record_quote(con, 'mint', 'creator', 1000, 4670, (20000, 1.2, 'pair'), model))
        self.assertEqual(con.execute('select count(*) from paper_trades').fetchone()[0], 1)

    def test_paper_dynamic_take_profit_and_stop_loss(self):
        con = sqlite3.connect(':memory:')
        setup(con)
        model = {
            'creator_scores': {'creator': .1}, 'fallback_score': 0,
            'tp_pct': 10, 'sl_pct': 8, 'hold_seconds': 3600,
            'cost_bps': 200,
        }
        self.assertIn('ENTRY', record_quote(con, 'tp', 'creator', 1000, 1060,
                                            (20000, 1.0, 'pair'), model))
        self.assertIn('reason=TP', record_quote(con, 'tp', 'creator', 1000, 1070,
                                                 (20000, 1.11, 'pair'), model))
        reason = con.execute('select exit_reason from paper_trades where mint=?', ('tp',)).fetchone()[0]
        self.assertEqual(reason, 'TP')

        self.assertIn('ENTRY', record_quote(con, 'sl', 'creator', 1000, 1060,
                                            (20000, 1.0, 'pair'), model))
        self.assertIn('reason=SL', record_quote(con, 'sl', 'creator', 1000, 1070,
                                                 (20000, .91, 'pair'), model))
        reason = con.execute('select exit_reason from paper_trades where mint=?', ('sl',)).fetchone()[0]
        self.assertEqual(reason, 'SL')

    def test_paper_entry_limits(self):
        con = sqlite3.connect(':memory:')
        setup(con)
        model = {'creator_scores': {'creator': .1}, 'fallback_score': 0}
        self.assertTrue(entry_allowed(con, 86400, max_open=1, max_entries_day=1))
        record_quote(con, 'one', 'creator', 86400, 86460,
                     (20000, 1.0, 'pair'), model)
        self.assertFalse(entry_allowed(con, 86460, max_open=1, max_entries_day=1))

        con.execute('''UPDATE paper_trades
                       SET status='closed', net_return=-0.11, exit_reason='SL'
                       WHERE mint='one' ''')
        self.assertFalse(entry_allowed(con, 86460, max_open=3,
                                       max_entries_day=20,
                                       max_daily_loss_pct=10))

    def test_liquidity_guard(self):
        pair = {'chainId': 'solana', 'baseToken': {'address': 'mint'}, 'priceUsd': '1',
                'liquidity': {'usd': 500}, 'pairAddress': 'pair'}
        self.assertIsNone(choose_quote([pair], 'mint'))
        pair['liquidity']['usd'] = 20000
        self.assertEqual(choose_quote([pair], 'mint'), (20000, 1, 'pair'))

    def test_momentum_grid_uses_only_pre_entry_price(self):
        events = [(1000 + i * 10000, str(i), f'creator{i % 3}',
                   f'mint{i}', 'pool') for i in range(50)]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'prices.csv'
            with path.open('w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['mint', 'timestamp', 'price_usd'])
                for ts, _, _, mint, _ in events:
                    w.writerow([mint, ts + 60, 1.0])
                    w.writerow([mint, ts + 300, 1.1])
                    w.writerow([mint, ts + 900, 1.3])
                    w.writerow([mint, ts + 3660, 1.5])
            with patch.object(research, 'verified_launches', return_value=events):
                result = research.momentum_grid(':memory:', path)
            self.assertEqual(result['status'], 'validated_momentum_found')
            self.assertEqual(result['eligible_exit_delays'], [900, 3660])
            self.assertEqual(result['runs'][0]['entry_delay'], 300)


if __name__ == '__main__':
    unittest.main()
