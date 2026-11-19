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
    phases = doc['stream']['phases']                      # a running maximum, phase after phase
    assert set(phases) == {'start', 'verify', 'first_pass', 'second_pass', 'third_pass'}
    assert phases['start'] <= phases['verify'] <= phases['first_pass'] <= phases['second_pass'] <= phases['third_pass'] == doc['stream']['peak_mb']
    assert doc['frozen']['phases'] is None
    from w1x import stream_export
    assert stream_export.verify.__name__ == 'verify' and stream_export._first_pass.__name__ == '_first_pass'   # untouched here
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
    phases = doc['stream']['phases']
    assert (phases['rows'], phases['tx_segments']) == (60, 3) and phases['verify'] <= phases['slim_rows'] <= phases['series']
    assert phases['series'] == doc['stream']['peak_mb'] and doc['frozen']['phases'] is None
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


def test_subset_is_a_smaller_verified_run_on_which_the_proofs_still_hold(tmp_path):
    chain = tlb.FakeChain()
    code, _ = tlb._run(tmp_path, chain, out='w')
    assert code == 0
    window = tmp_path / 'w'
    from w1x.tests import test_stream_export as tse
    rows = tse._rows(window)
    manifest = tse._rebuild(window, [rows[i:i + 40] for i in range(0, len(rows), 40)])       # five tx segments
    tx = [seg for seg in manifest['segments'] if seg['kind'] == 'tx']
    assert len(tx) == 5 and manifest['totals']['transactions'] == 173
    sizes = {}
    for n in (1, len(tx) - 1):
        code, doc = _run(['subset', '--run-dir', str(window), '--tx-segments', str(n), '--out', str(tmp_path / f's{n}')])
        small = tmp_path / f's{n}'
        kept = json.loads((small / 'manifest.json').read_text())
        checked = bf.verify(small)
        assert code == 0 and checked['ok'] and checked['complete'] and checked['manifest_sha256'] == doc['manifest_sha256']
        assert kept['w1x_subset']['tx_segments'] == n == doc['tx_segments'] and kept['w1x_subset']['of'] == len(tx) == doc['of']
        assert kept['w1x_subset']['source_manifest_sha256'] == bf.verify(window)['manifest_sha256']
        assert 'gsfa_anchor' not in kept and 'calls' not in kept and not (small / 'state.json').exists()
        assert [seg['path'] for seg in kept['segments'] if seg['kind'] == 'tx'] == [seg['path'] for seg in tx[:n]]
        for seg in tx[:n]:
            assert (small / seg['path']).read_bytes() == (window / seg['path']).read_bytes()
        assert doc['transactions'] == sum(seg['rows'] for seg in tx[:n]) == kept['totals']['transactions']
        sizes[n] = doc['transactions']
        code, proof = _run(['export', '--window-dir', str(small), '--out', str(tmp_path / f'proof{n}'), '--buckets', '3'])
        assert proof['frozen']['error'] == proof['stream']['error']        # same outcome on both sides, whatever it is
        assert code == (0 if proof['identical'] else 1) and (proof['identical'] or proof['frozen']['error'] is not None)
    assert sizes[1] < sizes[len(tx) - 1] < manifest['totals']['transactions']
    for bad in (0, len(tx), len(tx) + 5):
        with pytest.raises(prove.ProveError, match='tx_segments_must_be_between_1_and_'):
            _run(['subset', '--run-dir', str(window), '--tx-segments', str(bad), '--out', str(tmp_path / 'bad')])
        assert not (tmp_path / 'bad').exists()
    with pytest.raises(prove.ProveError, match='output_exists'):
        _run(['subset', '--run-dir', str(window), '--tx-segments', '1', '--out', str(tmp_path / 's1')])
    (window / tx[0]['path']).write_bytes((window / tx[0]['path']).read_bytes() + b' ')
    with pytest.raises(prove.ProveError, match='source_run_not_verified_complete_gtfa'):
        _run(['subset', '--run-dir', str(window), '--tx-segments', '1', '--out', str(tmp_path / 'bad')])
