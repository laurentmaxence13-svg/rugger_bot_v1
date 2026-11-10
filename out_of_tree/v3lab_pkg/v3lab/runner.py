"""Run the plan's trials on a visible-only pack with the FROZEN execution and accounting (R02 V-E).

``run_pool`` mirrors ``bot.master_v2.harness.run_policy_pool`` call for call: the same replay, the
same fee estimator, latency, own impact, costs, clock exit, migration and window rules, the same
trade row (``hrr._trade``). A V3 trial can differ from the reference only by its decisions:
* a V3 policy receives ``v3_extras`` next to the frozen native features, computed on the very
  history slice ``PolicyArm.entry`` hands over (``_WithHistory``), nothing after it;
* a probe arm additionally records the exact liquidation value after every real event.
A record keeps a ``v3`` block the frozen accounting never reads: the instant round-trip cost of
the entry (buy, then sell at once on the state our own buy left) and, for a probe, the mark path.

Every trial is appended to the V3 registry (a separate hash chain) BEFORE its replay.
"""
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from bot.market.collector import summarize
from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.market.replay import replay
from bot.master_v2 import registry
from bot.master_v2.harness import (PolicyArm, clock_latency_s, code_fingerprint, hold_gap_slots, rule_dict,
                                   validate_run_params)
from bot.master_v2.validation import preregistration
from bot.p4 import historical_research_replay as hrr

from v3lab import plan
from v3lab.features import v3_extras
from v3lab.pack import Pack, trial_objects

SCHEMA = 'rugger-master-v3-lab-v1'
FINGERPRINT_MODULES = ('features.py', 'pack.py', 'plan.py', 'policies.py', 'runner.py')


def v3lab_fingerprint():
    """sha256 over the V3 modules that choose the data, decide and build a bundle (not covered by the frozen one)."""
    root = Path(__file__).resolve().parent
    rows = [(name, hashlib.sha256((root / name).read_bytes()).hexdigest()) for name in FINGERPRINT_MODULES]
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


class _WithHistory:
    """Hands a V3 policy the extras of the history slice the frozen arm is deciding on."""

    def __init__(self, policy):
        self.policy, self.history = policy, None

    @property
    def name(self):
        return self.policy.name

    def params(self):
        return self.policy.params()

    def max_entry_age_s(self):
        return self.policy.max_entry_age_s()

    def decide(self, features, facts):
        return self.policy.decide(dict(features, **v3_extras(self.history, facts)), facts)


class V3Arm(PolicyArm):
    """The frozen ``PolicyArm`` (window cutoff, whole-transaction rule, journal, exits), unchanged."""

    def __init__(self, policy, *args, record_path=False):
        wrapped = _WithHistory(policy) if getattr(policy, 'needs_v3_features', False) else policy
        super().__init__(wrapped, *args)
        self.record_path, self.path = record_path, []

    def entry(self, history):
        if isinstance(self.policy, _WithHistory):
            self.policy.history = history
        return super().entry(history)

    def exit(self, history, position, mark):
        fired = super().exit(history, position, mark)
        if self.record_path:
            self.path.append([history[-1].block_time - position.entry_time, mark])
        return fired


def trial_window(entry, manifest, rule, params):
    """Frozen rule M1 with the entry cutoff moved back to cover this exit rule's bounded hold."""
    source = entry if ('entry_cutoff_slot' in entry or 'window_slot_max' in entry) else manifest
    cutoff, end = source.get('entry_cutoff_slot'), source.get('window_slot_max')
    if cutoff is None and end is None:
        return None
    if type(cutoff) is not int or type(end) is not int or not 0 < cutoff < end:
        raise ValueError('invalid_collection_window')
    gap = hold_gap_slots(rule, params)
    if gap is None:
        raise ValueError('collection_window_requires_bounded_max_hold_s')
    return dict(entry_cutoff_slot=min(cutoff, end - gap), window_slot_max=end, minimum_gap_slots=gap)


def _v3_block(result, events, model, arm):
    block = {}
    if result.entry_index is not None and result.tokens:
        fill = buy_exact_in(events[result.entry_index].state_after(), result.spent, result.fee_rate_ppm)
        if fill.amount_out != result.tokens:
            raise ValueError('entry_fill_not_reproduced')
        cost = result.spent + 2 * model.tx_cost
        try:
            immediate = sell_exact_in(fill.after, result.tokens, result.fee_rate_ppm).amount_out
        except CurveError:
            immediate = None
        block.update(cost_lamports=cost, immediate_mark=immediate, round_trip_cost_return=(
            None if immediate is None else (immediate - cost) / cost))
    if arm.record_path:
        block['path'] = arm.path
    return block


def run_pool(archive, policy, exit_rule, params, *, quote_mint, window=None, record_path=False,
             entry_lamports=hrr.ENTRY_LAMPORTS):
    """One pool; same steps, in the same order, as ``harness.run_policy_pool``."""
    validate_run_params(params)
    summary, timeline = summarize(archive)
    timeline, migration = hrr.usable_timeline(archive, summary, timeline)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    arm = V3Arm(policy, exit_rule, facts, Counter(e.signature for e in timeline.events), entry_lamports, window,
                record_path=record_path)
    model = params.execution_model()
    if exit_rule.clock_exit:
        model = replace(model, clock_exit_latency_s=clock_latency_s(params))
    result = replay(timeline, arm, model, quote_mint=quote_mint)
    if result.clock_exit is not None:
        arm.exit_trigger = dict(reason='max_hold_clock', index=result.clock_exit['last_index'], mark=result.received)
    row = hrr._trade(result, timeline.events, arm, params)
    if result.clock_exit is not None:
        row = hrr.clock_exit_row(row, result, timeline.events, params)
    if migration is not None:
        row = hrr._migrated(hrr._exit_after_migration(row, migration))
    row = hrr._apply_window(row, window)
    record = dict(pool=archive.pool, creator=facts['creator'], created_slot=facts['creation_slot'],
                  signed_creator_verified=facts['signed_creator_verified'], trades=len(timeline.events),
                  journal=arm.journal, trade=row)
    if migration is not None:
        record['migration'] = migration
    if window is not None:
        record['window'] = window
    record['v3'] = _v3_block(result, timeline.events, model, arm)
    return record


def preregister(manifest_sha256, row):
    """Pre-registration record of a plan trial, computable before any replay."""
    policy, rule, params = trial_objects(row)
    validate_run_params(params)
    design = dict(code_sha256=code_fingerprint(), v3lab_sha256=v3lab_fingerprint(), manifest_sha256=manifest_sha256,
                  plan_sha256=plan.plan_sha256(), trial=row['id'], record_path=bool(row.get('record_path')))
    sha = preregistration(policy.name, dict(policy=policy.params(), exit=rule_dict(rule), replay=asdict(params)),
                          design)
    return dict(preregistration_sha256=sha, policy=policy.name, policy_params=policy.params(),
                exit_rule=rule_dict(rule), replay_params=asdict(params), **design)


def check_registry(path, manifest_sha256):
    """A V3 registry holds V3 plan trials only: never the P0 / W1 registry, never more than the plan allows."""
    entries = registry.load(path)
    if any('plan_sha256' not in entry or 'trial' not in entry for entry in entries):
        raise ValueError('not_a_v3_registry')
    mine = [entry for entry in entries if entry['manifest_sha256'] == manifest_sha256]
    if len(mine) > plan.PLAN['max_trials']:
        raise ValueError('more_trials_than_the_plan_allows')
    return entries


def run_trial(pack_dir, trial_id, *, expect_manifest_sha256, registry_path, registered_at, out_dir):
    """Register, then replay one plan trial over the visible pools; write ``<out_dir>/<trial>.json``."""
    row = plan.trial(trial_id)
    out = Path(out_dir) / f'{trial_id}.json'
    if out.exists():
        raise ValueError('output_exists:%s' % out.name)
    pack = Pack(pack_dir, expect_manifest_sha256)
    record = preregister(pack.manifest_sha256, row)
    entries = check_registry(registry_path, pack.manifest_sha256)
    mine = [e for e in entries if e['manifest_sha256'] == pack.manifest_sha256]
    known = any(e['preregistration_sha256'] == record['preregistration_sha256'] for e in mine)
    if not known and len(mine) >= plan.PLAN['max_trials']:
        raise ValueError('plan_trial_budget_spent')
    entry, new = registry.register(registry_path, record, registered_at=registered_at)   # before the replay
    policy, rule, params = trial_objects(row)
    pools, excluded = [], []
    for manifest_entry, archive, segment in pack.pools():
        window = trial_window(manifest_entry, pack.manifest, rule, params)
        try:
            result = run_pool(archive, policy, rule, params, quote_mint=manifest_entry['quote_mint'], window=window,
                              record_path=bool(row.get('record_path')))
        except hrr.PoolExcluded as exc:
            excluded.append(dict(pool=archive.pool, file=manifest_entry['file'], reasons=exc.reasons))
            continue
        pools.append(dict(result, segment=segment))
    if len(pools) + len(excluded) != len(pack.entries):
        raise ValueError('pool_accounting_mismatch')
    bundle = dict(
        schema=SCHEMA, category=hrr.CATEGORY, policy_status='MASTER_RESEARCH', status='EXPLORATORY',
        trial=trial_id, role=row['role'], hypothesis=row.get('hypothesis'), base=row.get('base'),
        policy=policy.name, policy_params=policy.params(), exit_rule=rule_dict(rule), params=asdict(params),
        preregistration_sha256=entry['preregistration_sha256'], registry_index=entry['index'],
        newly_registered=new, code_sha256=record['code_sha256'], v3lab_sha256=record['v3lab_sha256'],
        plan_sha256=record['plan_sha256'],
        fixtures=dict(manifest_sha256=pack.manifest_sha256, files_read=dict(sorted(pack.files_read.items())),
                      source_manifest_sha256=pack.block['source_manifest_sha256'],
                      embargo_slots=pack.block['embargo_slots']),
        pools=pools, excluded_pools=excluded,
        flags=dict(admissible_in_paper_ledger=False, counted_in_master_gate=False, master_operational_trade=False,
                   financial_order_submitted=False, sol_usd_used=False, open_positions_in_pnl=False,
                   holdout_read=False, w1_data_read=False, promotion_allowed=False))
    bundle['bundle_sha256'] = hrr._sha(bundle)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    # Identifiers only: no result is shown at run time.
    return dict(trial=trial_id, pools=len(pools), excluded=len(excluded),
                preregistration_sha256=bundle['preregistration_sha256'], bundle_sha256=bundle['bundle_sha256'],
                registry_index=entry['index'], newly_registered=new, registry_head=registry.head(registry_path))
