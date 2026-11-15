"""Identity proofs of the two streaming steps on REAL, already opened data (run by RUGGER 03, checked by RUGGER 02).

    python -B -m w1x.prove export --window-dir RUN --out NEW_DIR [--buckets N]
    python -B -m w1x.prove series --run-dir PYTH_RUN --study-report REPORT --out NEW_DIR

Each command runs the FROZEN function and the streaming one on the same verified run, each in its own child
process, then compares every file written, byte for byte. It prints one JSON line: ``identical``, the sha256 of
every file of both trees, the peak memory (MB) and the seconds of each child. No outcome, no return: an export
and a price series only. For the streaming child, ``phases`` gives the peak memory reached at the end of each
phase (a running maximum: the phase where it rises is the one that dominates). Run it from a fresh process: a
forked child starts with the memory of its parent.

* ``export``: frozen ``backfill_export.export_pools`` against ``stream_export.export_pools`` (default options).
  Meant for the W1 pilot and an opened P0 pack (the frozen one needs the memory of the whole run).
* ``series``: frozen ``w1_run.sol_usd_series`` on every transaction row of the run, against the same frozen
  function inside ``stream_series.streaming_series()``. ``w1_run.pyth_entries`` is not used here because it only
  accepts the W1 window (its use on slim rows is covered by the tests of this package); the run must verify.
``RUGGER_NO_DOTENV=1`` required. Offline.
"""
import argparse
import hashlib
import json
import multiprocessing
import os
import resource
import sys
import time
from pathlib import Path


class ProveError(RuntimeError):
    pass


def _tree(path):
    path = Path(path)
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob('*')) if p.is_file()}


def _peak_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _export(kind, window_dir, out, buckets):
    from bot.market import backfill_export as bx
    from w1x import stream_export
    if kind == 'frozen':
        bx.export_pools(window_dir, out)
        return None
    phases = dict(start=_peak_mb())

    def marked(name, function):                        # same call, then the peak memory reached so far
        def call(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            finally:
                phases[name] = _peak_mb()
        return call
    names = dict(verify='verify', _first_pass='first_pass', _second_pass='second_pass', _export_bucket='third_pass')
    saved = {name: getattr(stream_export, name) for name in names}
    for name, phase in names.items():
        setattr(stream_export, name, marked(phase, saved[name]))
    try:
        stream_export.export_pools(window_dir, out, **({} if buckets is None else dict(buckets=buckets)))
    finally:
        for name, function in saved.items():
            setattr(stream_export, name, function)
    return phases


def _series(kind, run_dir, study_report, out):
    from bot.market import backfill as bf
    from bot.master_v2 import w1_run
    from w1x import stream_series
    checked = bf.verify(run_dir)
    if not checked['ok']:
        raise ProveError('run_does_not_verify:' + ','.join(checked['problems']))
    manifest = json.loads((Path(run_dir) / 'manifest.json').read_text())
    sha = hashlib.sha256(Path(study_report).read_bytes()).hexdigest()

    def rows():
        return [row for seg in manifest['segments'] if seg['kind'] == 'tx'
                for row in bf.read_segment(Path(run_dir) / seg['path'])]
    Path(out).mkdir(parents=True)
    if kind == 'frozen':
        w1_run.sol_usd_series(rows(), study_report, sha, Path(out) / 'sol_usd_series.json.gz')
        return None
    phases = dict(verify=_peak_mb())
    with stream_series.streaming_series():
        slim = rows()
        phases['slim_rows'] = _peak_mb()
        w1_run.sol_usd_series(slim, study_report, sha, Path(out) / 'sol_usd_series.json.gz')
    phases['series'] = _peak_mb()
    return dict(phases, rows=len(slim), tx_segments=sum(seg['kind'] == 'tx' for seg in manifest['segments']))


def _child(queue, function, args):
    started, phases = time.time(), None
    try:
        phases = function(*args)
        error = None
    except Exception as exc:                               # reported, compared, never hidden
        error = f'{type(exc).__name__}:{exc}'
    queue.put(dict(error=error, seconds=round(time.time() - started, 1), peak_mb=_peak_mb(), phases=phases))


def _both(function, args_of, out):
    out = Path(out)
    if out.exists():
        raise ProveError('output_exists')
    result = {}
    context = multiprocessing.get_context('fork')
    for kind in ('frozen', 'stream'):
        queue = context.Queue()
        process = context.Process(target=_child, args=(queue, function, args_of(kind, out / kind)))
        process.start()
        result[kind] = queue.get()
        process.join()
        result[kind]['files'] = _tree(out / kind) if (out / kind).exists() else {}
    identical = (result['frozen']['error'] is None and result['stream']['error'] is None
                 and bool(result['frozen']['files']) and result['frozen']['files'] == result['stream']['files'])
    return dict(identical=identical, frozen=result['frozen'], stream=result['stream'])


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description='Byte identity of a streaming step with the frozen one, on opened data')
    sub = parser.add_subparsers(dest='what', required=True)
    export = sub.add_parser('export')
    export.add_argument('--window-dir', type=Path, required=True)
    export.add_argument('--buckets', type=int)
    series = sub.add_parser('series')
    series.add_argument('--run-dir', type=Path, required=True)
    series.add_argument('--study-report', type=Path, required=True)
    for p in (export, series):
        p.add_argument('--out', type=Path, required=True, help='new directory: frozen/ and stream/ are written in it')
    a = parser.parse_args(argv)
    if os.environ.get('RUGGER_NO_DOTENV') != '1':
        raise ProveError('set_RUGGER_NO_DOTENV_1')
    if a.what == 'export':
        doc = _both(_export, lambda kind, target: (kind, a.window_dir, target, a.buckets), a.out)
    else:
        doc = _both(_series, lambda kind, target: (kind, a.run_dir, a.study_report, target), a.out)
    out.write(json.dumps(dict(what=a.what, **doc), sort_keys=True) + '\n')
    return 0 if doc['identical'] else 1


if __name__ == '__main__':                                  # pragma: no cover
    raise SystemExit(main())
