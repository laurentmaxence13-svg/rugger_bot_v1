"""paperstream 0.5 draft: --fast-analyser is byte-identical to the frozen run (bundle sha AND strict canonical JSON), on
the fixtures and on a synthetic K-copy pack, in batch and stream, 1 and 2 workers, with checkpoint; the memo is safe
(identity-keyed, per pool, restored); the series is loaded once; reconcile_all = reconcile."""
import gc
import hashlib
import json
import socket
from pathlib import Path

import pytest

import bot
from bot.analyser import behavior_pipeline as bp
from bot.analyser import final_decision_engine as fde
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from paperstream import engine as E
from paperstream import fast as F
from w1aux import dayj, synthetic

ROOT = Path(bot.__file__).resolve().parents[1]
PACK = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


@pytest.fixture
def series(tmp_path):
    path = tmp_path / 'series.json'
    dayj._selfcheck_series(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def synthetic_pack(tmp_path_factory):
    out = tmp_path_factory.mktemp('syn') / 'pack'
    import os
    cwd = os.getcwd()
    os.chdir(ROOT)                                    # synthetic.SOURCE is relative to the frozen tree
    try:
        synthetic.build(out, 3)
    finally:
        os.chdir(cwd)
    return out, hashlib.sha256((out / 'MANIFEST.json').read_bytes()).hexdigest()


def _same(a, b):
    return a['bundle_sha256'] == b['bundle_sha256'] and E._canonical_strict(a) == E._canonical_strict(b)


def _frozen(pack, series_path):
    return hrr.run_replay(pack, w1_run.l1_params(), sus.load_series(series_path), w1_run.L1_EXIT,
                          hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pack)[2]], 'manifest'),
                          placebo_arm=True)


@pytest.mark.parametrize('workers', [1, 2])
def test_fast_is_byte_identical_on_the_fixtures(series, tmp_path, workers):
    frozen = _frozen(PACK, series[0])
    fb, _ = E.records(PACK, SHA, *series, streaming=False, workers=workers, fast_analyser=True)
    fs, journals = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'j', workers=workers,
                             fast_analyser=True)
    slow, slow_j = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'k', workers=workers)
    assert _same(frozen, fb) and _same(frozen, fs) and _same(frozen, slow)
    assert E._canonical(journals) == E._canonical(slow_j)


def test_fast_is_byte_identical_on_a_synthetic_pack(series, tmp_path, synthetic_pack):
    pack, sha = synthetic_pack
    frozen = _frozen(pack, series[0])
    fs, _j = E.records(pack, sha, *series, streaming=True, journal_dir=tmp_path / 'j', workers=2, fast_analyser=True)
    assert _same(frozen, fs) and len(fs['pools']) + len(fs.get('excluded_pools', [])) >= 9


def test_verify_mode_recomputes_every_served_value(series, tmp_path):
    before = F.STATS['hits']
    bundle, _j = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'j', fast_analyser=True,
                           _verify_fast=True)
    assert F.STATS['hits'] > before and _same(bundle, _frozen(PACK, series[0]))


def test_the_memo_never_serves_another_object_and_copies_mutables():
    memo = F.Memo()
    a, b = {'x': 1}, {'x': 1}
    calls = []
    memo.store[('n', id(b), ())] = (a, 'stale', None)               # an entry whose id is b's but holds another object
    assert memo.get('n', b, (), lambda: calls.append(1) or 'fresh') == 'fresh' and calls == [1]
    first = memo.get('d', a, (), lambda: {'k': 1}, copy=dict)
    first['k'] = 99                                                   # a caller mutating its result
    assert memo.get('d', a, (), lambda: {'k': 1}, copy=dict) == {'k': 1}
    bad = F.Memo(verify=True)
    bad.get('v', a, (), lambda: 1)
    with pytest.raises(AssertionError, match='memo_differs'):
        bad.get('v', a, (), lambda: 2)


def test_frozen_helpers_are_restored_and_the_shim_delegates():
    names = (fde._contains_mint, fde.classify_creator_behavior, bp._owner_balances, bp._is_swap, bp.json)
    with F.memoized() as memo:
        assert bp.json is not json and bp.json.loads('[1]') == [1] and bp.json.JSONDecodeError is json.JSONDecodeError
        assert bp.json.dumps([1], separators=(',', ':')) == '[1]' and bp.json.dumps({'a': 1}, indent=1) == json.dumps({'a': 1}, indent=1)
        tx = {'a': 1}
        assert bp.json.dumps(tx, separators=(',', ':')) == '{"a":1}' and memo.store
    assert (fde._contains_mint, fde.classify_creator_behavior, bp._owner_balances, bp._is_swap, bp.json) == names


def test_one_memo_per_pool_nothing_kept(series, tmp_path):
    seen = []
    original = F.memoized

    def spy(verify=False):
        cm = original(verify)

        class Wrap:
            def __enter__(self):
                self.memo = cm.__enter__()
                seen.append(self.memo)
                return self.memo

            def __exit__(self, *exc):
                return cm.__exit__(*exc)
        return Wrap()
    F.memoized, saved = spy, F.memoized
    try:
        bundle, _j = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'j', fast_analyser=True)
    finally:
        F.memoized = saved
    assert len(seen) == len(bundle['pools']) + len(bundle.get('excluded_pools', [])) == 3
    assert len({id(m) for m in seen}) == 3 and hrr.replay_pool.__module__ == hrr.__name__


def test_the_fast_flag_is_in_the_checkpoint_key_and_the_output(series, tmp_path, capsys):
    ck = tmp_path / 'ck'
    _b, _j, i1 = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'a', checkpoint_dir=ck)
    _b, _j, i2 = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'b', checkpoint_dir=ck,
                           fast_analyser=True)
    assert i1['context']['fast_analyser'] is False and i2['context']['fast_analyser'] is True
    assert set(i2['last_states'].values()) == {'key_mismatch'}          # a slow entry is never served to a fast run
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha]
    assert E.main(['reference', *common, '--fast-analyser', '--out', str(tmp_path / 'ref')]) == 0
    capsys.readouterr()
    doc = json.loads((tmp_path / 'ref' / 'REFERENCE.json').read_text())
    assert doc['fast_analyser'] is True and doc['schema'] == 'paperstream-v0.5.2.1'


def test_the_series_is_loaded_once_per_command(series, tmp_path, monkeypatch, capsys):
    calls = []
    original = sus.load_series
    monkeypatch.setattr(sus, 'load_series', lambda p: calls.append(p) or original(p))
    path, sha = series
    assert E.main(['reference', '--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path),
                   '--sol-usd-series-sha256', sha, '--out', str(tmp_path / 'ref')]) == 0
    capsys.readouterr()
    assert len(calls) == 1
    with pytest.raises(E.StreamError, match='series_must_be_a_loaded_series'):
        E.records(PACK, SHA, path, sha, streaming=False, series={'not': 'a series'})


def test_reconcile_all_equals_reconcile_and_refuses_the_same(series, tmp_path):
    bundle, journals = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'j')
    assert E.reconcile_all(bundle['pools'], journals) == sum(E.reconcile(r, journals) for r in bundle['pools']) >= 1
    bad = json.loads(json.dumps(journals))
    for j in bad:
        for e in j['events']:
            if e['kind'] == 'SELL':
                e['received'] += 1
    for checker in (lambda: E.reconcile_all(bundle['pools'], bad),
                    lambda: E.reconcile_all(bundle['pools'], journals + journals)):      # residual / duplicate
        with pytest.raises(E.StreamError, match='journal_does_not_reconcile'):
            checker()
    gc.collect()


def test_the_memoized_helpers_return_fresh_copies_of_mutable_results():
    tx = {'meta': {'preTokenBalances': [], 'postTokenBalances': []}, 'transaction': {'message': {'accountKeys': []}}}
    with F.memoized():
        first = fde.classify_creator_behavior(tx, 'M', 'C')
        first['sale'] = 'tampered'
        assert fde.classify_creator_behavior(tx, 'M', 'C')['sale'] is False
        balances = bp._owner_balances(tx, 'M', 'postTokenBalances')
        balances['x'] = 1
        assert bp._owner_balances(tx, 'M', 'postTokenBalances') == {}


def test_the_streaming_code_sha_covers_the_fast_module():
    import inspect
    from bot.master_v2 import harness
    parts = [inspect.getsource(o) for o in (E.StreamTrade, E.stream_replay, E.streaming_engine, E._journaled_replay_pool,
                                             E.Checkpoint)]
    without = hashlib.sha256('\n'.join(parts + [harness.code_fingerprint()]).encode()).hexdigest()
    parts.append(inspect.getsource(F))
    expected = hashlib.sha256('\n'.join(parts + [harness.code_fingerprint()]).encode()).hexdigest()
    assert E.streaming_code_sha256() == expected != without


# ---- 0.5.1 (R02 conditional PASS) -------------------------------------------------------------------------------
def test_memo_probe_reports_sizes_only(capsys):
    from paperstream import memo_probe
    manifest = json.loads((PACK / 'MANIFEST.json').read_text())
    entry = max(manifest['pools'], key=lambda e: (PACK / e['file']).stat().st_size)
    assert memo_probe.main(['--archive', str(PACK / entry['file']), '--sha256', entry['sha256']]) == 0
    out = json.loads(capsys.readouterr().out)
    assert tuple(sorted(out)) == tuple(sorted(memo_probe.KEYS)) and out['transactions'] > 0
    assert 4 < out['dumps_per_gz_byte'] < E.MEMO_BYTES_PER_GZ_BYTE and entry['pool'] not in json.dumps(out)
    with pytest.raises(ValueError, match='archive_is_not_the_anchored_one'):
        memo_probe.probe(PACK / entry['file'], '0' * 64)


def test_the_memory_guard_adds_the_memo_margin(series, tmp_path, monkeypatch):
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha]
    largest = max(p.stat().st_size for p in PACK.glob('*.json.gz'))
    assert E.fast_memory_mb(PACK, 4) == round(4 * largest * E.MEMO_BYTES_PER_GZ_BYTE / 2 ** 20)
    base = dayj.memory_projection(PACK, 'trials')['projected_mb']
    margin = E.fast_memory_mb(PACK, 1)
    edge = int(dayj.MEMORY_MARGIN * base) + 1                              # enough without the memo, not with it
    monkeypatch.setattr(dayj, '_memory_available_mb', lambda: edge)
    monkeypatch.setattr(E, 'fast_memory_mb', lambda pools, workers: max(margin, base))
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        assert E.main(['reference', *common, '--out', str(tmp_path / 'slow')]) == 0
        with pytest.raises(E.StreamError, match='memory_projection_exceeds_available_owner_decision_needed'):
            E.main(['reference', *common, '--fast-analyser', '--out', str(tmp_path / 'fast')])
        assert E.main(['reference', *common, '--fast-analyser', '--memory-override', '--out', str(tmp_path / 'f2')]) == 0
    doc = json.loads((tmp_path / 'f2' / 'REFERENCE.json').read_text())
    assert doc['memory']['fits'] is False and doc['memory']['projected_with_memo_mb'] == base + max(margin, base)


def test_verify_fast_cli_and_its_requirement(series, tmp_path, capsys):
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha]
    with pytest.raises(E.StreamError, match='verify_fast_requires_fast_analyser'):
        E.main(['reference', *common, '--verify-fast', '--out', str(tmp_path / 'x')])
    with pytest.raises(E.StreamError, match='verify_fast_requires_fast_analyser'):
        E.records(PACK, SHA, path, sha, streaming=False, _verify_fast=True)
    before = F.STATS['hits']
    assert E.main(['reference', *common, '--fast-analyser', '--verify-fast', '--out', str(tmp_path / 'v')]) == 0
    capsys.readouterr()
    doc = json.loads((tmp_path / 'v' / 'REFERENCE.json').read_text())
    assert doc['verify_fast'] is True and F.STATS['hits'] > before
    assert doc['bundle_sha256'] == _frozen(PACK, path)['bundle_sha256']


@pytest.mark.parametrize('workers', [1, 2])
def test_perf_counters_change_nothing_and_name_no_pool(series, tmp_path, workers, capsys):
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha,
              '--workers', str(workers)]
    assert E.main(['reference', *common, '--perf-counters', '--out', str(tmp_path / 'p')]) == 0
    assert E.main(['reference', *common, '--out', str(tmp_path / 'q')]) == 0
    capsys.readouterr()
    with_p = json.loads((tmp_path / 'p' / 'REFERENCE.json').read_text())
    without = json.loads((tmp_path / 'q' / 'REFERENCE.json').read_text())
    assert with_p['bundle_sha256'] == without['bundle_sha256'] == _frozen(PACK, path)['bundle_sha256']
    text = (tmp_path / 'p' / 'PERF_COUNTERS.json').read_text()
    assert with_p['perf_counters_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    table = json.loads(text)
    rows = table['rows']
    assert [r['rank'] for r in rows] == [1, 2, 3] and rows[0]['gz_bytes'] >= rows[1]['gz_bytes'] >= rows[2]['gz_bytes']
    total = sum(r['full_evaluations'] + r['short_waits'] for r in rows)
    assert total == sum(t['decisions'] for t in [with_p['counts']['master']])                 # one evaluation per index
    assert all(r['wall_s'] >= 0 and r['cpu_s'] >= 0 for r in rows)
    for entry in json.loads((PACK / 'MANIFEST.json').read_text())['pools']:
        assert entry['pool'] not in text
    for word in ('pnl', 'return', 'HW', 'mark_'):
        assert word not in text
    assert hrr.build_features.__module__ != __name__ and hrr.replay_pool.__module__ == hrr.__name__


def test_verify_fast_refusal_writes_nothing_and_the_flag_reaches_the_memo(series, tmp_path, monkeypatch, capsys):
    path, sha = series
    common = ['--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path), '--sol-usd-series-sha256', sha]
    with pytest.raises(E.StreamError, match='verify_fast_requires_fast_analyser'):
        E.main(['run', *common, '--verify-fast', '--expect-bundle-file-sha256', '0' * 64,
                '--expect-bundle-json-sha256', '0' * 64, '--out', str(tmp_path / 'r')])
    assert not (tmp_path / 'r').exists()                                  # refused before anything is written
    seen = []
    original = F.memoized

    def spy(verify=False):
        seen.append(verify)
        return original(verify)
    monkeypatch.setattr(F, 'memoized', spy)
    assert E.main(['reference', *common, '--fast-analyser', '--verify-fast', '--out', str(tmp_path / 'v')]) == 0
    assert E.main(['reference', *common, '--fast-analyser', '--out', str(tmp_path / 'n')]) == 0
    capsys.readouterr()
    assert seen[:3] == [True, True, True] and seen[3:] == [False, False, False]


def test_perf_full_evaluations_match_an_independent_count(series, tmp_path, monkeypatch, capsys):
    path, sha = series
    calls = []
    build = hrr.build_features

    def counting(*args, **kwargs):
        calls.append(1)
        return build(*args, **kwargs)
    monkeypatch.setattr(hrr, 'build_features', counting)
    _frozen(PACK, path)
    independent = len(calls)
    monkeypatch.setattr(hrr, 'build_features', build)
    assert E.main(['reference', '--pools', str(PACK), '--manifest-sha256', SHA, '--sol-usd-series', str(path),
                   '--sol-usd-series-sha256', sha, '--perf-counters', '--out', str(tmp_path / 'p')]) == 0
    capsys.readouterr()
    rows = json.loads((tmp_path / 'p' / 'PERF_COUNTERS.json').read_text())['rows']
    assert independent > 0 and sum(r['full_evaluations'] for r in rows) == independent
