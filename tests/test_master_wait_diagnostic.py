import gzip, json, tempfile, unittest
from pathlib import Path
from bot import master_wait_diagnostic as d
import importlib.util
HAS_AIOHTTP = importlib.util.find_spec('aiohttp') is not None

ROOT = Path(__file__).resolve().parents[1] / 'evidence' / 'p3'


def _write(root, name, events):
    folder = Path(root) / name
    folder.mkdir()
    with gzip.open(folder / 'events.jsonl.gz', 'wt') as f:
        for e in events:
            f.write(json.dumps(e) + '\n')


class WaitDiagnostic(unittest.TestCase):
    def test_synthetic_counts(self):
        with tempfile.TemporaryDirectory() as t:
            _write(t, 'a', [
                dict(kind='transaction', outcome='observed', payload=dict(raw_transaction=dict(result=dict(meta=dict(fee=5000))))),
                dict(kind='transaction', outcome='observed', payload=dict(raw_transaction=dict(result=dict(meta={})))),
                dict(kind='transaction', outcome='chain_failed', payload={}),
                dict(kind='launch', outcome='observed', payload=dict(creator='C1')),
                dict(kind='checkpoint', outcome='creation_matched', payload=dict(creator='C2', meta_fee_lamports=5000)),
                dict(kind='candidate_decision', outcome='x', payload=dict(creation_verified=False)),
            ])
            r = d.diagnose(t)
        self.assertEqual(r['totals']['tx_with_meta_fee'], 1)
        self.assertEqual(r['totals']['tx_observed'], 2)
        self.assertEqual(r['distinct_creators'], 2)
        self.assertEqual(r['totals']['creation_verified_true'], 0)
        self.assertFalse(r['profitability_claimed'])

    def test_real_archives_cannot_satisfy_gates(self):
        r = d.diagnose(ROOT)
        self.assertGreaterEqual(r['archives'], 15)
        self.assertGreater(r['totals']['tx_with_meta_fee'], 0)   # data exists, non-vacuous
        self.assertLess(r['distinct_creators'], 20)              # below the frozen minimum
        self.assertEqual(r['totals'].get('creation_verified_true', 0), 0)

    @unittest.skipUnless(HAS_AIOHTTP, 'aiohttp missing: frozen decision module not importable here')
    def test_blockers_match_frozen_code_on_frame_without_inputs(self):
        from bot.master_decision import orchestrate
        out = orchestrate(dict(id='f', mint='m', creator='c', pool='p', detected_at_ms=1, available_at_ms=2,
                               data_kind='market_observation'))
        for b in d.BLOCKERS:
            self.assertIn(b, out['reasons'])
        self.assertEqual(out['action'], 'WAIT')


if __name__ == '__main__':
    unittest.main()
