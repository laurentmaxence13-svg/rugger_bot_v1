"""w2arms.orch: one run and one dayj per window, exact frozen bounds, C1 ledger launcher, credit calendar, checks."""
import hashlib
import json

import pytest

from bot.market import w1_collection as wc
from w2arms import orch as O

S0_W1 = 467_275_745


def test_bounds_overlap_and_credit_calendar(tmp_path):
    p = O.plan(S0_W1, 4, tmp_path)
    assert p['windows'][0]['collection_window']['slot_min'] == S0_W1 and p['windows'][0]['evaluation'] == [467_678_545, 469_291_345]
    for a, b in zip(p['windows'], p['windows'][1:]):
        assert b['s0'] - a['s0'] == 1_612_800 and b['evaluation'][0] == a['evaluation'][1]
        assert a['collection_window']['slot_max'] - b['collection_window']['slot_min'] + 1 == 407_313 == p['overlap_slots']
    for w in p['windows']:
        assert w['collection_window'] == dict(address=wc.bf.LAUNCHLAB_PROGRAM, **{k: wc.bounds(w['s0'])[k] for k in ('slot_min', 'slot_max')})
    assert O.caps() == dict(launchlab=343_323, sol_usd=108_867) and p['windows_per_quota_month'] == 2
    assert [w['quota_month'] for w in p['windows']] == [1, 1, 2, 2] and p['quota_months'] == 2
    assert O.plan(S0_W1, 15, tmp_path)['quota_months'] == 8 and O.plan(S0_W1, 1, tmp_path)['quota_months'] == 1


def test_each_window_runs_the_unchanged_dayj_with_the_c1_ledger(tmp_path):
    p = O.plan(S0_W1, 2, tmp_path, workers=8)
    for w in p['windows']:
        steps = {s['step']: s for s in w['steps']}
        assert [s['step'] for s in w['steps']] == list(O.STEPS)
        assert steps['ledger']['module'] == 'w1aux.dayj_c1p1' and steps['ledger']['argv'][:2] == ['--ledger-workers', '8']
        assert all(s['module'] == 'w1aux.dayj' for name, s in steps.items() if name != 'ledger')
        for s in w['steps']:
            argv = s['argv']
            assert argv[argv.index('--s0') + 1] == str(w['s0']) and argv[argv.index('--out') + 1] == w['dayj_out']
    assert len({w['dayj_out'] for w in p['windows']}) == 2 and len({w['run_dir'] for w in p['windows']}) == 2
    assert 'N_FOR_DSR = 32' in p['declared']['dsr'] and '--after-reading' in p['windows'][0]['inputs_to_provide']


def test_plan_refusals(tmp_path):
    with pytest.raises(O.OrchError, match='k_must_be_a_positive_integer'):
        O.plan(S0_W1, 0, tmp_path)
    with pytest.raises(O.OrchError, match='workers_must_be_positive'):
        O.plan(S0_W1, 1, tmp_path, workers=0)


def _manifest(w):
    return dict(window=dict(w['collection_window']))


def test_check_accepts_exact_runs_and_refuses_anything_else(tmp_path):
    p = O.plan(S0_W1, 3, tmp_path)
    runs = [_manifest(w) for w in p['windows']]
    states = [dict(s0=w['s0']) for w in p['windows']]
    assert O.check(p, runs, states) == dict(windows=3, ok=True)
    sliced = [dict(window=dict(runs[0]['window'], slot_max=runs[0]['window']['slot_min'] + 7 * 401_860))] + runs[1:]
    with pytest.raises(O.OrchError, match='run_1_is_not_the_planned_window'):
        O.check(p, sliced, states)
    with pytest.raises(O.OrchError, match='dayj_2_has_another_s0'):
        O.check(p, runs, [states[0], dict(s0=1), states[2]])
    with pytest.raises(O.OrchError, match='one_run_and_one_dayj_per_window'):
        O.check(p, runs[:2], states)
    bad = json.loads(json.dumps(p))
    bad['windows'][2]['s0'] += 1
    with pytest.raises(O.OrchError, match='windows_not_consecutive'):
        O.check(bad, [_manifest(w) for w in bad['windows']], [dict(s0=w['s0']) for w in bad['windows']])


def test_cli_plan_and_anchored_check(tmp_path, capsys):
    out = tmp_path / 'plan.json'
    assert O.main(['plan', '--s0', str(S0_W1), '--k', '2', '--root', str(tmp_path / 'w2'), '--out', str(out)]) == 0
    sha = capsys.readouterr().out.strip()
    assert sha == hashlib.sha256(out.read_bytes()).hexdigest()
    with pytest.raises(O.OrchError, match='output_exists'):
        O.main(['plan', '--s0', str(S0_W1), '--k', '2', '--root', str(tmp_path / 'w2'), '--out', str(out)])
    p = json.loads(out.read_text())
    files = []
    for w in p['windows']:
        m, s = tmp_path / f"m{w['index']}.json", tmp_path / f"s{w['index']}.json"
        m.write_text(json.dumps(_manifest(w)))
        s.write_text(json.dumps(dict(s0=w['s0'])))
        files.append((str(m), str(s)))
    args = ['check', '--plan', str(out), '--run-manifest', *[f[0] for f in files], '--dayj-state', *[f[1] for f in files]]
    with pytest.raises(O.OrchError, match='plan_is_not_the_anchored_one'):
        O.main([*args, '--plan-sha256', '0' * 64])
    assert O.main([*args, '--plan-sha256', sha]) == 0
    assert json.loads(capsys.readouterr().out) == dict(ok=True, windows=2)
