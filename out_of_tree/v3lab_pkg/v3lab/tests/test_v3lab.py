"""v3lab: frozen bookkeeping reused as is, no look-ahead, data guards, counting and verdict logic.

Run from a checkout of the frozen W1 tree with ``PYTHONPATH=<v3lab_pkg>`` (never with w1aux).
"""
from collections import Counter
from dataclasses import dataclass, replace
import io
import json
from pathlib import Path
import shutil
import sys

import pytest

from bot.market.collector import summarize
from bot.master_v2 import harness, policies as v2, registry
from bot.master_v2.harness import ExitRule, Policy
from bot.master_v2.validation import bootstrap_mean_ci
from bot.p4 import historical_research_replay as hrr
from v3lab import __main__ as cli, evaluate as ev, features, pack, plan, policies, runner

FIXTURES = Path('tests/fixtures/launchlab_sol_pools')
PARAMS = hrr.ReplayParams(**plan.REPLAY)


@pytest.fixture(scope='module')
def archives():
    return hrr.load_fixtures(FIXTURES)[2]


def _manual_pack(out, assignment):
    """A visible pack with a hand-made segment assignment (3 fixture pools cannot fill 4 segments)."""
    raw = (FIXTURES / 'MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    digests = {entry['pool']: entry['sha256'] for entry in manifest['pools']}
    counts = dict(Counter(assignment.values()))
    return pack._write(FIXTURES, Path(out), manifest, raw, assignment, digests, {}, counts,
                       pack.required_embargo_slots(), pack.required_embargo_slots())


@pytest.fixture()
def visible(tmp_path, archives):
    pools = sorted(archive.pool for _entry, archive in archives)
    summary = _manual_pack(tmp_path / 'vis', dict(zip(pools, plan.SEGMENTS)))
    return tmp_path / 'vis', summary['manifest_sha256']


# --- V-E: the frozen bookkeeping, unchanged ---------------------------------------------------

@pytest.mark.parametrize('policy, rule', [
    (v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=25, clock_exit=True)),
    (v2.RandomEntry(), ExitRule(max_hold_s=25, clock_exit=True)),
    (v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=300, clock_exit=True, stop_loss=0.30, trailing=0.25)),
    (v2.FixedDelay(delay_s=0), ExitRule(max_hold_s=40, stop_loss=0.2, take_profit=0.5)),
])
def test_run_pool_is_the_frozen_run_policy_pool_for_a_frozen_policy(archives, policy, rule):
    for entry, archive in archives:
        frozen = harness.run_policy_pool(archive, policy, rule, PARAMS, quote_mint=entry['quote_mint'])
        ours = runner.run_pool(archive, policy, rule, PARAMS, quote_mint=entry['quote_mint'])
        assert {k: v for k, v in ours.items() if k != 'v3'} == frozen


def test_recording_the_path_changes_no_decision_and_no_trade_row(archives):
    policy, rule = v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=900, clock_exit=True)
    for entry, archive in archives:
        plain = runner.run_pool(archive, policy, rule, PARAMS, quote_mint=entry['quote_mint'])
        probe = runner.run_pool(archive, policy, rule, PARAMS, quote_mint=entry['quote_mint'], record_path=True)
        assert (probe['trade'], probe['journal']) == (plain['trade'], plain['journal'])
        if probe['trade']['entry_index'] is not None:
            assert all(age >= 0 and mark >= 0 for age, mark in probe['v3']['path'])


def test_cost0_is_the_instant_round_trip_and_bounds_a_silent_cycle(archives):
    """A pool with no trade after our entry closes exactly at its instant round-trip cost."""
    policy, rule = v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=25, clock_exit=True)
    seen = 0
    for entry, archive in archives:
        row = runner.run_pool(archive, policy, rule, PARAMS, quote_mint=entry['quote_mint'], record_path=True)
        trade, block = row['trade'], row['v3']
        if trade['entry_index'] is None:
            assert block == {'path': []}
            continue
        seen += 1
        assert block['cost_lamports'] == trade['spent'] + trade['tx_costs'] and block['round_trip_cost_return'] < 0
        if not block['path']:
            assert trade['net_return'] == pytest.approx(block['round_trip_cost_return'])
    assert seen >= 2


def test_a_low_fee_veto_is_an_exact_ablation_of_its_base_arm(archives):
    rule = ExitRule(max_hold_s=25, clock_exit=True)
    veto = policies.LowFeeDelay5s()
    base = v2.FixedDelay(**veto.base_arm()['params'])
    kept = removed = 0
    for entry, archive in archives:
        b = runner.run_pool(archive, base, rule, PARAMS, quote_mint=entry['quote_mint'])
        f = runner.run_pool(archive, veto, rule, PARAMS, quote_mint=entry['quote_mint'])
        if f['trade']['entry_index'] is not None:
            kept += 1
            assert f['trade'] == b['trade'] and f['trade']['fee_rate_ppm'] <= veto.max_fee_ppm
        elif b['trade']['entry_index'] is not None:
            removed += 1
            assert b['trade']['fee_rate_ppm'] > veto.max_fee_ppm
            assert f['journal'][-1]['reasons'] == ['veto_fee_above_max']
    assert kept >= 1 and removed >= 1


# --- V-D: no look-ahead -----------------------------------------------------------------------

@dataclass(frozen=True)
class _Leaky(Policy):
    """Test only: reads the number of events of the WHOLE pool (a future leak)."""
    total: int = 0
    name = 'test-leaky'
    needs_v3_features = True

    def decide(self, features_, facts):
        return ('ENTER', ['leak']) if features_['trades'] * 2 >= self.total else ('WAIT', ['leak'])


def _decisions(events, facts, policy, upto, per_tx):
    """Journal of the frozen arm fed the causal slices of ``events[:upto]``.

    ``per_tx`` (events per transaction) comes from the real timeline in every case: a transaction is
    atomic, so knowing it whole is not a look-ahead; only what follows it is the future.
    """
    arm = runner.V3Arm(policy, ExitRule(max_hold_s=25, clock_exit=True), facts, per_tx, hrr.ENTRY_LAMPORTS, None)
    for k in range(upto):
        if arm.entry(events[:k + 1]):
            break
    return arm.journal


@pytest.mark.parametrize('policy', [policies.LowFeeDelay5s(), policies.GraduationRun(),
                                    policies.GraduationRun(min_progress_ppm=1, min_gain_60s_ppm=1)])
def test_decisions_do_not_change_when_the_future_changes(archives, policy):
    """Future shift (R02 V-D): replace everything after a decision, the journal up to it is identical."""
    checked = 0
    for _entry, archive in archives:
        summary, timeline = summarize(archive)
        events = hrr.usable_timeline(archive, summary, timeline)[0].events
        facts = dict(hrr.creation_facts(archive), pool=archive.pool)
        per_tx = Counter(e.signature for e in events)
        full = _decisions(events, facts, policy, len(events), per_tx)
        for cut in sorted({1, len(events) // 3, len(events) // 2, len(events) - 1} - {0}):
            # Same past, another future: the tail is replaced by copies of one late event moved far away.
            tail = tuple(replace(events[-1], slot=events[cut - 1].slot + 10_000 + i, signature=f'future{i}',
                                 block_time=events[cut - 1].block_time + 5_000 + i) for i in range(3))
            shifted = _decisions(tuple(events[:cut]) + tail, facts, policy, cut, per_tx)
            assert shifted == [row for row in full if row['index'] < cut]
            assert features.v3_extras(events[:cut], facts) == features.v3_extras((tuple(events[:cut]) + tail)[:cut], facts)
            checked += 1
    assert checked >= 6


def test_the_future_shift_test_does_detect_a_leak(archives):
    _entry, archive = max(archives, key=lambda item: len(item[1].transactions))
    summary, timeline = summarize(archive)
    events = hrr.usable_timeline(archive, summary, timeline)[0].events
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    cut, per_tx = len(events) // 2, Counter(e.signature for e in events)
    honest = _decisions(events, facts, _Leaky(total=len(events)), cut, per_tx)
    leaked = _decisions(events[:cut], facts, _Leaky(total=cut), cut, per_tx)   # the leak sees a shorter future
    assert honest != leaked


def test_an_entry_never_lands_in_the_decision_transaction(archives):
    for row in plan.TRIALS:
        policy, rule, params = pack.trial_objects(row)
        for entry, archive in archives:
            trade = runner.run_pool(archive, policy, rule, params, quote_mint=entry['quote_mint'])['trade']
            if trade['entry_index'] is not None:
                assert trade['entry_index'] >= trade['decision_index'] and trade['entry_slot'] >= trade['decision_slot']
                assert params.latency_slots >= 1


# --- policies ---------------------------------------------------------------------------------

def _features(**over):
    base = dict(age_s=120, progress_ppm=400_000, progress_gain_60s_ppm=80_000, top1_token_share=0.1,
                creator_sold_lamports=0, fee_rate_ppm_causal=12_500)
    return dict(base, **over)


def test_graduation_run_decisions():
    run, facts = policies.GraduationRun(), dict(signed_creator_verified=True)
    assert run.decide(_features(), facts) == ('ENTER', ['fast_fill_mid_curve'])
    assert run.decide(_features(progress_ppm=299_999), facts) == ('WAIT', ['curve_not_filled_enough'])
    assert run.decide(_features(progress_gain_60s_ppm=49_999), facts) == ('WAIT', ['fill_too_slow'])
    assert run.decide(_features(top1_token_share=0.21), facts) == ('WAIT', ['concentrated_holder'])
    assert run.decide(_features(progress_ppm=800_001), facts)[0] == 'NO_TRADE'
    assert run.decide(_features(age_s=601), facts)[0] == 'NO_TRADE'
    assert run.decide(_features(creator_sold_lamports=1), facts) == ('NO_TRADE', ['creator_sold'])
    assert run.decide(_features(), dict(signed_creator_verified=False)) == ('NO_TRADE', ['signed_creator_unverified'])


def test_low_fee_decisions():
    veto, facts = policies.LowFeeDelay5s(), dict(signed_creator_verified=True)
    assert veto.decide(_features(age_s=4), facts) == ('WAIT', ['before_target_delay'])
    assert veto.decide(_features(age_s=5), facts) == ('ENTER', ['low_fee_tier'])
    assert veto.decide(_features(age_s=5, fee_rate_ppm_causal=15_001), facts) == ('NO_TRADE', ['veto_fee_above_max'])
    assert veto.decide(_features(age_s=36), facts)[0] == 'NO_TRADE'


def test_the_plan_is_hashed_and_every_trial_builds():
    assert len(plan.plan_sha256()) == 64 and plan.PLAN['max_trials'] == len(plan.TRIALS) == 8
    assert plan.canonical() == plan.canonical(json.loads(plan.canonical()))
    ids = [row['id'] for row in plan.TRIALS]
    assert len(set(ids)) == len(ids)
    for row in plan.TRIALS:
        policy, rule, _params = pack.trial_objects(row)
        assert rule.clock_exit and rule.max_hold_s and policy.max_entry_age_s() is not None
        if row.get('base'):
            assert plan.trial(row['base'])['role'] == 'reference'
    assert pack.required_embargo_slots() == 6018


# --- V-A: data guards -------------------------------------------------------------------------

def test_build_copies_visible_pools_only_and_lists_the_others_as_sealed(tmp_path):
    summary = pack.build(FIXTURES, tmp_path / 'vis')
    files = sorted(p.name for p in (tmp_path / 'vis').glob('*.json.gz'))
    segments = json.loads((tmp_path / 'vis' / 'SEGMENTS.json').read_text())
    sealed = (tmp_path / 'vis' / 'SEALED_SHA256.txt').read_text().split()
    assert files == sorted(f'{pool}.json.gz' for pool in segments) and summary['visible_pools'] == len(files)
    assert len(files) + len(sealed) == summary['source_pools'] == 3 and len(sealed) >= 1
    opened = pack.Pack(tmp_path / 'vis', summary['manifest_sha256'])
    assert [entry['pool'] for entry, _archive, _segment in opened.pools()] == sorted(segments)
    assert set(opened.files_read) == {'MANIFEST.json', 'SEGMENTS.json', 'SEALED_SHA256.txt', *files}
    with pytest.raises(pack.PackError, match='output_directory_already_exists'):
        pack.build(FIXTURES, tmp_path / 'vis')
    with pytest.raises(pack.PackError, match='embargo_shorter_than_outcome_horizon'):
        pack.build(FIXTURES, tmp_path / 'short', embargo_slots=100)
    with pytest.raises(pack.PackError, match='source_is_already_a_visible_pack'):
        pack.build(tmp_path / 'vis', tmp_path / 'again')


def test_a_pack_is_refused_unless_anchored_visible_and_free_of_sealed_or_w1_data(visible, tmp_path, monkeypatch):
    directory, sha = visible
    with pytest.raises(pack.PackError, match='not_the_anchored_one'):
        pack.Pack(directory, '0' * 64)
    raw_sha = __import__('hashlib').sha256((FIXTURES / 'MANIFEST.json').read_bytes()).hexdigest()
    with pytest.raises(pack.PackError, match='not_a_visible_only_pack'):
        pack.Pack(FIXTURES, raw_sha)                                   # a raw export (P0 or W1) is refused
    extra = tmp_path / 'extra'
    shutil.copytree(directory, extra)
    (extra / 'Sealed111.json.gz').write_bytes(b'x')
    with pytest.raises(pack.PackError, match='pack_files_differ_from_manifest'):
        pack.Pack(extra, sha)
    changed = tmp_path / 'changed'
    shutil.copytree(directory, changed)
    (changed / 'SEGMENTS.json').write_text('{}')
    with pytest.raises(pack.PackError, match='pack_side_file_changed'):
        pack.Pack(changed, sha)
    pools = sorted(json.loads((directory / 'SEGMENTS.json').read_text()))
    summary = _manual_pack(tmp_path / 'two', dict(zip(pools[:2], plan.SEGMENTS)))
    two = pack.Pack(tmp_path / 'two', summary['manifest_sha256'])
    assert len(two.sealed) == 1
    monkeypatch.setattr(plan, 'S0_W1', 464_000_000)                    # the fixture slots are now "W1"
    with pytest.raises(pack.PackError, match='pack_built_with_another_w1_guard'):
        pack.Pack(directory, sha)
    with pytest.raises(pack.PackError, match='w1_slot_refused'):
        pack.build(FIXTURES, tmp_path / 'w1')


# --- V-C: registry, counting, run and evaluation ----------------------------------------------

def test_run_registers_before_replay_and_evaluate_counts_every_trial(visible, tmp_path):
    directory, sha = visible
    reg, out = tmp_path / 'v3_trials.jsonl', tmp_path / 'runs'
    buffer = io.StringIO()
    assert cli.main(['run', '--pack', str(directory), '--expect-manifest-sha', sha, '--registry', str(reg),
                     '--out', str(out), '--at', '2026-11-10T00:00:00+00:00'], out=buffer) == 0
    lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
    assert [row['trial'] for row in lines] == [row['id'] for row in plan.TRIALS]
    assert all(set(row) == {'trial', 'pools', 'excluded', 'preregistration_sha256', 'bundle_sha256',
                            'registry_index', 'newly_registered', 'registry_head'} for row in lines)
    entries = registry.load(reg)
    assert len(entries) == 8 and all(e['plan_sha256'] == plan.plan_sha256() for e in entries)
    bundle = json.loads((out / 'V3-06.json').read_text())
    assert bundle['flags']['promotion_allowed'] is False and bundle['flags']['holdout_read'] is False
    assert set(bundle['fixtures']['files_read']) >= {'MANIFEST.json', 'SEGMENTS.json', 'SEALED_SHA256.txt'}
    assert {row['segment'] for row in bundle['pools']} == set(plan.SEGMENTS)
    with pytest.raises(ValueError, match='output_exists'):
        runner.run_trial(directory, 'V3-01', expect_manifest_sha256=sha, registry_path=reg,
                         registered_at='2026-11-10T00:00:00+00:00', out_dir=out)
    report_path = tmp_path / 'report.json'
    buffer = io.StringIO()
    assert cli.main(['evaluate', '--bundles', str(out), '--registry', str(reg), '--out', str(report_path),
                     '--n-boot', '200'], out=buffer) == 0
    printed = json.loads(buffer.getvalue())
    report = json.loads(report_path.read_text())
    assert printed['n_cumulative'] == report['n_cumulative'] == 25 + 8 and report['status'] == 'EXPLORATORY'
    assert report['verdicts'] == dict(H1='NOT_EVALUABLE', H2='NOT_EVALUABLE', H3='NOT_EVALUABLE')
    assert report['flags']['promotion_allowed'] is False and report['flags']['profitability_demonstrated'] is False
    assert set(report['arms']) == {row['id'] for row in plan.TRIALS}
    (out / 'V3-08.json').rename(tmp_path / 'hidden.json')
    with pytest.raises(ValueError, match='registered_trials_missing:1'):
        ev.evaluate_directory(out, reg, n_boot=200)


def test_the_p0_or_w1_registry_is_never_written(visible, tmp_path):
    directory, sha = visible
    reg = tmp_path / 'trials.jsonl'
    record = harness.preregister(FIXTURES, v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=25, clock_exit=True), PARAMS)
    registry.register(reg, record, registered_at='2026-11-07T00:00:00+00:00')      # a V2 / W1 style registry
    before = reg.read_bytes()
    with pytest.raises(ValueError, match='not_a_v3_registry'):
        runner.run_trial(directory, 'V3-01', expect_manifest_sha256=sha, registry_path=reg,
                         registered_at='2026-11-10T00:00:00+00:00', out_dir=tmp_path / 'runs')
    assert reg.read_bytes() == before and not (tmp_path / 'runs').exists()


def test_the_cli_refuses_to_share_a_process_with_w1aux(monkeypatch):
    monkeypatch.setitem(sys.modules, 'w1aux', object())
    with pytest.raises(SystemExit, match='must not share a process'):
        cli.main(['plan'])
    assert not any(name.startswith('w1aux.') for name in sys.modules)


# --- statistics and verdict logic on hand-made bundles ----------------------------------------

def _row(pool, creator, segment, ret, *, entered=True, outcome='closed', fee=12_500, entry_index=3):
    cost = 100_210_000
    trade = dict(outcome=outcome if entered else 'no_entry', entry_index=entry_index if entered else None,
                 entry_slot=10 if entered else None, spent=100_000_000, tx_costs=210_000, failed_attempt_costs=0,
                 pnl_lamports=round(ret * cost) if entered and outcome == 'closed' else None, fee_rate_ppm=fee,
                 exit_trigger=dict(reason='max_hold_clock'))
    return dict(pool=pool, creator=creator, segment=segment, trade=trade, journal=[dict(intent='NO_TRADE', reasons=['veto_fee_above_max'])],
                v3=dict(cost_lamports=cost, immediate_mark=round(cost * 0.95), round_trip_cost_return=-0.05))


def _bundle(trial_id, rows):
    return dict(trial=trial_id, pools=rows, preregistration_sha256=trial_id, plan_sha256=plan.plan_sha256(),
                code_sha256='c', v3lab_sha256='v', fixtures=dict(manifest_sha256='m'))


def _entries(ids):
    return [dict(preregistration_sha256=i, manifest_sha256='m', plan_sha256=plan.plan_sha256(), trial=i,
                 code_sha256='c', v3lab_sha256='v', entry_sha256='head') for i in ids]


def _population(n=30):
    return [(f'p{segment[0]}{i:02d}', f'c{segment[0]}{i:02d}', segment) for segment in plan.SEGMENTS for i in range(n)]


def test_paired_bootstrap_matches_the_frozen_interval_and_holm_is_monotone():
    values, groups = [0.1, -0.2, 0.05, 0.3, -0.1, 0.2], ['a', 'a', 'b', 'c', 'c', 'd']
    means = ev.cluster_bootstrap_means(values, groups, n_boot=500, seed=7)
    assert tuple(ev._interval(means, 0.05)) == bootstrap_mean_ci(values, groups, n_boot=500, seed=7)
    assert ev.holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    assert ev.holm([0.5, None, 0.01]) == [0.5, None, 0.02]
    assert ev.cvar([-1, 0.5, 0.2] + [0.1] * 17) == -1 and ev.cvar([]) is None       # ceil(5 % of 20) = 1 worst
    assert ev.cvar([-1.0, -0.5] + [0.1] * 39) == pytest.approx(-1.4 / 3)            # ceil(5 % of 41) = 3 worst


def test_verdicts_follow_the_pre_registered_criteria():
    pop = _population(60)
    ref = _bundle('V3-01', [_row(p, c, s, -0.05, fee=12_500 if i % 2 else 25_000) for i, (p, c, s) in enumerate(pop)])
    better = _bundle('V3-03', [_row(p, c, s, 0.02 + 0.001 * (i % 7)) for i, (p, c, s) in enumerate(pop)])
    worse = _bundle('V3-04', [_row(p, c, s, -0.20) for p, c, s in pop])
    tail = _bundle('V3-05', [_row(p, c, s, 0.30 if i % 3 else -1.0, outcome='closed' if i % 3 else 'migrated_unpriced')
                             for i, (p, c, s) in enumerate(pop)])
    fee = _bundle('V3-07', [_row(p, c, s, -0.05, entered=bool(i % 2)) for i, (p, c, s) in enumerate(pop)])
    run = _bundle('V3-08', [_row(p, c, s, 0.4 if i % 4 else -0.3, entered=i % 60 < 50) for i, (p, c, s) in enumerate(pop)])
    bundles = {b['trial']: b for b in (ref, better, worse, tail, fee, run)}
    report = ev.evaluate(bundles, registry_entries=_entries(sorted(bundles)), n_boot=400)
    h2 = report['hypotheses']['H2']
    assert h2['by_candidate'] == {'V3-03': 'PASS_EXPLORATORY', 'V3-04': 'REJECTED_ON_P0', 'V3-05': 'REJECTED_ON_P0'}
    assert h2['candidates']['V3-05']['validation']['cvar_5pct_candidate'] == -1.0       # the tail rule rejects it
    assert report['verdicts'] == dict(H1='REJECTED_ON_P0', H2='PASS_EXPLORATORY', H3='PASS_EXPLORATORY')
    assert report['hypotheses']['H1']['validation']['kept_minus_removed'] == pytest.approx(0.0)
    assert report['n_cumulative'] == 25 + 6
    arm = report['arms']['V3-05']['validation']
    assert (arm['entered'], arm['closed'], arm['non_closed']) == (60, 40, {'migrated_unpriced': 20})
    assert arm['pessimistic_mean'] == pytest.approx((40 * 0.30 - 20) / 60) and arm['mean_cost0'] == pytest.approx(-0.05)
    assert arm['mean_drift'] == pytest.approx(0.35)
    few = dict(bundles, **{'V3-08': _bundle('V3-08', [_row(p, c, s, 0.4, entered=i % 60 < 19)
                                                       for i, (p, c, s) in enumerate(pop)])})
    assert ev.evaluate(few, registry_entries=_entries(sorted(few)), n_boot=400)['verdicts']['H3'] == 'NOT_EVALUABLE'
    with pytest.raises(ValueError, match='unregistered_runs'):
        ev.evaluate(bundles, registry_entries=_entries(['V3-01']), n_boot=400)
    with pytest.raises(ValueError, match='not_a_v3_registry'):
        ev.evaluate(bundles, registry_entries=[dict(preregistration_sha256='V3-01', manifest_sha256='m')], n_boot=400)


def test_paired_arms_must_share_their_entries():
    pop = _population(3)
    base = _bundle('V3-01', [_row(p, c, s, -0.05) for p, c, s in pop])
    moved = _bundle('V3-03', [_row(p, c, s, 0.1, entry_index=4) for p, c, s in pop])
    with pytest.raises(ValueError, match='paired_arms_do_not_share_their_entries'):
        ev.paired(base, moved, {p for p, _c, _s in pop}, n_boot=200)


def test_probe_reads_mfe_mae_and_the_horizon_curve():
    cost = 100_210_000
    row = _row('p', 'c', 'exploration', 0.0)
    row['v3'].update(immediate_mark=round(cost * 0.95), path=[[2, round(cost * 1.5)], [30, round(cost * 0.6)],
                                                              [200, round(cost * 0.9)]])
    out = ev.probe(_bundle('V3-06', [row]), {'p'})
    assert out['mfe_mean'] == pytest.approx(0.5, abs=1e-6) and out['mae_mean'] == pytest.approx(-0.4, abs=1e-6)
    assert out['peak_age_s_median'] == 2 and out['share_mfe_above']['0.25'] == 1.0
    curve = out['horizon_curve']
    assert curve['10']['mean'] == pytest.approx(0.5, abs=1e-6) and curve['25']['mean'] == pytest.approx(0.5, abs=1e-6)
    assert curve['60']['mean'] == pytest.approx(-0.4, abs=1e-6) and curve['900']['mean'] == pytest.approx(-0.1, abs=1e-6)


def test_a_table_bundle_builds_the_same_pack_without_opening_non_visible_files(tmp_path, monkeypatch):
    direct = pack.build(FIXTURES, tmp_path / 'direct')
    bundle = harness.run_policy(FIXTURES, v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=25, clock_exit=True), PARAMS)
    (tmp_path / 'run.json').write_text(json.dumps(bundle))
    opened, real = [], Path.read_bytes

    def spy(self):
        opened.append(self.name)
        return real(self)
    monkeypatch.setattr(Path, 'read_bytes', spy)
    via = pack.build(FIXTURES, tmp_path / 'via', table_bundle=tmp_path / 'run.json')
    monkeypatch.undo()
    assert via == direct
    segments = json.loads((tmp_path / 'via' / 'SEGMENTS.json').read_text())
    assert sorted(name for name in opened if name.endswith('.json.gz')) == sorted(f'{p}.json.gz' for p in segments)
    other = dict(bundle, fixtures=dict(bundle['fixtures'], manifest_sha256='0' * 64))
    (tmp_path / 'other.json').write_text(json.dumps(other))
    with pytest.raises(pack.PackError, match='table_bundle_is_not_of_this_export'):
        pack.build(FIXTURES, tmp_path / 'no', table_bundle=tmp_path / 'other.json')
