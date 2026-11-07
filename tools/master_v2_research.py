#!/usr/bin/env python3
"""MASTER V2 research runs and evaluation (offline; no network, keys or orders).

  python -B tools/master_v2_research.py run --fixtures DIR --registry trials.jsonl \
      --policy delayed-confirmation --param min_age_s=30 --exit stop_loss=0.3 --exit max_hold_s=40 \
      --out run.json
  python -B tools/master_v2_research.py evaluate --registry trials.jsonl run1.json run2.json ... \
      [--holdout --unseal SHA ...]
  python -B tools/master_v2_research.py lifecycle --fixtures DIR --out life.json [--segment exploration]

Every ``run`` is appended to the hash-chained trial registry BEFORE its replay.

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

from datetime import datetime, timezone  # noqa: E402

from bot.master_v2 import policies, registry  # noqa: E402
from bot.master_v2.harness import ExitRule, outcome_horizon_slots, preregister, run_policy  # noqa: E402
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


OPEN_OUTCOMES = ('open_at_end', 'open_at_window_end', 'migrated_unpriced', 'counterfactual_divergence')
MARKABLE_OUTCOMES = ('open_at_end', 'open_at_window_end')   # still priced on this curve


def _open_positions(bundle, pools):
    """Entered positions that are not closed cycles: counted and marked, never neutral (R02 U3).

    Only positions still on this curve carry a mark; a migrated position (its last mark
    predates the migration) and a counterfactual divergence are unpriced.
    """
    rows = [p['trade'] for p in bundle['pools'] if p['pool'] in pools and p['trade']['outcome'] in OPEN_OUTCOMES]
    marks = [r['mark_pnl_lamports'] for r in rows
             if r['outcome'] in MARKABLE_OUTCOMES and r.get('mark_pnl_lamports') is not None]
    return dict(count=len(rows), marked=len(marks), mark_pnl_lamports=sum(marks),
                unpriced=len(rows) - len(marks),
                migrated=sum(r['outcome'] == 'migrated_unpriced' for r in rows))


def _outcomes(bundle, pools):
    counts = {}
    for p in bundle['pools']:
        if p['pool'] in pools:
            counts[p['trade']['outcome']] = counts.get(p['trade']['outcome'], 0) + 1
    return dict(sorted(counts.items()))


def _cycles(bundle, pools):
    rows = []
    for pool in bundle['pools']:
        trade = pool['trade']
        if pool['pool'] in pools and trade['outcome'] == 'closed':
            rows.append(dict(pool=pool['pool'], creator=pool['creator'], pnl_lamports=trade['pnl_lamports'],
                             cost_lamports=trade['spent'] + trade['tx_costs'] + trade['failed_attempt_costs'],
                             order_key=(trade['exit_slot'], pool['pool'])))
    return rows


def _policy(bundle):
    if bundle['policy'] not in POLICIES:
        raise ValueError('unknown_policy:%s' % bundle['policy'])
    return POLICIES[bundle['policy']](**bundle['policy_params'])


def required_embargo_slots(bundles):
    """Embargo covering every bundle's outcome horizon: entry age + bounded hold + latency (R02 O1, D)."""
    needs = []
    for bundle in bundles:
        rule = ExitRule(**bundle['exit_rule'])
        if rule.max_hold_s is None:
            raise ValueError('evaluation_requires_bounded_max_hold_s')
        need = outcome_horizon_slots(_policy(bundle), rule, ReplayParams(**bundle['params']))
        if need is None:
            raise ValueError('evaluation_requires_bounded_entry_age')
        needs.append(need)
    return max(needs)


def evaluate(bundles, *, registry_entries, holdout=False, unseal=(), embargo_slots=None, n_boot=10_000):
    """Per-run, per-segment metrics; the holdout only for registered, unsealed pre-registrations."""
    manifests = {b['fixtures']['manifest_sha256'] for b in bundles}
    if len(manifests) != 1:
        raise ValueError('runs_on_different_fixtures')
    manifest_sha256 = manifests.pop()
    registered = registry.trials_for(registry_entries, manifest_sha256)
    given = {b['preregistration_sha256'] for b in bundles}
    if given - registered:
        raise ValueError('unregistered_runs:%d' % len(given - registered))
    if registered - given:
        raise ValueError('registered_trials_missing:%d' % len(registered - given))   # DSR counts all trials
    if set(unseal) - registered:
        raise ValueError('unseal_of_unregistered_preregistration')
    required = required_embargo_slots(bundles)
    embargo_slots = max(750, required) if embargo_slots is None else embargo_slots
    if embargo_slots < required:
        raise ValueError('embargo_shorter_than_outcome_horizon:%d' % required)
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
        row = dict(policy=bundle['policy'], preregistration_sha256=sha, segments={})
        for segment in segments:
            if segment == 'holdout' and sha not in unseal:
                row['segments'][segment] = 'sealed'
                continue
            pools = set(split[segment])
            cycles = _cycles(bundle, pools)
            returns = [c['pnl_lamports'] / c['cost_lamports'] for c in cycles]
            metrics = cycle_metrics(cycles)
            metrics['outcomes'] = _outcomes(bundle, pools)
            metrics['open_positions'] = _open_positions(bundle, pools)
            entered = len(returns) + metrics['open_positions']['count']
            # Pessimistic reading: every entered position that is not a closed cycle is lost.
            metrics['mean_return_open_as_total_loss'] = (
                (sum(returns) - metrics['open_positions']['count']) / entered if entered else None)
            if len(returns) >= 2:
                metrics['mean_return_ci95_creator_cluster'] = bootstrap_mean_ci(
                    returns, [c['creator'] for c in cycles], n_boot=n_boot, seed=7)
            metrics['psr_vs_zero'] = probabilistic_sharpe_ratio(returns)
            usable = [s for s in trial_sharpes.values() if s is not None]
            metrics['dsr_all_trials'] = (deflated_sharpe_ratio(returns, usable)
                                         if len(usable) >= 2 and len(returns) >= 3 else None)
            row['segments'][segment] = metrics
        runs.append(row)
    return dict(split={k: len(v) for k, v in split.items()}, trials=len(registered), runs=runs,
                embargo_slots=embargo_slots, registry_head=registry_entries[-1]['entry_sha256'],
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
    run.add_argument('--registry', type=Path, required=True, help='append-only trial registry (JSON lines)')
    run.add_argument('--at', default=None, help='registration time (default: now, UTC ISO 8601)')
    life = sub.add_parser('lifecycle')
    life.add_argument('--fixtures', type=Path, required=True)
    life.add_argument('--out', type=Path, required=True)
    life.add_argument('--segment', choices=('exploration', 'train', 'validation', 'all'),
                      default='exploration')
    life.add_argument('--embargo-slots', type=int, default=750)
    ev = sub.add_parser('evaluate')
    ev.add_argument('bundles', type=Path, nargs='+')
    ev.add_argument('--registry', type=Path, required=True)
    ev.add_argument('--holdout', action='store_true')
    ev.add_argument('--unseal', action='append', default=[])
    ev.add_argument('--embargo-slots', type=int, default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            policy = POLICIES[args.policy](**_pairs(args.param, 'param'))
            rule, params = ExitRule(**_pairs(args.exit, 'exit')), ReplayParams()
            record = preregister(args.fixtures, policy, rule, params)
            at = args.at or datetime.now(timezone.utc).isoformat(timespec='seconds')
            entry, new = registry.register(args.registry, record, registered_at=at)   # before the replay
            bundle = run_policy(args.fixtures, policy, rule, params)
            if bundle['preregistration_sha256'] != entry['preregistration_sha256']:
                raise ValueError('preregistration_mismatch')
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(bundle, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                encoding='utf-8')
            # Identifiers only: no result over all pools is shown at run time (R02 U1).
            print(json.dumps(dict(policy=bundle['policy'], pools=len(bundle['pools']),
                                  excluded=len(bundle['excluded_pools']),
                                  preregistration_sha256=bundle['preregistration_sha256'],
                                  bundle_sha256=bundle['bundle_sha256'], registry_index=entry['index'],
                                  newly_registered=new, registry_head=registry.head(args.registry)),
                             sort_keys=True))
        elif args.command == 'lifecycle':
            rows, excluded, segment = lifecycle_table(args.fixtures, segment=args.segment,
                                                      embargo_slots=args.embargo_slots)
            doc = dict(schema='rugger-master-v2-lifecycle-v1', segment=segment, pools=rows,
                       excluded_pools=excluded)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                encoding='utf-8')
            print(json.dumps(dict(pools=len(rows), excluded=len(excluded)), sort_keys=True))
        else:
            if args.unseal and not args.holdout:
                parser.error('unseal_requires_holdout')
            bundles = [json.loads(path.read_text(encoding='utf-8')) for path in args.bundles]
            print(json.dumps(evaluate(bundles, registry_entries=registry.load(args.registry),
                                      holdout=args.holdout, unseal=args.unseal,
                                      embargo_slots=args.embargo_slots), sort_keys=True, indent=1))
    except (TypeError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
