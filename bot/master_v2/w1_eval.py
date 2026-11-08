"""W1 evaluation (W1 protocol items R3, R5, R8). Research only; nothing here trades.

* **R5 -- L1 trials.** The Master scorer (L1 arm ``master``, M1) and the placebo P1b (L1 arm
  ``placebo_random``) are pre-registered BEFORE the replay with every L1 parameter (latency,
  receipt latency, vault exclusion, horizon, fees, SOL/USD source, exit options, creator
  history), then replayed once; each arm becomes a trial document carrying its code fingerprint.
  The L1 ``reference`` arm is never a W1 trial and is never reported.
* **R3 -- W1 mode.** One MANIFEST evaluated whole: only pools created in the pre-registered
  evaluation range [start, end) count (the warm-up range only feeds the creator history); two
  halves by creation slot, the second starting ``embargo_slots`` after the boundary (pools in
  between are embargoed and published as such). N of the deflated Sharpe ratio is the number
  of distinct pre-registrations over every registry given (P0 and W1); the spread of trial
  Sharpe ratios is the one of the W1 trials.
* **R8 -- tests.** Creator-cluster bootstrap of the mean (B=10000, seed 20261108), one-sided
  p = (1 + #{b: m*_b - m >= m}) / (B + 1); H2 is the unpaired difference M1 - P1b, each arm
  resampled by creator; H3 is the exact partition of S3 against S2 (random-abstention p); Holm
  within each family of two. The decision follows the gate of the protocol.

Every cycle here is HISTORICAL_REPLAY research: never an operational Master trade, never
counted toward the protected 50-cycle / 20-creator thresholds.
"""
from dataclasses import asdict
import hashlib
import json
import math
import random
import statistics

from bot.master_decision import MasterDecisionOrchestrator
from bot.master_v2 import challengers, registry
from bot.master_v2.harness import code_fingerprint
from bot.master_v2.validation import (EULER_GAMMA, _NORMAL, bootstrap_mean_ci, preregistration,
                                      probabilistic_sharpe_ratio, sharpe_ratio)
from bot.p4 import historical_research_replay as hrr
from bot.p4_experiment import POLICY as P4_POLICY

TRIAL_SCHEMA = 'rugger-w1-trial-v1'
L1_ARMS = {'M1': 'master', 'P1b': hrr.PLACEBO_ARM}
B_DEFAULT = 10_000
SEED = 20261108
ALPHA = 0.025
NON_CLOSED_MAX = 0.05
NOT_CLOSED = ('migrated_unpriced', 'counterfactual_divergence', 'open_at_window_end', 'open_at_end')


def _sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


# --- R5: L1 trials ------------------------------------------------------------------------

def l1_design(fixtures_dir, params):
    """(manifest_sha256, windows_sha256) of a MANIFEST, computable before any replay."""
    manifest_sha256, _digests, archives, manifest = hrr.load_fixtures(fixtures_dir)
    windows = {entry['pool']: hrr.collection_window(entry, manifest, params) for entry, _a in archives}
    return manifest_sha256, _sha(windows)


def l1_preregister(manifest_sha256, windows_sha256, params, exit_options, *, arm, sol_usd_source,
                   creator_history_sha256):
    """Pre-registration record of one L1 arm (registry.register), every L1 parameter included."""
    if arm not in L1_ARMS.values():
        raise ValueError('not_a_w1_l1_arm')
    if type(exit_options) is not hrr.ExitOptions or type(params) is not hrr.ReplayParams:
        raise ValueError('invalid_l1_configuration')
    if type(sol_usd_source) is not str or not sol_usd_source:
        raise ValueError('sol_usd_source_required')
    config = dict(engine='l1-historical-research-replay', arm=arm, replay=asdict(params),
                  exit_options=exit_options.record(), placebo_arm=True, sol_usd_source=sol_usd_source,
                  creator_history_sha256=creator_history_sha256,
                  master_policy_sha256=MasterDecisionOrchestrator().policy_sha256,
                  reference_policy_sha256=_sha(P4_POLICY))
    design = dict(code_sha256=code_fingerprint(), manifest_sha256=manifest_sha256, windows_sha256=windows_sha256)
    return dict(preregistration_sha256=preregistration('l1:' + arm, config, design), policy='l1:' + arm,
                policy_params=config, exit_rule=exit_options.record(), replay_params=asdict(params), **design)


def run_l1_trials(fixtures_dir, params, exit_options, *, registry_path, registered_at, sol_usd_series=None):
    """Register M1 and P1b, then replay once; return {trial id: trial document}."""
    manifest_sha256, windows_sha256 = l1_design(fixtures_dir, params)
    archives = [archive for _entry, archive in hrr.load_fixtures(fixtures_dir)[2]]
    history = hrr.CreatorHistory.from_archives(archives, label='manifest')
    source = ('series:' + sol_usd_series.sha256) if sol_usd_series is not None else (
        f'declared:{params.sol_usd}' if params.sol_usd is not None else 'none')
    entries = {}
    for trial_id, arm in L1_ARMS.items():      # registered BEFORE the replay
        record = l1_preregister(manifest_sha256, windows_sha256, params, exit_options, arm=arm,
                                sol_usd_source=source, creator_history_sha256=history.sha256)
        entries[trial_id], _new = registry.register(registry_path, record, registered_at=registered_at)
    bundle = hrr.run_replay(fixtures_dir, params, sol_usd_series, exit_options, history, placebo_arm=True)
    if bundle['fixtures']['manifest_sha256'] != manifest_sha256:
        raise ValueError('manifest_changed_during_run')
    return {trial_id: trial_from_l1_bundle(bundle, trial_id, entries[trial_id]) for trial_id in L1_ARMS}


def trial_from_l1_bundle(bundle, trial_id, entry):
    arm = L1_ARMS[trial_id]
    if entry['manifest_sha256'] != bundle['fixtures']['manifest_sha256']:
        raise ValueError('l1_trial_manifest_mismatch')
    if entry['replay_params'] != bundle['params'] or entry['exit_rule'] != bundle.get(
            'exit_options', hrr.ExitOptions().record()):
        raise ValueError('l1_trial_configuration_mismatch')
    if entry['code_sha256'] != code_fingerprint():
        raise ValueError('code_sha256_mismatch')
    pools = [dict(pool=p['pool'], creator=p['creator'], created_slot=p['creation_slot'],
                  signed_creator_verified=p['signed_creator_verified'], trade=p['arms'][arm],
                  journal=[r for r in p['journal'] if r['arm'] == arm]) for p in bundle['pools']]
    return dict(schema=TRIAL_SCHEMA, trial_id=trial_id, engine='l1', preregistration_sha256=entry['preregistration_sha256'],
                code_sha256=entry['code_sha256'], manifest_sha256=entry['manifest_sha256'],
                bundle_sha256=bundle['bundle_sha256'], pools=pools)


def trial_from_v2_bundle(bundle, trial_id):
    pools = [dict(pool=p['pool'], creator=p['creator'], created_slot=p['created_slot'],
                  signed_creator_verified=p['signed_creator_verified'], trade=p['trade'], journal=p['journal'])
             for p in bundle['pools']]
    return dict(schema=TRIAL_SCHEMA, trial_id=trial_id, engine='v2', preregistration_sha256=bundle['preregistration_sha256'],
                code_sha256=bundle['code_sha256'], manifest_sha256=bundle['fixtures']['manifest_sha256'],
                bundle_sha256=bundle['bundle_sha256'], pools=pools)


# --- R3: W1 mode --------------------------------------------------------------------------

def w1_split(pools, *, start, end, embargo_slots):
    """Evaluation pools by half: {'all', 'A', 'B', 'embargoed', 'outside'} (lists of pool ids)."""
    if type(start) is not int or type(end) is not int or not start < end:
        raise ValueError('invalid_evaluation_range')
    if type(embargo_slots) is not int or embargo_slots < 0:
        raise ValueError('invalid_embargo_slots')
    rows = sorted({(p['created_slot'], p['pool']) for p in pools})
    inside = [row for row in rows if start <= row[0] < end]
    outside = [pool for slot, pool in rows if not start <= slot < end]
    half = len(inside) // 2
    first = [pool for _s, pool in inside[:half]]
    boundary = inside[half][0] if half < len(inside) else end
    second = [pool for slot, pool in inside[half:] if slot >= boundary + embargo_slots]
    embargoed = [pool for slot, pool in inside[half:] if slot < boundary + embargo_slots]
    return dict(all=[pool for _s, pool in inside], A=first, B=second, embargoed=embargoed, outside=outside,
                boundary_slot=boundary)


def _rows(trial, pools):
    wanted = set(pools)
    return [p for p in trial['pools'] if p['pool'] in wanted]


def trial_metrics(trial, pools, n_boot=B_DEFAULT):
    rows = _rows(trial, pools)
    entered = [p for p in rows if p['trade']['entry_index'] is not None]
    closed = [p for p in entered if p['trade']['outcome'] == 'closed']
    returns = [p['trade']['pnl_lamports'] / (p['trade']['spent'] + p['trade']['tx_costs']
                                              + p['trade']['failed_attempt_costs']) for p in closed]
    non_closed = len(entered) - len(closed)
    creators = sorted({p['creator'] for p in closed if p['signed_creator_verified'] and p['creator']})
    return dict(entries=len(entered), closed=len(closed), non_closed=non_closed,
                non_closed_share=(non_closed / len(entered)) if entered else None,
                mean_return=statistics.fmean(returns) if returns else None,
                pessimistic_mean=((sum(returns) - non_closed) / len(entered)) if entered else None,
                independent_creators=len(creators), sharpe=sharpe_ratio(returns),
                ci95_creator=(bootstrap_mean_ci(returns, [p['creator'] for p in closed], n_boot=n_boot, seed=SEED)
                              if len(returns) >= 2 else None),
                returns=returns, return_creators=[p['creator'] for p in closed])


# --- R8: tests ----------------------------------------------------------------------------

def _boot_means(values, groups, n_boot, rng):
    clusters = {}
    for value, group in zip(values, groups):
        clusters.setdefault(group, []).append(value)
    clusters = list(clusters.values())
    means = []
    for _ in range(n_boot):
        sample = [v for _k in range(len(clusters)) for v in clusters[rng.randrange(len(clusters))]]
        means.append(sum(sample) / len(sample))
    return means


def mean_test(values, groups, *, n_boot=B_DEFAULT, seed=SEED):
    """One-sided p of mean > 0, creator-cluster bootstrap centred on the estimate."""
    if len(values) < 2:
        return None
    estimate = statistics.fmean(values)
    boots = _boot_means(values, groups, n_boot, random.Random(seed))
    return (1 + sum(b - estimate >= estimate for b in boots)) / (n_boot + 1)


def difference_test(a, a_groups, b, b_groups, *, n_boot=B_DEFAULT, seed=SEED):
    """One-sided p of mean(a) > mean(b), unpaired, each arm resampled by creator."""
    if len(a) < 2 or len(b) < 2:
        return None
    estimate = statistics.fmean(a) - statistics.fmean(b)
    rng = random.Random(seed)
    boots_a, boots_b = _boot_means(a, a_groups, n_boot, rng), _boot_means(b, b_groups, n_boot, rng)
    return (1 + sum((x - y) - estimate >= estimate for x, y in zip(boots_a, boots_b))) / (n_boot + 1)


def holm(pvalues):
    """Holm-adjusted p values (None stays None and is not counted)."""
    named = sorted((p, key) for key, p in pvalues.items() if p is not None)
    m, adjusted, running = len(named), {key: None for key in pvalues}, 0.0
    for rank, (p, key) in enumerate(named):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[key] = running
    return adjusted


def deflated_sharpe(values, trial_sharpes, n_trials):
    """PSR against the expected maximum Sharpe of ``n_trials`` trials with the given spread."""
    usable = [s for s in trial_sharpes if s is not None]
    if len(usable) < 2 or n_trials < 2 or len(values) < 3:
        return None
    spread = statistics.pstdev(usable)
    benchmark = spread * ((1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / n_trials)
                          + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (n_trials * math.e)))
    return probabilistic_sharpe_ratio(values, benchmark)


# --- evaluation and gate ------------------------------------------------------------------

REQUIRED = ('M1', 'P1b', 'P1', 'P2', 'S1', 'S2', 'S3')


def evaluate_w1(trials, registry_entries, *, start, end, embargo_slots, targets=(140, 50),
                sensitivity_latency10=None, n_boot=B_DEFAULT):
    """W1 report and decision; ``trials`` maps the protocol ids to trial documents."""
    if set(trials) != set(REQUIRED):
        raise ValueError('w1_trials_must_be_exactly:' + ','.join(REQUIRED))
    recorded = {e['preregistration_sha256']: e for e in registry_entries}
    manifests = {t['manifest_sha256'] for t in trials.values()}
    if len(manifests) != 1:
        raise ValueError('runs_on_different_fixtures')
    for trial in trials.values():
        entry = recorded.get(trial['preregistration_sha256'])
        if entry is None:
            raise ValueError('unregistered_trial:' + trial['trial_id'])
        if entry.get('code_sha256') != trial['code_sha256']:
            raise ValueError('code_sha256_mismatch:' + trial['trial_id'])
    w1_registered = registry.trials_for(registry_entries, manifests.pop())
    if w1_registered != {t['preregistration_sha256'] for t in trials.values()}:
        raise ValueError('registered_w1_trials_not_all_evaluated')
    n_trials = len(recorded)
    split = w1_split(trials['M1']['pools'], start=start, end=end, embargo_slots=embargo_slots)
    report = dict(n_trials=n_trials, split={k: (len(v) if type(v) is list else v) for k, v in split.items()},
                  evaluator_code_sha256=code_fingerprint(), trials={})
    for key, trial in trials.items():
        report['trials'][key] = {period: {k: v for k, v in trial_metrics(trial, split[period], n_boot).items()
                                          if k not in ('returns', 'return_creators')}
                                 for period in ('all', 'A', 'B')}
    m1 = trial_metrics(trials['M1'], split['all'], n_boot)
    p1b = trial_metrics(trials['P1b'], split['all'], n_boot)
    s1 = trial_metrics(trials['S1'], split['all'], n_boot)
    sharpes = [trial_metrics(t, split['all'], n_boot)['sharpe'] for t in trials.values()]
    tests = dict(
        H1=mean_test(m1['returns'], m1['return_creators'], n_boot=n_boot),
        H2=difference_test(m1['returns'], m1['return_creators'], p1b['returns'], p1b['return_creators'], n_boot=n_boot),
        H4=mean_test(s1['returns'], s1['return_creators'], n_boot=n_boot))
    partition = challengers.veto_partition(trials['S2'], trials['S3'], set(split['all']), n_perm=10_000, seed=7)
    tests['H3'] = partition['random_abstention_p']
    report['tests'] = dict(raw=tests, holm_primary=holm(dict(H1=tests['H1'], H2=tests['H2'])),
                           holm_secondary=holm(dict(H3=tests['H3'], H4=tests['H4'])), partition_S3_S2=partition)
    report['dsr_M1'] = deflated_sharpe(m1['returns'], sharpes, n_trials)
    sens = None
    if sensitivity_latency10 is not None:
        if sensitivity_latency10['code_sha256'] != trials['M1']['code_sha256']:
            raise ValueError('sensitivity_code_mismatch')
        sens = trial_metrics(sensitivity_latency10, split['all'], n_boot)['mean_return']
    report['sensitivity_latency10_mean'] = sens
    report['decision'], report['decision_reasons'] = _decide(report, m1, p1b, s1, targets)
    report['flags'] = dict(category=hrr.CATEGORY, master_operational_trade=False, counted_in_master_gate=False,
                           reference_arm_reported=False)
    return report


def _decide(report, m1, p1b, s1, targets):
    min_cycles, min_creators = targets
    if m1['closed'] < min_cycles or m1['independent_creators'] < min_creators:
        return 'WAIT_INSUFFICIENT_DATA', [f"M1 closed {m1['closed']} / {min_cycles}",
                                          f"M1 creators {m1['independent_creators']} / {min_creators}"]
    if m1['non_closed_share'] > NON_CLOSED_MAX:
        return 'WAIT_NON_CLOSED', [f"M1 non-closed share {m1['non_closed_share']:.3f} > {NON_CLOSED_MAX}"]
    if p1b['non_closed_share'] is None or p1b['non_closed_share'] > NON_CLOSED_MAX:
        return 'WAIT_H2_NOT_EVALUABLE', ['P1b non-closed share above the limit or no entry']
    trials = report['trials']['M1']
    holm_p = report['tests']['holm_primary']
    checks = {
        'H1_rejected': holm_p['H1'] is not None and holm_p['H1'] < ALPHA,
        'H2_rejected': holm_p['H2'] is not None and holm_p['H2'] < ALPHA,
        'ci95_low_positive': m1['ci95_creator'] is not None and m1['ci95_creator'][0] > 0,
        'pessimistic_positive': m1['pessimistic_mean'] is not None and m1['pessimistic_mean'] > 0,
        'half_A_positive': (trials['A']['mean_return'] or 0) > 0,
        'half_B_positive': (trials['B']['mean_return'] or 0) > 0,
        'latency10_positive': report['sensitivity_latency10_mean'] is not None and report['sensitivity_latency10_mean'] > 0,
        'dsr_above_0_95': report['dsr_M1'] is not None and report['dsr_M1'] > 0.95,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if s1['non_closed_share'] is not None and s1['non_closed_share'] > NON_CLOSED_MAX:
        report['tests']['H4_not_evaluable'] = True
    return ('CHALLENGER_FOR_W2', []) if not failed else ('NO_GO', failed)
