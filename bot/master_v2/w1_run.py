"""W1 run script (W1 protocol v2.4): plan, collection command, SOL/USD series, trials, evaluation.

OFFLINE BY CONSTRUCTION: nothing here opens a socket. The only network step of W1, the
collection, is RUGGER 03's audited CLI (bot.market.backfill_cli run --network), for which
``collect_command`` only RETURNS the argument list after ``w1_collection.check_run_cap``; it
is run by a person after the owner's GO, never by this module. Every replay and evaluation
step requires ``RUGGER_NO_DOTENV=1`` in the environment (R02 O-R4-2): bot.config then never
loads a .env file, so no secret can enter these processes.

Order of a W1 run (each step writes its outputs with their sha256 under ``out``):
1. ``plan``: the W1 bounds from S0 (and, after the pilot, the cap rule).
2. ``collect_command``: the CLI arguments, with the run cap checked against the pilot ledger.
3. ``export`` (w1_collection.export, pilot_dir required) -> pools directory + MANIFEST.
4. ``sol_usd_series``: Pyth push points decoded from collected entries, with the measured
   acceptance rule, as a COLLECTED series document.
5. ``run_trials``: every trial is registered BEFORE its replay (L1 M1 and P1b in one run,
   V2 P1, P2, S1, S2, S3, and the latency-10 sensitivity in its own registry), bundles saved.
6. ``evaluate``: trial documents REBUILT from the saved bundles (R02 O-F1: never trusted from
   a previous step), bundle sha256 recomputed, then ``w1_eval.evaluate_w1``.

Research only (HISTORICAL_REPLAY): never an operational Master trade, never counted toward
the protected 50-cycle / 20-creator thresholds.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path

from bot.market import pyth_push, w1_collection
from bot.master_v2 import challengers, harness, policies, registry, w1_eval
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus

EXECUTION = dict(latency_slots=4, base_fee_lamports=5_000, priority_fee_lamports=100_000,
                 failed_attempt_fee_lamports=0)
L1_HORIZON_MS = 30_000
V2_HOLD_S = 25
L1_EXIT = hrr.ExitOptions(clock_horizon=True)
V2_ARMS = {
    'P1': (lambda: policies.RandomEntry(), harness.ExitRule(max_hold_s=V2_HOLD_S, clock_exit=True)),
    'P2': (lambda: policies.NoTrade(), harness.ExitRule(max_hold_s=V2_HOLD_S)),
    'S1': (lambda: policies.ImmediateSnipe(), harness.ExitRule(max_hold_s=V2_HOLD_S, clock_exit=True)),
    'S2': (lambda: policies.FixedDelay(delay_s=5), harness.ExitRule(max_hold_s=V2_HOLD_S, clock_exit=True)),
    'S3': (lambda: challengers.InsiderVeto5s(), harness.ExitRule(max_hold_s=V2_HOLD_S, clock_exit=True)),
}


class W1RunError(RuntimeError):
    pass


def require_no_dotenv(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get('RUGGER_NO_DOTENV') != '1':
        raise W1RunError('set_RUGGER_NO_DOTENV_1_before_any_w1_step')


def l1_params():
    return hrr.ReplayParams(exit_horizon_ms=L1_HORIZON_MS, **EXECUTION)


def v2_params():
    return hrr.ReplayParams(exit_horizon_ms=V2_HOLD_S * 1000, **EXECUTION)


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, doc):
    data = json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(gzip.compress(data, mtime=0) if str(path).endswith('.gz') else data)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path):
    data = Path(path).read_bytes()
    return json.loads(gzip.decompress(data) if str(path).endswith('.gz') else data)


def plan(s0, *, evaluation_slots=w1_collection.EVALUATION_SLOTS):
    return w1_collection.bounds(s0, evaluation_slots)


def collect_command(s0, *, pilot_dir, max_credits, out, evaluation_slots=w1_collection.EVALUATION_SLOTS,
                    max_requests=200_000, endpoint_env='RUGGER_BACKFILL_RPC_URL', address=None, other_runs=()):
    """Arguments for backfill_cli (NOT executed here); the run cap must fit what the pilot and the
    other runs of the month left. ``address``: None for the LaunchLab program, or the SOL/USD
    price account (v2.4) for the SOL/USD collection over the same W1 slots."""
    w1_collection.check_run_cap(max_credits, pilot_dir, other_runs)
    if address not in (None, pyth_push.SOL_USD_ACCOUNT):
        raise W1RunError('w1_collects_the_launchlab_program_or_the_sol_usd_account_only')
    b = plan(s0, evaluation_slots=evaluation_slots)
    extra = [] if address is None else ['--address', address]
    return ['run', '--network', '--endpoint-env', endpoint_env, *extra, '--slot-min', str(b['slot_min']),
            '--slot-max', str(b['slot_max']), '--bodies', 'gtfa', '--costs', w1_collection.COSTS,
            '--max-requests', str(max_requests), '--max-credits', str(max_credits), '--out', str(out)]


def pyth_entries(run_dir, s0, *, evaluation_slots=w1_collection.EVALUATION_SLOTS):
    """Entries of a verified, complete SOL/USD account window over the W1 slots (v2.4)."""
    from bot.market import backfill as bf
    checked = bf.verify(run_dir)
    manifest = _read_json(Path(run_dir) / 'manifest.json')
    b = plan(s0, evaluation_slots=evaluation_slots)
    window = manifest['window']
    if not checked['ok'] or not manifest['complete']:
        raise W1RunError('sol_usd_window_not_verified_or_incomplete')
    if (window['address'], window['slot_min'], window['slot_max']) != (pyth_push.SOL_USD_ACCOUNT, b['slot_min'], b['slot_max']):
        raise W1RunError('not_the_w1_sol_usd_window')
    if manifest['budget']['costs'] != bf.COST_PRESETS[w1_collection.COSTS]:
        raise W1RunError('sol_usd_window_not_on_the_w1_cost_table')
    return [row for seg in manifest['segments'] if seg['kind'] == 'tx' for row in bf.read_segment(Path(run_dir) / seg['path'])]


def sol_usd_series(entries, acceptance, out):
    """COLLECTED series of Pyth push points from collected entries, with the measured acceptance rule."""
    require_no_dotenv()
    document = dict(schema=sus.SERIES_SCHEMA, label='COLLECTED', points=pyth_push.sol_usd_points(entries),
                    acceptance=dict(acceptance))
    series = sus.series_from_document(document)                    # validates before anything is written
    _write_json(out, document)
    return series


def _bundle_path(out, trial_id):
    return Path(out) / 'bundles' / f'{trial_id}.json.gz'


def run_trials(pools_dir, series_path, *, registry_path, sensitivity_registry_path, registered_at, out):
    """Register then replay every W1 trial; return {trial id: bundle file sha256}."""
    require_no_dotenv()
    series = sus.load_series(series_path)
    if series.label != 'COLLECTED' or series.max_age_ms == sus.MAX_AGE_MS and series.max_confidence_ppm is None:
        raise W1RunError('w1_needs_a_collected_series_with_its_measured_acceptance')
    written = {}
    trials = w1_eval.run_l1_trials(pools_dir, l1_params(), L1_EXIT, registry_path=registry_path,
                                   registered_at=registered_at, sol_usd_series=series)
    for trial_id, (make, rule) in V2_ARMS.items():
        policy = make()
        record = harness.preregister(pools_dir, policy, rule, v2_params())
        registry.register(registry_path, record, registered_at=registered_at)     # before the replay
        bundle = harness.run_policy(pools_dir, policy, rule, v2_params())
        if bundle['preregistration_sha256'] != record['preregistration_sha256']:
            raise W1RunError('v2_preregistration_changed:' + trial_id)
        written[trial_id] = _write_json(_bundle_path(out, trial_id), bundle)
    # L1: one replay holds both arms; re-run deterministically to save the bundle itself.
    l1 = hrr.run_replay(pools_dir, l1_params(), series, L1_EXIT,
                        hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pools_dir)[2]], 'manifest'),
                        placebo_arm=True)
    for trial_id in w1_eval.L1_ARMS:
        if l1['bundle_sha256'] != trials[trial_id]['bundle_sha256']:
            raise W1RunError('l1_replay_not_deterministic')
    written['L1'] = _write_json(_bundle_path(out, 'L1'), l1)
    sensitivity = w1_eval.run_l1_sensitivity(pools_dir, l1_params(), L1_EXIT,
                                             registry_path=sensitivity_registry_path,
                                             registered_at=registered_at, sol_usd_series=series)
    l10 = hrr.run_replay(pools_dir, hrr.ReplayParams(**dict(vars(l1_params()), latency_slots=10)), series, L1_EXIT,
                         hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pools_dir)[2]], 'manifest'),
                         placebo_arm=True)
    if l10['bundle_sha256'] != sensitivity['bundle_sha256']:
        raise W1RunError('sensitivity_replay_not_deterministic')
    written[w1_eval.SENSITIVITY_ID] = _write_json(_bundle_path(out, w1_eval.SENSITIVITY_ID), l10)
    _write_json(Path(out) / 'bundles' / 'SHA256SUMS.json', written)
    return written


def _entry_for(entries, bundle_or_trial_prereg):
    for entry in entries:
        if entry['preregistration_sha256'] == bundle_or_trial_prereg:
            return entry
    raise W1RunError('no_registry_entry_for_bundle')


def evaluate(pools_dir, out, s0, *, registry_paths, registry_path, sensitivity_registry_path, embargo_slots,
             evaluation_slots=w1_collection.EVALUATION_SLOTS, n_boot=w1_eval.B_DEFAULT):
    """Rebuild every trial document from its saved bundle, then evaluate W1 (R02 O-F1)."""
    require_no_dotenv()
    sums = _read_json(Path(out) / 'bundles' / 'SHA256SUMS.json')
    for trial_id, sha in sums.items():
        if _sha_file(_bundle_path(out, trial_id)) != sha:
            raise W1RunError('bundle_file_changed:' + trial_id)
    w1_entries = registry.load(registry_path)
    sensitivity_entries = registry.load(sensitivity_registry_path)
    all_entries = [e for path in registry_paths for e in registry.load(path)]
    if not {e['preregistration_sha256'] for e in w1_entries} <= {e['preregistration_sha256'] for e in all_entries}:
        raise W1RunError('w1_registry_not_among_the_registries_given')
    l1 = _read_json(_bundle_path(out, 'L1'))
    if hrr._sha({k: v for k, v in l1.items() if k != 'bundle_sha256'}) != l1['bundle_sha256']:
        raise W1RunError('l1_bundle_hash_mismatch')
    trials = {}
    for trial_id, arm in w1_eval.L1_ARMS.items():
        record = w1_eval.l1_preregister(*w1_eval.l1_design(pools_dir, l1_params()), l1_params(), L1_EXIT, arm=arm,
                                        sol_usd_source='series:' + l1['sol_usd_series']['sha256'],
                                        creator_history_sha256=l1['creator_history']['sha256'])
        entry = _entry_for(w1_entries, record['preregistration_sha256'])
        trials[trial_id] = w1_eval.trial_from_l1_bundle(l1, trial_id, entry, pools_dir)
    for trial_id in V2_ARMS:
        bundle = _read_json(_bundle_path(out, trial_id))
        _entry_for(w1_entries, bundle['preregistration_sha256'])
        trials[trial_id] = w1_eval.trial_from_v2_bundle(bundle, trial_id)
    l10 = _read_json(_bundle_path(out, w1_eval.SENSITIVITY_ID))
    record = w1_eval.l1_preregister(*w1_eval.l1_design(pools_dir, hrr.ReplayParams(**dict(vars(l1_params()), latency_slots=10))),
                                    hrr.ReplayParams(**dict(vars(l1_params()), latency_slots=10)), L1_EXIT, arm='master',
                                    sol_usd_source='series:' + l10['sol_usd_series']['sha256'],
                                    creator_history_sha256=l10['creator_history']['sha256'])
    sensitivity = w1_eval.trial_from_l1_bundle(l10, w1_eval.SENSITIVITY_ID,
                                               _entry_for(sensitivity_entries, record['preregistration_sha256']),
                                               pools_dir, arm='master')
    b = plan(s0, evaluation_slots=evaluation_slots)
    report = w1_eval.evaluate_w1(trials, all_entries, start=b['evaluation'][0], end=b['evaluation'][1],
                                 embargo_slots=embargo_slots, sensitivity_latency10=sensitivity,
                                 sensitivity_entries=sensitivity_entries, n_boot=n_boot)
    report['bundles_sha256'] = sums
    report['w1_bounds'] = b
    _write_json(Path(out) / 'w1_report.json', report)
    return report
