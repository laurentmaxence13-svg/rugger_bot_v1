"""EXPLORATORY ``ledger`` step with the pool-parallel or the resumable ledger (w1x 0.1.4; R02 0c51450f P1, bac856e7 P1-bis).

0.1.4 (R02 bac856e7, P1-bis): ``step --resumable`` runs the same unchanged explore step inside
``w1aux.ledger_resume.resumable_ledger(<root>/ledger_resume, binding=<trials digest>)`` (w1aux v7.6): ONE process, no
fork, no workers guard (the explore step's own memory guard applies, without override); every derive_l1_plans
result is cached on disk, so the same command after a restart resumes. LEDGER_PARALLELE.json then also gives the
calls reused, computed and rejected.


NOT THE OFFICIAL W1 CHAIN AND NEVER THE W1 VERDICT. Runs ONLY after RUGGER 02's audit and explicit PASS.

``explore.py`` is NOT modified: its sha256 is part of the identities checked between steps, so the state written by
the 0.1.2 steps stays valid. This runner calls the UNCHANGED ``w1x.explore.main`` for the ``ledger`` step inside
``w1aux.ledger_parallel.parallel_ledger(workers)`` (w1aux v7.5; ``w1aux/ledger.py`` v7.4 unchanged): the explore
step, its memory guard WITHOUT override, its checks and the hashed ``ledger/`` directory are those of 0.1.2, and
the ledger files are byte-identical to the sequential ones (tested). Before it, a second memory guard for the
workers (no override either): MemAvailable >= 1.5 x (the sequential ledger projection + workers x the projection of
the largest pool), with the ledger's own measured 27 KB per exported signature. Afterwards, outside ``ledger/``,
``LEDGER_PARALLELE.json``: workers, number of derived calls, code sha256, memory, duration (no figure of any result).

``control`` (R02 0a3f59d4, voie i): the parallel ledger of an exploratory root, written ELSEWHERE than ``ledger/`` (a new
directory outside the stamped root), with the same inputs as the explore ledger step, after the same checks of the
earlier steps' outputs and of the code identities; ``compare`` then compares it byte for byte with the 0.1.2
``ledger/`` once that step is done. Nothing of the chain changes; the standard output carries sha256 only.

``prove``: the sequential v7.4 ledger and the parallel one in two fresh processes on any pools/bundles directory
(the pilot), byte comparison, sha256 of both, peak memory of the parent and of the largest worker, durations. The
standard output never carries a P&L, a return, a cycle count or a verdict of the ledger.
"""
import argparse
import hashlib
import io
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from w1aux import dayj, ledger, ledger_parallel, ledger_resume
from w1x import explore

RECORD = 'LEDGER_PARALLELE.json'
SCHEMA = 'rugger-w1x-ledger-parallel-v1'
PROVE_PRINTED = ('identical', 'sequential_sha256', 'parallel_sha256', 'rc_equal', 'workers', 'calls', 'seconds',
                 'peak_rss_mb', 'sequential_peak_rss_mb', 'probe_peak_rss_mb', 'worker_peak_rss_mb', 'recorded_events')
MEASURES = ('probe_peak_rss_mb', 'worker_peak_rss_mb', 'recorded_events')


class LedgerParError(RuntimeError):
    pass


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_sha256():
    return {'w1aux/ledger.py': _sha_file(ledger.__file__), 'w1aux/ledger_parallel.py': _sha_file(ledger_parallel.__file__),
            'w1aux/ledger_resume.py': _sha_file(ledger_resume.__file__),
            'w1x/ledger_par.py': _sha_file(__file__), 'w1x/explore.py': _sha_file(explore.__file__)}


def workers_memory_guard(pools_dir, workers):
    """STOP when the parallel ledger may not fit: the sequential projection plus one largest pool per worker."""
    manifest = json.loads((Path(pools_dir) / 'MANIFEST.json').read_text())
    largest = max((int(e['signatures']) for e in manifest['pools']), default=0)
    sequential = dayj.memory_projection(pools_dir, 'ledger')
    per_worker = dayj.BASE_MB + largest * dayj.KB_PER_SIGNATURE['ledger'] / 1024
    projected = sequential['projected_mb'] + workers * per_worker
    available = dayj._memory_available_mb()
    memory = dict(sequential_projected_mb=sequential['projected_mb'], largest_pool_signatures=largest,
                  per_worker_projected_mb=round(per_worker), workers=workers, projected_mb=round(projected),
                  available_mb=available, margin=dayj.MEMORY_MARGIN,
                  fits=available is not None and available >= dayj.MEMORY_MARGIN * projected)
    if not memory['fits']:
        raise LedgerParError('parallel_ledger_memory_exceeds_available_no_override:' + json.dumps(memory, sort_keys=True))
    return memory


def _peaks():
    me = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
    return dict(parent_mb=me, largest_worker_mb=children)


RESUME_DIR = 'ledger_resume'
RESUME_MEASURES = ('reused', 'computed', 'rejected', 'tmp_removed', 'resumes', 'recorded_events', 'probe_peak_rss_mb',
                   'compute_peak_rss_mb')


def step(workers, explore_argv, *, out=None, resumable=False):
    out = sys.stdout if out is None else out
    if resumable:
        if workers is not None:
            raise LedgerParError('resumable_runs_one_process_without_workers')
    elif type(workers) is not int or workers < 2:
        raise LedgerParError('ledger_workers_must_be_an_integer_of_at_least_2_otherwise_use_explore')
    a = explore.parser().parse_args(explore_argv)
    if a.step != 'ledger':
        raise LedgerParError('this_runner_only_runs_the_ledger_step')
    root = Path(a.out) / explore.STAMP_DIR
    if (root / RECORD).exists():
        raise LedgerParError('ledger_parallel_record_exists')
    started = time.time()
    buffer = io.StringIO()
    if resumable:
        state = json.loads((root / explore.STATE).read_text(encoding='utf-8'))
        trials = (state.get('steps', {}).get('trials') or {}).get('digest')
        if not trials:
            raise LedgerParError('previous_step_not_done:trials')
        memory = None                                                # the explore step's own guard applies
        with ledger_resume.resumable_ledger(root / RESUME_DIR, 'trials:' + trials) as stats:
            code = explore.main(explore_argv, out=buffer)            # the unchanged 0.1.2 step
            calls, measures = stats['calls'], {k: stats[k] for k in RESUME_MEASURES}
    else:
        memory = workers_memory_guard(root / 'pools', workers)
        with ledger_parallel.parallel_ledger(workers) as stats:
            code = explore.main(explore_argv, out=buffer)            # the unchanged 0.1.2 step
            calls, measures = stats['calls'], {k: stats[k] for k in MEASURES}
    record = json.loads(buffer.getvalue())
    doc = dict(stamp=explore.STAMP, schema=SCHEMA, step='ledger', explore_digest=record['digest'], workers=workers,
               mode='resumable_one_process' if resumable else 'parallel', calls=calls, code_sha256=code_sha256(),
               resume_dir=(RESUME_DIR + '/ (outside ledger/; in no step digest, no SHA256SUMS, no reading hash)')
               if resumable else None,
               memory_guard=memory, peaks=_peaks(), **measures,
               seconds=round(time.time() - started, 1), finished_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    (root / RECORD).write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False), encoding='utf-8')
    out.write(buffer.getvalue())
    out.write(json.dumps(dict(ledger_parallel=dict(workers=workers, mode=doc['mode'], calls=calls, peaks=doc['peaks'],
                                                   **measures, record_sha256=_sha_file(root / RECORD))),
                         sort_keys=True) + '\n')
    return code


def _checked_root(root):
    """The exploratory root after trials: earlier outputs unchanged since their step, same code identities."""
    root = Path(root)
    if root.name != explore.STAMP_DIR or not (root / explore.STATE).is_file():
        raise LedgerParError('not_an_exploratory_root')
    state = json.loads((root / explore.STATE).read_text(encoding='utf-8'))
    if state.get('identities') != explore.identities():
        raise LedgerParError('code_identities_differ_from_the_chain')
    for name in explore.STEPS[:explore.STEPS.index('ledger')]:
        record = state['steps'].get(name)
        if record is None:
            raise LedgerParError('previous_step_not_done:' + name)
        for rel, sha in record['outputs'].items():
            if not (root / rel).is_file() or _sha_file(root / rel) != sha:
                raise LedgerParError('output_changed_since_its_step:' + rel)
        if dayj.digest(record['outputs']) != record['digest']:
            raise LedgerParError('state_digest_changed:' + name)
    return root, state


def control(root, workers, out_dir, *, out=None):
    out = sys.stdout if out is None else out
    if type(workers) is not int or workers < 2:
        raise LedgerParError('ledger_workers_must_be_an_integer_of_at_least_2_otherwise_use_explore')
    root, state = _checked_root(root)
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        raise LedgerParError('output_directory_already_exists')
    if root.resolve() == out_dir or root.resolve() in out_dir.parents:
        raise LedgerParError('control_must_be_written_outside_the_exploratory_root')
    memory = workers_memory_guard(root / 'pools', workers)
    out_dir.mkdir(parents=True)
    started, buffer = time.time(), io.StringIO()
    argv = ['--pools', str(root / 'pools'), '--bundles', str(root / 'run' / 'bundles'),
            '--series', str(root / 'sol_usd_series.json.gz'), '--out', str(out_dir / 'ledger')]
    with ledger_parallel.parallel_ledger(workers) as stats:
        code = ledger.main(argv, out=buffer)                         # no report, as the explore ledger step
        calls, measures = stats['calls'], {k: stats[k] for k in MEASURES}
    tree = dayj._hash_tree(out_dir / 'ledger', 'ledger/')
    doc = dict(stamp=explore.STAMP, schema=SCHEMA, kind='control_outside_the_chain', root=str(root),
               trials_digest=state['steps']['trials']['digest'], workers=workers, calls=calls, rc=code,
               ledger_outputs=tree, ledger_digest=dayj.digest(tree), code_sha256=code_sha256(), memory_guard=memory,
               peaks=_peaks(), **measures, seconds=round(time.time() - started, 1),
               finished_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    (out_dir / 'CONTROLE_LEDGER_PARALLELE.json').write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False),
                                                           encoding='utf-8')
    out.write(json.dumps(dict(control_ledger_digest=doc['ledger_digest'], rc=code, workers=workers, calls=calls,
                              peaks=doc['peaks'], seconds=doc['seconds'], **measures), sort_keys=True) + '\n')
    return 0


def compare(root, control_dir, *, out=None):
    """The control ledger against the chain's ledger step, byte for byte (sha256 only on the standard output)."""
    out = sys.stdout if out is None else out
    root, state = _checked_root(root)
    record = state['steps'].get('ledger')
    if record is None:
        raise LedgerParError('the_chain_ledger_step_is_not_done_yet')
    for rel, sha in record['outputs'].items():
        if not (root / rel).is_file() or _sha_file(root / rel) != sha:
            raise LedgerParError('output_changed_since_its_step:' + rel)
    doc = json.loads((Path(control_dir) / 'CONTROLE_LEDGER_PARALLELE.json').read_text(encoding='utf-8'))
    tree = dayj._hash_tree(Path(control_dir) / 'ledger', 'ledger/')
    if tree != doc['ledger_outputs']:
        raise LedgerParError('control_ledger_changed_since_it_was_written')
    identical = tree == record['outputs'] and doc['trials_digest'] == state['steps']['trials']['digest']
    out.write(json.dumps(dict(identical=identical, chain_ledger_digest=record['digest'],
                              control_ledger_digest=dayj.digest(tree)), sort_keys=True) + '\n')
    return 0 if identical else 6


def _one(mode, pools, bundles, series, workers, target):
    """One ledger run in THIS process (called in a fresh subprocess by prove): mode seq (eager v7.4) or par."""
    argv = ['--pools', str(pools), '--bundles', str(bundles), '--out', str(target)]
    if series is not None:
        argv += ['--series', str(series)]
    started, buffer = time.time(), io.StringIO()
    if mode == 'seq':
        code, calls, measures = ledger.main(argv, out=buffer), None, {k: None for k in MEASURES}
    else:
        with ledger_parallel.parallel_ledger(workers) as stats:
            code = ledger.main(argv, out=buffer)
            calls, measures = stats['calls'], {k: stats[k] for k in MEASURES}
    return dict(rc=code, calls=calls, seconds=round(time.time() - started, 1), peaks=_peaks(), **measures,
                summary_sha256=hashlib.sha256(buffer.getvalue().encode()).hexdigest())


def prove(pools, bundles, series, workers, out_dir, *, out=None):
    out = sys.stdout if out is None else out
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise LedgerParError('output_directory_already_exists')
    out_dir.mkdir(parents=True)
    runs = {}
    for mode in ('seq', 'par'):
        cmd = [sys.executable, '-B', '-m', 'w1x.ledger_par', '_one', mode, str(pools), str(bundles),
               '' if series is None else str(series), str(workers), str(out_dir / mode)]
        done = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ))
        if done.returncode != 0:
            raise LedgerParError(f'prove_{mode}_failed:' + done.stderr.strip().splitlines()[-1][:300])
        runs[mode] = json.loads(done.stdout.strip().splitlines()[-1])
    files = ('ledger.json', 'ledger.md')
    sha = {mode: {f: _sha_file(out_dir / mode / f) for f in files} for mode in runs}
    identical = all((out_dir / 'seq' / f).read_bytes() == (out_dir / 'par' / f).read_bytes() for f in files) \
        and runs['seq']['summary_sha256'] == runs['par']['summary_sha256']
    result = dict(identical=identical, sequential_sha256=sha['seq'], parallel_sha256=sha['par'],
                  rc_equal=runs['seq']['rc'] == runs['par']['rc'], workers=workers, calls=runs['par']['calls'],
                  seconds=dict(sequential=runs['seq']['seconds'], parallel=runs['par']['seconds']),
                  peak_rss_mb=runs['par']['peaks'], sequential_peak_rss_mb=runs['seq']['peaks']['parent_mb'],
                  code_sha256=code_sha256(), **{k: runs['par'][k] for k in MEASURES})
    (out_dir / 'PROVE_LEDGER_PARALLELE.json').write_text(json.dumps(result, indent=1, sort_keys=True))
    out.write(json.dumps({k: result[k] for k in PROVE_PRINTED}, sort_keys=True) + '\n')
    return 0 if identical and result['rc_equal'] else 5


def main(argv=None, *, out=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if os.environ.get('RUGGER_NO_DOTENV') != '1':
        raise LedgerParError('set_RUGGER_NO_DOTENV_1')
    if argv[:1] == ['_one']:
        _mode, pools, bundles, series, workers, target = argv[1:7]
        doc = _one(_mode, pools, bundles, series or None, int(workers), target)
        (out or sys.stdout).write(json.dumps(doc, sort_keys=True) + '\n')
        return 0
    p = argparse.ArgumentParser(description='EXPLORATORY W1 ledger step, pool-parallel (NOT the official verdict)')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('step', help='the explore ledger step in parallel; explore arguments after --')
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument('--ledger-workers', type=int)
    g.add_argument('--resumable', action='store_true', help='one process, per-call disk cache (P1-bis)')
    s.add_argument('explore_argv', nargs=argparse.REMAINDER)
    c = sub.add_parser('control', help='voie (i): the parallel ledger of an exploratory root, written outside the chain')
    c.add_argument('--root', type=Path, required=True, help='<out>/PRELIMINAIRE_PAS_LE_VERDICT_OFFICIEL_W1')
    c.add_argument('--ledger-workers', type=int, required=True)
    c.add_argument('--out', type=Path, required=True, help='a new directory OUTSIDE the root')
    k = sub.add_parser('compare', help='the control ledger against the chain ledger step, byte for byte')
    k.add_argument('--root', type=Path, required=True)
    k.add_argument('--control', type=Path, required=True)
    q = sub.add_parser('prove', help='sequential vs parallel ledger on a pools/bundles directory (pilot)')
    q.add_argument('--pools', type=Path, required=True)
    q.add_argument('--bundles', type=Path, required=True)
    q.add_argument('--series', type=Path)
    q.add_argument('--workers', type=int, required=True)
    q.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    if a.command == 'step':
        rest = a.explore_argv[1:] if a.explore_argv[:1] == ['--'] else a.explore_argv
        return step(a.ledger_workers, rest, out=out, resumable=a.resumable)
    if a.command == 'control':
        return control(a.root, a.ledger_workers, a.out, out=out)
    if a.command == 'compare':
        return compare(a.root, a.control, out=out)
    if type(a.workers) is not int or a.workers < 1:
        raise LedgerParError('workers_must_be_a_positive_integer')
    return prove(a.pools, a.bundles, a.series, a.workers, a.out, out=out)


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
