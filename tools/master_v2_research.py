#!/usr/bin/env python3
"""MASTER V2 research runs and evaluation (offline; no network, keys or orders).

  python -B tools/master_v2_research.py run --fixtures DIR --policy delayed-confirmation \
      --param min_age_s=30 --exit stop_loss=0.3 --exit max_hold_s=120 --out run.json
  python -B tools/master_v2_research.py evaluate run1.json run2.json ... [--holdout --unseal SHA ...]

``evaluate`` splits pools chronologically (exploration / train / validation / holdout,
creators disjoint, embargo at boundaries) and reports closed-cycle metrics per
segment with a creator-cluster bootstrap interval, PSR and, across all runs given
(every trial counts), the deflated Sharpe ratio. The holdout stays sealed unless
``--holdout`` is given together with the pre-registration hashes to unseal; runs
not listed are never evaluated on it.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.master_v2 import policies  # noqa: E402
from bot.master_v2.harness import ExitRule, run_policy  # noqa: E402
from bot.master_v2.lifecycle import lifecycle_table  # noqa: E402
from bot.master_v2.validation import (  # noqa: E402
    SEGMENTS, bootstrap_mean_ci, chronological_split, cycle_metrics, deflated_sharpe_ratio,
    probabilistic_sharpe_ratio, sharpe_ratio)
from bot.p4.historical_research_replay import ReplayParams  # noqa: E402

POLICIES = {cls.name: cls for cls in (policies.NoTrade, policies.RandomEntry, policies.ImmediateSnipe,
                                      policies.DelayedConfirmation, policies.FillMomentum,
                                      policies.FixedDelay)}


def _value(text):
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    if text in ('true', 'false'):
        return text == 'true'
    if text == 'none':
        return None
    return text


def _pairs(items, what):
    out = {}
    for item in items or ():
        if '=' not in item:
            raise ValueError(f'invalid_{what}:{item}')
        key, raw = item.split('=', 1)
        out[key] = _value(raw)
    return out


def _cycles(bundle, pools):
    rows = []
    for pool in bundle['pools']:
        trade = pool['trade']
        if pool['pool'] in pools and trade['outcome'] == 'closed':
            rows.append(dict(pool=pool['pool'], creator=pool['creator'], pnl_lamports=trade['pnl_lamports'],
                             cost_lamports=trade['spent'] + trade['tx_costs'] + trade['failed_attempt_costs'],
                             order_key=(trade['exit_slot'], pool['pool'])))
    return rows


def evaluate(bundles, *, holdout=False, unseal=(), embargo_slots=750, n_boot=10_000):
    """Per-run, per-segment metrics; the holdout only for unsealed pre-registrations."""
    manifests = {b['fixtures']['manifest_sha256'] for b in bundles}
    if len(manifests) != 1:
        raise ValueError('runs_on_different_fixtures')
    table = {}
    for bundle in bundles:
        for pool in bundle['pools']:
            table.setdefault(pool['pool'], dict(pool=pool['pool'], creator=pool['creator'],
                                                created_slot=pool['created_slot']))
    split = chronological_split(list(table.values()), embargo_slots=embargo_slots)
    segments = [s for s in SEGMENTS if s != 'holdout'] + (['holdout'] if holdout else [])
    trial_sharpes = {}
    for bundle in bundles:
        returns = [c['pnl_lamports'] / c['cost_lamports'] for c in _cycles(bundle, set(split['exploration']))]
        trial_sharpes[bundle['preregistration_sha256']] = sharpe_ratio(returns)
    runs = []
    for bundle in bundles:
        sha = bundle['preregistration_sha256']
        row = dict(policy=bundle['policy'], preregistration_sha256=sha, outcomes=bundle['outcomes'], segments={})
        for segment in segments:
            if segment == 'holdout' and sha not in unseal:
                row['segments'][segment] = 'sealed'
                continue
            cycles = _cycles(bundle, set(split[segment]))
            returns = [c['pnl_lamports'] / c['cost_lamports'] for c in cycles]
            metrics = cycle_metrics(cycles)
            if len(returns) >= 2:
                metrics['mean_return_ci95_creator_cluster'] = bootstrap_mean_ci(
                    returns, [c['creator'] for c in cycles], n_boot=n_boot, seed=7)
            metrics['psr_vs_zero'] = probabilistic_sharpe_ratio(returns)
            usable = [s for s in trial_sharpes.values() if s is not None]
            metrics['dsr_all_trials'] = (deflated_sharpe_ratio(returns, usable)
                                         if len(usable) >= 2 and len(returns) >= 3 else None)
            row['segments'][segment] = metrics
        runs.append(row)
    return dict(split={k: len(v) for k, v in split.items()}, trials=len(bundles), runs=runs,
                holdout_unsealed=sorted(set(unseal)) if holdout else [])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--fixtures', type=Path, required=True)
    run.add_argument('--policy', choices=sorted(POLICIES), required=True)
    run.add_argument('--param', action='append', help='policy parameter key=value')
    run.add_argument('--exit', action='append', help='exit rule key=value')
    run.add_argument('--out', type=Path, required=True)
    life = sub.add_parser('lifecycle')
    life.add_argument('--fixtures', type=Path, required=True)
    life.add_argument('--out', type=Path, required=True)
    ev = sub.add_parser('evaluate')
    ev.add_argument('bundles', type=Path, nargs='+')
    ev.add_argument('--holdout', action='store_true')
    ev.add_argument('--unseal', action='append', default=[])
    ev.add_argument('--embargo-slots', type=int, default=750)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            policy = POLICIES[args.policy](**_pairs(args.param, 'param'))
            bundle = run_policy(args.fixtures, policy, ExitRule(**_pairs(args.exit, 'exit')), ReplayParams())
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(bundle, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                encoding='utf-8')
            print(json.dumps(dict(policy=bundle['policy'], outcomes=bundle['outcomes'], metrics=bundle['metrics'],
                                  preregistration_sha256=bundle['preregistration_sha256'],
                                  bundle_sha256=bundle['bundle_sha256']), sort_keys=True))
        elif args.command == 'lifecycle':
            rows, excluded = lifecycle_table(args.fixtures)
            doc = dict(schema='rugger-master-v2-lifecycle-v1', pools=rows, excluded_pools=excluded)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                encoding='utf-8')
            print(json.dumps(dict(pools=len(rows), excluded=len(excluded)), sort_keys=True))
        else:
            if args.unseal and not args.holdout:
                parser.error('unseal_requires_holdout')
            bundles = [json.loads(path.read_text(encoding='utf-8')) for path in args.bundles]
            print(json.dumps(evaluate(bundles, holdout=args.holdout, unseal=args.unseal,
                                      embargo_slots=args.embargo_slots), sort_keys=True, indent=1))
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
