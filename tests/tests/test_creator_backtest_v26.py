import unittest
from contextlib import redirect_stdout
from io import StringIO

from bot.analyser.creator_backtest_v26 import (
    _v25_execute,
    _v26_accept,
    _v26_features,
    run_v26_launch_selector,
)


class CreatorBacktestV26Tests(unittest.TestCase):
    def setUp(self):
        self.row = {
            'launch_time': 1000,
            'sale_time': 1300,
            'relay': 'relay-a',
            'transfer_time': 1002,
            'market_series': [
                {'time': 1005, 'price': 1.0},
                {'time': 1010, 'price': 1.20},
                {'time': 1050, 'price': 1.10},
            ],
        }

    def test_v25_uses_observed_price_and_dynamic_exit(self):
        result = _v25_execute(
            self.row, delay_s=2, tp_pct=10, sl_pct=10,
            timeout_s=300, latency_s=2, cost_side_pct=1.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['reason'], 'TP')
        self.assertEqual(result['entry_time'], 1005)
        self.assertGreater(result['pnl_pct'], 0)

    def test_v26_features_only_use_information_before_signal(self):
        rows = [dict(self.row)]
        features = _v26_features(rows, 0, delay_s=2, latency_s=2)
        self.assertIsNotNone(features)
        self.assertTrue(features['relay_visible'])
        self.assertEqual(features['observed_points'], 0)
        self.assertIsNone(features['momentum_pct'])

    def test_v26_accept_applies_relay_and_transfer_guards(self):
        features = {
            'relay_visible': True,
            'relay_prior_count': 1,
            'transfer_delay': 2,
            'observed_points': 2,
            'momentum_pct': 5,
        }
        self.assertTrue(_v26_accept(features, {
            'require_relay': True, 'min_relay_prior': 1,
            'max_transfer_delay': 2, 'min_points': 2,
            'min_momentum': 0, 'max_momentum': 20,
        }))
        features['transfer_delay'] = 3
        self.assertFalse(_v26_accept(features, {
            'require_relay': True, 'min_relay_prior': 1,
            'max_transfer_delay': 2, 'min_points': 2,
            'min_momentum': 0, 'max_momentum': 20,
        }))

    def test_v26_report_refuses_insufficient_data(self):
        with redirect_stdout(StringIO()):
            report = run_v26_launch_selector([])
        self.assertEqual(report['status'], 'insufficient_data')
        self.assertEqual(report['selected'], 0)


if __name__ == '__main__':
    unittest.main()
