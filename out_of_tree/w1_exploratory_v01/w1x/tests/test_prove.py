"""w1x.prove: the identity proofs RUGGER 03 runs on opened data, tried here on the frozen test windows."""
import io
import json

import pytest

from bot.market import backfill as bf
from bot.master_v2 import w1_run as run
from tests import test_launchlab_backfill as tlb
from w1x import prove
from w1x.tests import test_stream_series as tss


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(bf, 'GSFA_PAGE', 25)
    monkeypatch.setattr(bf, 'GTFA_FULL_PAGE', 10)
    monkeypatch.setattr(bf, 'GTFA_SIG_PAGE', 40)


def _run(argv):
    buffer = io.StringIO()
    code = prove.main(argv, out=buffer)
    return code, json.loads(buffer.getvalue())


def test_export_proof_on_the_frozen_test_window(tmp_path):
    code, _ = tlb._run(tmp_path, tlb.FakeChain(), out='w')
    assert code == 0
    code, doc = _run(['export', '--window-dir', str(tmp_path / 'w'), '--out', str(tmp_path / 'proof'), '--buckets', '3'])
    assert code == 0 and doc['identical'] and doc['what'] == 'export'
    assert doc['frozen']['files'] == doc['stream']['files'] and 'MANIFEST.json' in doc['frozen']['files'] and len(doc['frozen']['files']) == 4
    assert doc['frozen']['error'] is None and doc['stream']['peak_mb'] > 0 and doc['stream']['seconds'] >= 0
    with pytest.raises(prove.ProveError, match='output_exists'):
        _run(['export', '--window-dir', str(tmp_path / 'w'), '--out', str(tmp_path / 'proof')])


def test_series_proof_and_a_difference_is_reported(tmp_path, monkeypatch):
    study = tmp_path / 'study.json'
    study.write_text(json.dumps(dict(verdict='ACCEPTED', acceptance=dict(max_age_ms=65_000, max_confidence_ppm=1_000))))
    import hashlib
    monkeypatch.setattr(run, 'ANCHORED_STUDY_REPORT_SHA256', hashlib.sha256(study.read_bytes()).hexdigest())
    window = tss._window(tmp_path)
    tss._rebuild(window, tss._groups(tss._many(60, 11), (20, 20)))
    code, doc = _run(['series', '--run-dir', str(window), '--study-report', str(study), '--out', str(tmp_path / 'proof')])
    assert code == 0 and doc['identical']
    assert sorted(doc['stream']['files']) == ['sol_usd_series.json.gz', 'sol_usd_series.json.gz.decoding.json']
    # a streaming step that changes one byte is seen, and so is a failure of either side
    from w1x import stream_series
    slim = stream_series._slim
    monkeypatch.setattr(stream_series, '_slim', lambda row, u, e: {**slim(row, u, e), 'blockTime': 1})
    code, doc = _run(['series', '--run-dir', str(window), '--study-report', str(study), '--out', str(tmp_path / 'p2')])
    assert code == 1 and not doc['identical'] and doc['frozen']['files'] != doc['stream']['files']
    monkeypatch.setattr(stream_series, '_slim', slim)
    monkeypatch.setattr(run, 'ANCHORED_STUDY_REPORT_SHA256', '0' * 64)
    code, doc = _run(['series', '--run-dir', str(window), '--study-report', str(study), '--out', str(tmp_path / 'p3')])
    assert code == 1 and not doc['identical'] and doc['frozen']['error'] == 'W1RunError:age_study_report_is_not_the_anchored_one'
    monkeypatch.delenv('RUGGER_NO_DOTENV')
    with pytest.raises(prove.ProveError, match='set_RUGGER_NO_DOTENV_1'):
        _run(['series', '--run-dir', str(window), '--study-report', str(study), '--out', str(tmp_path / 'p4')])
