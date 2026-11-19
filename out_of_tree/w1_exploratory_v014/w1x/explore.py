"""EXPLORATORY W1 chain, one step per command: selfcheck -> export -> series -> trials -> ledger -> reading.

THIS IS NOT THE OFFICIAL W1 CHAIN (``w1aux.dayj``) AND IT NEVER GIVES THE W1 VERDICT. It exists because the
frozen ``export`` and ``series`` steps need more memory than the session has; it is run only after the owner's
explicit agreement to read W1 before its official verdict, and after RUGGER 02's audit (method 2ee87535).

What runs, and what does not:
* ``selfcheck``: the day-J selfcheck, unchanged (frozen run_trials on the frozen pack must give 4aee76a3).
* ``export``: the FROZEN ``w1_collection.export`` inside ``stream_export.streaming_export()`` (byte-identical
  pools, tested), after checking the coverage gate anchored by RUGGER 02 (``--gate-json`` and its sha256, which
  must be a PASS on this very window). Then the day-J exclusion count and its 5 % stop.
* ``series``: the FROZEN ``pyth_entries`` and ``sol_usd_series`` inside ``stream_series.streaming_series()``.
* ``trials``: the day-J trials step, UNCHANGED (frozen ``run_trials`` through lazy + parallel, memory guard
  WITHOUT any override, resume as in day J).
* ``ledger``: ``w1aux.ledger`` WITHOUT a report (memory guard without override). No W1 decision exists here.
* ``reading``: ``w1x.reading`` (the closed list of figures fixed by RUGGER 02), on the evaluation range.
* ``evaluate`` and ``dossier`` are REFUSED, and ``w1_run.evaluate`` / ``w1_eval.evaluate_w1`` raise if anything
  calls them while a step runs.

Every output is written under ``<out>/PRELIMINAIRE_PAS_LE_VERDICT_OFFICIEL_W1/``: the pools, the series and the
bundles keep the exact bytes the official chain would write (so that their sha256 can be compared with the
official run later), hence the stamp is carried by the directory, by ``EXPLORATORY_STATE.json``, by
``SHA256SUMS_PRELIMINAIRE.json`` (every output and its sha256, rewritten after each step) and by the reading.
Each step needs ``--expect-sha``, the digest of the previous step. The standard output carries the step, its
digest and technical details only: NEVER a P&L or a return (those are in the reading files only).
Offline; ``RUGGER_NO_DOTENV=1`` required.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

from w1aux import dayj
from w1x import reading, stream_export, stream_series

STEPS = ('selfcheck', 'export', 'series', 'trials', 'ledger', 'reading')
REFUSED = ('gate', 'evaluate', 'dossier')
STATE = 'EXPLORATORY_STATE.json'
STAMP_DIR = 'PRELIMINAIRE_PAS_LE_VERDICT_OFFICIEL_W1'
STAMP = reading.STAMP
SUMS = 'SHA256SUMS_PRELIMINAIRE.json'
SCHEMA = 'rugger-w1-exploratory-v1'
NEEDS = dict(export=('window_dir', 'pilot_dir', 'gate_json', 'gate_json_sha256'), series=('sol_usd_dir', 'study_report'))
PRINTED = ('workers', 'stats', 'memory', 'exclusions', 'series_sha256', 'points', 'entries', 'verdict',
           'sha256sums_sha256', 'memory_available_mb', 'registered_at', 'checkpoint_index_sha256', 'resumed')


class ExploreError(RuntimeError):
    pass


def _refuse_evaluate(*_args, **_kwargs):
    raise ExploreError('evaluate_is_refused_this_is_not_the_official_w1_chain')


@contextlib.contextmanager
def _guards():
    """While a step runs: dayj saves its state under OUR name, and the W1 evaluation cannot be called."""
    from bot.master_v2 import w1_eval, w1_run
    saved = dayj.STATE, w1_run.evaluate, w1_eval.evaluate_w1
    dayj.STATE, w1_run.evaluate, w1_eval.evaluate_w1 = STATE, _refuse_evaluate, _refuse_evaluate
    try:
        yield
    finally:
        dayj.STATE, w1_run.evaluate, w1_eval.evaluate_w1 = saved


def identities():
    """The day-J identities (frozen tree, anchored code, CPython 3.12) plus the sha256 of this package."""
    here = Path(__file__).parent
    return dict(dayj.identities(), w1x={name: dayj._sha_file(here / name) for name in (
        'explore.py', 'reading.py', 'stream_export.py', 'stream_series.py')})


def _check_previous(root, state, step, expect_sha):
    order = STEPS.index(step)
    for earlier in STEPS[:order]:
        record = state['steps'].get(earlier)
        if record is None:
            raise ExploreError(f'previous_step_not_done:{earlier}')
        for rel, sha in record['outputs'].items():
            path = root / rel
            if not path.is_file() or dayj._sha_file(path) != sha:
                raise ExploreError(f'output_changed_since_its_step:{rel}')
        if dayj.digest(record['outputs']) != record['digest']:
            raise ExploreError(f'state_digest_changed:{earlier}')
    if step in state['steps']:
        raise ExploreError(f'step_already_done:{step}')
    if order:
        previous = STEPS[order - 1]
        if expect_sha is None:
            raise ExploreError(f'{step}_needs:--expect-sha (digest of {previous})')
        if expect_sha != state['steps'][previous]['digest']:
            raise ExploreError(f'expect_sha_is_not_the_digest_of:{previous}')


def _check_gate(a):
    """The coverage gate anchored by RUGGER 02 must be a PASS on this very LaunchLab window."""
    if dayj._sha_file(a.gate_json) != a.gate_json_sha256:
        raise ExploreError('gate_json_is_not_the_anchored_one')
    gate = json.loads(Path(a.gate_json).read_text())
    verify = gate.get('launchlab_verify') or {}
    if (gate.get('coverage_compare') or {}).get('verdict') != 'PASS' or not (verify.get('ok') and verify.get('complete')):
        raise ExploreError('gate_is_not_a_pass')
    if gate.get('launchlab_manifest_sha256') != dayj._sha_file(Path(a.window_dir) / 'manifest.json'):
        raise ExploreError('gate_is_for_another_launchlab_window')
    return dict(gate_json_sha256=a.gate_json_sha256, launchlab_manifest_sha256=gate['launchlab_manifest_sha256'])


def _run_step(step, a, root, state):
    """Run one step; return (outputs: relative path -> sha256, details without any P&L figure)."""
    if step in ('selfcheck', 'trials'):
        return dayj._run_step(step, a, root, state)                   # the day-J step, unchanged
    if step == 'export':
        gate = _check_gate(a)
        with stream_export.streaming_export(workers=1):
            outputs, details = dayj._run_step('export', a, root, state)
        return outputs, dict(details, gate=gate, streaming_export=True)
    if step == 'series':
        from bot.market import backfill as bf
        checked = bf.verify(a.sol_usd_dir)                            # frozen verification, on the full rows
        with stream_series.streaming_series():
            if bf.verify(a.sol_usd_dir) != checked:
                raise ExploreError('sol_usd_verification_differs_on_slim_rows')
            outputs, details = dayj._run_step('series', a, root, state)
        return outputs, dict(details, streaming_series=True, sol_usd_manifest_sha256=checked['manifest_sha256'])
    if step == 'ledger':
        from w1aux import ledger
        dayj._fresh(root / 'ledger')
        memory = dayj.memory_guard('ledger', root / 'pools', None)    # no override, ever
        buffer = io.StringIO()
        code = ledger.main(['--pools', str(root / 'pools'), '--bundles', str(root / 'run' / 'bundles'),
                            '--series', str(root / 'sol_usd_series.json.gz'), '--out', str(root / 'ledger')], out=buffer)
        summary = json.loads(buffer.getvalue())
        if code != 0 or summary.get('verdict') != 'PASS':
            raise ExploreError('ledger_verdict_not_pass')
        if json.loads((root / 'ledger' / 'ledger.json').read_text()).get('w1_report') is not None:
            raise ExploreError('ledger_quotes_a_w1_report')
        return dayj._hash_tree(root / 'ledger', 'ledger/'), dict(verdict='PASS', mismatches=summary.get('mismatches'),
                                                                   memory=memory, report=None)
    if step == 'reading':
        from bot.market import w1_collection
        start, end = w1_collection.bounds(a.s0)['evaluation']
        reading.run(root / 'ledger' / 'ledger.json', root / 'run' / 'bundles' / 'L1.json.gz', root / 'lecture',
                    evaluation_min=start, evaluation_max=end)
        return dayj._hash_tree(root / 'lecture', 'lecture/'), dict(evaluation_min=start, evaluation_max=end)
    raise ExploreError('unknown_step:' + step)


def _write_sums(root, state):
    doc = dict(stamp=STAMP, schema=SCHEMA, digests={s: r['digest'] for s, r in state['steps'].items()},
               outputs={rel: sha for record in state['steps'].values() for rel, sha in record['outputs'].items()})
    (root / SUMS).write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False), encoding='utf-8')


def run_step(step, a):
    if step in REFUSED:
        raise ExploreError(f'{step}_is_refused_this_is_not_the_official_w1_chain')
    if os.environ.get('RUGGER_NO_DOTENV') != '1':
        raise ExploreError('set_RUGGER_NO_DOTENV_1')
    missing = [k for k in NEEDS.get(step, ()) if getattr(a, k) is None]
    if missing:
        raise ExploreError(f'{step}_needs:' + ','.join('--' + k.replace('_', '-') for k in missing))
    if type(a.workers) is not int or a.workers < 1:
        raise ExploreError('workers_must_be_a_positive_integer')
    a.memory_override_anchored = None                                 # the memory guard is never overridden here
    root = Path(a.out) / STAMP_DIR
    if (Path(a.out) / dayj.STATE).exists() or (root / dayj.STATE).exists():
        raise ExploreError('out_is_a_day_j_directory_use_a_separate_one')
    root.mkdir(parents=True, exist_ok=True)
    with _guards():
        state = dayj._load_state(root)
        state.setdefault('stamp', STAMP)
        state['schema'] = SCHEMA
        ids = identities()
        if state.get('identities') not in (None, ids):
            raise ExploreError('code_identities_changed_between_steps')
        if state.get('s0') not in (None, a.s0):
            raise ExploreError('s0_changed_between_steps')
        _check_previous(root, state, step, a.expect_sha)
        state.update(identities=ids, s0=a.s0)
        started = time.time()
        outputs, details = _run_step(step, a, root, state)
        state['steps'][step] = dict(outputs=outputs, digest=dayj.digest(outputs), details=details,
                                    seconds=round(time.time() - started, 1),
                                    finished_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        dayj._save_state(root, state)
        _write_sums(root, state)
    return state['steps'][step]


def parser():
    p = argparse.ArgumentParser(description='EXPLORATORY W1 chain, one step per command (NOT the official verdict)')
    p.add_argument('--step', required=True, choices=STEPS + REFUSED)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--s0', required=True, type=int)
    p.add_argument('--expect-sha', help='digest of the previous step')
    p.add_argument('--workers', type=int, default=4, help='selfcheck/trials: processes (parallel_replays)')
    p.add_argument('--window-dir', type=Path, help='export: the LaunchLab W1 collection run')
    p.add_argument('--pilot-dir', type=Path, help='export: the pilot run (cap rule)')
    p.add_argument('--other-run', type=Path, action='append', help='export: other runs of the month (cap rule)')
    p.add_argument('--gate-json', type=Path, help='export: GATE.json of the official day-J gate step')
    p.add_argument('--gate-json-sha256', help='export: its sha256, as anchored by RUGGER 02')
    p.add_argument('--sol-usd-dir', type=Path, help='series: the SOL/USD W1 collection run')
    p.add_argument('--study-report', type=Path, help='series: the anchored age study report (e3d92847)')
    p.add_argument('--checkpoint', type=Path, help='trials: resume directory (default <root>/checkpoint)')
    p.add_argument('--resume', action='store_true', help='trials: resume after an interruption, as in day J')
    return p


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    a = parser().parse_args(argv)
    record = run_step(a.step, a)
    shown = {k: v for k, v in record['details'].items() if k in PRINTED}
    out.write(json.dumps(dict(stamp=STAMP, step=a.step, digest=record['digest'], seconds=record['seconds'],
                              details=shown), sort_keys=True, default=str, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
