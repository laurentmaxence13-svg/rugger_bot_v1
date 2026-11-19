"""w1aux.ledger_resume (R02 bac856e7, P1-bis): one process, per-call disk cache, same bytes as the v7.4 ledger.

Reference = ``w1aux.ledger.main`` v7.4 run sequentially and eagerly. Cases: the frozen pack, pools without entry,
migrated / excluded / absent pools, a SIGKILL in the middle then a resume, altered / truncated / foreign caches,
identical calls kept distinct, and the guards.
"""
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from bot.p4 import sol_usd_series as sus
from w1aux import ledger as L
from w1aux import ledger_parallel as LP
from w1aux import ledger_resume as LR
from w1aux.tests.test_ledger import PACK, _copy, _rewrite, rehearsal  # noqa: F401  (module fixture)
from w1aux.tests.test_ledger_parallel import L1POOL, _main, _migrated_summarize, synthetic_rehearsal  # noqa: F401
from bot.market.collector import summarize as real_summarize

BINDING = 'test-binding'


def _excluded_summarize():
    def summarize(archive):
        summary, timeline = real_summarize(archive)
        if archive.pool == L1POOL:
            summary = dict(summary, complete=False, transactions_missing=1)
        return summary, timeline
    return summarize


def _drifting_summarize():
    count = {}

    def summarize(archive):                                       # the assembly pass does not repeat the probe
        summary, timeline = real_summarize(archive)
        count[archive.pool] = count.get(archive.pool, 0) + 1
        if archive.pool == L1POOL and count[archive.pool] > 1:
            timeline = type(timeline)(timeline.pool, timeline.events[:-1], timeline.gaps, timeline.rejected)
        return summary, timeline
    return summarize


def _seq_and_resumable(tmp_path, pools, bundles, cache, *, series=None, report=None, binding=BINDING):
    seq = _main(pools, bundles, tmp_path / 'seq', series=series, report=report)
    with LR.resumable_ledger(cache, binding) as stats:
        res = _main(pools, bundles, tmp_path / 'res', series=series, report=report)
    return seq, res, dict(stats)


def _series(rehearsal):
    return rehearsal / 'sol_usd.json'


@pytest.mark.parametrize('with_report', [False, True])
def test_frozen_pack_ledger_is_byte_identical_then_fully_reused(rehearsal, tmp_path, with_report):
    report = rehearsal / 'out' / 'w1_report.json' if with_report else None
    seq, res, stats = _seq_and_resumable(tmp_path, PACK, rehearsal / 'out' / 'bundles', tmp_path / 'cache',
                                         series=_series(rehearsal), report=report)
    assert seq == res and json.loads(res[1])['verdict'] == 'PASS'
    assert stats['calls'] == stats['computed'] == 4 and stats['reused'] == 0 and stats['recorded_events'] > 0
    assert stats['resumes'] == 0
    assert stats['probe_peak_rss_mb'] > 0 and stats['compute_peak_rss_mb'] >= stats['probe_peak_rss_mb']
    with LR.resumable_ledger(tmp_path / 'cache', BINDING) as again:     # a second run computes nothing
        rerun = _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'res2', series=_series(rehearsal), report=report)
    assert rerun == seq and again['reused'] == 4 and again['computed'] == 0 and again['resumes'] == 1
    assert len((tmp_path / 'cache' / LR.OPENINGS).read_text().splitlines()) == 2


def test_identical_calls_keep_distinct_keys(rehearsal, tmp_path):
    with LR.resumable_ledger(tmp_path / 'cache', BINDING):
        _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'res', series=_series(rehearsal))
    index = [json.loads(x) for x in (tmp_path / 'cache' / LR.INDEX).read_text().splitlines()]
    assert len(index) == len({r['key'] for r in index}) == 4                   # L1 and L1_event_horizon included
    pkl = {p.stem for p in (tmp_path / 'cache').glob('*.pkl')}
    assert pkl == {r['key'] for r in index}


def test_pools_without_entry_migrated_excluded_and_absent_are_identical(synthetic_rehearsal, rehearsal, tmp_path,
                                                                       monkeypatch):
    root = synthetic_rehearsal
    seq, res, _ = _seq_and_resumable(tmp_path / 'syn', root / 'pack', root / 'out' / 'bundles', tmp_path / 'c1',
                                     series=_series(rehearsal))
    assert seq == res
    bundles = _copy(rehearsal, tmp_path / 'absent')
    _rewrite(bundles, 'S1', lambda b: [p.__setitem__('pool', 'X' * 44) for p in b['pools']
                                       if p['trade']['entry_index'] is not None][:1])
    seq, res, _ = _seq_and_resumable(tmp_path / 'abs', PACK, bundles, tmp_path / 'c2', series=_series(rehearsal))
    assert seq == res and seq[0] == 4
    for name, summarize in (('mig', _migrated_summarize(1)), ('exc', _excluded_summarize())):
        with monkeypatch.context() as m:
            m.setattr(L, 'summarize', summarize)
            seq, res, _ = _seq_and_resumable(tmp_path / name, PACK, rehearsal / 'out' / 'bundles', tmp_path / f'c{name}',
                                             series=_series(rehearsal))
        assert seq == res


_KILLER = textwrap.dedent('''
    import os, signal, sys
    from pathlib import Path
    from w1aux import ledger as L
    from w1aux import ledger_resume as LR
    original, count = L.derive_l1_plans, [0]
    def derive(*a):
        count[0] += 1
        if count[0] == int(sys.argv[5]):
            os.kill(os.getpid(), signal.SIGKILL)
        return original(*a)
    L.derive_l1_plans = derive
    with LR.resumable_ledger(Path(sys.argv[3]), sys.argv[6]):
        L.main(['--pools', sys.argv[1], '--bundles', sys.argv[2], '--series', sys.argv[4], '--out', sys.argv[7]])
''')


def _killed_run(rehearsal, tmp_path, cache, at):
    done = subprocess.run([sys.executable, '-B', '-c', _KILLER, str(PACK), str(rehearsal / 'out' / 'bundles'), str(cache),
                           str(_series(rehearsal)), str(at), BINDING, str(tmp_path / 'killed_out')],
                          env=dict(os.environ), capture_output=True, text=True)
    assert done.returncode == -signal.SIGKILL, done.stderr[-500:]
    assert not (tmp_path / 'killed_out').exists()


def test_sigkill_in_the_middle_then_resume_gives_the_same_bytes(rehearsal, tmp_path):
    _killed_run(rehearsal, tmp_path, tmp_path / 'cache', 3)                  # two calls stored, killed in the third
    seq, res, stats = _seq_and_resumable(tmp_path, PACK, rehearsal / 'out' / 'bundles', tmp_path / 'cache',
                                         series=_series(rehearsal))
    assert seq == res and stats['reused'] == 2 and stats['computed'] == 2 and stats['rejected'] == 0
    assert stats['resumes'] == 1


def _filled_cache(rehearsal, tmp_path):
    cache = tmp_path / 'cache'
    with LR.resumable_ledger(cache, BINDING):
        _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'first', series=_series(rehearsal))
    return cache, [json.loads(x) for x in (cache / LR.INDEX).read_text().splitlines()]


def _resume(rehearsal, tmp_path, cache, name, binding=BINDING):
    seq = _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / f'seq_{name}', series=_series(rehearsal))
    with LR.resumable_ledger(cache, binding) as stats:
        res = _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / f'res_{name}', series=_series(rehearsal))
    return seq, res, dict(stats)


@pytest.mark.parametrize('damage', ['altered', 'truncated', 'missing', 'other_key_inside'])
def test_an_invalid_entry_is_rejected_and_recomputed(rehearsal, tmp_path, damage):
    cache, index = _filled_cache(rehearsal, tmp_path)
    path = cache / f"{index[1]['key']}.pkl"
    if damage == 'altered':
        data = bytearray(path.read_bytes())
        data[-3] ^= 1
        path.write_bytes(bytes(data))
    elif damage == 'truncated':
        path.write_bytes(path.read_bytes()[:20])
    elif damage == 'missing':
        path.unlink()
    else:                                                                    # a valid file of another key, renamed
        path.write_bytes((cache / f"{index[0]['key']}.pkl").read_bytes())
        (cache / LR.INDEX).write_text(''.join(json.dumps(dict(r, sha256=index[0]['sha256'] if i == 1 else r['sha256'])) + '\n'
                                              for i, r in enumerate(index)))
    seq, res, stats = _resume(rehearsal, tmp_path, cache, damage)
    assert seq == res and stats['rejected'] == 1 and stats['computed'] == 1 and stats['reused'] == 3


def test_interrupted_writes_are_cleaned_and_a_truncated_last_index_line_ignored(rehearsal, tmp_path):
    cache, index = _filled_cache(rehearsal, tmp_path)
    (cache / 'leftover.tmp').write_bytes(b'partial')
    (cache / f"{index[3]['key']}.pkl").unlink()
    text = (cache / LR.INDEX).read_text()
    (cache / LR.INDEX).write_text(text[:-10])                                # the last append was cut
    seq, res, stats = _resume(rehearsal, tmp_path, cache, 'tail')
    assert seq == res and stats['tmp_removed'] == 1 and stats['computed'] == 1 and stats['reused'] == 3
    assert not (cache / 'leftover.tmp').exists()
    lines = (cache / LR.INDEX).read_text().splitlines()
    assert (cache / LR.INDEX).read_text().endswith('\n') and len(lines) == 4 and all(json.loads(x)['key'] for x in lines)
    _seq2, res2, again = _resume(rehearsal, tmp_path, cache, 'tail_again')        # the repaired index reads back
    assert res2 == seq and again['reused'] == 4 and again['computed'] == 0


@pytest.mark.parametrize('case, error', [
    ('orphan_pkl', 'orphan_file_in_resume_dir'), ('unknown_file', 'orphan_file_in_resume_dir'),
    ('foreign_entry', 'foreign_entry_in_resume_dir'), ('bad_middle_line', 'resume_index_line_unreadable'),
    ('other_binding', 'resume_dir_is_for_another_run_or_code'), ('no_meta', 'resume_dir_without_meta'),
    ('other_code', 'resume_dir_is_for_another_run_or_code')])
def test_a_foreign_or_damaged_cache_is_refused_without_any_file(rehearsal, tmp_path, case, error):
    cache, index = _filled_cache(rehearsal, tmp_path)
    binding = BINDING
    if case == 'orphan_pkl':
        (cache / ('f' * 64 + '.pkl')).write_bytes(b'x')
    elif case == 'unknown_file':
        (cache / 'notes.txt').write_text('x')
    elif case == 'foreign_entry':
        with open(cache / LR.INDEX, 'a') as handle:
            handle.write(json.dumps(dict(key='e' * 64, sha256='0' * 64)) + '\n')
    elif case == 'bad_middle_line':
        lines = (cache / LR.INDEX).read_text().splitlines()
        (cache / LR.INDEX).write_text('\n'.join([lines[0], '{not json', *lines[1:]]) + '\n')
    elif case == 'other_binding':
        binding = 'another-run'
    elif case == 'no_meta':
        (cache / LR.META).unlink()
    else:
        meta = json.loads((cache / LR.META).read_text())
        meta['code']['ledger_resume_py'] = '0' * 64
        (cache / LR.META).write_text(json.dumps(meta))
    with pytest.raises(LR.LedgerResumeError, match=error):
        with LR.resumable_ledger(cache, binding):
            _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'out', series=_series(rehearsal))
    assert not (tmp_path / 'out').exists()


def test_assembly_refuses_a_call_that_differs_from_the_probe(rehearsal, tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'summarize', _drifting_summarize())
    with pytest.raises(LR.LedgerResumeError, match='ledger_call_differs_from_probe'):
        with LR.resumable_ledger(tmp_path / 'cache', BINDING):
            _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'out', series=_series(rehearsal))
    assert not (tmp_path / 'out').exists()


def test_assembly_refuses_unused_results(rehearsal, tmp_path, monkeypatch):
    count = {}

    def vanishing(archive):                                       # the assembly excludes the pool the probe kept
        summary, timeline = real_summarize(archive)
        count[archive.pool] = count.get(archive.pool, 0) + 1
        if archive.pool == L1POOL and count[archive.pool] > 1:
            summary = dict(summary, complete=False, transactions_missing=1)
        return summary, timeline
    monkeypatch.setattr(L, 'summarize', vanishing)
    with pytest.raises(LR.LedgerResumeError, match='ledger_calls_not_all_used'):
        with LR.resumable_ledger(tmp_path / 'cache', BINDING):
            _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'out', series=_series(rehearsal))
    assert not (tmp_path / 'out').exists()


def test_guards(tmp_path, monkeypatch):
    for bad in ('', None, 3):
        with pytest.raises(LR.LedgerResumeError, match='binding_required'):
            with LR.resumable_ledger(tmp_path / 'c', bad):
                pass
    with LR.resumable_ledger(tmp_path / 'c', BINDING):
        with pytest.raises(LR.LedgerResumeError, match='not_reentrant'):
            with LR.resumable_ledger(tmp_path / 'd', BINDING):
                pass
    with LP.parallel_ledger(2):
        with pytest.raises(LR.LedgerResumeError, match='not_reentrant'):
            with LR.resumable_ledger(tmp_path / 'f', BINDING):
                pass
    assert L.build_ledger.__module__ == 'w1aux.ledger' and L.derive_l1_plans.__module__ == 'w1aux.ledger'
    monkeypatch.setattr(LP, 'LEDGER_SHA256', '0' * 64)
    with pytest.raises(LP.LedgerParallelError, match='w1aux_ledger_is_not_v7_4'):
        with LR.resumable_ledger(tmp_path / 'e', BINDING):
            pass


def test_keys_depend_on_every_argument_and_on_the_occurrence(rehearsal):
    from bot.p4 import historical_research_replay as hrr
    from w1aux import lazy
    with lazy.lazy_archives():
        pools = hrr.load_fixtures(PACK)[2]
        archive = next(a for _e, a in pools if a.pool == L1POOL)
        other = next(a for _e, a in pools if a.pool != L1POOL)
        timeline = hrr.usable_timeline(archive, *L.summarize(archive))[0]
        history = hrr.CreatorHistory.from_archives([a for _e, a in pools], 'manifest')
        series = sus.load_series(_series(rehearsal))
        params = hrr.ReplayParams()
        base = (archive, timeline, params, series, history, {1})
        resealed = lazy.LazyArchive(archive._path, archive.pool, 'f' * 64)     # same pool, another archive sha256
        variants = [(other, timeline, params, series, history, {1}),
                    (resealed, timeline, params, series, history, {1}),
                    (archive, type(timeline)(timeline.pool, timeline.events[:-1], (), ()), params, series, history, {1}),
                    (archive, timeline, hrr.ReplayParams(latency_slots=params.latency_slots + 1), series, history, {1}),
                    (archive, timeline, params, None, history, {1}),
                    (archive, timeline, params, series, None, {1}),
                    (archive, timeline, params, series, hrr.CreatorHistory.from_archives([a for _e, a in pools], 'x'), {1}),
                    (archive, timeline, params, series, history, {0, 1})]
        keys = [LR.call_keys([(call, {})])[0] for call in [base, *variants]]     # each alone: occurrence 0
        assert len(set(keys)) == len(keys)
        twice = LR.call_keys([(base, {}), (base, {})])
        assert twice[0] != twice[1] and twice[0] == keys[0]
        with pytest.raises(LR.LedgerResumeError, match='unexpected_keyword_arguments'):
            LR.call_keys([(base, {'x': 1})])
        eager = hrr.PoolArchive.from_json(archive._data())
        with pytest.raises(LR.LedgerResumeError, match='cache_needs_lazy_archives'):
            LR.call_keys([((eager, *base[1:]), {})])
