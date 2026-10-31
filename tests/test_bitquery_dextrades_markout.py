"""No-network / no-wallet regression tests for DEXTrades observed-markout audit."""
import unittest
from decimal import Decimal

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

# The isolated CI runner does not add the repo root to sys.path.
module_path = Path(__file__).resolve().parents[1] / 'tools' / 'bitquery_dextrades_markout.py'
spec = spec_from_file_location('rugger_bitquery_dextrades_markout', module_path)
module = module_from_spec(spec)
spec.loader.exec_module(module)
BUY, SELL = module.BUY, module.SELL
make_report, parse_rows = module.make_report, module.parse_rows
WSOL, PROGRAMS = module.WSOL, module.PROGRAMS

MINT = 'DoNotUseThisAsATokenMint0000000000000000000001'
POOL = 'SyntheticPoolResearchOnly'


def event(event_id, slot, second, direction, price, pool=POOL):
    """Synthetic equal-quantity swaps; price is WSOL per token."""
    token_amount = '100'
    wsol_amount = str(Decimal(str(price)) * Decimal('100'))
    buy = direction == BUY
    return {
        'event_id': event_id,
        'block_slot': str(slot),
        'block_time_utc': '2026-10-31T18:29:%02dZ' % second,
        'signature': 'synthetic-' + event_id,
        'protocol': 'raydium_launchpad',
        'program_address': PROGRAMS['raydium_launchpad'],
        'market_address': pool,
        'wsol_trade': 'True',
        'trade_direction': direction,
        'buy_mint': MINT if buy else WSOL,
        'sell_mint': WSOL if buy else MINT,
        'token_mint': MINT,
        'token_amount': token_amount,
        'wsol_amount': wsol_amount,
        'execution_price_wsol_per_token': str(price),
    }


class DextradesGateTest(unittest.TestCase):
    def test_strict_later_price_observation_never_becomes_pnl(self):
        rows = [
            event('entry', 100, 1, BUY, 0.01),
            event('sale', 101, 3, SELL, 0.009),
        ]
        report, markouts = make_report(rows)
        self.assertEqual(report['strictly_later_first_opposite_side_markouts'], 1)
        self.assertEqual(markouts[0]['observed_price_markout_pct'], '-10.00000000')
        self.assertIsNone(report['net_pnl_sol'])
        self.assertIsNone(report['master_minus_reference_net_pnl_sol'])
        self.assertEqual(report['certified_paper_trades'], 0)
        self.assertFalse(markouts[0]['exit_fill_for_our_order_proven'])

    def test_same_slot_never_proves_order(self):
        report, marks = make_report([
            event('entry', 100, 1, BUY, 0.01),
            event('same-slot-exit', 100, 2, SELL, 0.02),
        ])
        self.assertEqual(report['strictly_later_first_opposite_side_markouts'], 0)
        self.assertEqual(report['no_later_exit_observation'], 1)
        self.assertFalse(marks)

    def test_ambiguous_first_sale_slot_excluded(self):
        report, marks = make_report([
            event('entry', 100, 1, BUY, 0.01),
            event('sale-a', 101, 2, SELL, 0.009),
            event('sale-b', 101, 2, SELL, 0.02),
            event('sale-later', 102, 3, SELL, 0.03),
        ])
        self.assertEqual(report['ambiguous_first_exit_slot'], 1)
        self.assertEqual(len(marks), 0)

    def test_cross_pool_exit_not_substituted(self):
        report, marks = make_report([
            event('entry', 100, 1, BUY, 0.01),
            event('another-pool', 101, 3, SELL, 0.02, pool='different'),
        ])
        self.assertEqual(report['no_later_exit_observation'], 1)
        self.assertFalse(marks)

    def test_wrong_program_rejected(self):
        row = event('entry', 100, 1, BUY, 0.01)
        row['program_address'] = 'not-raydium'
        with self.assertRaises(ValueError):
            parse_rows([row])

    def test_price_mismatch_rejected(self):
        row = event('entry', 100, 1, BUY, 0.01)
        row['execution_price_wsol_per_token'] = '100'
        with self.assertRaises(ValueError):
            parse_rows([row])

    def test_duplicate_event_id_rejected(self):
        row = event('entry', 100, 1, BUY, 0.01)
        with self.assertRaises(ValueError):
            parse_rows([row, dict(row)])

    def test_backward_exit_never_selected(self):
        report, marks = make_report([
            event('entry', 100, 3, BUY, 0.01),
            event('old', 99, 2, SELL, 0.02),
        ])
        self.assertEqual(report['strictly_later_first_opposite_side_markouts'], 0)
        self.assertFalse(marks)


if __name__ == '__main__':
    unittest.main()
