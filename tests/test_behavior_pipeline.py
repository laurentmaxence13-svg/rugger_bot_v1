import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.analyser import behavior_pipeline as behavior


def _tx(block_time, mint, creator, sale=False, transfer=False):
    keys = [creator, 'destination', 'source']
    logs = ['Program log: Instruction: Sell'] if sale else []
    pre = [
        {'accountIndex': 2, 'mint': mint, 'owner': creator,
         'uiTokenAmount': {'uiAmount': 10.0, 'decimals': 0}},
    ]
    post = [
        {'accountIndex': 2, 'mint': mint, 'owner': creator,
         'uiTokenAmount': {'uiAmount': 0.0 if sale else 10.0, 'decimals': 0}},
    ]
    if transfer:
        post.append({'accountIndex': 1, 'mint': mint, 'owner': 'relay',
                     'uiTokenAmount': {'uiAmount': 10.0, 'decimals': 0}})
    instruction = {
        'parsed': {
            'type': 'transfer',
            'info': {'authority': creator, 'source': 'source',
                     'destination': 'destination'},
        }
    } if transfer else {}
    return {
        'blockTime': block_time,
        'transaction': {'message': {'accountKeys': keys,
                                    'instructions': [instruction]}},
        'meta': {
            'logMessages': logs,
            'preBalances': [1_000_000_000, 0, 0],
            'postBalances': [2_000_000_000 if sale else 1_000_000_000, 0, 0],
            'preTokenBalances': pre,
            'postTokenBalances': post,
        },
    }


class BehaviorTests(unittest.TestCase):
    def test_creator_sale_and_relay_are_classified(self):
        sale = behavior.classify_creator_behavior(
            _tx(1300, 'mint', 'creator', sale=True), 'mint', 'creator')
        self.assertTrue(sale['sale'])
        relay = behavior.classify_creator_behavior(
            _tx(1300, 'mint', 'creator', transfer=True), 'mint', 'creator')
        self.assertTrue(relay['relay'])

    def test_post_entry_transaction_is_not_used(self):
        event = (1000, 'launch', 'creator', 'mint', 'pool')
        prices = {'mint': [(1060, 1.0), (1300, 1.1), (1900, 1.2)]}
        cached = [(1500, 'sale', _tx(1500, 'mint', 'creator', sale=True))]
        observation = behavior.behavior_observation(
            event, prices, cached, prior_launches=1, exit_delay=900)
        self.assertIsNotNone(observation)
        self.assertFalse(observation['behavior_known'])
        self.assertFalse(observation['dev_sell_before_entry'])

    def test_behavior_grid_is_chronological_and_costed(self):
        events = [(1000 + i * 10000, str(i), f'creator{i % 3}',
                   f'mint{i}', 'pool') for i in range(50)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            db = root / 'db.sqlite'
            con = sqlite3.connect(db)
            con.execute('CREATE TABLE research_tx_cache '
                        '(signature TEXT, payload TEXT, fetched_ok INTEGER)')
            con.commit()
            con.close()
            prices_path = root / 'prices.csv'
            with prices_path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['mint', 'timestamp', 'price_usd'])
                for ts, _, _, mint, _ in events:
                    writer.writerow([mint, ts + 60, 1.0])
                    writer.writerow([mint, ts + 300, 1.1])
                    writer.writerow([mint, ts + 900, 1.3])
                    writer.writerow([mint, ts + 3660, 1.5])
            with patch.object(behavior, 'verified_launches', return_value=events):
                result = behavior.behavior_grid(db, prices_path)
            self.assertIn(result['status'], {'validated_behavior_found',
                                              'no_validated_behavior'})
            self.assertEqual(result['runs'][0]['train'], 35)
            self.assertEqual(result['runs'][0]['test'], 15)
            for run in result['runs']:
                self.assertEqual(run['cache_transactions'], 0)
                self.assertIn('message', run)


if __name__ == '__main__':
    unittest.main()
