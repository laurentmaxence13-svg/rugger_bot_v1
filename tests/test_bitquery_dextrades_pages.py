"""Strict offline tests for paged Solana DEXTrades observations."""
import json
import unittest
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'tools' / 'bitquery_dextrades_pages.py'
spec = spec_from_file_location('rugger_paged_dextrades', path)
m = module_from_spec(spec)
spec.loader.exec_module(m)


def row(slot=120, amount='12.345', signature='signature-A'):
    return {
        'Block': {'Slot': str(slot), 'Time': '2026-10-31T18:30:00Z'},
        'Transaction': {'Signature': signature, 'Signer': 'Signer-A'},
        'Trade': {
            'Dex': {'ProtocolName': 'raydium_cp_swap',
                    'ProgramAddress': m.VALID_PROGRAMS['raydium_cp_swap']},
            'Market': {'MarketAddress': 'pool-A'},
            'Buy': {'Amount': str(amount), 'AmountInUSD': '0.15',
                    'Currency': {'MintAddress': 'token-B', 'Symbol': 'B', 'Decimals': 6}},
            'Sell': {'Amount': '0.002', 'AmountInUSD': '0.15',
                     'Currency': {'MintAddress': 'So11111111111111111111111111111111111111112',
                                  'Symbol': 'WSOL', 'Decimals': 9}},
        },
    }


def page(*rows):
    return {'Solana': {'DEXTrades': list(rows)}}


class PaginatedBitqueryTests(unittest.TestCase):
    def test_overlap_keeps_distinct_swaps(self):
        report, rows = m.merge_pages([
            ('1', page(row(130, 1), row(120, 2), row(120, 3))),
            ('2', page(row(120, 2), row(120, 3), row(110, 4))),
        ])
        self.assertEqual(len(rows), 4)
        self.assertEqual(report['pages'][1]['overlap_records'], 2)
        self.assertEqual(report['oldest_slot'], 110)

    def test_identical_rows_within_page_are_preserved(self):
        r = row()
        _, rows = m.merge_pages([('1', page(r, r))])
        self.assertEqual(len(rows), 2)

    def test_identical_overlap_deduplicates_by_occurrence(self):
        r = row()
        report, rows = m.merge_pages([
            ('1', page(r, r)),
            ('2', page(r, r, row(119, 2))),
        ])
        self.assertEqual(len(rows), 3)
        self.assertEqual(report['pages'][1]['overlap_records'], 2)

    def test_distinct_swaps_with_same_signature_survive(self):
        report, rows = m.merge_pages([
            ('1', page(row(120, 1), row(119, 2))),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(report['distinct_signatures'], 1)

    def test_newer_page_rejected(self):
        with self.assertRaises(ValueError):
            m.merge_pages([('1', page(row(120))),
                           ('2', page(row(130)))])

    def test_full_page_stall_rejected(self):
        r = row()
        with self.assertRaises(ValueError):
            m.merge_pages([('1', page(r, r)), ('2', page(r, r))],
                          page_limit=2)

    def test_unsorted_page_rejected(self):
        with self.assertRaises(ValueError):
            m.merge_pages([('1', page(row(100), row(120)))])

    def test_invalid_program_rejected(self):
        r = row()
        r['Trade']['Dex']['ProgramAddress'] = 'unknown'
        with self.assertRaises(ValueError):
            m.merge_pages([('1', page(r))])

    def test_graphql_errors_rejected(self):
        with self.assertRaises(ValueError):
            m.merge_pages([('1', {'errors': [{'message': 'access denied'}],
                                  'data': page(row())})])

    def test_cursor_query_includes_overlap_and_both_programs(self):
        q = m.build_query(463789516)
        self.assertIn('le: "463789516"', q)
        self.assertIn('raydium_launchpad', q)
        self.assertIn('raydium_cp_swap', q)
        self.assertIn('dataset: realtime', q)

    def test_never_claims_executable_pnl(self):
        report, _ = m.merge_pages([('1', page(row()))])
        self.assertFalse(report['history_complete'])
        self.assertFalse(report['creator_cohort_verified'])
        self.assertFalse(report['executable_exit_proven'])
        self.assertIsNone(report['master_vs_baseline_net_profit'])
        self.assertTrue(report['economic_gate'].startswith('NO_GO'))

    def test_wrapped_json_response(self):
        report, rows = m.merge_pages([('1', {'data': page(row())})])
        self.assertEqual(len(rows), 1)
        self.assertEqual(report['oldest_slot'], 120)


if __name__ == '__main__':
    unittest.main()
