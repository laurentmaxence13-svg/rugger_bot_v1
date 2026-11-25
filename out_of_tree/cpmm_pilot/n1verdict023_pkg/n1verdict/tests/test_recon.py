"""n1verdict 0.2.3 (PROJECT): the UNDECODED rule, the G-0 exclusion, cpmmrecon before the positions, and the identity
with the anchored 0.2.2 (n1verdict_pkg) when nothing is truncated or excluded."""
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from cpmmcost import model as CC
from cpmmgen3.tests.test_gen3 import CONFIG_A
from cpmmpilot.store import write_gz_page
from cpmmx.tests.test_cpmmx import BASE_B58
from lpcost import model as LP
from n1verdict import lines as L, verdict as N
from n1verdict.tests.test_lines import POOL_IDS, POOLS, T0, calm, layout, txs_of
from n1verdict.tests.test_verdict import SHEET, real_line

DAY = 86_400
BASE_DIR = 'n1verdict_pkg'
ANCHORED = dict(lines='de0732b35c2065e3ab1f912f74e2f7ca35d5337388db772b6ddd991da4ace0fd',
                verdict='e6db8985b24e8eb4f7246428041a3f9d8a22d7ea580a9ef05c7d1d2631a199f8')
CPMM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'


def k(t, index=0):
    return (2 * t, index)                                                     # line_of: slot = 2 x time


# -- the UNDECODED rule (verdict) ---------------------------------------------------------------------------------------
def test_an_undecoded_transaction_between_a_state_and_its_landing_is_found():
    line = real_line()                                       # swaps at T0 - 600 + j x 1 800, last at T0 + 8 d - 600
    land_in = LP.landing_time(T0)
    assert T0 < land_in < T0 + 1_200
    reason = lambda u: N.undecoded_reason(line, u, t0=T0, d_days=8)              # noqa: E731
    assert reason(()) is None and reason([k(T0 + 3 * DAY)]) is None
    assert reason([k(T0 + 100)]) == reason([k(T0 - 600, 1)]) == 'undecoded_transaction_at_entry'
    assert reason([k(T0 + 1_199, 9)]) == 'undecoded_transaction_at_entry'        # before the swap that fixes it
    assert reason([(2 * (T0 - 600) - 1, 0)]) is None                              # before the decision state's swap
    assert reason([k(T0 + 1_200, 1)]) is None                                     # after that swap: not separating
    assert reason([k(T0 + 8 * DAY - 600, 1)]) == reason([k(T0 + 9 * DAY)]) == 'undecoded_transaction_at_exit'
    assert reason([k(T0 + 8 * DAY - 2_400, 1)]) is None                           # before the exit state's swap
    assert reason([k(T0 + 100), k(T0 + 9 * DAY)]) == 'undecoded_transaction_at_entry'   # entry checked first


def test_the_position_is_then_a_total_loss_and_otherwise_unchanged():
    line = real_line()
    plain, pos = N.pool_days(line, CONFIG_A, t0=T0, d_days=8)
    same, pos2 = N.pool_days(line, CONFIG_A, t0=T0, d_days=8, undecoded=[k(T0 + 3 * DAY)])
    assert same == plain and pos2 == pos and pos is not None
    for u, why in (([k(T0 + 100)], 'undecoded_transaction_at_entry'), ([k(T0 + 9 * DAY)], 'undecoded_transaction_at_exit')):
        rows, none = N.pool_days(line, CONFIG_A, t0=T0, d_days=8, undecoded=u)
        stake0 = N.unpriced_stake(line, T0)
        assert none is None and len(rows) == 8 and all(
            r['status'] == 'unpriced_total_loss' and r['unpriced'] == why and r['entered'] is True
            and r['net_return'] == float(N.total_loss_per_day(stake0, 8)) and r['stake_lamports'] == stake0 for r in rows)
    sens, _ = N.pool_days(line, CONFIG_A, t0=T0, d_days=8, undecoded=[k(T0 + 100)], failures=CC.SENSITIVITY_FAILURES)
    assert sens[0]['net_return'] == float(N.total_loss_per_day(N.unpriced_stake(line, T0), 8, CC.SENSITIVITY_FAILURES))


def three_lines():
    return [replace(real_line(), pool=p) for p in ('pA', 'pB', 'pC')]


def test_report_applies_the_rule_in_the_main_series_and_the_sensitivities():
    lines = three_lines()
    base = N.report(lines, CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                    d_days=8, draws=50)
    assert N.report(lines, CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                    d_days=8, draws=50, undecoded={'pA': [], 'pB': [k(T0 + 2 * DAY)]}, excluded={}) == base
    hit = N.report(lines, CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                   d_days=8, draws=50, undecoded={'pB': [k(T0 + 100)]})
    assert hit['unpriced'] == dict(pools=['pB'], reasons=['undecoded_transaction_at_entry'])
    assert hit['per_pool']['pB']['status'] == 'unpriced_total_loss' and 'g0_excluded' not in hit
    assert hit['sensitivities']['rent_lost']['mean_gap_return'] < base['sensitivities']['rent_lost']['mean_gap_return']


def test_a_pool_excluded_by_g0_is_published_and_the_floors_judge():
    lines = three_lines()
    doc = N.report(lines[:2], CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                   d_days=8, draws=50, excluded={'pC': ['token_transfer_fee']})
    assert doc['decision'] == 'INCONCLUSIF' and doc['floors']['passed'] is False and doc['n'] == 16
    assert doc['g0_excluded'] == {'pC': ['token_transfer_fee']} and doc['pools'] == ['pA', 'pB', 'pC']
    assert doc['per_pool']['pC'] == dict(status='excluded_by_g0', g0_reasons=['token_transfer_fee'], pool_days=0,
                                         entries=0)
    assert set(doc['per_pool']) == {'pA', 'pB', 'pC'} and doc['unpriced']['pools'] == []
    with pytest.raises(N.N1Error, match='excluded_pool_not_named'):
        N.report(lines[:2], CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                 d_days=8, draws=50, excluded={'pZ': ['x']})
    with pytest.raises(N.N1Error, match='sheet_order'):
        N.report(lines, CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                 d_days=8, draws=50, excluded={'pC': ['x']})                  # an excluded pool's line is absent
    none = N.report([], CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=T0,
                    d_days=8, draws=50, excluded={p: ['x'] for p in ('pA', 'pB', 'pC')})
    assert none['decision'] == 'INCONCLUSIF' and none['n'] == 0 and set(none['g0_excluded']) == {'pA', 'pB', 'pC'}
    stop = N.report(lines[:2], CONFIG_A, pools=['pA', 'pB', 'pC'], g0_passed=False, freeze_sheet_sha256=SHEET, t0=T0,
                    d_days=8, draws=50, excluded={'pC': ['x']})
    assert stop['decision'] == 'STOP' and stop['published_numbers'] is False


# -- the lines: cpmmrecon before the positions, G-0 computed ----------------------------------------------------------
def truncated_tx(slot, index, when, sig):
    return dict(slot=slot, transactionIndex=index, blockTime=when,
                meta=dict(err=None, logMessages=['Program %s invoke [1]' % CPMM, 'Log truncated']),
                transaction=dict(signatures=[sig], message=dict(accountKeys=[], instructions=[])))


def rows():
    return [dict(pool=p, base_mint=BASE_B58, wsol_vault='WV' + p[:4]) for p in POOLS]


def test_a_pre_t0_undecoded_transaction_before_the_entry_landing_makes_the_position_unpriced(tmp_path):
    for pid in POOL_IDS:                              # swaps at T0 - 3 540, T0 - 1 740, T0 + 60, ...: none at T0
        layout(tmp_path, pid, calm(T0 - 3_540, T0 + 8 * DAY, every=1_800))
    write_gz_page(tmp_path / 'pre' / POOLS[0] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(2 * (T0 - 60), 0, T0 - 60, 'cut1'),           # after the last pre-T0 swap
                             truncated_tx(2 * (T0 - 3_000), 0, T0 - 3_000, 'cut0')]))   # deep in the history
    lines, undecoded, excluded, ok, rep = L.prepared(rows(), tmp_path / 'pre', tmp_path / 'win', CONFIG_A, pools=POOLS,
                                                     t0=T0, d_days=8)
    assert ok is True and excluded == {} and [x.pool for x in lines] == POOLS      # G-0 sees the window: admitted
    assert undecoded[POOLS[0]] == [(2 * (T0 - 3_000), 0), (2 * (T0 - 60), 0)] and undecoded[POOLS[1]] == []
    assert rep[POOLS[0]]['union']['skipped'] == 2 and rep[POOLS[0]]['union']['rebuilt'] == 0
    assert sum(rep[POOLS[0]]['union']['kept'].values()) == 2 and rep[POOLS[0]]['undecoded_after'] == 2
    assert rep[POOLS[0]]['window']['skipped'] == 0 and rep[POOLS[0]]['g0']['admitted'] is True
    doc = N.report(lines, CONFIG_A, pools=POOLS, g0_passed=ok, freeze_sheet_sha256=SHEET, t0=T0, d_days=8, draws=50,
                   undecoded=undecoded, excluded=excluded)
    assert doc['unpriced'] == dict(pools=[POOLS[0]], reasons=['undecoded_transaction_at_entry'])


def test_an_undecoded_window_transaction_excludes_the_pool_by_g0(tmp_path):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    write_gz_page(tmp_path / 'win' / POOLS[2] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(2 * (T0 + DAY), 0, T0 + DAY, 'cut2')]))
    lines, undecoded, excluded, ok, rep = L.prepared(rows(), tmp_path / 'pre', tmp_path / 'win', CONFIG_A, pools=POOLS,
                                                     t0=T0, d_days=8)
    assert ok is True and list(excluded) == [POOLS[2]] and 'undecoded_transactions' in excluded[POOLS[2]]
    assert [x.pool for x in lines] == POOLS[:2] and rep[POOLS[2]]['window']['skipped'] == 1
    doc = N.report(lines, CONFIG_A, pools=POOLS, g0_passed=ok, freeze_sheet_sha256=SHEET, t0=T0, d_days=8, draws=50,
                   undecoded=undecoded, excluded=excluded)
    assert doc['decision'] == 'INCONCLUSIF' and doc['per_pool'][POOLS[2]]['status'] == 'excluded_by_g0'


def test_the_rebuilt_lines_are_the_ones_used(tmp_path, monkeypatch):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    write_gz_page(tmp_path / 'pre' / POOLS[1] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(2 * (T0 - 60), 0, T0 - 60, 'cut1')]))
    write_gz_page(tmp_path / 'win' / POOLS[2] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(2 * (T0 + DAY), 0, T0 + DAY, 'cut2')]))
    calls = []

    def fake(line, txs, *, wsol_vault, fees, on_input):
        calls.append((line.pool, wsol_vault, fees, on_input, line.skipped[0][0] in txs))
        return replace(line, skipped=()), {line.skipped[0][0]: 'rebuilt:1'}
    monkeypatch.setattr(L.RB, 'rebuild', fake)
    lines, undecoded, excluded, ok, rep = L.prepared(rows(), tmp_path / 'pre', tmp_path / 'win', CONFIG_A, pools=POOLS,
                                                     t0=T0, d_days=8)
    fees = CC.fees_from_amm_config(CONFIG_A)
    assert calls == [(POOLS[1], 'WV' + POOLS[1][:4], fees, True, True)] + [(POOLS[2], 'WV' + POOLS[2][:4], fees, True,
                                                                             True)] * 2     # union, then window
    assert lines[1].skipped == () and undecoded[POOLS[1]] == [] and undecoded[POOLS[2]] == []
    assert ok is True and excluded == {} and rep[POOLS[2]]['window']['rebuilt'] == 1   # G-0 judged the rebuilt window
    assert rep[POOLS[1]]['union'] == dict(skipped=1, rebuilt=1, rebuilt_swaps=0, kept={}, transactions={'cut1': 'rebuilt:1'})


def test_the_daily_marks_touched_are_counted_descriptively():
    line = real_line()                                         # mark of day 1 at T0 + 86 400: swaps at 85 800, 87 600
    assert L.marks_touched(line, [], t0=T0, d_days=8) == 0
    assert L.marks_touched(line, [k(T0 + DAY + 100)], t0=T0, d_days=8) == 1
    assert L.marks_touched(line, [k(T0 + DAY + 1_300)], t0=T0, d_days=8) == 0      # after the swap that fixes it
    assert L.marks_touched(line, [k(T0 + 100), k(T0 + 9 * DAY)], t0=T0, d_days=8) == 0   # entry / exit only
    assert L.marks_touched(line, [k(T0 + DAY + 100), k(T0 + 7 * DAY + 100)], t0=T0, d_days=8) == 2


def test_a_line_whose_creator_side_is_unknown_is_not_tried():
    line = replace(real_line(), skipped=(('s', 'log_truncated'),))
    flipped = replace(line.swaps[0], event=replace(line.swaps[0].event, creator_fee_on_input=False))
    odd = replace(line, swaps=(flipped,) + line.swaps[1:])
    assert L.rebuilt(odd, {}, dict(wsol_vault='x'), CONFIG_A) == (odd, dict(
        skipped=1, rebuilt=0, rebuilt_swaps=0, kept={'kept:not_tried_creator_side': 1}, transactions={}))
    empty = replace(line, swaps=())
    assert L.rebuilt(empty, {}, dict(wsol_vault='x'), CONFIG_A)[1]['kept'] == {'kept:not_tried_creator_side': 1}
    clean = real_line()
    assert L.rebuilt(clean, {}, {}, CONFIG_A) == (clean, dict(skipped=0, rebuilt=0, rebuilt_swaps=0, kept={},
                                                              transactions={}))


# -- identity with the anchored 0.2.2 -----------------------------------------------------------------------------------
def _anchored():
    root = Path(__file__).resolve().parents[3] / BASE_DIR / 'n1verdict'
    mods = {}
    for name in ('verdict', 'lines'):
        path = root / ('%s.py' % name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ANCHORED[name]
        spec = importlib.util.spec_from_file_location('n1verdict_anchored_%s' % name, path)
        mods[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mods[name])
    mods['lines'].N = mods['verdict']                                    # the anchored lines on the anchored verdict
    return mods['lines']


def test_without_truncation_the_result_is_byte_identical_to_the_anchored_0_2_2(tmp_path, monkeypatch, capsys):
    old = _anchored()
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    for mod in (L, old):
        monkeypatch.setattr(mod, 'POOLS', tuple(POOLS))
        monkeypatch.setattr(mod, 'POOLS_SHA256', hashlib.sha256('\n'.join(POOLS).encode()).hexdigest())
        monkeypatch.setattr(mod, 'T0', T0)
        monkeypatch.setattr(mod, 'D_DAYS', 8)
        monkeypatch.setattr(mod.PILOT, 'amm_config_for_rules', lambda r, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0, selected=rows())))
    common = ['--u2', str(tmp_path / 'u2.json'), '--pre-root', str(tmp_path / 'pre'), '--window-root',
              str(tmp_path / 'win'), '--t0-slot', '7', '--sheet-sha', SHEET]
    old.main(common + ['--g0', 'passed', '--result', str(tmp_path / 'old.json')])
    L.main(common + ['--reconstruction', str(tmp_path / 'rc.json'), '--result', str(tmp_path / 'new.json')])
    out = capsys.readouterr().out.split('\n')
    assert (tmp_path / 'new.json').read_bytes() == (tmp_path / 'old.json').read_bytes()
    assert out[0].split()[0] == out[1].split()[0]
    recon = json.loads((tmp_path / 'rc.json').read_text())
    assert out[2].split()[0] == hashlib.sha256((tmp_path / 'rc.json').read_bytes()).hexdigest()
    assert recon['g0_passed'] is True and all(v['undecoded_after'] == 0 and v['union']['skipped'] == 0
                                              for v in recon['pools'].values())
    with pytest.raises(L.LinesError, match='result_exists'):
        L.main(common + ['--reconstruction', str(tmp_path / 'rc.json'), '--result', str(tmp_path / 'other.json')])


def test_the_one_shot_run_feeds_the_undecoded_and_the_excluded_pools_to_the_verdict(tmp_path, monkeypatch, capsys):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_540, T0 + 8 * DAY, every=1_800))
    write_gz_page(tmp_path / 'pre' / POOLS[0] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(2 * (T0 - 60), 0, T0 - 60, 'cut1')]))
    write_gz_page(tmp_path / 'win' / POOLS[2] / 'page_09999.json.gz',
                  dict(data=[truncated_tx(2 * (T0 + DAY), 0, T0 + DAY, 'cut2')]))
    monkeypatch.setattr(L, 'POOLS', tuple(POOLS))
    monkeypatch.setattr(L, 'POOLS_SHA256', hashlib.sha256('\n'.join(POOLS).encode()).hexdigest())
    monkeypatch.setattr(L, 'T0', T0)
    monkeypatch.setattr(L, 'D_DAYS', 8)
    monkeypatch.setattr(L.PILOT, 'amm_config_for_rules', lambda r, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0, selected=rows())))
    L.main(['--u2', str(tmp_path / 'u2.json'), '--pre-root', str(tmp_path / 'pre'), '--window-root',
            str(tmp_path / 'win'), '--t0-slot', '7', '--sheet-sha', SHEET, '--reconstruction', str(tmp_path / 'rc.json'),
            '--result', str(tmp_path / 'r.json')])
    doc = json.loads((tmp_path / 'r.json').read_text())
    recon = json.loads((tmp_path / 'rc.json').read_text())
    assert doc['unpriced'] == dict(pools=[POOLS[0]], reasons=['undecoded_transaction_at_entry'])
    assert list(doc['g0_excluded']) == [POOLS[2]] and doc['decision'] == 'INCONCLUSIF'
    assert doc['lines']['swaps'] == {p: len(calm(T0 - 3_540, T0 + 8 * DAY, every=1_800)) for p in POOLS[:2]}
    assert recon['pools'][POOLS[0]]['undecoded_after'] == 1 and recon['pools'][POOLS[2]]['g0']['admitted'] is False
    assert recon['pools'][POOLS[0]]['undecoded_marks'] == 0 and recon['pools'][POOLS[2]]['undecoded_marks'] == 1


def test_prepared_keeps_the_boundary_checks_of_pool_line(tmp_path):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    first_pre = sorted((tmp_path / 'pre' / POOLS[1]).glob('page_*.json.gz'))[0]
    from cpmmpilot.store import read_gz_page
    shared = read_gz_page(first_pre)['data'][0]['transaction']['signatures'][0]
    win = read_gz_page(sorted((tmp_path / 'win' / POOLS[1]).glob('page_*.json.gz'))[0])['data'][0]
    write_gz_page(tmp_path / 'win' / POOLS[1] / 'page_09999.json.gz',
                  dict(data=[dict(win, transaction=dict(win['transaction'], signatures=[shared]))]))
    with pytest.raises(L.LinesError, match='signature_on_both_sides'):
        L.prepared(rows(), tmp_path / 'pre', tmp_path / 'win', CONFIG_A, pools=POOLS, t0=T0, d_days=8)
    with pytest.raises(L.LinesError, match='missing'):
        L.prepared(rows()[:2], tmp_path / 'pre', tmp_path / 'win', CONFIG_A, pools=POOLS, t0=T0, d_days=8)
