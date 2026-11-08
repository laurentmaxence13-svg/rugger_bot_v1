"""W1 evaluation (protocol R3, R5, R8): L1 trials registered before replay, W1 mode, tests, gate."""
import hashlib
from pathlib import Path
import random

import pytest

from bot.master_v2 import registry
from bot.master_v2 import w1_eval as w
from bot.master_v2.harness import code_fingerprint
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


def test_l1_trial_checks_its_registry_entry(tmp_path):
    reg = tmp_path / 'trials.jsonl'
    w.run_l1_trials(PACK, W1_L1, CLOCK, registry_path=reg, registered_at=AT)
    entry = registry.load(reg)[0]
    bundle = hrr.run_replay(PACK, W1_L1, None, CLOCK, hrr.CreatorHistory.from_archives(
        [a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'), placebo_arm=True)
    assert w.trial_from_l1_bundle(bundle, 'M1', entry)['trial_id'] == 'M1'
    for bad, error in ((dict(entry, manifest_sha256='0' * 64), 'l1_trial_manifest_mismatch'),
                       (dict(entry, replay_params=dict(entry['replay_params'], latency_slots=2)), 'configuration'),
                       (dict(entry, exit_rule=hrr.ExitOptions().record()), 'configuration'),
                       (dict(entry, code_sha256='f' * 64), 'code_sha256_mismatch')):
        with pytest.raises(ValueError, match=error):
            w.trial_from_l1_bundle(bundle, 'M1', bad)


# --- R3 -----------------------------------------------------------------------------------

def test_w1_split_keeps_the_evaluation_range_and_embargoes_the_boundary():
    pools = [dict(pool=f'p{i}', created_slot=slot) for i, slot in enumerate([5, 10, 20, 30, 40, 41, 60, 70, 200])]
    split = w.w1_split(pools, start=10, end=100, embargo_slots=5)
    assert split['outside'] == ['p0', 'p8'] and split['all'] == ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7']
    assert split['A'] == ['p1', 'p2', 'p3'] and split['boundary_slot'] == 40
    assert split['embargoed'] == ['p4', 'p5'] and split['B'] == ['p6', 'p7']
    for bad in (dict(start=10, end=10, embargo_slots=0), dict(start=1, end=2, embargo_slots=-1)):
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
    assert w.holm(dict(a=0.6, b=None)) == dict(a=0.6, b=None)
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
    return dict(schema=w.TRIAL_SCHEMA, trial_id=key, engine='test', preregistration_sha256=hashlib.sha256(key.encode()).hexdigest(),
                code_sha256='c' * 64, manifest_sha256='m' * 64, bundle_sha256='b' * 64, pools=pools)


def _registry(trials, extra=0):
    entries = [dict(preregistration_sha256=t['preregistration_sha256'], code_sha256=t['code_sha256'],
                    manifest_sha256=t['manifest_sha256']) for t in trials.values()]
    entries += [dict(preregistration_sha256=hashlib.sha256(f'p0trial{i}'.encode()).hexdigest(), code_sha256='x', manifest_sha256='p0')
                for i in range(25)]
    entries += [dict(preregistration_sha256=hashlib.sha256(f'extra{i}'.encode()).hexdigest(), code_sha256='c' * 64, manifest_sha256='m' * 64)
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
    return w.evaluate_w1(trials, _registry(trials), start=1_000, end=1_000_000, embargo_slots=5, n_boot=500, **kwargs)


def test_strong_edge_passes_the_gate_only_with_every_criterion():
    trials = _w1(0.08)
    sens = _trial('M1', [0.06] * 300)
    report = _evaluate(trials, sensitivity_latency10=sens)
    assert report['decision'] == 'CHALLENGER_FOR_W2' and report['n_trials'] == 32
    assert report['flags']['reference_arm_reported'] is False and 'reference' not in report['trials']
    without = _evaluate(trials)
    assert without['decision'] == 'NO_GO' and without['decision_reasons'] == ['latency10_positive']


def test_no_edge_is_no_go_and_small_samples_wait():
    assert _evaluate(_w1(-0.05), sensitivity_latency10=_trial('M1', [0.06] * 300))['decision'] == 'NO_GO'
    small = _w1(0.08, n=100)
    assert _evaluate(small)['decision'] == 'WAIT_INSUFFICIENT_DATA'


def test_non_closed_rule_and_h2_against_a_placebo_with_the_same_exit():
    assert _evaluate(_w1(0.08, not_closed=30))['decision'] == 'WAIT_NON_CLOSED'
    same = _evaluate(_w1(0.08, p1b_mean=0.08), sensitivity_latency10=_trial('M1', [0.06] * 300))
    assert same['decision'] == 'NO_GO' and 'H2_rejected' in same['decision_reasons']
    assert same['tests']['holm_primary']['H1'] < w.ALPHA                 # M1 > 0 alone is not enough


def test_integrity_checks():
    trials = _w1(0.08)
    with pytest.raises(ValueError, match='w1_trials_must_be_exactly'):
        w.evaluate_w1(dict(trials, reference=trials['M1']), _registry(trials), start=1, end=2, embargo_slots=0)
    with pytest.raises(ValueError, match='unregistered_trial'):
        w.evaluate_w1(trials, _registry(trials)[1:], start=1_000, end=10 ** 6, embargo_slots=5)
    with pytest.raises(ValueError, match='code_sha256_mismatch'):
        w.evaluate_w1(dict(trials, M1=dict(trials['M1'], code_sha256='d' * 64)), _registry(trials),
                      start=1_000, end=10 ** 6, embargo_slots=5)
    with pytest.raises(ValueError, match='registered_w1_trials_not_all_evaluated'):
        w.evaluate_w1(trials, _registry(trials, extra=1), start=1_000, end=10 ** 6, embargo_slots=5)
    with pytest.raises(ValueError, match='sensitivity_code_mismatch'):
        _evaluate(trials, sensitivity_latency10=dict(_trial('M1', [0.06] * 300), code_sha256='e' * 64))


def test_warm_up_pools_never_count_r02_o_r2_1():
    trials = _w1(0.08)
    report = w.evaluate_w1(trials, _registry(trials), start=1_150, end=10 ** 6, embargo_slots=5, n_boot=500)
    assert report['split']['outside'] == 150 and report['trials']['M1']['all']['closed'] == 150
