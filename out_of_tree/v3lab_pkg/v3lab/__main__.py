"""MASTER V3 lab CLI (offline; no network, key or order).

  python -m v3lab plan                                     # the pre-registered plan and its sha256
  python -m v3lab pack --source EXPORT --out VISIBLE --table-from-bundle RUN.json
                                                           # visible-only pack (holdout never copied)
  python -m v3lab run --pack VISIBLE --expect-manifest-sha SHA --registry v3_trials.jsonl --out DIR
                      [--trial V3-01 ...] [--at ISO]
  python -m v3lab evaluate --bundles DIR --registry v3_trials.jsonl --out report.json [--p0-sharpes FILE]

``run`` prints identifiers only. ``evaluate`` writes the report and prints its sha256 and the verdicts.
Research only (HISTORICAL_REPLAY, EXPLORATORY): never an operational Master trade.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    os.environ.setdefault('RUGGER_NO_DOTENV', '1')
    if any(name == 'w1aux' or name.startswith('w1aux.') for name in sys.modules):
        raise SystemExit('v3lab must not share a process with the W1 day-J tooling (R02 V-G)')
    from v3lab import evaluate as ev, pack, plan, runner
    parser = argparse.ArgumentParser(prog='v3lab', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('plan')
    p = sub.add_parser('pack')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--embargo-slots', type=int, default=None)
    p.add_argument('--table-from-bundle', type=Path, required=True,
                   help='registered bundle of the same export (pool table); non-visible pool files are never opened')
    r = sub.add_parser('run')
    r.add_argument('--pack', type=Path, required=True)
    r.add_argument('--expect-manifest-sha', required=True, help='MANIFEST sha256 of the pack, anchored by RUGGER 02')
    r.add_argument('--registry', type=Path, required=True)
    r.add_argument('--out', type=Path, required=True)
    r.add_argument('--trial', action='append', help='default: every trial of the plan, in order')
    r.add_argument('--at', default=None, help='registration time (default: now, UTC ISO 8601)')
    e = sub.add_parser('evaluate')
    e.add_argument('--bundles', type=Path, required=True)
    e.add_argument('--registry', type=Path, required=True)
    e.add_argument('--out', type=Path, required=True)
    e.add_argument('--p0-sharpes', type=Path, default=None, help='JSON list of the 25 P0 trial Sharpe ratios')
    e.add_argument('--n-boot', type=int, default=plan.N_BOOT)
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            print(json.dumps(dict(plan.PLAN, plan_sha256=plan.plan_sha256(),
                                  v3lab_sha256=runner.v3lab_fingerprint(),
                                  required_embargo_slots=pack.required_embargo_slots()), sort_keys=True, indent=1),
                  file=out)
        elif args.command == 'pack':
            print(json.dumps(pack.build(args.source, args.out, embargo_slots=args.embargo_slots,
                                        table_bundle=args.table_from_bundle), sort_keys=True, indent=1), file=out)
        elif args.command == 'run':
            at = args.at or datetime.now(timezone.utc).isoformat(timespec='seconds')
            for trial_id in args.trial or [row['id'] for row in plan.TRIALS]:
                print(json.dumps(runner.run_trial(args.pack, trial_id, expect_manifest_sha256=args.expect_manifest_sha,
                                                  registry_path=args.registry, registered_at=at, out_dir=args.out),
                                 sort_keys=True), file=out, flush=True)
        else:
            if args.out.exists():
                raise ValueError('output_exists:%s' % args.out.name)
            sharpes = json.loads(args.p0_sharpes.read_text()) if args.p0_sharpes else ()
            report = ev.evaluate_directory(args.bundles, args.registry, p0_trial_sharpes=sharpes, n_boot=args.n_boot)
            raw = (json.dumps(report, sort_keys=True, indent=1, allow_nan=False) + '\n').encode()
            args.out.write_bytes(raw)
            print(json.dumps(dict(report_sha256=hashlib.sha256(raw).hexdigest(), verdicts=report['verdicts'],
                                  n_cumulative=report['n_cumulative'], status=report['status']), sort_keys=True),
                  file=out)
    except (TypeError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
