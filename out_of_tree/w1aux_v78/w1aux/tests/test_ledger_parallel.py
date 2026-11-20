"""w1aux.ledger_parallel (R02 0c51450f, P1): the pool-parallel ledger writes the same bytes as the v7.4 ledger.

Reference = ``w1aux.ledger.main`` v7.4 run SEQUENTIALLY and EAGERLY (exactly what the exploratory ledger step runs).
Cases: the frozen pack rehearsal (PASS, 9 cycles), a pool absent from the export, an excluded pool, a migrated
pool, pools without any entry (synthetic copies), several L1 bundles entered on one pool, the v7.4 input checks,
a worker raising, a worker killed, a probe/assembly divergence and the guards.
"""
import collections
import hashlib
import io
import json
import os
import signal
from pathlib import Path

import pytest

from bot.market.collector import summarize as real_summarize
from bot.market.launchlab_curve import fee_for
from bot.market.launchlab_events import TradeEvent, check_trade
from bot.market.pool_timeline import build_timeline
from bot.master_v2 import w1_run as run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from w1aux import lazy, synthetic
from w1aux import ledger as L
from w1aux import ledger_parallel as LP
from w1aux.tests.test_ledger import PACK, _copy, _rewrite, rehearsal  # noqa: F401  (module fixture)

L1POOL = 'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r'     # the frozen-pack pool with L1 entries (4 bundles)


def _main(pools, bundles, out, *, series=None, report=None):
    buffer = io.StringIO()
    argv = ['--pools', str(pools), '--bundles', str(bundles), '--out', str(out)]
    if series is not None:
        argv += ['--series', str(series)]
    if report is not None:
        argv += ['--report', str(report)]
    code = L.main(argv, out=buffer)
    return code, buffer.getvalue(), (out / 'ledger.json').read_bytes(), (out / 'ledger.md').read_bytes()


def _both(tmp_path, pools, bundles, workers, **kw):
    """(sequential eager v7.4, parallel) outputs of ledger.main: return code, summary line, json, md."""
    seq = _main(pools, bundles, tmp_path / 'seq', **kw)
    with LP.parallel_ledger(workers) as stats:
        par = _main(pools, bundles, tmp_path / f'par{workers}', **kw)
    return seq, par, dict(stats)


def _series(rehearsal):
    return rehearsal / 'sol_usd.json'


def _calls_per_pool(pools, bundles, series):
    """Sequential v7.4 run with a counting derive_l1_plans: {pool: [indices of each call]}."""
    seen, original = collections.defaultdict(list), L.derive_l1_plans

    def counting(archive, timeline, params, series_, history, indices):
        seen[archive.pool].append((len(timeline.events), sorted(indices)))
        return original(archive, timeline, params, series_, history, indices)
    L.derive_l1_plans = counting
    try:
        L.build_ledger(pools, bundles, series=sus.load_series(series))
    finally:
        L.derive_l1_plans = original
    return seen


@pytest.mark.parametrize('workers', [1, 2, 4])
@pytest.mark.parametrize('with_report', [False, True])
def test_frozen_pack_ledger_is_byte_identical(rehearsal, tmp_path, workers, with_report):
    report = rehearsal / 'out' / 'w1_report.json' if with_report else None
    seq, par, stats = _both(tmp_path, PACK, rehearsal / 'out' / 'bundles', workers, series=_series(rehearsal),
                            report=report)
    assert seq == par
    summary = json.loads(par[1])
    assert par[0] == 0 and summary['verdict'] == 'PASS' and summary['cycles_verified'] == 9
    assert stats['calls'] > 0 and stats['workers'] == workers and stats['recorded_events'] > 0
    assert stats['probe_peak_rss_mb'] > 0 and stats['worker_peak_rss_mb'] and all(v > 0 for v in stats['worker_peak_rss_mb'].values())
    assert 1 <= len(stats['worker_peak_rss_mb']) <= (1 if workers == 1 else min(workers, stats['calls']))


def test_several_l1_bundles_entered_on_one_pool_are_derived_separately(rehearsal, tmp_path):
    calls = _calls_per_pool(PACK, rehearsal / 'out' / 'bundles', _series(rehearsal))
    assert max(len(v) for v in calls.values()) >= 2             # one call per L1 bundle (R-1), none shared (P2 refused)
    seq, par, stats = _both(tmp_path, PACK, rehearsal / 'out' / 'bundles', 3, series=_series(rehearsal))
    assert seq == par and stats['calls'] == sum(len(v) for v in calls.values())


def test_pool_absent_from_the_export_is_identical(rehearsal, tmp_path):
    bundles = _copy(rehearsal, tmp_path)
    _rewrite(bundles, 'S1', lambda b: [p.__setitem__('pool', 'X' * 44) for p in b['pools']
                                       if p['trade']['entry_index'] is not None][:1])
    seq, par, _ = _both(tmp_path, PACK, bundles, 2, series=_series(rehearsal))
    assert seq == par and seq[0] == 4 and b'pool_not_in_the_exported_pools' in seq[2]


def _crossing(previous, signature, rate=12_500):
    state = previous.state_after()
    amount_in = 10 ** 14
    fee = fee_for(amount_in, rate)
    values = {name: getattr(previous, name) for name in (
        'slot', 'block_time', 'fee_payer', 'pool', 'pool_status', 'total_base_sell', 'virtual_base', 'virtual_quote')}
    values.update(signature=signature, event_index=0, side='buy', exact_in=True,
                  real_base_before=state.real_base, real_quote_before=state.real_quote,
                  real_base_after=state.total_base_sell, real_quote_after=state.real_quote + amount_in - fee,
                  amount_in=amount_in, amount_out=state.total_base_sell - state.real_base,
                  protocol_fee=fee, platform_fee=0, creator_fee=0, share_fee=0)
    return TradeEvent(violations=check_trade(values), **values)


def _migrated_summarize(boundary):
    """The frozen summarize, except L1POOL: its events stop at ``boundary`` with a migrating buy (as test_lazy)."""
    def summarize(archive):
        summary, timeline = real_summarize(archive)
        if archive.pool != L1POOL:
            return summary, timeline
        kept, crossing = list(timeline.events[:boundary]), timeline.events[boundary].signature
        migrated = build_timeline(L1POOL, kept + [_crossing(kept[-1], crossing)])
        return dict(summary, complete=False, trades=len(migrated.events), rejected=1,
                    max_progress_ppm=max(e.state_after().progress_ppm for e in kept)), migrated
    return summarize


def test_migrated_pool_is_identical(rehearsal, tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'summarize', _migrated_summarize(1))
    calls = _calls_per_pool(PACK, rehearsal / 'out' / 'bundles', _series(rehearsal))
    assert L1POOL in calls and all(n == 1 for n, _ in calls[L1POOL])      # usable_timeline cut it at the migration
    seq, par, _ = _both(tmp_path, PACK, rehearsal / 'out' / 'bundles', 2, series=_series(rehearsal))
    assert seq == par


def test_excluded_pool_is_identical(rehearsal, tmp_path, monkeypatch):
    def summarize(archive):
        summary, timeline = real_summarize(archive)
        if archive.pool == L1POOL:
            summary = dict(summary, complete=False, transactions_missing=1)
        return summary, timeline
    monkeypatch.setattr(L, 'summarize', summarize)
    calls = _calls_per_pool(PACK, rehearsal / 'out' / 'bundles', _series(rehearsal))
    assert L1POOL not in calls                                          # excluded: no derivation, entries not verified
    seq, par, _ = _both(tmp_path, PACK, rehearsal / 'out' / 'bundles', 2, series=_series(rehearsal))
    assert seq == par and seq[0] == 4


@pytest.fixture(scope='module')
def synthetic_rehearsal(tmp_path_factory, rehearsal):
    """The frozen pack x2 (synthetic copies: unverified creators, the L1 arms WAIT): pools WITHOUT any entry."""
    root = tmp_path_factory.mktemp('synthetic')
    synthetic.build(root / 'pack', 2)
    mp = pytest.MonkeyPatch()
    mp.setenv('RUGGER_NO_DOTENV', '1')
    try:
        run.run_trials(root / 'pack', _series(rehearsal), registry_path=root / 't.jsonl',
                       sensitivity_registry_path=root / 's.jsonl', registered_at='2026-11-08T00:00:00+00:00',
                       out=root / 'out')
    finally:
        mp.undo()
    return root


def test_pools_without_entry_are_identical(synthetic_rehearsal, rehearsal, tmp_path):
    root = synthetic_rehearsal
    pools = {e['pool'] for e in json.loads((root / 'pack' / 'MANIFEST.json').read_text())['pools']}
    bundles, _sums = L.load_bundles(root / 'out' / 'bundles')
    entered = {pool for trial_id, bundle in bundles.items() for _a, pool, row, _p, _s in L.cycles(trial_id, bundle)
               if row['entry_index'] is not None}
    assert len(pools) == 6 and entered and entered < pools              # some pools have no entry in any bundle
    assert _calls_per_pool(root / 'pack', root / 'out' / 'bundles', _series(rehearsal))
    for workers in (1, 2, 4):
        seq, par, _ = _both(tmp_path / str(workers), root / 'pack', root / 'out' / 'bundles', workers,
                            series=_series(rehearsal))
        assert seq == par


def test_v7_4_input_checks_are_the_same(rehearsal, tmp_path):
    cases = []
    bundles = _copy(rehearsal, tmp_path / 'a')
    path = bundles / 'S2.json.gz'
    path.write_bytes(path.read_bytes() + b'\0')
    cases.append((bundles, None, 'bundle_file_changed:S2'))
    bundles = _copy(rehearsal, tmp_path / 'b')
    _rewrite(bundles, 'L1', lambda b: [r for p in b['pools'] for r in p['arms'].values()
                                       if r['outcome'] == 'closed'][0].__setitem__('spent', 1), rehash_l1=False)
    cases.append((bundles, None, 'bundle_internal_hash_mismatch:L1'))
    other = dict(json.loads(_series(rehearsal).read_text()))
    other['points'][0]['price'] += 1
    (tmp_path / 'other.json').write_text(json.dumps(other))
    cases.append((rehearsal / 'out' / 'bundles', tmp_path / 'other.json', 'series_is_not_the_one_replayed'))
    for i, (bundles, series, message) in enumerate(cases):
        for mode in ('seq', 'par'):
            out = tmp_path / f'{mode}{i}'
            with pytest.raises(L.LedgerError, match=message):
                if mode == 'seq':
                    _main(PACK, bundles, out, series=series)
                else:
                    with LP.parallel_ledger(2):
                        _main(PACK, bundles, out, series=series)
            assert not out.exists()


class _Boom(RuntimeError):
    pass


def _faulty(kind):
    original = L.derive_l1_plans

    def derive(archive, *args):
        if archive.pool == L1POOL:
            if kind == 'raise':
                raise _Boom('injected')
            os.kill(os.getpid(), signal.SIGKILL)
        return original(archive, *args)
    return derive


@pytest.mark.parametrize('kind, error', [('raise', _Boom), ('kill', LP.LedgerParallelError)])
def test_a_failing_worker_fails_everything_without_any_file(rehearsal, tmp_path, monkeypatch, kind, error):
    monkeypatch.setattr(L, 'derive_l1_plans', _faulty(kind))          # taken as the per-pool function by the block
    with pytest.raises(error):
        with LP.parallel_ledger(2):
            _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'out', series=_series(rehearsal))
    assert not (tmp_path / 'out').exists()
    assert L.build_ledger.__module__ == 'w1aux.ledger' and not LP._ACTIVE['on']


def test_assembly_refuses_a_call_that_differs_from_the_probe(rehearsal, tmp_path, monkeypatch):
    count = collections.Counter()

    def drifting(archive):                                            # a second pass that does not repeat the first
        summary, timeline = real_summarize(archive)
        count[archive.pool] += 1
        if archive.pool == L1POOL and count[archive.pool] > 1:
            timeline = type(timeline)(timeline.pool, timeline.events[:-1], timeline.gaps, timeline.rejected)
        return summary, timeline
    monkeypatch.setattr(L, 'summarize', drifting)
    with pytest.raises(LP.LedgerParallelError, match='ledger_call_differs_from_probe'):
        with LP.parallel_ledger(2):
            _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'out', series=_series(rehearsal))
    assert not (tmp_path / 'out').exists()


def test_assembly_refuses_unused_results(rehearsal, tmp_path, monkeypatch):
    count = collections.Counter()

    def vanishing(archive):                                           # the assembly excludes a pool the probe kept
        summary, timeline = real_summarize(archive)
        count[archive.pool] += 1
        if archive.pool == L1POOL and count[archive.pool] > 1:
            summary = dict(summary, complete=False, transactions_missing=1)
        return summary, timeline
    monkeypatch.setattr(L, 'summarize', vanishing)
    pools = sorted(_calls_per_pool(PACK, rehearsal / 'out' / 'bundles', _series(rehearsal)))
    count.clear()
    match = 'ledger_calls_not_all_used' if pools[-1] == L1POOL else 'ledger_call_differs_from_probe'
    with pytest.raises(LP.LedgerParallelError, match=match):
        with LP.parallel_ledger(2):
            _main(PACK, rehearsal / 'out' / 'bundles', tmp_path / 'out', series=_series(rehearsal))


def test_guards_and_lazy_archives(rehearsal, tmp_path, monkeypatch):
    for bad in (0, -1, 2.0, '2', True):
        with pytest.raises(LP.LedgerParallelError, match='workers_must_be_a_positive_integer'):
            with LP.parallel_ledger(bad):
                pass
    with LP.parallel_ledger(2):
        assert hrr.load_fixtures is lazy.load_fixtures_lazy           # the parent holds no archive
        with pytest.raises(LP.LedgerParallelError, match='parallel_ledger_is_not_reentrant'):
            with LP.parallel_ledger(2):
                pass
    assert hrr.load_fixtures is not lazy.load_fixtures_lazy and not LP._ACTIVE['on']
    assert L.build_ledger.__module__ == 'w1aux.ledger' and L.derive_l1_plans.__module__ == 'w1aux.ledger'
    monkeypatch.setattr(LP, 'LEDGER_SHA256', '0' * 64)
    with pytest.raises(LP.LedgerParallelError, match='w1aux_ledger_is_not_v7_4'):
        with LP.parallel_ledger(2):
            pass


def test_compute_returns_every_result_at_its_call_rank_largest_first(monkeypatch):
    order = []

    def function(tag, *, weight):
        order.append(tag)
        return {tag: weight}
    weights = [(7 * i) % 11 for i in range(40)]
    calls = [((i,), dict(weight=w)) for i, w in enumerate(weights)]
    LP._JOB['weights'] = weights
    assert LP._compute(function, calls, 1) == [{i: w} for i, w in enumerate(weights)]
    assert order == sorted(range(40), key=lambda i: (-weights[i], i))              # largest first, then call rank
    for workers in (2, 3, 7):
        LP._JOB['weights'] = weights
        assert LP._compute(function, calls, workers) == [{i: w} for i, w in enumerate(weights)]
    assert LP._JOB == {}


def test_same_compares_the_rebuilt_creator_history_by_sha256_and_label():
    archives = [a for _e, a in hrr.load_fixtures(PACK)[2]]
    a, b = hrr.CreatorHistory.from_archives(archives, 'manifest'), hrr.CreatorHistory.from_archives(archives, 'manifest')
    assert a is not b and LP._same(a, b) and not LP._same(a, None) and not LP._same(None, a)
    assert not LP._same(a, hrr.CreatorHistory.from_archives(archives, 'other'))
    assert not LP._same(a, hrr.CreatorHistory.from_archives(archives[:-1], 'manifest'))
    assert LP._same(None, None) and LP._same({1, 2}, {2, 1}) and not LP._same({1}, {1, 2})


def test_ledger_module_is_the_v7_4_one():
    assert hashlib.sha256(Path(L.__file__).read_bytes()).hexdigest() == LP.LEDGER_SHA256


class _FakeArchive:
    transactions = {'a': 1, 'b': 2}


class _FakeTimeline:
    events = (1, 2, 3)


@pytest.mark.parametrize('second, error', [(1, None), (2, 'ledger_call_differs_from_probe')])
def test_lookup_compares_keyword_arguments_too(monkeypatch, second, error):
    def derive(archive, timeline, *, k):
        return {'k': k}
    monkeypatch.setitem(LP._ORIGINAL, 'derive_l1_plans', derive)
    monkeypatch.setattr(L, 'derive_l1_plans', derive)
    runs, archive, timeline = iter([1, second]), _FakeArchive(), _FakeTimeline()

    def build():
        return L.derive_l1_plans(archive, timeline, k=next(runs))
    if error is None:
        assert LP._parallel_build_ledger(build, 1)() == {'k': 1}
    else:
        with pytest.raises(LP.LedgerParallelError, match=error):
            LP._parallel_build_ledger(build, 1)()


def test_compute_refuses_a_call_without_result():
    LP._JOB['weights'] = [1, 2]
    with pytest.raises(LP.LedgerParallelError, match='ledger_call_without_result'):
        LP._compute(lambda tag: None if tag else {}, [((0,), {}), ((1,), {})], 1)
    assert LP._JOB == {}
