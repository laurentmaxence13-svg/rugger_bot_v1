"""End-to-end read-only regression for DEXTrades pagination -> markout replay."""
import unittest
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'tools' / 'bitquery_dextrades_replay.py'
spec = spec_from_file_location('rugger_bitquery_replay', source)
m = module_from_spec(spec)
spec.loader.exec_module(m)

PROGRAM = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
WSOL = 'So11111111111111111111111111111111111111112'


def swap(slot, buy_token, price):
    # 100 units; only real observed swaps are fed to production.
    token = '100'
    sol = str(100 * price)
    buy = (token, 'mint-A') if buy_token else (sol, WSOL)
    sell = (sol, WSOL) if buy_token else (token, 'mint-A')
    def leg(amount, mint):
        return {'Amount': amount, 'AmountInUSD': '1',
                'Currency': {'MintAddress': mint, 'Symbol': 'TKN', 'Decimals': 6}}
    return {
        'Block': {'Slot': str(slot),
                  'Time': '2026-10-31T18:29:%02dZ' % (slot - 90)},
        'Transaction': {'Signature': 'signature-' + str(slot), 'Signer': 'signer-A'},
        'Trade': {
            'Dex': {'ProtocolName': 'raydium_launchpad', 'ProgramAddress': PROGRAM},
            'Market': {'MarketAddress': 'pool-A'},
            'Buy': leg(*buy), 'Sell': leg(*sell),
        },
    }


class ReplayPipelineTest(unittest.TestCase):
    def test_replay_is_observation_not_profit(self):
        pages = [('page1', {'Solana': {'DEXTrades': [
            swap(102, False, 0.009),
            swap(100, True, 0.01),
        ]}})]
        manifest, tape, report, marks = m.process(pages)
        self.assertEqual(manifest['observed_rows'], 2)
        self.assertEqual(report['strictly_later_first_opposite_side_markouts'], 1)
        self.assertEqual(marks[0]['observed_price_markout_pct'], '-10.00000000')
        self.assertFalse(marks[0]['exit_fill_for_our_order_proven'])
        self.assertIsNone(report['net_pnl_sol'])
        self.assertIsNone(report['master_minus_reference_net_pnl_sol'])

    def test_replay_page_overlap_is_not_double_counted(self):
        entry, sale = swap(100, True, 0.01), swap(102, False, 0.009)
        pages = [
            ('p1', {'Solana': {'DEXTrades': [sale, entry]}}),
            ('p2', {'Solana': {'DEXTrades': [entry, swap(99, True, 0.008)]}}),
        ]
        manifest, tape, report, marks = m.process(pages)
        self.assertEqual(manifest['observed_rows'], 3)
        self.assertEqual(manifest['pages'][1]['overlap_records'], 1)
        self.assertEqual(len(tape), 3)

    def test_cross_pair_cannot_create_wsol_price(self):
        row = swap(100, True, 0.01)
        row['Trade']['Sell']['Currency']['MintAddress'] = 'other-mint'
        tape = m.normalize([row])
        self.assertEqual(tape[0]['trade_direction'], 'CROSS_PAIR_NO_WSOL')
        self.assertFalse(tape[0]['wsol_trade'])
        self.assertEqual(tape[0]['execution_price_wsol_per_token'], '')


if __name__ == '__main__':
    unittest.main()
