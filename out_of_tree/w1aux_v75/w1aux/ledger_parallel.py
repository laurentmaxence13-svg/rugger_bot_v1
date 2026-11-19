"""Pool-parallel W1 ledger (w1aux v7.5, R02 0c51450f, option P1): same files as the sequential ledger.

The ledger of ``w1aux.ledger`` (v7.4, sha256 115f3cb5, imported UNCHANGED) spends almost all its time in
``derive_l1_plans``: for each pool with an entry and each L1 bundle, the FROZEN observer fed every causal
history up to the largest decision index (R02 R-1), on one process. ``derive_l1_plans`` is a PURE
per-pool function of its arguments (archive, usable timeline, replay params, SOL/USD series, creator
history, decision indices), called by name from ``build_ledger``. Within ``parallel_ledger(workers)``,
every call of ``ledger.build_ledger`` (hence of the unchanged ``ledger.main``) runs as in
``w1aux.parallel`` for the trials:

1. PROBE: the ORIGINAL ``build_ledger`` with ``derive_l1_plans`` replaced by a recorder that keeps the
   exact arguments of each call and answers ``{}``; the probe ledger is discarded. The per-pool arguments
   are therefore computed by the v7.4 code itself, never re-implemented here.
2. COMPUTE: the ORIGINAL ``derive_l1_plans`` on every recorded call, in ``workers`` forked processes,
   largest pool first (T squared, T = number of transactions of the pool). Any failure of any worker
   (exception, killed process) cancels the rest and raises: no result, no file.
3. ASSEMBLY: the ORIGINAL ``build_ledger`` again, ``derive_l1_plans`` replaced by a lookup that checks
   that the call, at its rank, has the same arguments as the recorded one and returns the computed
   plans; every computed result must be used. The ledger is therefore assembled by the v7.4 loop, in its
   own order, from per-pool results equal to the sequential ones: byte-identical ledger.json and
   ledger.md (tested).

Archives are lazy (``w1aux.lazy``, already proven equivalent for the ledger) so that the parent holds no
archive; the recorded timelines of the pools with an entry stay in memory until the assembly. No network,
no change to any rule, parameter, input check or output. Nothing here reads a result.
"""
import concurrent.futures
import contextlib
import gc
import hashlib
import multiprocessing
import os
import resource
from pathlib import Path

from bot.p4 import historical_research_replay as hrr
from w1aux import lazy, ledger, parallel

LEDGER_SHA256 = '115f3cb59dcb5db61f46bda73858a7395e13b862e0b3ab3ba5768cc8d7591b61'     # w1aux v7.4
_JOB = {}                       # set in the parent before the fork, read by the forked workers
_ACTIVE = {'on': False}
STATS = {'calls': 0, 'workers': 0, 'recorded_events': 0, 'probe_peak_rss_mb': None, 'worker_peak_rss_mb': {}}


class LedgerParallelError(RuntimeError):
    pass


def _check_ledger_module():
    if hashlib.sha256(Path(ledger.__file__).read_bytes()).hexdigest() != LEDGER_SHA256:
        raise LedgerParallelError('w1aux_ledger_is_not_v7_4')


def _same(a, b):
    """Argument equality for the lookup: the creator history is rebuilt by each build_ledger, hence compared by
    its sha256 and label; everything else as in w1aux.parallel (archive by pool and sha256, then equality)."""
    if isinstance(a, hrr.CreatorHistory) or isinstance(b, hrr.CreatorHistory):
        return type(a) is type(b) and a.sha256 == b.sha256 and a.label == b.label
    return parallel._same(a, b)


def _weight(call):
    archive = call[0][0]
    return len(archive.transactions) ** 2


def _peak_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def _work(index):
    args, kwargs = _JOB['calls'][index]
    value = _JOB['function'](*args, **kwargs)
    return index, value, os.getpid(), _peak_mb()


def _compute(function, calls, workers):
    """Every recorded call, largest first; results in call order. Any failure raises (no partial result)."""
    order = sorted(range(len(calls)), key=lambda i: (-_JOB['weights'][i], i))
    results = [None] * len(calls)
    _JOB.update(function=function, calls=calls)
    try:
        if workers == 1 or len(order) <= 1:
            for i in order:
                results[i] = _work(i)[1]
            STATS['worker_peak_rss_mb'] = {'parent_process': _peak_mb()}
        else:
            gc.collect()
            gc.freeze()            # forked workers share the parent's pages: their GC must not touch them (COW)
            try:
                executor = concurrent.futures.ProcessPoolExecutor(
                    max_workers=workers, mp_context=multiprocessing.get_context('fork'))
                try:
                    futures = [executor.submit(_work, i) for i in order]
                    peaks = {}
                    for future in concurrent.futures.as_completed(futures):
                        i, value, pid, peak = future.result()    # an exception or a dead worker raises here
                        results[i] = value
                        peaks[pid] = max(peaks.get(pid, 0), peak)
                    STATS['worker_peak_rss_mb'] = {f'worker_{n}': peaks[pid] for n, pid in enumerate(sorted(peaks))}
                except BaseException:
                    executor.shutdown(wait=True, cancel_futures=True)
                    raise
                executor.shutdown(wait=True)
            finally:
                gc.unfreeze()
    except concurrent.futures.process.BrokenProcessPool as exc:
        raise LedgerParallelError('a_ledger_worker_died') from exc
    finally:
        _JOB.clear()
    if any(result is None for result in results):                   # derive_l1_plans always returns a dict
        raise LedgerParallelError('ledger_call_without_result')
    return results


def _parallel_build_ledger(original, workers):
    def build(*args, **kwargs):
        calls, weights = [], []

        def recorder(*a, **k):
            calls.append((a, k))
            weights.append(_weight((a, k)))
            return {}

        ledger.derive_l1_plans = recorder
        try:
            original(*args, **kwargs)                                # probe, discarded
        finally:
            ledger.derive_l1_plans = _ORIGINAL['derive_l1_plans']
        STATS['calls'] += len(calls)
        STATS['recorded_events'] += sum(len(a[1].events) for a, _k in calls)   # timelines kept until the assembly
        STATS['probe_peak_rss_mb'] = _peak_mb()                                # high-water mark after the probe
        _JOB['weights'] = weights
        results = _compute(_ORIGINAL['derive_l1_plans'], calls, workers)
        position = iter(range(len(calls)))

        def lookup(*a, **k):
            i = next(position, None)
            if i is None or len(a) != len(calls[i][0]) or k.keys() != calls[i][1].keys() \
                    or not all(_same(x, y) for x, y in zip(a, calls[i][0])) \
                    or not all(_same(k[name], calls[i][1][name]) for name in k):
                raise LedgerParallelError('ledger_call_differs_from_probe')
            return results[i]

        ledger.derive_l1_plans = lookup
        try:
            out = original(*args, **kwargs)                          # assembly by the v7.4 loop
        finally:
            ledger.derive_l1_plans = _ORIGINAL['derive_l1_plans']
        if next(position, None) is not None:
            raise LedgerParallelError('ledger_calls_not_all_used')
        return out
    return build


_ORIGINAL = {}


@contextlib.contextmanager
def parallel_ledger(workers):
    """Within the block, ledger.build_ledger (and the unchanged ledger.main) derive the L1 plans in parallel."""
    if type(workers) is not int or workers < 1:
        raise LedgerParallelError('workers_must_be_a_positive_integer')
    if _ACTIVE['on']:
        raise LedgerParallelError('parallel_ledger_is_not_reentrant')
    _check_ledger_module()
    _ORIGINAL.update(build_ledger=ledger.build_ledger, derive_l1_plans=ledger.derive_l1_plans)
    _ACTIVE['on'] = True
    STATS.update(calls=0, workers=workers, recorded_events=0, probe_peak_rss_mb=None, worker_peak_rss_mb={})
    try:
        with lazy.lazy_archives():
            ledger.build_ledger = _parallel_build_ledger(_ORIGINAL['build_ledger'], workers)
            try:
                yield STATS
            finally:
                ledger.build_ledger = _ORIGINAL['build_ledger']
                ledger.derive_l1_plans = _ORIGINAL['derive_l1_plans']
    finally:
        _ACTIVE['on'] = False
        _ORIGINAL.clear()
