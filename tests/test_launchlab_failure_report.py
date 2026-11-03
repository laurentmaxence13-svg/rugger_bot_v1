import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import launchlab_failure_report as report  # noqa: E402


def row(slot, err=None):
    return {'slot': slot, 'err': err, 'signature': 's%d' % slot}


class FailureReportTests(unittest.TestCase):
    def test_counts_and_age_buckets(self):
        doc = {'pool': 'P', 'signatures_complete': True,
               'signatures': [row(100), row(105, {'InstructionError': [0, {'Custom': 7}]}),
                              row(160, {'InstructionError': [0, {'Custom': 7}]}), row(300)]}
        out = report.analyse_document(doc)
        self.assertEqual((out['total'], out['failed'], out['succeeded']), (4, 2, 2))
        self.assertEqual(out['failure_rate'], 0.5)
        self.assertEqual(out['by_age']['slots>=0']['total'], 2)
        self.assertEqual(out['by_age']['slots>=50']['failed'], 1)
        self.assertEqual(out['by_age']['slots>=150']['total'], 1)
        self.assertEqual(sum(out['error_kinds'].values()), 2)
        self.assertEqual(out['warnings'], [])

    def test_empty_and_partial(self):
        out = report.analyse_document({'pool': 'P', 'signatures': []})
        self.assertEqual(out['total'], 0)
        self.assertIsNone(out['failure_rate'])
        self.assertTrue(any('not marked complete' in w for w in out['warnings']))

    def test_malformed(self):
        doc = {'signatures_complete': True,
               'signatures': [row(1), {'slot': 'x', 'err': None}, 5, {'slot': 2}, row(3, {'X': 1})]}
        out = report.analyse_document(doc, 'n')
        self.assertEqual((out['total'], out['failed'], out['malformed_rows']), (2, 1, 3))
        for bad in (None, [], {'signatures': 'no'}):
            self.assertEqual(report.analyse_document(bad)['total'], 0)

    def test_directory_with_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with gzip.open(Path(tmp) / 'A.json.gz', 'wt') as h:
                json.dump({'pool': 'A', 'signatures_complete': True, 'signatures': [row(1), row(2, {'E': 1})]}, h)
            (Path(tmp) / 'B.json.gz').write_bytes(b'not gzip')
            out = report.analyse_directory(tmp)
        self.assertEqual((out['pool_count'], out['total'], out['failed']), (2, 2, 1))
        self.assertIn('unreadable', out['pools'][1]['warnings'][0])

    def test_committed_fixtures_reproducible(self):
        out = report.analyse_directory(report.DEFAULT_DIR)
        self.assertEqual(out['pool_count'], 3)
        self.assertEqual((out['total'], out['failed']), (173, 59))
        self.assertEqual(out, report.analyse_directory(report.DEFAULT_DIR))
        self.assertIn('not the bot', out['caveat'])
