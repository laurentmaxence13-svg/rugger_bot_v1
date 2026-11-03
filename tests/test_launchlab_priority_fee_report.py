"""Offline tests for tools/launchlab_priority_fee_report.py (synthetic + committed fixtures)."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import launchlab_priority_fee_report as rep  # noqa: E402

B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58encode(raw):
    n = int.from_bytes(raw, 'big')
    out = ''
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return '1' * (len(raw) - len(raw.lstrip(b'\x00'))) + out


def tx(price=None, limit=None):
    keys, ins = ['payer', rep.COMPUTE_BUDGET], []
    if price is not None:
        ins.append({'programIdIndex': 1, 'data': b58encode(b'\x03' + price.to_bytes(8, 'little'))})
    if limit is not None:
        ins.append({'programIdIndex': 1, 'data': b58encode(b'\x02' + limit.to_bytes(4, 'little'))})
    return {'transaction': {'message': {'accountKeys': keys, 'instructions': ins}}}


class DecodeTests(unittest.TestCase):
    def test_b58_roundtrip(self):
        for raw in (b'\x03\x01', b'\x00\x00\x07', b'\xff' * 9):
            self.assertEqual(rep.b58decode(b58encode(raw)), raw)

    def test_price_and_limit(self):
        self.assertEqual(rep.decode_compute_budget(tx(1_111_112, 200_000)), (1_111_112, 200_000))

    def test_missing_or_wrong_program(self):
        self.assertEqual(rep.decode_compute_budget(tx()), (None, None))
        other = tx(5, 5)
        other['transaction']['message']['accountKeys'][1] = 'Other'
        self.assertEqual(rep.decode_compute_budget(other), (None, None))
        self.assertEqual(rep.decode_compute_budget({}), (None, None))

    def test_malformed_data_ignored(self):
        bad = tx()
        bad['transaction']['message']['instructions'] = [{'programIdIndex': 1, 'data': '0OIl'}]
        self.assertEqual(rep.decode_compute_budget(bad), (None, None))

    def test_quantiles(self):
        self.assertIsNone(rep.quantiles([]))
        q = rep.quantiles([5, 1, 3])
        self.assertEqual((q['n'], q['min'], q['median'], q['max']), (3, 1, 3, 5))


class FixtureTests(unittest.TestCase):
    def test_counts_match_manifest(self):
        manifest = json.loads((rep.DEFAULT_DIR / 'MANIFEST.json').read_text())
        for entry in manifest['pools']:
            r = rep.report_archive(rep.DEFAULT_DIR / entry['file'])
            self.assertEqual(r['pool'], entry['pool'])
            self.assertGreaterEqual(r['transactions'], entry['trades'])
            self.assertLessEqual(r['transactions'], entry['signatures'])
            self.assertEqual(sum(v['n'] for v in r['fee_by_slot_age'].values() if v), r['transactions'])
            self.assertEqual(r['with_unit_price'] + r['without_unit_price'], r['transactions'])
            self.assertGreaterEqual(r['fee_lamports']['min'], rep.BASE_FEE_PER_SIGNATURE)

    def test_cli_is_deterministic_and_read_only(self):
        cmd = [sys.executable, '-B', str(ROOT / 'tools' / 'launchlab_priority_fee_report.py')]
        a = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        b = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        self.assertEqual(a, b)
        self.assertIn('not a winning-fee estimate', json.loads(a)['limits'])


if __name__ == '__main__':
    unittest.main()
