"""ps051verdict on a REAL paperstream 0.5.1 --fast-analyser output (fixtures), with fixture anchors."""
import contextlib
import gzip
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

import bot
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from paperstream import engine as E
from ps051verdict import verdict as V
from w1aux import dayj

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()


def _line(rss, vmrss, usage, max_usage, when='2026-11-22T15:33:00Z'):
    return f'{when} {rss} {vmrss} {usage} {max_usage}\n'


@pytest.fixture(scope='module')
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('v')
    series = tmp / 's.json'
    dayj._selfcheck_series(series)
    ssha = hashlib.sha256(series.read_bytes()).hexdigest()
    frozen = hrr.run_replay(PACK, w1_run.l1_params(), sus.load_series(series), w1_run.L1_EXIT,
                            hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'),
                            placebo_arm=True)
    l1 = tmp / 'w' / 'bundles' / 'L1.json.gz'
    anchors = dict(manifest=SHA, series=ssha, file=w1_run._write_json(l1, frozen),
                   json=hashlib.sha256(gzip.decompress(l1.read_bytes())).hexdigest(), field=frozen['bundle_sha256'],
                   master_closed=frozen['totals']['master']['closed_cycles'])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = E.main(['run', '--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(series),
                     '--sol-usd-series-sha256', ssha, '--workers', '2', '--fast-analyser', '--perf-counters',
                     '--expect-bundle-file-sha256', anchors['file'], '--expect-bundle-json-sha256', anchors['json'],
                     '--expect-bundle-field-sha256', anchors['field'], '--checkpoint', str(tmp / 'ck'),
                     '--out', str(tmp / 'out')])
    doc = json.loads((tmp / 'out' / 'PAPERSTREAM.json').read_text())
    log = tmp / 'mem.log'
    low = int(doc['memory']['available_mb'] * 2 ** 20 * 0.5)
    log.write_text(_line(low, low, low, low) + _line(low - 10, low - 10, low - 10, low))
    return dict(tmp=tmp, out=tmp / 'out', rc=rc, printed=buf.getvalue().strip(), anchors=anchors, log=log, doc=doc)


def _check(run, **over):
    kw = dict(printed_sha256=run['printed'], rc=run['rc'], mem_log=run['log'], anchors=run['anchors'])
    kw.update(over)
    return V.check(over.pop('out', run['out']), **{k: v for k, v in kw.items() if k != 'out'})


def test_a_real_fast_run_is_verified(run):
    res = _check(run)
    assert run['rc'] == 0 and res['verdict'] == 'VERIFIED' and res['failed'] == []
    assert res['memory']['rule'] == 1 and res['memory']['note'] is None and res['perf_counters_sha256']
    assert 'pnl' not in json.dumps(res)


def test_the_w1_anchors(run):
    assert (V.W1['file'][:8], V.W1['json'][:8], V.W1['field'][:8], V.W1['master_closed']) == \
        ('3409bf9d', '9eb43426', 'c7556f14', 191)
    assert _check(run, anchors=V.W1)['verdict'] == 'INVALID_RUN'                # the fixture run is not W1


def _tampered(run, tmp_path, change):
    out = tmp_path / 'copy'
    shutil.copytree(run['out'], out)
    p = out / 'PAPERSTREAM.json'
    doc = json.loads(p.read_text())
    change(doc, out)
    p.write_text(json.dumps(doc))
    return out, hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize('name,change,failed,verdict', [
    ('slow', lambda d, o: d.update(fast_analyser=False), ['I1_schema_and_flags'], 'IDENTITY_FAILED'),
    ('schema04', lambda d, o: d.update(schema='paperstream-v0.4'), ['I1_schema_and_flags'], 'IDENTITY_FAILED'),
    ('verify', lambda d, o: d.update(verify_fast=True), ['I1_schema_and_flags'], 'IDENTITY_FAILED'),
    ('file', lambda d, o: d.update(matches_expected_bundle_file=False), ['I2_file'], 'IDENTITY_FAILED'),
    ('json', lambda d, o: d.update(bundle_json_sha256='0' * 64), ['I3_json'], 'IDENTITY_FAILED'),
    ('field', lambda d, o: d.update(matches_expected_bundle_field=False), ['I4_field'], 'IDENTITY_FAILED'),
    ('consistent', lambda d, o: d.update(bundle_sha256_consistent=False), ['I5_field_consistent'], 'IDENTITY_FAILED'),
    ('cycles', lambda d, o: d.update(reconciled_cycles=0), ['I6_cycles'], 'IDENTITY_FAILED'),
    ('override', lambda d, o: d.update(memory_override=True), ['M1_guard_without_override'], 'MEMORY_EXCEEDED'),
    ('no_margin', lambda d, o: d['memory'].pop('fast_memo_mb'), ['M1_guard_without_override'], 'MEMORY_EXCEEDED'),
    ('network', lambda d, o: d.update(network=True), ['G4_labels'], 'INVALID_RUN'),
    ('expected', lambda d, o: d.update(expected_bundle_file_sha256='1' * 64), ['G5_expected_are_the_anchors'], 'INVALID_RUN'),
    ('index', lambda d, o: (o / 'CHECKPOINT_INDEX.json').write_text('{}'), ['G6_checkpoint'], 'INVALID_RUN'),
])
def test_each_failure_is_named(run, tmp_path, name, change, failed, verdict):
    out, sha = _tampered(run, tmp_path, change)
    res = V.check(out, printed_sha256=sha, rc=0, mem_log=run['log'], anchors=run['anchors'])
    assert res['failed'] == failed and res['verdict'] == verdict, (name, res['failed'])


def _mem(run, tmp_path, lines, name='m.log'):
    path = tmp_path / name
    path.write_text(''.join(lines))
    return _check(run, mem_log=path)


def test_memory_rule_1_2_3(run, tmp_path):
    avail = run['doc']['memory']['available_mb'] * 2 ** 20
    under, over = int(avail * 0.4), int(avail * 1.3)
    r1 = _mem(run, tmp_path, [_line(under, under, under, under)], 'r1.log')          # (1) max_usage within
    assert r1['verdict'] == 'VERIFIED' and r1['memory']['rule'] == 1
    r2 = _mem(run, tmp_path, [_line(under, under, over, over)], 'r2.log')            # (2) page cache high, anon low
    assert r2['verdict'] == 'VERIFIED' and r2['memory']['rule'] == 2
    assert r2['memory']['note'] == 'unsampled window 15:29:53-15:32:51Z'
    r3 = _mem(run, tmp_path, [_line(under, over, over, over)], 'r3.log')             # (3) the processes exceed
    assert r3['verdict'] == 'MEMORY_EXCEEDED' and r3['failed'] == ['M2_peak_within_available'] and r3['memory']['rule'] == 3
    r3b = _mem(run, tmp_path, [_line(over, under, over, over)], 'r3b.log')           # (3) memory.stat rss exceeds
    assert r3b['verdict'] == 'MEMORY_EXCEEDED'
    peaks = _mem(run, tmp_path, [_line(1, 2, 3, 4), _line(5 * 2 ** 20, 6 * 2 ** 20, 7 * 2 ** 20, 8 * 2 ** 20)], 'p.log')
    assert peaks['memory']['peaks_mb'] == dict(rss=5, sum_vmrss=6, usage=7, max_usage=8) and peaks['memory']['samples'] == 2


@pytest.mark.parametrize('content,message', [
    ('', 'memory_log_has_no_sample'), ('\n\n', 'memory_log_has_no_sample'),
    ('2026-11-22T15:33:00Z 1 2 3\n', 'memory_log_malformed_line:1'),                 # 4 columns (v0.1 format)
    ('2026-11-22T15:33:00Z 1 2 3 4 5\n', 'memory_log_malformed_line:1'),             # 6 columns
    ('2026-11-22T15:33:00Z 1 2 3 4\nx 1 NA 3 4\n', 'memory_log_malformed_line:2'),  # not a number
])
def test_the_log_format_is_exact(run, tmp_path, content, message):
    path = tmp_path / 'bad.log'
    path.write_text(content)
    with pytest.raises(V.VerdictError, match=message):
        _check(run, mem_log=path)


def test_bad_inputs(run, tmp_path):
    assert _check(run, rc=1)['verdict'] == 'INVALID_RUN' and _check(run, printed_sha256='0' * 64)['failed'] == ['G1_printed_sha']
    with pytest.raises(V.VerdictError, match='no_paperstream_output'):
        V.check(tmp_path, printed_sha256='', rc=0, mem_log=run['log'])
