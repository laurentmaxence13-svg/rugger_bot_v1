"""Resumable W1 ledger (w1aux v7.6, R02 bac856e7, P1-bis): the v7.4 ledger, one process, with a per-call disk cache.

The sequential ledger keeps nothing before its end, so a container restart loses hours of work. Within
``resumable_ledger(cache_dir)``, every call of ``ledger.build_ledger`` (v7.4, 115f3cb5, UNCHANGED; hence of the
unchanged ``ledger.main``) runs as in ``w1aux.ledger_parallel`` but with ONE process and no fork:

1. PROBE: the ORIGINAL ``build_ledger``, ``derive_l1_plans`` replaced by a recorder (exact arguments; answers ``{}``);
   the probe ledger is discarded.
2. COMPUTE: in this process, in call order, the ORIGINAL ``derive_l1_plans`` on each recorded call, unless the cache
   holds a valid entry for its key. Each computed result is stored at once: index line (key, sha256 of the content),
   fsync, then temporary file, fsync, rename. A key is the sha256 of the canonical description of the call: archive
   pool and sha256, canonical fingerprint of the timeline, replay params, series (sha256, max age, max confidence),
   creator history (sha256, label), sorted decision indices, the rank of an identical call within the build (two
   identical calls never share a result: P2 refused, R02 rule P-1), the sha256 of ledger.py and of this module, and
   the frozen code fingerprint.
3. ASSEMBLY: the ORIGINAL ``build_ledger`` again, ``derive_l1_plans`` replaced by the rank-checked lookup of
   ``ledger_parallel`` (same arguments as recorded, every result used).

Cache rules (opened before the PROBE, checked against the PROBE keys before any use):
- ``OPENINGS.jsonl`` gets one line per run that opens the cache (the trace gives resumes = lines - 1);
- ``META.json`` binds the directory to its caller's ``binding`` (e.g. the trials digest) and to the code; a different
  one is refused;
- an index line whose file is missing, altered or does not carry its key is an INVALID entry: rejected (counted)
  and recomputed; a truncated LAST index line (interrupted append) is ignored; any other unreadable line is refused;
- leftover ``*.tmp`` files and ``INDEX.jsonl.rewrite`` (interrupted writes) are removed (counted); any ``*.pkl`` without an index line, any other
  file, and any indexed key that is not a key of this build (a foreign cache) are refused.
Results are Python objects returned by the frozen function (pickle, as the trials checkpoint of w1aux.parallel); a
file is unpickled only when its sha256 matches its index line written by this module. No network, no result read.
"""
import contextlib
import dataclasses
import hashlib
import json
import os
import pickle
import resource
import time
from pathlib import Path

from bot.master_v2 import harness
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from w1aux import lazy, ledger
from w1aux import ledger_parallel as lp

INDEX = 'INDEX.jsonl'
META = 'META.json'
OPENINGS = 'OPENINGS.jsonl'          # one line per run that opened the cache: resumes = lines - 1
SCHEMA = 'rugger-w1aux-ledger-resume-v1'
_ACTIVE = {'on': False}
_ORIGINAL = {}
STATS = {}


class LedgerResumeError(RuntimeError):
    pass


def _module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _peak_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def _canonical(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {'__dataclass__': type(value).__module__ + '.' + type(value).__qualname__,
                'fields': {f.name: _canonical(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value, dict):
        if not all(type(k) is str for k in value):
            raise LedgerResumeError('cannot_key_non_string_dict_keys')
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [type(value).__name__, [_canonical(v) for v in value]]
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise LedgerResumeError('cannot_key:' + type(value).__qualname__)


def _describe_call(archive, timeline, params, series, history, indices):
    if not isinstance(archive, hrr.PoolArchive) or getattr(archive, '_sha256', None) is None:
        raise LedgerResumeError('cache_needs_lazy_archives')
    if series is not None and not isinstance(series, sus.SolUsdSeries):
        raise LedgerResumeError('cannot_key_series')
    if history is not None and not isinstance(history, hrr.CreatorHistory):
        raise LedgerResumeError('cannot_key_history')
    timeline_doc = json.dumps(_canonical(timeline), sort_keys=True, separators=(',', ':'))
    return dict(archive=[archive.pool, archive._sha256],
                timeline_sha256=hashlib.sha256(timeline_doc.encode()).hexdigest(),
                params=_canonical(params),
                series=None if series is None else [series.sha256, series.max_age_ms, series.max_confidence_ppm],
                history=None if history is None else [history.sha256, history.label],
                indices=sorted(indices))


def code_identity():
    return dict(ledger_py=lp.LEDGER_SHA256, ledger_resume_py=_module_sha256(), frozen_code=harness.code_fingerprint())


def call_keys(calls):
    """One key per recorded call, in call order; identical calls get distinct keys through their occurrence rank."""
    code, seen, keys = code_identity(), {}, []
    for args, kwargs in calls:
        if kwargs:
            raise LedgerResumeError('unexpected_keyword_arguments')
        base = json.dumps(dict(call=_describe_call(*args), code=code), sort_keys=True, separators=(',', ':'))
        occurrence = seen.get(base, 0)
        seen[base] = occurrence + 1
        keys.append(hashlib.sha256(json.dumps([base, occurrence]).encode()).hexdigest())
    return keys


class Cache:
    def __init__(self, directory, binding):
        self.dir = Path(directory)
        self.meta = dict(schema=SCHEMA, binding=binding, code=code_identity())
        self.entries, self.rejected, self.tmp_removed = {}, 0, 0
        if not self.dir.exists():
            self.dir.mkdir(parents=True)
            self._write_meta()
            self._log_opening()
            return
        meta_path = self.dir / META
        if not meta_path.is_file():
            raise LedgerResumeError('resume_dir_without_meta')
        if json.loads(meta_path.read_text(encoding='utf-8')) != self.meta:
            raise LedgerResumeError('resume_dir_is_for_another_run_or_code')
        index, lines = {}, (self.dir / INDEX).read_text(encoding='utf-8').split('\n') if (self.dir / INDEX).exists() else []
        complete = lines[:-1] if lines and lines[-1] == '' else lines   # a final newline ends the last complete line
        for n, line in enumerate(complete):
            try:
                row = json.loads(line)
                key, sha = row['key'], row['sha256']
            except (ValueError, KeyError, TypeError):
                if n == len(complete) - 1 and not (lines and lines[-1] == ''):
                    continue                                         # an interrupted append: ignored
                raise LedgerResumeError('resume_index_line_unreadable')
            index[key] = sha
        if lines and lines[-1] != '':                               # drop the interrupted tail before appending
            kept = [json.dumps(dict(key=k, sha256=v)) + '\n' for k, v in index.items()]
            tmp = self.dir / (INDEX + '.rewrite')
            with open(tmp, 'w', encoding='utf-8') as handle:
                handle.write(''.join(kept))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.dir / INDEX)
        for path in sorted(self.dir.iterdir()):
            if path.name in (META, INDEX, OPENINGS):
                continue
            if path.suffix == '.tmp' or path.name == INDEX + '.rewrite':
                path.unlink()
                self.tmp_removed += 1
            elif path.suffix != '.pkl' or path.stem not in index:
                raise LedgerResumeError('orphan_file_in_resume_dir:' + path.name)
        self.index = index
        self._log_opening()

    def _log_opening(self):
        with open(self.dir / OPENINGS, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(opened_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                         indexed_entries=len(self.index), tmp_removed=self.tmp_removed)) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        self.openings = sum(1 for line in (self.dir / OPENINGS).read_text(encoding='utf-8').splitlines() if line.strip())

    def _write_meta(self):
        tmp = self.dir / (META + '.tmp')
        tmp.write_text(json.dumps(self.meta, indent=1, sort_keys=True), encoding='utf-8')
        os.replace(tmp, self.dir / META)
        self.index = {}

    def check_keys(self, keys):
        foreign = set(self.index) - set(keys)
        if foreign:
            raise LedgerResumeError('foreign_entry_in_resume_dir:' + sorted(foreign)[0])

    def get(self, key):
        """The stored result, or None when absent or invalid (an invalid entry is counted, then recomputed)."""
        if key not in self.index:
            return None
        path = self.dir / f'{key}.pkl'
        if not path.is_file():
            self.rejected += 1
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.index[key]:
            self.rejected += 1
            return None
        # Resume cache only, not evidence: this run's own directory, written by put() below; a file is unpickled
        # only when its sha256 matches its index line (as the trials checkpoint of w1aux.parallel).
        doc = pickle.loads(data)                                     # noqa: S301
        if not isinstance(doc, dict) or doc.get('key') != key:
            self.rejected += 1
            return None
        return doc['result']

    def put(self, key, result):
        data = pickle.dumps(dict(key=key, result=result), protocol=4)
        sha = hashlib.sha256(data).hexdigest()
        with open(self.dir / INDEX, 'a', encoding='utf-8') as handle:       # index line first: no orphan file
            handle.write(json.dumps(dict(key=key, sha256=sha)) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        tmp = self.dir / f'{key}.tmp'
        with open(tmp, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.dir / f'{key}.pkl')
        self.index[key] = sha


def _resumable_build_ledger(original, cache_dir, binding):
    def build(*args, **kwargs):
        cache = Cache(cache_dir, binding)
        calls = []

        def recorder(*a, **k):
            calls.append((a, k))
            return {}

        ledger.derive_l1_plans = recorder
        try:
            original(*args, **kwargs)                                # probe, discarded
        finally:
            ledger.derive_l1_plans = _ORIGINAL['derive_l1_plans']
        STATS.update(calls=len(calls), recorded_events=sum(len(a[1].events) for a, _k in calls),
                     probe_peak_rss_mb=_peak_mb(), tmp_removed=cache.tmp_removed, resumes=cache.openings - 1)
        keys = call_keys(calls)
        cache.check_keys(keys)
        results = []
        for (a, k), key in zip(calls, keys):
            value = cache.get(key)
            if value is None:
                value = _ORIGINAL['derive_l1_plans'](*a, **k)
                cache.put(key, value)
                STATS['computed'] += 1
            else:
                STATS['reused'] += 1
            results.append(value)
        STATS.update(rejected=cache.rejected, compute_peak_rss_mb=_peak_mb())
        position = iter(range(len(calls)))

        def lookup(*a, **k):
            i = next(position, None)
            if i is None or len(a) != len(calls[i][0]) or k.keys() != calls[i][1].keys() \
                    or not all(lp._same(x, y) for x, y in zip(a, calls[i][0])) \
                    or not all(lp._same(k[name], calls[i][1][name]) for name in k):
                raise LedgerResumeError('ledger_call_differs_from_probe')
            return results[i]

        ledger.derive_l1_plans = lookup
        try:
            out = original(*args, **kwargs)                          # assembly by the v7.4 loop
        finally:
            ledger.derive_l1_plans = _ORIGINAL['derive_l1_plans']
        if next(position, None) is not None:
            raise LedgerResumeError('ledger_calls_not_all_used')
        return out
    return build


@contextlib.contextmanager
def resumable_ledger(cache_dir, binding):
    """Within the block, ledger.build_ledger (and the unchanged ledger.main) resume from ``cache_dir``."""
    if type(binding) is not str or not binding:
        raise LedgerResumeError('binding_required')
    if _ACTIVE['on'] or lp._ACTIVE['on']:
        raise LedgerResumeError('resumable_ledger_is_not_reentrant')
    lp._check_ledger_module()
    _ORIGINAL.update(build_ledger=ledger.build_ledger, derive_l1_plans=ledger.derive_l1_plans)
    _ACTIVE['on'] = True
    STATS.clear()
    STATS.update(calls=0, reused=0, computed=0, rejected=0, tmp_removed=0, resumes=0, recorded_events=0,
                 probe_peak_rss_mb=None, compute_peak_rss_mb=None)
    try:
        with lazy.lazy_archives():
            ledger.build_ledger = _resumable_build_ledger(_ORIGINAL['build_ledger'], cache_dir, binding)
            try:
                yield STATS
            finally:
                ledger.build_ledger = _ORIGINAL['build_ledger']
                ledger.derive_l1_plans = _ORIGINAL['derive_l1_plans']
    finally:
        _ACTIVE['on'] = False
        _ORIGINAL.clear()
