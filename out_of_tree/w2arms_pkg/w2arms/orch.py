"""w2arms.orch 0.1 -- W2 orchestration of the arms A0 (MASTER) and A1 (placebo): ONE collection run and ONE dayj per
window (dossier B v1.8, R02 2a6901f8: option (a), no slicer). It PLANS and CHECKS; it runs nothing and sends nothing.

  python -B -m w2arms.orch plan  --s0 <s0 of window 1> --k <windows> --root <W2 dir> [--workers 8] --out <plan.json>
  python -B -m w2arms.orch check --plan <plan.json> --plan-sha256 <sha> --run-manifest <manifest.json> ... \
                                 --dayj-state <DAYJ_STATE.json> ...

PLAN (window i = 1..k):
* s0_i = s0_1 + (i - 1) x 1 612 800; bounds = the frozen ``w1_collection.bounds(s0_i)`` (warm-up 402 800, evaluation
  1 612 800, gap 4 513): the collection run of window i covers EXACTLY [slot_min, slot_max]; consecutive runs overlap by
  402 800 + 4 513 = 407 313 slots (collected twice, ~ +25 % credits);
* the dayj chain of the window, unchanged (w1aux v7.8): selfcheck, gate, export, series, trials, evaluate, then the
  ledger through ``w1aux.dayj_c1p1`` (C1 + P1, package A2 b2e83b39), then dossier; ``--s0 s0_i``, its own ``--out``;
* the credit calendar under the frozen ``main_run_cap`` (1 000 000 per quota month, pilot and SOL/USD included, each
  run counted at its largest cap): caps per window = 1.5 x the W1 measure of R03 (LaunchLab 228 882 -> 343 323, SOL/USD
  72 578 -> 108 867), pilot 6 363; windows per month = floor((1 000 000 - pilot) / 452 190) = 2.
DECLARED (not changed, frozen W1 constants of dayj): the evaluate step pins N_FOR_DSR = 32 = the P0 registry (25) + the
window's own 7 trials; the trials of W1 and of the other W2 windows are NOT in that DSR. A0 is published and compared
without conditioning the GO (dossier B section 5). The gate step needs --coverage-summary, --summary-sha256 and
--after-reading for each window: who signs the reading of each window is an owner / R02 decision (left as inputs).
CHECK: each run manifest has exactly the planned window, each dayj state has the planned s0, windows are consecutive.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.market import backfill as bf
from bot.market import w1_collection as wc

SCHEMA = 'w2arms-orch-plan-v1'
STEPS = ('selfcheck', 'gate', 'export', 'series', 'trials', 'evaluate', 'ledger', 'dossier')
CREDIT_CAP = wc.CREDIT_CAP
PILOT_CREDITS = 6_363                       # R03: the W1 pilot as counted by its ledger
W1_CREDITS = dict(launchlab=228_882, sol_usd=72_578)     # R03: measured W1 spend per window
MARGIN = (3, 2)                             # x 1.5, dossier B / R03
WINDOW_SLOTS = wc.EVALUATION_SLOTS


class OrchError(RuntimeError):
    pass


def caps():
    return {name: -(-value * MARGIN[0] // MARGIN[1]) for name, value in W1_CREDITS.items()}


def windows_per_month():
    return (CREDIT_CAP - PILOT_CREDITS) // sum(caps().values())


def plan(s0_1, k, root, *, workers=8):
    if type(k) is not int or k < 1:
        raise OrchError('k_must_be_a_positive_integer')
    if type(workers) is not int or workers < 1:
        raise OrchError('workers_must_be_positive')
    per_month = windows_per_month()
    if per_month < 1:
        raise OrchError('no_window_fits_one_quota_month')
    root = Path(root)
    windows = []
    for i in range(k):
        s0 = s0_1 + i * WINDOW_SLOTS
        b = wc.bounds(s0)
        out = root / f'window_{i + 1:02d}'
        steps = []
        for step in STEPS:
            module = 'w1aux.dayj_c1p1' if step == 'ledger' else 'w1aux.dayj'
            launcher = (['--ledger-workers', str(workers), '--trace', str(out / 'dayj_c1p1_trace.json'), '--']
                        if step == 'ledger' else [])
            steps.append(dict(step=step, module=module,
                              argv=launcher + ['--step', step, '--out', str(out / 'dayj'), '--s0', str(s0)]
                              + (['--workers', str(workers)] if step in ('selfcheck', 'trials') else [])))
        windows.append(dict(index=i + 1, s0=s0, collection_window=dict(address=bf.LAUNCHLAB_PROGRAM, slot_min=b['slot_min'],
                                                                       slot_max=b['slot_max']),
                            evaluation=list(b['evaluation']), run_dir=str(out / 'launchlab_run'),
                            sol_usd_run_dir=str(out / 'sol_usd_run'), dayj_out=str(out / 'dayj'),
                            quota_month=i // per_month + 1, caps=caps(), steps=steps,
                            inputs_to_provide=['--window-dir', '--coverage-summary', '--summary-sha256', '--after-reading',
                                               '--pilot-dir', '--other-run', '--sol-usd-dir', '--study-report',
                                               '--registry', '--expect-sha (R02 anchor of the previous step)']))
    return dict(schema=SCHEMA, s0_1=s0_1, k=k, window_slots=WINDOW_SLOTS, overlap_slots=wc.WARMUP_SLOTS + wc.GAP_SLOTS,
                credit_cap=CREDIT_CAP, pilot_credits=PILOT_CREDITS, windows_per_quota_month=per_month,
                quota_months=-(-k // per_month), windows=windows,
                declared=dict(dsr='per window: N_FOR_DSR = 32 = P0 (25) + the window (7); A0 does not condition the GO',
                              gate='--after-reading of each window: owner / R02 decision'))


def check(plan_doc, run_manifests, dayj_states):
    if plan_doc.get('schema') != SCHEMA:
        raise OrchError('not_a_w2_plan')
    windows = plan_doc['windows']
    if len(run_manifests) != len(windows) or len(dayj_states) != len(windows):
        raise OrchError('one_run_and_one_dayj_per_window')
    for w, manifest, state in zip(windows, run_manifests, dayj_states):
        got = manifest.get('window') or {}
        if {key: got.get(key) for key in ('address', 'slot_min', 'slot_max')} != w['collection_window']:
            raise OrchError(f"run_{w['index']}_is_not_the_planned_window")
        if state.get('s0') != w['s0']:
            raise OrchError(f"dayj_{w['index']}_has_another_s0")
    for a, b in zip(windows, windows[1:]):
        if b['s0'] - a['s0'] != WINDOW_SLOTS or b['evaluation'][0] != a['evaluation'][1]:
            raise OrchError('windows_not_consecutive')
    return dict(windows=len(windows), ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='w2arms.orch')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--s0', type=int, required=True)
    p.add_argument('--k', type=int, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--out', type=Path, required=True)
    c = sub.add_parser('check')
    c.add_argument('--plan', type=Path, required=True)
    c.add_argument('--plan-sha256', required=True)
    c.add_argument('--run-manifest', type=Path, nargs='+', required=True)
    c.add_argument('--dayj-state', type=Path, nargs='+', required=True)
    a = parser.parse_args(argv)
    if a.command == 'plan':
        if a.out.exists():
            raise OrchError('output_exists')
        a.out.write_text(json.dumps(plan(a.s0, a.k, a.root, workers=a.workers), sort_keys=True, indent=1) + '\n')
        print(hashlib.sha256(a.out.read_bytes()).hexdigest())
        return 0
    raw = a.plan.read_bytes()
    if hashlib.sha256(raw).hexdigest() != a.plan_sha256:
        raise OrchError('plan_is_not_the_anchored_one')
    result = check(json.loads(raw), [json.loads(p.read_text()) for p in a.run_manifest],
                   [json.loads(p.read_text()) for p in a.dayj_state])
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
