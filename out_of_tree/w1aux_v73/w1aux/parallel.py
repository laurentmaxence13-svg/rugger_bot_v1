"""Pool-parallel and resumable replays for the FROZEN W1 chain (R02 T-1, options c and e).

The frozen ``hrr.run_replay`` and ``harness.run_policy`` are loops over the MANIFEST pools: each
pool goes through a PURE per-pool function (``hrr.replay_pool`` / ``harness.run_policy_pool``)
whose inputs are the pool archive and read-only arguments (params, window, exit options, arms,
SOL/USD series, creator history, policy), then the frozen code assembles the bundle. Within
``parallel_replays(workers, checkpoint_dir)``, every call of those two frozen functions runs as:

1. PROBE: the frozen function itself, with its per-pool function replaced by a recorder that
   stores the exact arguments of each call and answers ``PoolExcluded`` (the frozen loop
   accepts it); the probe bundle is discarded. The per-pool arguments are therefore computed by
   the frozen code, never re-implemented here.
2. COMPUTE: the ORIGINAL per-pool function on every recorded call, in ``workers`` forked
   processes (largest archive first); with a checkpoint directory, each result is written as it
   arrives (atomic file + sha256 index line) and an existing verified result of the same call key
   is reused (resume after an interrupted session). The key carries the rank of an identical call
   within the execution (R02 P-1): the frozen determinism re-runs of run_trials are computed and
   stored separately, so their comparison stays a real check, with or without a checkpoint.
3. ASSEMBLY: the frozen function again, its per-pool function replaced by a lookup that checks
   that the call, in order, has the same arguments as the recorded one and returns the computed
   result (or raises the same ``PoolExcluded``). The bundle is therefore assembled by the frozen
   code, from per-pool results equal to the sequential ones: byte-identical bundles (tested).

No network, no change to any rule, parameter or data. Results are Python objects returned by
the frozen per-pool function (pickle: the multiprocessing transport, and the checkpoint format so
that types are kept exactly); a checkpoint file is read only if its sha256 matches the index line
written by this module after the file was complete.
"""
import contextlib
import dataclasses
import gc
import hashlib
import json
import multiprocessing
import os
import pickle
from pathlib import Path

from bot.master_v2 import harness
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus

PROBE_REASON = 'w1aux_parallel_probe'
INDEX = 'INDEX.jsonl'
_JOB = {}                       # set in the parent before the fork, read by the forked workers
_ACTIVE = {'on': False, 'frozen_code': None, 'occurrences': {}}
STATS = {'computed': 0, 'reused': 0}


class ParallelError(RuntimeError):
    pass


def _module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _describe(value):
    """A JSON description of a per-pool argument, for the checkpoint key; unknown types refused."""
    if isinstance(value, hrr.PoolArchive):
        sha = getattr(value, '_sha256', None)
        if sha is None:
            raise ParallelError('checkpoint_needs_lazy_archives')
        return ['archive', value.pool, sha]
    if isinstance(value, sus.SolUsdSeries):
        return ['sol_usd_series', value.sha256, value.max_age_ms, value.max_confidence_ppm]
    if isinstance(value, hrr.CreatorHistory):
        return ['creator_history', value.sha256, value.label]
    if isinstance(value, harness.Policy):
        return ['policy', type(value).__module__ + '.' + type(value).__qualname__, value.name,
                _describe(value.params())]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return ['dataclass', type(value).__module__ + '.' + type(value).__qualname__,
                _describe(dataclasses.asdict(value))]
    if isinstance(value, dict):
        if not all(type(k) is str for k in value):
            raise ParallelError('cannot_key_non_string_dict_keys')
        return {k: _describe(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [type(value).__name__, [_describe(v) for v in value]]
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise ParallelError('cannot_key:' + type(value).__qualname__)


def call_key(name, args, kwargs, occurrence=0):
    """Checkpoint key of one per-pool call; ``occurrence`` = rank of this identical call within the
    execution (R02 P-1): run_trials replays each L1 configuration twice ON PURPOSE and compares the
    bundles, so the second replay must be computed and stored on its own, never reuse the first."""
    if type(occurrence) is not int or occurrence < 0:
        raise ParallelError('invalid_occurrence')
    doc = dict(function=name, frozen_code=_ACTIVE['frozen_code'], w1aux_parallel=_module_sha256(),
               args=_describe(list(args)), kwargs=_describe(dict(kwargs)), occurrence=occurrence)
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _same(a, b):
    if isinstance(a, hrr.PoolArchive) or isinstance(b, hrr.PoolArchive):
        return type(a) is type(b) and a.pool == b.pool and getattr(a, '_sha256', None) == getattr(b, '_sha256', None)
    if type(a) is not type(b):
        return False
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a is b or a == b


def _work(index):
    function, (args, kwargs) = _JOB['function'], _JOB['calls'][index]
    try:
        return index, ('ok', function(*args, **kwargs))
    except hrr.PoolExcluded as exc:
        return index, ('excluded', list(exc.reasons))


class _Checkpoint:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index = {}
        path = self.dir / INDEX
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.index[row['key']] = row['sha256']

    def get(self, key):
        if key not in self.index:
            return None
        data = (self.dir / f'{key}.pkl').read_bytes()
        if hashlib.sha256(data).hexdigest() != self.index[key]:
            raise ParallelError('checkpoint_file_changed:' + key)
        # Resume cache only, not evidence: the directory is this run's private output, written by
        # put() below; a file is unpickled only when its sha256 matches its index line.
        return pickle.loads(data)                                   # noqa: S301

    def put(self, key, result):
        data = pickle.dumps(result, protocol=4)
        tmp = self.dir / f'{key}.tmp'
        with open(tmp, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.dir / f'{key}.pkl')
        with open(self.dir / INDEX, 'a') as handle:
            handle.write(json.dumps(dict(key=key, sha256=hashlib.sha256(data).hexdigest())) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        self.index[key] = hashlib.sha256(data).hexdigest()


def _size(call):
    archive = call[0][0] if call[0] else None
    path = getattr(archive, '_path', None)
    return path.stat().st_size if path is not None else 0


def _compute(name, function, calls, workers, checkpoint):
    results, todo, keys = [None] * len(calls), [], {}
    for i, (args, kwargs) in enumerate(calls):
        if checkpoint is not None:
            base = call_key(name, args, kwargs)
            occurrence = _ACTIVE['occurrences'].get(base, 0)
            _ACTIVE['occurrences'][base] = occurrence + 1
            keys[i] = call_key(name, args, kwargs, occurrence)
            found = checkpoint.get(keys[i])
            if found is not None:
                results[i] = found
                STATS['reused'] += 1
                continue
        todo.append(i)
    todo.sort(key=lambda i: -_size(calls[i]))                      # largest first: balance the workers

    def store(i, result):
        results[i] = result
        STATS['computed'] += 1
        if checkpoint is not None:
            checkpoint.put(keys[i], result)

    _JOB.update(function=function, calls=calls)
    try:
        if workers == 1 or len(todo) <= 1:
            for i in todo:
                store(*_work(i))
        else:
            gc.collect()
            gc.freeze()            # forked workers share the parent's pages: their GC must not touch them (COW)
            try:
                with multiprocessing.get_context('fork').Pool(workers) as pool:
                    for i, result in pool.imap_unordered(_work, todo, chunksize=1):
                        store(i, result)
            finally:
                gc.unfreeze()
    finally:
        _JOB.clear()
    return results


def _run(module, name, frozen, args, kwargs, workers, checkpoint):
    original = getattr(module, name)
    calls = []

    def recorder(*a, **k):
        calls.append((a, k))
        raise hrr.PoolExcluded([PROBE_REASON])

    setattr(module, name, recorder)
    try:
        frozen(*args, **kwargs)                                      # probe, discarded
    finally:
        setattr(module, name, original)
    results = _compute(name, original, calls, workers, checkpoint)
    position = iter(range(len(calls)))

    def lookup(*a, **k):
        i = next(position, None)
        if i is None or not (_same(list(a), list(calls[i][0])) and _same(dict(k), dict(calls[i][1]))):
            raise ParallelError('per_pool_call_differs_from_probe:' + name)
        status, value = results[i]
        if status == 'excluded':
            raise hrr.PoolExcluded(value)
        return value

    setattr(module, name, lookup)
    try:
        bundle = frozen(*args, **kwargs)                             # assembly by the frozen code
    finally:
        setattr(module, name, original)
    if next(position, None) is not None:
        raise ParallelError('per_pool_calls_not_all_used:' + name)
    return bundle


@contextlib.contextmanager
def parallel_replays(workers, checkpoint_dir=None):
    """Within the block, frozen hrr.run_replay and harness.run_policy compute their pools in parallel."""
    if type(workers) is not int or workers < 1:
        raise ParallelError('workers_must_be_a_positive_integer')
    if _ACTIVE['on']:
        raise ParallelError('parallel_replays_is_not_reentrant')
    checkpoint = None if checkpoint_dir is None else _Checkpoint(checkpoint_dir)
    _ACTIVE['frozen_code'] = harness.code_fingerprint()
    _ACTIVE['occurrences'] = {}                 # one execution = one with-block (R02 P-1)
    run_replay, run_policy = hrr.run_replay, harness.run_policy

    def replay(*args, **kwargs):
        return _run(hrr, 'replay_pool', run_replay, args, kwargs, workers, checkpoint)

    def policy(*args, **kwargs):
        return _run(harness, 'run_policy_pool', run_policy, args, kwargs, workers, checkpoint)

    _ACTIVE['on'] = True
    hrr.run_replay, harness.run_policy = replay, policy
    try:
        yield STATS
    finally:
        hrr.run_replay, harness.run_policy = run_replay, run_policy
        _ACTIVE['on'] = False
