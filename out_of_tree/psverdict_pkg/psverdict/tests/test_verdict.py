"""psverdict: on a REAL paperstream 0.4 output (fixtures), the verdict is IDENTITY_PROVEN with the right anchors and
names every check that fails otherwise."""
import gzip
import hashlib
import json
import shutil
import socket
from pathlib import Path

import pytest

import bot
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from paperstream import engine as E
from psverdict import verdict as V
from w1aux import dayj

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


@pytest.fixture(scope='module')
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('ps')
    series = tmp / 'series.json'
    dayj._selfcheck_series(series)
    series_sha = hashlib.sha256(series.read_bytes()).hexdigest()
    frozen = hrr.run_replay(PACK, w1_run.l1_params(), sus.load_series(series), w1_run.L1_EXIT,
                            hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'),
                            placebo_arm=True)
    l1 = tmp / 'w1run' / 'bundles' / 'L1.json.gz'
    anchors = (w1_run._write_json(l1, frozen), hashlib.sha256(gzip.decompress(l1.read_bytes())).hexdigest(),
               frozen['bundle_sha256'])
    out = tmp / 'run'
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = E.main(['run', '--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(series),
                     '--sol-usd-series-sha256', series_sha, '--expect-bundle-file-sha256', anchors[0],
                     '--expect-bundle-json-sha256', anchors[1], '--expect-bundle-field-sha256', anchors[2],
                     '--checkpoint', str(tmp / 'ck'), '--out', str(out)])
    doc = json.loads((out / 'PAPERSTREAM.json').read_text())
    return dict(out=out, rc=rc, printed=buf.getvalue().strip(), series_sha=series_sha, anchors=anchors,
                master_closed=doc['counts']['master']['closed_cycles'])


def _check(run, out=None, **over):
    kw = dict(printed_sha256=run['printed'], rc=run['rc'], manifest_sha256=SHA, series_file_sha256=run['series_sha'],
              expect_master_closed=run['master_closed'], anchors=run['anchors'])
    kw.update(over)
    return V.check(out or run['out'], **kw)


def test_a_real_identical_run_is_proven(run):
    res = _check(run)
    assert res['verdict'] == 'IDENTITY_PROVEN' and res['failed'] == [] and run['rc'] == 0
    assert set(res['counts']) == set(hrr.ARMS) | {hrr.PLACEBO_ARM} and res['checkpoint_counts'] == {'absent': 3}
    assert 'pnl' not in json.dumps(res) and 'not a trial' in res['scope']


@pytest.mark.parametrize('over,failed,verdict', [
    (dict(printed_sha256='0' * 64), ['printed_sha'], 'INVALID_RUN'),
    (dict(rc=1), ['rc'], 'INVALID_RUN'),
    (dict(manifest_sha256='0' * 64), ['manifest'], 'INVALID_RUN'),
    (dict(series_file_sha256='0' * 64), ['series'], 'INVALID_RUN'),
    (dict(expect_master_closed=128), ['master_closed'], 'IDENTITY_FAILED'),
])
def test_wrong_inputs_are_named(run, over, failed, verdict):
    if over.get('expect_master_closed') == run['master_closed']:
        pytest.skip('fixture count equals the W1 one')
    res = _check(run, **over)
    assert res['failed'] == failed and res['verdict'] == verdict


def test_the_w1_anchors_are_the_ones_r02_anchored(run):
    assert (V.W1_FILE[:8], V.W1_JSON[:8], V.W1_FIELD[:8]) == ('3409bf9d', '9eb43426', 'c7556f14')
    res = _check(run, anchors=(V.W1_FILE, V.W1_JSON, V.W1_FIELD))      # the fixture run is not W1
    assert {'expected_file', 'expected_json', 'expected_field', 'identity_file', 'identity_json',
            'identity_field'} <= set(res['failed']) and res['verdict'] == 'INVALID_RUN'


def _batch_index(doc, out):
    """A self-consistent index (its sha re-recorded) whose context is not the streaming one."""
    path = out / 'CHECKPOINT_INDEX.json'
    path.write_text(json.dumps(dict(json.loads(path.read_text()), context=dict(mode='batch'))))
    doc['checkpoint_index_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()


def _tampered(run, tmp_path, change):
    out = tmp_path / 'copy'
    shutil.copytree(run['out'], out)
    path = out / 'PAPERSTREAM.json'
    doc = json.loads(path.read_text())
    change(doc, out)
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + '\n')
    return out, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('name,change,failed,verdict', [
    ('file', lambda d, o: d.update(matches_expected_bundle_file=False), ['identity_file'], 'IDENTITY_FAILED'),
    ('json', lambda d, o: d.update(bundle_json_sha256='0' * 64), ['identity_json'], 'IDENTITY_FAILED'),
    ('field', lambda d, o: d.update(bundle_sha256_consistent=False), ['field_consistent'], 'IDENTITY_FAILED'),
    ('journal', lambda d, o: d.update(reconciled_cycles=d['reconciled_cycles'] - 1), ['journal'], 'IDENTITY_FAILED'),
    ('override', lambda d, o: d.update(memory_override=True), ['memory_override'], 'INVALID_RUN'),
    ('schema', lambda d, o: d.update(schema='paperstream-v0.3'), ['schema'], 'INVALID_RUN'),
    ('trial', lambda d, o: d.update(trials_added=1), ['trials_added'], 'INVALID_RUN'),
    ('network', lambda d, o: d.update(network=True), ['network'], 'INVALID_RUN'),
    ('not_a_trial', lambda d, o: d.update(identity_check_not_a_trial=False), ['not_a_trial'], 'INVALID_RUN'),
    ('index_mode', lambda d, o: _batch_index(d, o), ['checkpoint'], 'INVALID_RUN'),
    ('firewall_top', lambda d, o: d.update(pnl_lamports=12), ['firewall'], 'INVALID_RUN'),
    ('firewall_nested', lambda d, o: d['counts']['master'].update(net_return=0.1), ['firewall'], 'INVALID_RUN'),
    ('firewall_deep', lambda d, o: d['memory'].update(x=[{'mark_pnl_lamports': 1}]), ['firewall'], 'INVALID_RUN'),
    ('firewall_hw', lambda d, o: d.update(HW1_label=1), ['firewall'], 'INVALID_RUN'),
    ('reason_not_int', lambda d, o: d['counts']['master']['blocking_reasons'].update(x='1'), ['firewall'], 'INVALID_RUN'),
    ('labels_count', lambda d, o: d['thresholds'].update(these_cycles_count_toward_them=True), ['labels'], 'INVALID_RUN'),
    ('labels_operational', lambda d, o: d['thresholds'].update(operational_master_entry=True), ['labels'], 'INVALID_RUN'),
    ('cycles_sum', lambda d, o: d['counts']['master'].update(closed_cycles=d['counts']['master']['closed_cycles'] + 1),
     ['cycles_sum', 'master_closed'], 'IDENTITY_FAILED'),
    ('no_cycle', lambda d, o: d.update(reconciled_cycles=0, closed_cycles_all_arms=0), ['cycles_sum', 'journal'], 'IDENTITY_FAILED'),
    ('index', lambda d, o: (o / 'CHECKPOINT_INDEX.json').write_text('{}'), ['checkpoint'], 'INVALID_RUN'),
])
def test_each_failure_is_named(run, tmp_path, name, change, failed, verdict):
    out, sha = _tampered(run, tmp_path, change)
    res = _check(run, out=out, printed_sha256=sha)
    assert res['failed'] == failed and res['verdict'] == verdict, name


def test_frozen_reason_names_never_trip_the_firewall(run, tmp_path):
    """R02 V-1 (a): reason names of the frozen engine (keys of blocking_reasons) may contain any token."""
    def change(d, o):
        d['counts']['master']['blocking_reasons'].update({'high_volatility_return': 3,
                                                          'causal_adjacent_price_return_proxy': 1,
                                                          'critical_veto:mark_pnl_HW': 2})
    out, sha = _tampered(run, tmp_path, change)
    res = _check(run, out=out, printed_sha256=sha)
    assert res['verdict'] == 'IDENTITY_PROVEN' and res['firewall_offending_keys'] == []


def test_the_r02_anchors():
    assert (V.W1_MANIFEST[:8], V.W1_SERIES[:8], V.W1_MASTER_CLOSED) == ('ebe1959d', '7458f615', 128)
    assert V.firewall({'a': {'blocking_reasons': {'net_return': 1}, 'net_return': 1}}) == ['a/net_return']


def test_cli(run, capsys):
    assert V.main(['--run', str(run['out']), '--printed-sha256', run['printed'], '--rc', '0', '--manifest-sha256', SHA,
                   '--series-file-sha256', run['series_sha'], '--expect-master-closed', str(run['master_closed'])]) == 1
    assert json.loads(capsys.readouterr().out)['verdict'] == 'INVALID_RUN'       # default anchors are W1's
    with pytest.raises(V.VerdictError, match='no_paperstream_output'):
        V.check(run['out'].parent / 'nothing', printed_sha256='', rc=0, manifest_sha256='', series_file_sha256='',
                expect_master_closed=0)
