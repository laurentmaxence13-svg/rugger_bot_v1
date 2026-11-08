"""W1 evaluation (protocol R3, R5, R8): L1 trials registered before replay, W1 mode, tests, gate."""
from dataclasses import replace
import hashlib
from pathlib import Path
import random

import pytest

from bot.master_v2 import registry
from bot.master_v2 import w1_eval as w
from bot.master_v2.harness import code_fingerprint, code_modules as h_code_modules
from bot.p4 import historical_research_replay as hrr

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
W1_L1 = hrr.ReplayParams(latency_slots=4, sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')
CLOCK = hrr.ExitOptions(clock_horizon=True)
AT = '2026-11-08T00:00:00+00:00'


# --- R5 -----------------------------------------------------------------------------------

def test_l1_trials_are_registered_before_the_replay(tmp_path, monkeypatch):
    reg = tmp_path / 'trials.jsonl'

    def boom(*_args, **_kwargs):
        raise RuntimeError('replay')
    monkeypatch.setattr(hrr, 'run_replay', boom)
    with pytest.raises(RuntimeError):
        w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=reg, registered_at=AT)
    assert [e['policy'] for e in registry.load(reg)] == ['l1:master', 'l1:' + hrr.PLACEBO_ARM]


def test_l1_trial_documents(tmp_path):
    reg = tmp_path / 'trials.jsonl'
    trials = w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=reg, registered_at=AT)
    entries = registry.load(reg)
    assert set(trials) == {'M1', 'P1b'} and len(entries) == 2
    for key, trial in trials.items():
        entry = next(e for e in entries if e['preregistration_sha256'] == trial['preregistration_sha256'])
        assert trial['code_sha256'] == entry['code_sha256'] == code_fingerprint()
        assert entry['replay_params']['latency_slots'] == 4 and entry['exit_rule'] == CLOCK.record()
        assert all(set(p) >= {'pool', 'creator', 'created_slot', 'trade'} for p in trial['pools'])
        assert all(r['arm'] == w.L1_ARMS[key] for p in trial['pools'] for r in p['journal'])
    again = w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=reg, registered_at=AT)
    assert len(registry.load(reg)) == 2 and again['M1']['bundle_sha256'] == trials['M1']['bundle_sha256']


@pytest.mark.parametrize('change', [dict(latency_slots=2), dict(receipt_latency_ms=300),
                                    dict(exclude_launchlab_vault=True), dict(exit_horizon_ms=25_000),
                                    dict(priority_fee_lamports=1), dict(failed_attempt_fee_lamports=1)])
def test_every_l1_parameter_is_in_the_preregistration_r02_o_r9_2(change):
    manifest, windows = w.l1_design(PACK, W1_L1)
    base = w.l1_preregister(manifest, windows, W1_L1, CLOCK, arm='master', sol_usd_source='x', creator_history_sha256='h')
    other = hrr.ReplayParams(**dict(W1_L1.__dict__, **change))
    changed = w.l1_preregister(manifest, windows, other, CLOCK, arm='master', sol_usd_source='x', creator_history_sha256='h')
    assert changed['preregistration_sha256'] != base['preregistration_sha256']
    for kwargs in (dict(sol_usd_source='y'), dict(creator_history_sha256='g'), dict(arm=hrr.PLACEBO_ARM)):
        params = dict(dict(arm='master', sol_usd_source='x', creator_history_sha256='h'), **kwargs)
        assert w.l1_preregister(manifest, windows, W1_L1, CLOCK, **params)['preregistration_sha256'] != base['preregistration_sha256']
    assert w.l1_preregister(manifest, windows, W1_L1, hrr.ExitOptions(), arm='master', sol_usd_source='x',
                            creator_history_sha256='h')['preregistration_sha256'] != base['preregistration_sha256']
    with pytest.raises(ValueError, match='not_a_w1_l1_arm'):
        w.l1_preregister(manifest, windows, W1_L1, CLOCK, arm='reference', sol_usd_source='x', creator_history_sha256='h')


def _manifest_history():
    return hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest')


def test_l1_trial_checks_its_registry_entry(tmp_path):
    reg = tmp_path / 'trials.jsonl'
    w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=reg, registered_at=AT)
    entry = registry.load(reg)[0]
    bundle = hrr.run_replay(PACK, W1_L1, None, CLOCK, _manifest_history(), placebo_arm=True)
    assert w.trial_from_l1_bundle(bundle, 'M1', entry, PACK)['trial_id'] == 'M1'
    for bad, error in ((dict(entry, manifest_sha256='0' * 64), 'l1_trial_manifest_mismatch'),
                       (dict(entry, replay_params=dict(entry['replay_params'], latency_slots=2)), 'configuration'),
                       (dict(entry, exit_rule=hrr.ExitOptions().record()), 'configuration'),
                       (dict(entry, code_sha256='f' * 64), 'code_sha256_mismatch')):
        with pytest.raises(ValueError, match=error):
            w.trial_from_l1_bundle(bundle, 'M1', bad, PACK)
    with pytest.raises(ValueError, match='l1_trial_preregistration_mismatch'):
        w.trial_from_l1_bundle(bundle, 'P1b', entry, PACK)                     # the M1 entry is not P1b's


def test_l1_trial_refuses_a_bundle_replayed_otherwise_r02_f1(tmp_path):
    """R02 F1 probes: another creator history, no history, no placebo arm, another SOL/USD source."""
    reg = tmp_path / 'trials.jsonl'
    w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=reg, registered_at=AT)
    entry = registry.load(reg)[0]
    other = hrr.CreatorHistory([('someone', 1, 0, 'old')], 'other')
    for bundle, error in (
            (hrr.run_replay(PACK, W1_L1, None, CLOCK, other, placebo_arm=True), 'l1_trial_preregistration_mismatch'),
            (hrr.run_replay(PACK, W1_L1, None, CLOCK, None, placebo_arm=True), 'creator_history_required'),
            (hrr.run_replay(PACK, W1_L1, None, CLOCK, _manifest_history()), 'l1_trial_without_placebo_arm')):
        with pytest.raises(ValueError, match=error):
            w.trial_from_l1_bundle(bundle, 'M1', entry, PACK)
    declared = replace(W1_L1, sol_usd=151)
    bundle = hrr.run_replay(PACK, declared, None, CLOCK, _manifest_history(), placebo_arm=True)
    with pytest.raises(ValueError, match='l1_trial_preregistration_mismatch'):
        w.trial_from_l1_bundle(bundle, 'M1', dict(entry, replay_params=bundle['params']), PACK)


def test_latency10_sensitivity_is_registered_before_its_replay_outside_n_r02_f2(tmp_path, monkeypatch):
    trials_reg, sens_reg = tmp_path / 'trials.jsonl', tmp_path / 'sensitivity.jsonl'
    trials = w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=trials_reg, registered_at=AT)
    sens = w.run_l1_sensitivity(PACK, W1_L1, CLOCK, registry_path=sens_reg, registered_at=AT)
    assert len(registry.load(trials_reg)) == 2 and len(registry.load(sens_reg)) == 1
    entry, m1_entry = registry.load(sens_reg)[0], registry.load(trials_reg)[0]
    assert sens['trial_id'] == w.SENSITIVITY_ID and entry['replay_params']['latency_slots'] == 10
    assert dict(entry['replay_params'], latency_slots=4) == m1_entry['replay_params']
    w._check_sensitivity(sens, [entry], m1_entry, trials['M1'], {e['preregistration_sha256'] for e in registry.load(trials_reg)})
    with pytest.raises(ValueError, match='sensitivity_needs_the_m1_parameters'):
        w.run_l1_sensitivity(PACK, replace(W1_L1, latency_slots=10), CLOCK, registry_path=sens_reg, registered_at=AT)

    def boom(*_args, **_kwargs):
        raise RuntimeError('replay')
    monkeypatch.setattr(hrr, 'run_replay', boom)
    fresh = tmp_path / 'fresh.jsonl'
    with pytest.raises(RuntimeError):
        w.run_l1_sensitivity(PACK, W1_L1, CLOCK, registry_path=fresh, registered_at=AT)
    assert [e['replay_params']['latency_slots'] for e in registry.load(fresh)] == [10]


# --- R3 -----------------------------------------------------------------------------------

def test_w1_split_cuts_the_range_at_its_middle_slot_and_embargoes_the_start_of_b_r02_f4():
    pools = [dict(pool=f'p{i}', created_slot=slot) for i, slot in enumerate([5, 10, 20, 30, 54, 55, 64, 65, 99, 100, 200])]
    split = w.w1_split(pools, start=10, end=100, embargo_slots=10)
    assert split['boundary_slot'] == 55                                    # (10 + 100) // 2, data-independent
    assert split['outside'] == ['p0', 'p9', 'p10']                        # the end bound is excluded
    assert split['all'] == ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8']
    assert split['A'] == ['p1', 'p2', 'p3', 'p4'] and split['embargoed'] == ['p5', 'p6']
    assert split['B'] == ['p7', 'p8']
    crowded = [dict(pool=f'q{i}', created_slot=11 + i) for i in range(20)] + pools
    assert w.w1_split(crowded, start=10, end=100, embargo_slots=10)['boundary_slot'] == 55   # not by pool count
    for bad in (dict(start=10, end=10, embargo_slots=0), dict(start=1, end=2, embargo_slots=-1),
                dict(start=10, end=100, embargo_slots=45)):
        with pytest.raises(ValueError):
            w.w1_split(pools, **bad)


# --- R8 -----------------------------------------------------------------------------------

def test_mean_and_difference_tests():
    rng = random.Random(1)
    good = [0.05 + rng.gauss(0, 0.05) for _ in range(200)]
    zero = [rng.gauss(0, 0.05) for _ in range(200)]
    zero = [v - sum(zero) / len(zero) for v in zero]                 # exactly zero mean
    groups = [f'c{i % 60}' for i in range(200)]
    assert w.mean_test(good, groups, n_boot=2_000) < 0.001
    assert 0.1 < w.mean_test(zero, groups, n_boot=2_000) < 0.95
    assert w.mean_test([-v for v in good], groups, n_boot=2_000) > 0.99
    assert w.mean_test(good, groups, n_boot=500, seed=3) == w.mean_test(good, groups, n_boot=500, seed=3)
    assert w.difference_test(good, groups, zero, groups, n_boot=2_000) < 0.001
    assert w.difference_test(zero, groups, good, groups, n_boot=2_000) > 0.99
    assert w.mean_test([1.0], ['a']) is None and w.difference_test([1.0], ['a'], good, groups) is None


def test_holm_and_deflated_sharpe():
    assert w.holm(dict(a=0.01, b=0.04)) == dict(a=0.02, b=0.04)
    assert w.holm(dict(a=0.03, b=0.01)) == dict(a=0.03, b=0.02)
    assert w.holm(dict(a=0.01, b=0.015)) == dict(a=0.02, b=0.02)        # step-down stays monotone
    assert w.holm(dict(a=0.02, b=None)) == dict(a=0.04, b=None)         # m = 2, missing p counts as 1
    assert w.holm(dict(a=0.6, b=None)) == dict(a=1.0, b=None)
    values = [0.02 + 0.01 * ((i % 7) - 3) for i in range(100)]
    low, high = w.deflated_sharpe(values, [0.1, 0.3, -0.2], 32), w.deflated_sharpe(values, [0.1, 0.3, -0.2], 4)
    assert low < high                                         # more trials, stronger deflation
    assert w.deflated_sharpe(values, [0.1], 32) is None


# --- evaluation and gate -------------------------------------------------------------------

def _trade(pnl, outcome='closed', entered=True):
    return dict(entry_index=1 if entered else None, outcome=outcome if entered else 'no_entry',
                pnl_lamports=pnl if outcome == 'closed' and entered else None,
                spent=100_000_000, tx_costs=210_000, failed_attempt_costs=0)


def _trial(key, returns, *, start_slot=1_000, creators=80, not_closed=0, skip=()):
    pools = []
    for i, r in enumerate(returns):
        outcome = 'open_at_window_end' if i < not_closed else 'closed'
        pools.append(dict(pool=f'p{i}', creator=f'c{i % creators}', created_slot=start_slot + i,
                          signed_creator_verified=True, journal=[],
                          trade=_trade(None if r is None else int(r * 100_210_000), outcome, entered=r is not None and i not in skip)))
    prereg = _L1_RECORDS[key]['preregistration_sha256'] if key in _L1_RECORDS else hashlib.sha256(key.encode()).hexdigest()
    return dict(schema=w.TRIAL_SCHEMA, trial_id=key, engine='test', preregistration_sha256=prereg,
                code_sha256=CODE, manifest_sha256='m' * 64, bundle_sha256='b' * 64, pools=pools)


CODE = code_fingerprint()
_L1_RECORDS = {key: w.l1_preregister('m' * 64, 'w' * 64, params, CLOCK, arm='master', sol_usd_source='declared:150',
                                     creator_history_sha256='h')
               for key, params in (('M1', W1_L1), (w.SENSITIVITY_ID, replace(W1_L1, latency_slots=10)))}


def _sensitivity(mean=0.06, n=300):
    return _trial(w.SENSITIVITY_ID, [mean] * n)


def _registry(trials, extra=0):
    entries = [dict(_L1_RECORDS[key]) if key in _L1_RECORDS else dict(
        preregistration_sha256=t['preregistration_sha256'], code_sha256=t['code_sha256'],
        manifest_sha256=t['manifest_sha256']) for key, t in trials.items()]
    entries += [dict(preregistration_sha256=hashlib.sha256(f'p0trial{i}'.encode()).hexdigest(), code_sha256='x', manifest_sha256='p0')
                for i in range(25)]
    entries += [dict(preregistration_sha256=hashlib.sha256(f'extra{i}'.encode()).hexdigest(), code_sha256=CODE, manifest_sha256='m' * 64)
                for i in range(extra)]
    return entries


def _w1(m1_mean, n=300, not_closed=0, p1b_mean=-0.01):
    rng = random.Random(5)
    m1 = [m1_mean + rng.gauss(0, 0.03) for _ in range(n)]
    trials = dict(M1=_trial('M1', m1, not_closed=not_closed),
                  P1b=_trial('P1b', [p1b_mean + rng.gauss(0, 0.1) for _ in range(n)]),
                  P1=_trial('P1', [-0.05] * n), P2=_trial('P2', [None] * n), S1=_trial('S1', [-0.005 + rng.gauss(0, 0.1) for _ in range(n)]))
    # Placebo and secondary arms near zero: the DSR spread then comes mostly from M1 itself.
    base = _trial('S2', [-0.005 + rng.gauss(0, 0.1) for _ in range(n)])
    s3 = _trial('S3', [None] * n)
    s3['pools'] = [dict(p, trade=p['trade'] if i % 3 else _trade(None, entered=False),
                        journal=[] if i % 3 else [dict(intent='NO_TRADE', reasons=['veto_x'])])
                   for i, p in enumerate(base['pools'])]
    trials.update(S2=base, S3=s3)
    return trials


def _evaluate(trials, **kwargs):
    if kwargs.get('sensitivity_latency10') is not None:
        kwargs.setdefault('sensitivity_entries', [_L1_RECORDS[w.SENSITIVITY_ID]])
    return w.evaluate_w1(trials, _registry(trials), start=1_000, end=1_300, embargo_slots=5, n_boot=500, **kwargs)


def test_strong_edge_passes_the_gate_only_with_every_criterion():
    trials = _w1(0.08)
    report = _evaluate(trials, sensitivity_latency10=_sensitivity())
    assert report['decision'] == 'CHALLENGER_FOR_W2' and report['n_trials'] == 32
    assert report['pool_coverage']['identical'] is True
    assert report['code_modules'] == list(h_code_modules()) and 'transitive-closure-v1' in report['code_fingerprint_rule']
    assert report['runtime']['python'] and 'distributions' in report['runtime']
    assert report['flags']['reference_arm_reported'] is False and 'reference' not in report['trials']
    without = _evaluate(trials)
    assert without['decision'] == 'NO_GO' and without['decision_reasons'] == ['latency10_positive']


def test_no_edge_is_no_go_and_small_samples_wait():
    assert _evaluate(_w1(-0.05), sensitivity_latency10=_sensitivity())['decision'] == 'NO_GO'
    small = _w1(0.08, n=100)
    assert _evaluate(small)['decision'] == 'WAIT_INSUFFICIENT_DATA'


def test_non_closed_rule_and_h2_against_a_placebo_with_the_same_exit():
    assert _evaluate(_w1(0.08, not_closed=30))['decision'] == 'WAIT_NON_CLOSED'
    same = _evaluate(_w1(0.08, p1b_mean=0.08), sensitivity_latency10=_sensitivity())
    assert same['decision'] == 'NO_GO' and 'H2_rejected' in same['decision_reasons']
    assert same['tests']['holm_primary']['H1'] < w.ALPHA                 # M1 > 0 alone is not enough


def test_integrity_checks():
    trials = _w1(0.08)
    with pytest.raises(ValueError, match='w1_trials_must_be_exactly'):
        w.evaluate_w1(dict(trials, reference=trials['M1']), _registry(trials), start=1, end=2, embargo_slots=0)
    with pytest.raises(ValueError, match='unregistered_trial'):
        w.evaluate_w1(trials, _registry(trials)[1:], start=1_000, end=1_300, embargo_slots=5)
    with pytest.raises(ValueError, match='code_sha256_mismatch'):
        w.evaluate_w1(dict(trials, M1=dict(trials['M1'], code_sha256='d' * 64)), _registry(trials),
                      start=1_000, end=1_300, embargo_slots=5)
    with pytest.raises(ValueError, match='registered_w1_trials_not_all_evaluated'):
        w.evaluate_w1(trials, _registry(trials, extra=1), start=1_000, end=1_300, embargo_slots=5)
    with pytest.raises(ValueError, match='runs_on_different_fixtures'):
        w.evaluate_w1(dict(trials, P1=dict(trials['P1'], manifest_sha256='n' * 64)), _registry(trials),
                      start=1_000, end=1_300, embargo_slots=5)


def test_sensitivity_must_be_m1_at_latency_10_outside_n_r02_f2():
    trials = _w1(0.08)
    m1_as_sensitivity = dict(trials['M1'])
    with pytest.raises(ValueError, match='sensitivity_trial_id'):                      # R02 probe
        _evaluate(trials, sensitivity_latency10=m1_as_sensitivity)
    with pytest.raises(ValueError, match='sensitivity_registered_inside_N'):
        _evaluate(trials, sensitivity_latency10=dict(m1_as_sensitivity, trial_id=w.SENSITIVITY_ID))
    with pytest.raises(ValueError, match='unregistered_sensitivity'):
        _evaluate(trials, sensitivity_latency10=_sensitivity(), sensitivity_entries=[])
    with pytest.raises(ValueError, match='sensitivity_code_mismatch'):
        _evaluate(trials, sensitivity_latency10=dict(_sensitivity(), code_sha256='e' * 64))
    for params, error in ((replace(W1_L1, latency_slots=9), 'sensitivity_latency_not_10'),
                          (replace(W1_L1, latency_slots=10, receipt_latency_ms=300), 'beyond_latency')):
        record = w.l1_preregister('m' * 64, 'w' * 64, params, CLOCK, arm='master', sol_usd_source='declared:150',
                                  creator_history_sha256='h')
        sens = dict(_sensitivity(), preregistration_sha256=record['preregistration_sha256'])
        with pytest.raises(ValueError, match=error):
            _evaluate(trials, sensitivity_latency10=sens, sensitivity_entries=[record])
    other_arm = w.l1_preregister('m' * 64, 'w' * 64, replace(W1_L1, latency_slots=10), CLOCK, arm=hrr.PLACEBO_ARM,
                                 sol_usd_source='declared:150', creator_history_sha256='h')
    with pytest.raises(ValueError, match='sensitivity_not_m1'):
        _evaluate(trials, sensitivity_latency10=dict(_sensitivity(), preregistration_sha256=other_arm['preregistration_sha256']),
                  sensitivity_entries=[other_arm])


def test_warm_up_pools_never_count_r02_o_r2_1():
    trials = _w1(0.08)
    report = w.evaluate_w1(trials, _registry(trials), start=1_150, end=1_300, embargo_slots=5, n_boot=500)
    assert report['split']['outside'] == 150 and report['trials']['M1']['all']['closed'] == 150


# --- R02 F3: one test per decisive rule ---------------------------------------------------

def test_pessimistic_mean_counts_minus_one_per_non_closed_entry():
    trial = _trial('M1', [0.1, 0.1, 0.1, None], not_closed=1)
    metrics = w.trial_metrics(trial, ['p0', 'p1', 'p2', 'p3'], n_boot=200)
    assert (metrics['entries'], metrics['closed'], metrics['non_closed']) == (3, 2, 1)
    assert metrics['pessimistic_mean'] == pytest.approx((0.1 + 0.1 - 1) / 3)
    assert metrics['non_closed_share'] == pytest.approx(1 / 3)


def test_failed_attempt_costs_are_in_the_denominator():
    trial = _trial('M1', [0.1, 0.1])
    trial['pools'][0]['trade'] = dict(trial['pools'][0]['trade'], failed_attempt_costs=9_790_000)
    returns = w.trial_metrics(trial, ['p0', 'p1'], n_boot=200)['returns']
    pnl = trial['pools'][0]['trade']['pnl_lamports']
    assert returns[0] == pytest.approx(pnl / (100_000_000 + 210_000 + 9_790_000)) and returns[0] < returns[1]


def test_only_verified_creators_are_counted():
    trial = _trial('M1', [0.1] * 6, creators=6)
    for pool in trial['pools'][:2]:
        pool['signed_creator_verified'] = False
    trial['pools'][2]['creator'] = None
    assert w.trial_metrics(trial, [f'p{i}' for i in range(6)], n_boot=200)['independent_creators'] == 3


def test_confidence_interval_resamples_creator_clusters():
    from bot.master_v2.validation import bootstrap_mean_ci
    values = [(i % 10) * 0.02 - 0.09 for i in range(200)]               # 10 creators, constant inside each
    trial = _trial('M1', values, creators=10)
    pools = [f'p{i}' for i in range(200)]
    metrics = w.trial_metrics(trial, pools, n_boot=1_000)
    clustered = bootstrap_mean_ci(metrics['returns'], metrics['return_creators'], n_boot=1_000, seed=w.SEED)
    per_pool = bootstrap_mean_ci(metrics['returns'], pools, n_boot=1_000, seed=w.SEED)
    assert metrics['ci95_creator'] == clustered
    assert clustered[1] - clustered[0] > 2 * (per_pool[1] - per_pool[0])


def _gate(**changes):
    report = dict(trials=dict(M1=dict(A=dict(mean_return=0.05), B=dict(mean_return=0.05))),
                  tests=dict(holm_primary=dict(H1=0.001, H2=0.001)), sensitivity_latency10_mean=0.04, dsr_M1=0.99)
    m1 = dict(closed=200, independent_creators=60, non_closed_share=0.0, ci95_creator=(0.01, 0.09), pessimistic_mean=0.04)
    p1b, s1 = dict(non_closed_share=0.0), dict(non_closed_share=0.0)
    for key, value in changes.items():
        if key in ('A', 'B'):
            report['trials']['M1'][key] = dict(mean_return=value)
        elif key == 'p1b_share':
            p1b['non_closed_share'] = value
        else:
            m1[key] = value
    return w._decide(report, m1, p1b, s1, (140, 50))


def test_gate_rules():
    assert _gate() == ('CHALLENGER_FOR_W2', [])
    assert _gate(ci95_creator=(-0.001, 0.09)) == ('NO_GO', ['ci95_low_positive'])     # the LOWER bound decides
    assert _gate(A=None) == ('NO_GO', ['half_A_positive'])                           # a half without cycle fails
    assert _gate(B=None) == ('NO_GO', ['half_B_positive'])
    assert _gate(pessimistic_mean=-0.01) == ('NO_GO', ['pessimistic_positive'])
    assert _gate(p1b_share=0.051)[0] == 'WAIT_H2_NOT_EVALUABLE'                      # D5
    assert _gate(p1b_share=None)[0] == 'WAIT_H2_NOT_EVALUABLE'
    assert _gate(p1b_share=0.05) == ('CHALLENGER_FOR_W2', [])
    assert _gate(non_closed_share=0.051)[0] == 'WAIT_NON_CLOSED'
    assert _gate(closed=139)[0] == _gate(independent_creators=49)[0] == 'WAIT_INSUFFICIENT_DATA'


def test_pool_coverage_is_published():
    trials = _w1(0.08)
    trials['P1'] = dict(trials['P1'], pools=trials['P1']['pools'][1:])
    coverage = _evaluate(trials)['pool_coverage']
    assert coverage['identical'] is False and coverage['per_trial']['P1']['missing_vs_M1'] == 1


def test_descriptive_sensitivities_are_registered_outside_n_r02_d5():
    trials = _w1(0.08)
    record = w.l1_preregister('m' * 64, 'w' * 64, replace(W1_L1, failed_attempt_fee_lamports=105_000), CLOCK,
                              arm='master', sol_usd_source='declared:150', creator_history_sha256='h')
    fee = dict(_trial('M1_failed_fee_105000', [0.07] * 300), preregistration_sha256=record['preregistration_sha256'])
    report = _evaluate(trials, sensitivity_latency10=_sensitivity(),
                       sensitivity_entries=[_L1_RECORDS[w.SENSITIVITY_ID], record],
                       descriptive={'M1_failed_fee_105000': fee})
    assert report['decision'] == 'CHALLENGER_FOR_W2'                   # descriptive results never gate
    assert report['descriptive_sensitivities']['M1_failed_fee_105000']['all']['closed'] == 300
    for bad, error in (({'other': fee}, 'unknown_descriptive_sensitivity'),
                       ({'M1_failed_fee_105000': dict(fee, preregistration_sha256='0' * 64)}, 'unregistered_descriptive'),
                       ({'M1_failed_fee_105000': dict(fee, code_sha256='e' * 64)}, 'code_or_manifest_mismatch'),
                       ({'M1_failed_fee_105000': dict(fee, preregistration_sha256=trials['P1']['preregistration_sha256'])},
                        'registered_inside_N')):
        with pytest.raises(ValueError, match=error):
            _evaluate(trials, sensitivity_latency10=_sensitivity(),
                      sensitivity_entries=[_L1_RECORDS[w.SENSITIVITY_ID], record], descriptive=bad)


def test_near_threshold_share_uses_the_thresholds_acting_on_m1_r02_n1():
    rows = [dict(liquidity_usd=25.1),                       # funding 25: |25.1 - 25| = 0.1 <= 0.1255
            dict(liquidity_usd=249.0),                      # funding 250: 1.0 <= 1.245
            dict(liquidity_usd=3014.0),                     # TP/SL 3000: 14 <= 15.07
            dict(liquidity_usd=3015.05),                    # 15.05 <= 0.5 % of the VALUE (15.075), > 0.5 % of 3000
            dict(liquidity_usd=25200.0),                    # TP/SL 25000: 200 > 126: not near
            dict(liquidity_usd=1000.0),                     # 1000 USD is not a threshold for the curve
            dict(liquidity_usd=4000.0, volume_5m_usd=5020.0),       # volume floor 5000 (0.25 x 4000 = 1000)
            dict(liquidity_usd=40000.0, volume_5m_usd=5020.0),      # 0.25 x 40000 = 10000 > 5000: not counted
            dict()]
    trial = dict(pools=[dict(pool='a', journal=rows), dict(pool='b', journal=[dict(liquidity_usd=25.0)])])
    share = w.near_threshold_share(trial, ['a'])
    assert share['decisions'] == 8 and share['decisions_with_volume'] == 2
    near = {k: v['near'] for k, v in share['by_threshold'].items()}
    assert near == {'funding_5': 0, 'funding_25': 1, 'funding_250': 1, 'liquidity_tpsl_3000': 2,
                    'liquidity_tpsl_25000': 0, 'volume_5000': 1}
    assert share['near_any'] == 5 and share['share_any'] == 5 / 8
    assert 'liquidity_1000' not in share['by_threshold']
    assert w.near_threshold_share(trial, [])['share_any'] is None
