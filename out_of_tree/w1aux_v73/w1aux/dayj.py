"""W1 day J: the post-collection chain, ONE step per command, each gated by RUGGER 02's anchor.

The frozen tree has no command that chains the W1 steps after the collection: ``w1_run`` and
``w1_collection`` are libraries. This module only CALLS them, in the protocol order, with the
anchored w1aux tools around them. It implements no rule, computes and prints no economic figure,
and the W1 decision stays evaluate_w1's.

Steps (R02 dayj requirements E1-E9), each run alone; every step after ``selfcheck`` needs
``--expect-sha`` = the digest of the previous step, as anchored by RUGGER 02 after his reading:
  selfcheck  machine check BEFORE any W1 data: CPython 3.12 only, tree aff97638, anchored code,
             run_trials on the frozen pack (lazy + parallel) -> SHA256SUMS sha must be 4aee76a3
  gate       data acceptance: backfill.verify ok + complete (no cap stop) on the LaunchLab run,
             coverage compare PASS against the anchored fetch summary, owner's AFTER reading recorded
  export     w1_collection.export, then pools excluded by reason (> 5 % for data defects: STOP)
  series     w1_run.pyth_entries + w1_run.sol_usd_series with the anchored age study report
  trials     w1_run.run_trials in lazy_archives() + parallel_replays (registered_at = launch time)
  evaluate   w1_run.evaluate (trial documents rebuilt from the saved bundles)
  ledger     w1aux.ledger with the replayed series (R-1); verdict PASS required
  dossier    DOSSIER_W1.json: identities, steps, digests, file hashes; cycle_receipt PENDING_R02
A step digest is the sha256 of its outputs (relative path -> sha256, canonical JSON). Every earlier
output is re-hashed before a step; a step runs once and never overwrites. Offline, no secret read,
RUGGER_NO_DOTENV=1. Research only (HISTORICAL_REPLAY), never an operational Master trade.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

STEPS = ('selfcheck', 'gate', 'export', 'series', 'trials', 'evaluate', 'ledger', 'dossier')
STATE = 'DAYJ_STATE.json'
FROZEN_TREE = 'aff97638cd011bcc3dc2b2826d42a208eb855aed'
FROZEN = dict(collector_code='9c69e4822b3dbe573ce91a2e25258c4cf48cd486bd85e057efe6f4feda159f8e',
              w1_run_py='b5ccc3182e2421360d5e7c3d3c3bcdd0f41d146163d6e48dd9c2a035152f0ab3',
              code_fingerprint='682447fd534dc632765886f664c56c2d8f46ff6e6a86286854209cae8679593e')
W1AUX_ANCHORED = {                                                   # MANIFEST_v61 a0b31d03 (R02 ce7ef0ed)
    'coverage.py': '78bb75fefc4ef3cab2f67a6715479af592d28c92f5a698c9427d6782266df14d',
    'lazy.py': '0403358aec2954dba9211968d53385f2752bf7a41a7414855a3fae7e2da3ad52',
    'ledger.py': '115f3cb59dcb5db61f46bda73858a7395e13b862e0b3ab3ba5768cc8d7591b61',             # v7.2: bundles read one at a time
    'parallel.py': 'b29abd6603ed0ec4ef1bdf23e985ef25dd9cbe9b8404bf4b182436dbf2de4563',           # v7.2: gc.freeze before fork
}
PYTHONS = ((3, 12),)       # 3.11 differs: 3.12 sum() of floats is compensated (features_sha256 differ)
FROZEN_PACK = Path('tests/fixtures/launchlab_sol_pools')
SELFCHECK_SUMS_SHA256 = '4aee76a3573344b37646202441c8b57c9fad0492d0674145691252dafbe85149'   # R02 v6.1 audit
SELFCHECK_REGISTERED_AT = '2026-11-09T00:00:00+00:00'
EXCLUDED_MAX_SHARE = 0.05                                            # protocol stop_conditions
# Memory per step (R02 M-2a): MemAvailable drop (trials: parent + 4 forked workers) or process peak (evaluate,
# ledger), measured on the synthetic packs x20 / x40 (KB per exported signature: 24.6, 54, 25.7), rounded up.
KB_PER_SIGNATURE = dict(trials=26, evaluate=56, ledger=27)
BASE_MB = 150                  # interpreter, frozen modules and fixed buffers (measured 6 to 85 MB)
MEMORY_MARGIN = 1.5            # R02 condition: available memory >= 1.5 x the projection
N_FOR_DSR = 32                 # protocol: 25 P0 trials + 7 W1 trials (R02 D-2)
OTHER_REGISTRIES_SHA256 = ('f1f26e366bec2cdc3093bf027617d453d6d7dfbdd4b721173c290433004f47de',)   # P0 registry, 25 trials, anchored by R02 (96865df7)
_FIRST_SLOT, _FIRST_TIME = 464661843, 1793658217


class DayJError(RuntimeError):
    pass


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _hash_tree(root, prefix, exclude=()):
    root = Path(root)
    return {prefix + p.relative_to(root).as_posix(): _sha_file(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not any(part in exclude for part in p.relative_to(root).parts)}


def digest(outputs):
    return hashlib.sha256(json.dumps(outputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _git(*args):
    try:
        return subprocess.run(['git', *args], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DayJError('git_unavailable_in_the_frozen_checkout') from exc


def identities():
    """Fingerprints of the code that runs; anything but the anchored ones is refused."""
    from bot.market import w1_collection
    from bot.master_v2 import harness
    from bot.master_v2 import w1_run
    if sys.version_info[:2] not in PYTHONS or platform.python_implementation() != 'CPython':
        raise DayJError('python_must_be_cpython_3_12')
    tree = _git('rev-parse', 'HEAD^{tree}').strip()
    if tree != FROZEN_TREE:
        raise DayJError('checkout_is_not_the_frozen_tree:' + tree)
    if _git('status', '--porcelain', '--untracked-files=no').strip():
        raise DayJError('frozen_checkout_has_modified_tracked_files')
    got = dict(collector_code=w1_collection.collector_code()['sha256'], w1_run_py=_sha_file(w1_run.__file__),
               code_fingerprint=harness.code_fingerprint())
    if got != FROZEN:
        raise DayJError('frozen_code_is_not_the_anchored_one:' + ','.join(k for k in FROZEN if got[k] != FROZEN[k]))
    here = Path(__file__).parent
    w1aux = {name: _sha_file(here / name) for name in W1AUX_ANCHORED}
    if w1aux != W1AUX_ANCHORED:
        raise DayJError('w1aux_module_is_not_the_anchored_one:' + ','.join(
            k for k in W1AUX_ANCHORED if w1aux[k] != W1AUX_ANCHORED[k]))
    return dict(frozen=got, git_tree=tree, w1aux=w1aux, dayj_py=_sha_file(__file__),
                python=platform.python_version(), implementation=platform.python_implementation(),
                machine=platform.machine(), system=platform.system())


def _load_state(out):
    path = Path(out) / STATE
    return json.loads(path.read_text()) if path.exists() else dict(schema='rugger-w1-dayj-v2', steps={})


def _save_state(out, state):
    path = Path(out) / STATE
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, path)


def _check_previous(out, state, step, expect_sha):
    order = STEPS.index(step)
    for earlier in STEPS[:order]:
        record = state['steps'].get(earlier)
        if record is None:
            raise DayJError(f'previous_step_not_done:{earlier}')
        for rel, sha in record['outputs'].items():
            path = Path(out) / rel
            if not path.is_file() or _sha_file(path) != sha:
                raise DayJError(f'output_changed_since_its_step:{rel}')
        if digest(record['outputs']) != record['digest']:
            raise DayJError(f'state_digest_changed:{earlier}')
    if step in state['steps']:
        raise DayJError(f'step_already_done:{step}')
    if order:
        previous = STEPS[order - 1]
        if expect_sha is None:
            raise DayJError(f'{step}_needs:--expect-sha (anchored digest of {previous})')
        if expect_sha != state['steps'][previous]['digest']:
            raise DayJError(f'expect_sha_is_not_the_digest_of:{previous}')


def _p(out, *parts):
    return Path(out).joinpath(*parts)


def _fresh(*paths):
    for path in paths:
        if Path(path).exists():
            raise DayJError('output_exists:' + Path(path).name)


def _cgroup_headroom_mb():
    """Limit minus usage of this process's memory cgroup (v1 or v2), or None when unlimited (R02 G-1)."""
    try:
        for line in Path('/proc/self/cgroup').read_text().splitlines():
            hierarchy, controllers, path = line.split(':', 2)
            if 'memory' in controllers.split(','):
                base = Path('/sys/fs/cgroup/memory') / path.lstrip('/')
                limit, usage = base / 'memory.limit_in_bytes', base / 'memory.usage_in_bytes'
                break
            if hierarchy == '0' and controllers == '':
                base = Path('/sys/fs/cgroup') / path.lstrip('/')
                limit, usage = base / 'memory.max', base / 'memory.current'
        else:
            return None
        text = limit.read_text().strip()
        if text == 'max' or int(text) >= 1 << 60:
            return None
        return (int(text) - int(usage.read_text().strip())) // (1024 * 1024)
    except (OSError, ValueError, UnboundLocalError):
        return None


def _memory_available_mb():
    """min(MemAvailable, cgroup limit - cgroup usage): the memory this process can really use (R02 G-1)."""
    available = None
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1]) // 1024
    except OSError:
        pass
    headroom = _cgroup_headroom_mb()
    if headroom is not None:
        available = headroom if available is None else min(available, headroom)
    return available


def _selfcheck_series(path):
    from bot.p4 import sol_usd_series as sus
    point = dict(schema=sus.POINT_SCHEMA, slot=_FIRST_SLOT - 50, transaction_index=0, block_time=_FIRST_TIME - 12,
                 received_at_ms=None, publish_time=_FIRST_TIME - 13, price=15_000_000_000, exponent=-8,
                 confidence=7_500_000, source_kind='pyth_onchain_account', source_ref='synthetic-test-account',
                 evidence_sha256='0' * 64, signature=None)
    path.write_text(json.dumps(dict(schema=sus.SERIES_SCHEMA, label='COLLECTED', points=[point],
                                    acceptance=dict(max_age_ms=120_000, max_confidence_ppm=1_000))))


@contextlib.contextmanager
def slim_l1_trial_documents():
    """run_trials keeps the L1 trial documents (journals of whole bundles) only to compare their
    bundle_sha256 with its re-runs. Within the block, the frozen w1_eval.run_l1_* still build and
    validate them, then only bundle_sha256 is kept: same outputs (tested), less memory (R01 T-1)."""
    from bot.master_v2 import w1_eval
    names = ('run_l1_trials', 'run_l1_sensitivity', 'run_l1_descriptive')
    original = {name: getattr(w1_eval, name) for name in names}

    def keep(doc):
        return dict(bundle_sha256=doc['bundle_sha256'])
    w1_eval.run_l1_trials = lambda *a, **k: {t: keep(d) for t, d in original['run_l1_trials'](*a, **k).items()}
    w1_eval.run_l1_sensitivity = lambda *a, **k: keep(original['run_l1_sensitivity'](*a, **k))
    w1_eval.run_l1_descriptive = lambda *a, **k: {t: keep(d) for t, d in original['run_l1_descriptive'](*a, **k).items()}
    try:
        yield
    finally:
        for name, function in original.items():
            setattr(w1_eval, name, function)


def memory_projection(pools_dir, step='trials'):
    """Memory of step projected from the exported signatures (a count, no outcome), against MemAvailable."""
    manifest = json.loads((Path(pools_dir) / 'MANIFEST.json').read_text())
    signatures = sum(int(entry['signatures']) for entry in manifest['pools'])
    projected = BASE_MB + signatures * KB_PER_SIGNATURE[step] / 1024
    available = _memory_available_mb()
    return dict(step=step, signatures=signatures, kb_per_signature=KB_PER_SIGNATURE[step],
                projected_mb=round(projected), available_mb=available, margin=MEMORY_MARGIN,
                fits=available is not None and available >= MEMORY_MARGIN * projected)


def memory_guard(step, pools_dir, override):
    """STOP before a step whose projected memory does not fit (owner decision on a larger machine)."""
    memory = memory_projection(pools_dir, step)
    if not memory['fits'] and not override:
        raise DayJError('memory_projection_exceeds_available_owner_decision_needed:' + json.dumps(memory, sort_keys=True))
    return memory


def _trials(run, pools, series_path, out_dir, reg, sens, registered_at, workers, checkpoint):
    from w1aux import lazy, parallel
    before = dict(parallel.STATS)
    with lazy.lazy_archives(), parallel.parallel_replays(workers, checkpoint), slim_l1_trial_documents():
        sums = run.run_trials(pools, series_path, registry_path=reg, sensitivity_registry_path=sens,
                              registered_at=registered_at, out=out_dir)
    index = Path(checkpoint) / parallel.INDEX
    return sums, {k: parallel.STATS[k] - before[k] for k in before}, (_sha_file(index) if index.exists() else None)


def exclusions(pools_dir):
    """Pools the replay would exclude, by reason (frozen summarize + usable_timeline, no outcome read)."""
    from bot.market.collector import summarize
    from bot.p4 import historical_research_replay as hrr
    from w1aux import lazy
    by_reason, excluded, total = {}, 0, 0
    with lazy.lazy_archives():
        for _entry, archive in hrr.load_fixtures(pools_dir)[2]:
            total += 1
            summary, timeline = summarize(archive)
            try:
                hrr.usable_timeline(archive, summary, timeline)
            except hrr.PoolExcluded as exc:
                excluded += 1
                for reason in exc.reasons:
                    key = reason.split(':')[0]
                    by_reason[key] = by_reason.get(key, 0) + 1
    share = excluded / total if total else 1.0
    return dict(pools=total, excluded=excluded, share=share, by_reason=dict(sorted(by_reason.items())),
                max_share=EXCLUDED_MAX_SHARE, stop=share > EXCLUDED_MAX_SHARE)


def _run_step(step, a, out, state):
    """Run one step; return (outputs: relative path -> sha256, details without any P&L figure)."""
    from bot.master_v2 import w1_run as run
    if step == 'selfcheck':
        work = _p(out, 'selfcheck')
        _fresh(work)
        work.mkdir()
        _selfcheck_series(work / 'series.json')
        sums, stats, _index = _trials(run, FROZEN_PACK, work / 'series.json', work / 'run', work / 'r.jsonl',
                                      work / 's.jsonl', SELFCHECK_REGISTERED_AT, a.workers, work / 'checkpoint')
        got = _sha_file(work / 'run' / 'bundles' / 'SHA256SUMS.json')
        if got != SELFCHECK_SUMS_SHA256:
            raise DayJError('selfcheck_bundles_differ_from_the_reference:' + got)
        doc = dict(identities=state['identities'], sha256sums_sha256=got, workers=a.workers, stats=stats,
                   cpu_count=os.cpu_count(), memory_available_mb=_memory_available_mb())
        (out / 'SELFCHECK.json').write_text(json.dumps(doc, indent=1, sort_keys=True))
        return {'SELFCHECK.json': _sha_file(out / 'SELFCHECK.json')}, doc
    if step == 'gate':
        from bot.market import backfill as bf
        from w1aux import coverage
        _fresh(_p(out, 'GATE.json'))
        checked = bf.verify(a.window_dir)
        manifest = json.loads((Path(a.window_dir) / 'manifest.json').read_text())
        if not (checked['ok'] and checked['complete'] and manifest['complete']):
            raise DayJError('launchlab_run_not_verified_or_incomplete:' + ','.join(checked['problems']))
        buffer = io.StringIO()
        code = coverage.main(['compare', '--summary', str(a.coverage_summary), '--summary-sha256', a.summary_sha256,
                              '--run', str(a.window_dir)], out=buffer)
        result = json.loads(buffer.getvalue().strip().splitlines()[-1])
        if code != 0 or result.get('verdict') != 'PASS':
            raise DayJError('coverage_compare_not_pass')
        reading = Path(a.after_reading)
        doc = dict(launchlab_verify=dict(ok=checked['ok'], complete=checked['complete'], problems=checked['problems']),
                   launchlab_manifest_sha256=_sha_file(Path(a.window_dir) / 'manifest.json'),
                   coverage_compare=result, owner_after_reading=dict(file=reading.name, sha256=_sha_file(reading),
                                                                     content=json.loads(reading.read_text())),
                   note='the owner reading is recorded, not judged: RUGGER 02 checks real = counted - s')
        (out / 'GATE.json').write_text(json.dumps(doc, indent=1, sort_keys=True))
        return {'GATE.json': _sha_file(out / 'GATE.json')}, dict(compare='PASS', verify='ok')
    if step == 'export':
        from bot.market import w1_collection
        _fresh(_p(out, 'pools'), _p(out, 'EXCLUSIONS.json'))
        result = w1_collection.export(a.window_dir, _p(out, 'pools'), a.s0, pilot_dir=a.pilot_dir,
                                      other_runs=tuple(a.other_run or ()))
        excl = exclusions(_p(out, 'pools'))
        (out / 'EXCLUSIONS.json').write_text(json.dumps(excl, indent=1, sort_keys=True))
        if excl['stop']:
            raise DayJError('stop_more_than_5_percent_of_pools_excluded_for_data_defects')
        outputs = _hash_tree(_p(out, 'pools'), 'pools/')
        outputs['EXCLUSIONS.json'] = _sha_file(out / 'EXCLUSIONS.json')
        return outputs, dict(export=result, exclusions=excl)
    if step == 'series':
        target = _p(out, 'sol_usd_series.json.gz')
        _fresh(target)
        entries = run.pyth_entries(a.sol_usd_dir, a.s0)
        series = run.sol_usd_series(entries, a.study_report, _sha_file(a.study_report), target)
        names = (target.name, target.name + '.decoding.json')
        return {n: _sha_file(_p(out, n)) for n in names}, dict(series_sha256=series.sha256, points=len(series.points),
                                                              entries=len(entries))
    if step == 'trials':
        reg, sens = _p(out, 'registry_w1.jsonl'), _p(out, 'registry_sensitivity.jsonl')
        memory = memory_guard('trials', _p(out, 'pools'), a.memory_override_anchored)
        quarantined = []
        if a.resume:                                                  # R02 D-1: same registered_at, nothing deleted
            started = state.get('trials_started')
            if started is None:
                raise DayJError('resume_without_trials_started')
            registered_at, checkpoint = started['registered_at'], Path(started['checkpoint'])
            target = _p(out, 'quarantine', time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
            for path in (_p(out, 'run'), reg, sens):
                if path.exists():
                    target.mkdir(parents=True, exist_ok=True)
                    hashes = _hash_tree(path, path.name + '/') if path.is_dir() else {path.name: _sha_file(path)}
                    os.replace(path, target / path.name)
                    quarantined.append(dict(path=path.name, to=target.relative_to(out).as_posix(), sha256=hashes))
            state.setdefault('trials_resumes', []).append(dict(at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                                               workers=a.workers, quarantined=quarantined))
        else:
            _fresh(_p(out, 'run'), reg, sens)
            if state.get('trials_started') is not None:
                raise DayJError('trials_already_started_use_resume')
            checkpoint = Path(a.checkpoint) if a.checkpoint else _p(out, 'checkpoint')
            registered_at = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())     # real launch time (E6)
        if not a.resume:
            state['trials_started'] = dict(registered_at=registered_at, checkpoint=str(checkpoint), workers=a.workers,
                                           started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        _save_state(out, state)                                       # recorded BEFORE run_trials (R02 D-1)
        sums, stats, index = _trials(run, _p(out, 'pools'), _p(out, 'sol_usd_series.json.gz'), _p(out, 'run'),
                                     reg, sens, registered_at, a.workers, checkpoint)
        for item in quarantined:                                      # partial registries: byte prefixes of the final
            if item['path'] in (reg.name, sens.name):
                old, new = (out / item['to'] / item['path']).read_bytes(), _p(out, item['path']).read_bytes()
                if not new.startswith(old):
                    raise DayJError('partial_registry_is_not_a_prefix_of_the_final:' + item['path'])
        outputs = _hash_tree(_p(out, 'run'), 'run/')
        outputs.update({reg.name: _sha_file(reg), sens.name: _sha_file(sens)})
        return outputs, dict(bundles_sha256=sums, registered_at=registered_at, workers=a.workers, stats=stats,
                             resumed=bool(a.resume), quarantined=quarantined,
                             lazy=True, parallel=True, slim_l1_trial_documents=True, memory=memory,
                             memory_override_anchored=a.memory_override_anchored,
                             checkpoint_index_sha256=index)
    if step == 'evaluate':
        from w1aux import lazy
        _fresh(_p(out, 'run', 'w1_report.json'))
        from bot.master_v2 import registry
        reg, sens = _p(out, 'registry_w1.jsonl'), _p(out, 'registry_sensitivity.jsonl')
        others = [Path(r) for r in (a.registry or ())]
        if not OTHER_REGISTRIES_SHA256:
            raise DayJError('p0_registry_not_pinned_yet')
        got = sorted(_sha_file(r) for r in others)
        if got != sorted(OTHER_REGISTRIES_SHA256):                    # R02 D-2: the pinned P0 registry, required
            raise DayJError('registry_paths_are_not_the_pinned_ones')
        memory = memory_guard('evaluate', _p(out, 'pools'), a.memory_override_anchored)
        prereg = {e['preregistration_sha256'] for path in [*others, reg] for e in registry.load(path)}
        if len(prereg) != N_FOR_DSR:
            raise DayJError(f'n_for_dsr_is_not_{N_FOR_DSR}:{len(prereg)}')
        with lazy.lazy_archives():
            report = run.evaluate(_p(out, 'pools'), _p(out, 'run'), a.s0, registry_paths=[*others, reg],
                                  registry_path=reg, sensitivity_registry_path=sens,
                                  **({} if a.n_boot is None else dict(n_boot=a.n_boot)))
        if report['n_trials'] != N_FOR_DSR:
            raise DayJError(f'evaluate_n_trials_is_not_{N_FOR_DSR}:{report["n_trials"]}')
        return {'run/w1_report.json': _sha_file(_p(out, 'run', 'w1_report.json'))}, dict(
            decision=report['decision'], n_trials=report['n_trials'], memory=memory,
            memory_override_anchored=a.memory_override_anchored,
            registries_sha256=dict(others=got, w1=_sha_file(reg)))
    if step == 'ledger':
        from w1aux import ledger
        memory = memory_guard('ledger', _p(out, 'pools'), a.memory_override_anchored)
        buffer = io.StringIO()
        code = ledger.main(['--pools', str(_p(out, 'pools')), '--bundles', str(_p(out, 'run', 'bundles')),
                            '--report', str(_p(out, 'run', 'w1_report.json')),
                            '--series', str(_p(out, 'sol_usd_series.json.gz')), '--out', str(_p(out, 'ledger'))],
                           out=buffer)
        summary = json.loads(buffer.getvalue())
        if code != 0:
            raise DayJError('ledger_verdict_not_pass')
        return _hash_tree(_p(out, 'ledger'), 'ledger/'), dict(summary, memory=memory,
                                                                memory_override_anchored=a.memory_override_anchored)
    if step == 'dossier':
        _fresh(_p(out, 'DOSSIER_W1.json'))
        report = json.loads(_p(out, 'run', 'w1_report.json').read_text())
        doc = dict(schema='rugger-w1-dossier-v1', category='HISTORICAL_REPLAY', s0=a.s0,
                   identities=state['identities'], steps=state['steps'],
                   digests={s: r['digest'] for s, r in state['steps'].items()},
                   w1_decision=report['decision'], w1_decision_reasons=report.get('decision_reasons'),
                   profitability_demonstrated=report.get('profitability_demonstrated', False),
                   profitability_source=('w1_report' if 'profitability_demonstrated' in report
                                         else 'absent_from_frozen_report'),
                   cycle_receipt='PENDING_R02',
                   files=_hash_tree(out, '', exclude=('checkpoint', 'selfcheck', STATE, 'DOSSIER_W1.json')),
                   flags=dict(master_operational_trade=False, counted_in_master_gate=False,
                              financial_order_submitted=False, admissible_in_paper_ledger=False),
                   note='no interpretation: the W1 decision is evaluate_w1 output; the report is accepted only '
                        'after RUGGER 02 recomputes the first closed M1 cycle by hand (cycle_receipt)')
        (out / 'DOSSIER_W1.json').write_text(json.dumps(doc, indent=1, sort_keys=True))
        return {'DOSSIER_W1.json': _sha_file(out / 'DOSSIER_W1.json')}, dict(w1_decision=report['decision'],
                                                                           cycle_receipt='PENDING_R02')
    raise DayJError('unknown_step:' + step)


NEEDS = dict(gate=('window_dir', 'coverage_summary', 'summary_sha256', 'after_reading'),
             export=('window_dir', 'pilot_dir'), series=('sol_usd_dir', 'study_report'), evaluate=('registry',))


def run_step(step, a):
    if os.environ.get('RUGGER_NO_DOTENV') != '1':
        raise DayJError('set_RUGGER_NO_DOTENV_1')
    missing = [k for k in NEEDS.get(step, ()) if getattr(a, k) is None]
    if missing:
        raise DayJError(f'{step}_needs:' + ','.join('--' + k.replace('_', '-') for k in missing))
    if type(a.workers) is not int or a.workers < 1:
        raise DayJError('workers_must_be_a_positive_integer')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state = _load_state(out)
    ids = identities()
    if state.get('identities') not in (None, ids):
        raise DayJError('code_identities_changed_between_steps')
    if state.get('s0') not in (None, a.s0):
        raise DayJError('s0_changed_between_steps')
    _check_previous(out, state, step, a.expect_sha)
    state.update(identities=ids, s0=a.s0)
    started = time.time()
    outputs, details = _run_step(step, a, out, state)
    state['steps'][step] = dict(outputs=outputs, digest=digest(outputs), details=details,
                                seconds=round(time.time() - started, 1),
                                finished_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    _save_state(out, state)
    return state['steps'][step]


def parser():
    p = argparse.ArgumentParser(description='W1 day J, one step per command (offline, after the accepted collections)')
    p.add_argument('--step', required=True, choices=STEPS)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--s0', required=True, type=int)
    p.add_argument('--expect-sha', help='digest of the previous step, as anchored by RUGGER 02')
    p.add_argument('--workers', type=int, default=4, help='selfcheck/trials: processes (parallel_replays)')
    p.add_argument('--window-dir', type=Path, help='gate/export: the LaunchLab W1 collection run')
    p.add_argument('--coverage-summary', type=Path, help='gate: the fetch summary (blocks_summary.json)')
    p.add_argument('--summary-sha256', help='gate: the fetch summary sha256 anchored by RUGGER 02')
    p.add_argument('--after-reading', type=Path, help="gate: the owner's AFTER reading (JSON), recorded only")
    p.add_argument('--pilot-dir', type=Path, help='export: the pilot run (cap rule)')
    p.add_argument('--other-run', type=Path, action='append', help='export: other runs of the month (cap rule)')
    p.add_argument('--sol-usd-dir', type=Path, help='series: the SOL/USD W1 collection run')
    p.add_argument('--study-report', type=Path, help='series: the anchored age study report (e3d92847)')
    p.add_argument('--checkpoint', type=Path, help='trials: resume directory (default <out>/checkpoint)')
    p.add_argument('--resume', action='store_true', help='trials: resume after an interruption (same registered_at; '
                                                          'partial outputs moved to quarantine/, never deleted)')
    p.add_argument('--memory-override-anchored', help='trials/evaluate/ledger: R02 anchor id allowing a run above the memory '
                                                      'projection (owner decision on a larger machine), recorded')
    p.add_argument('--registry', type=Path, action='append',
                   help='evaluate: the pinned P0 registry (required; N for the DSR must be 32)')
    p.add_argument('--n-boot', type=int, help='evaluate: bootstrap draws (default: the protocol B_DEFAULT)')
    return p


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    a = parser().parse_args(argv)
    record = run_step(a.step, a)
    shown = {k: v for k, v in record['details'].items() if k in (
        'decision', 'n_trials', 'verdict', 'cycles_with_entry', 'cycles_verified', 'mismatches', 'stats', 'workers',
        'exclusions', 'series_sha256', 'points', 'compare', 'sha256sums_sha256', 'memory_available_mb', 'w1_decision',
        'cycle_receipt', 'registered_at', 'checkpoint_index_sha256', 'memory')}
    out.write(json.dumps(dict(step=a.step, digest=record['digest'], seconds=record['seconds'], details=shown),
                         sort_keys=True, default=str) + '\n')
    return 0


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
