"""n1verdict 0.2.2 lines: the union of pre-T0 and window pages (synthetic pages written in the cpmmpilot.store layout),
the boundary refusals, and the one-shot run (constants patched to synthetic pools)."""
import hashlib
import json

import pytest

from cpmmgen3.tests.test_gen3 import CONFIG_A, Pool, calm, FEES_A, SOL
from cpmmpilot.store import write_gz_page
from cpmmx import events, timeline as TL
from cpmmx.tests.test_cpmmx import BASE_B58, logs, tx
from n1verdict import lines as L

DAY = 86_400
T0 = 10 * DAY
POOL_IDS = [bytes(range(k, k + 32)) for k in (1, 41, 81)]
POOLS = [events.b58encode(p) for p in POOL_IDS]


def txs_of(pool, steps):
    sim, out = Pool(pool, 10 ** 15, 200 * SOL, FEES_A), {}
    for k, (t, kind, amount) in enumerate(steps):
        payload = sim.deposit(*amount) if kind == 'lp' else sim.swap(kind, amount)
        sig = '%s%05d' % (pool[:2].hex(), k)
        out[sig] = dict(tx(t * 2, 0, logs(payload), when=t), transaction=dict(signatures=[sig]))
    return out


def write_pages(directory, txs, per_page=40):
    rows = sorted(txs.values(), key=lambda r: r.get('blockTime', 0))
    for n in range(0, len(rows), per_page):
        write_gz_page(directory / ('page_%05d.json.gz' % (n // per_page)), dict(data=rows[n:n + per_page]))


def layout(tmp_path, pool, steps, d_days=8):
    all_txs = txs_of(pool, steps)
    pre = {s: r for s, r in all_txs.items() if r['blockTime'] < T0}
    win = {s: r for s, r in all_txs.items() if r['blockTime'] >= T0}
    name = events.b58encode(pool)
    write_pages(tmp_path / 'pre' / name, pre)
    write_pages(tmp_path / 'win' / name, win)
    return all_txs


def test_the_line_is_the_union_of_the_two_sides(tmp_path):
    steps = calm(T0 - 3 * 3_600, T0 + 8 * DAY, every=1_800)
    all_txs = layout(tmp_path, POOL_IDS[0], steps)
    line = L.pool_line(POOLS[0], BASE_B58, tmp_path / 'pre' / POOLS[0], tmp_path / 'win' / POOLS[0], t0=T0, d_days=8)
    direct = TL.build(POOLS[0], all_txs, base_mint=BASE_B58)
    assert line.swaps == direct.swaps and len(line.swaps) == len(steps)
    assert any(s.block_time < T0 for s in line.swaps) and any(s.block_time >= T0 for s in line.swaps)


def test_boundaries_duplicates_and_missing_pages_are_refused(tmp_path):
    pool = POOL_IDS[0]
    name = POOLS[0]
    good = txs_of(pool, calm(T0 - 3_600, T0 + 3_600, every=600))
    pre = {s: r for s, r in good.items() if r['blockTime'] < T0}
    win = {s: r for s, r in good.items() if r['blockTime'] >= T0}
    write_pages(tmp_path / 'a' / 'pre', dict(pre, extra=dict(next(iter(win.values())))))    # a T0 tx on the pre side
    write_pages(tmp_path / 'a' / 'win', win)
    with pytest.raises(L.LinesError, match='pre_t0_page_at_or_after_t0'):
        L.pool_line(name, BASE_B58, tmp_path / 'a' / 'pre', tmp_path / 'a' / 'win', t0=T0, d_days=8)
    write_pages(tmp_path / 'b' / 'pre', pre)
    write_pages(tmp_path / 'b' / 'win', dict(win, early=next(iter(pre.values()))))
    with pytest.raises(L.LinesError, match='outside_the_window'):
        L.pool_line(name, BASE_B58, tmp_path / 'b' / 'pre', tmp_path / 'b' / 'win', t0=T0, d_days=8)
    late = dict(next(iter(win.values())), blockTime=T0 + 8 * DAY)
    write_pages(tmp_path / 'c' / 'pre', pre)
    write_pages(tmp_path / 'c' / 'win', dict(win, late=late))
    with pytest.raises(L.LinesError, match='outside_the_window'):
        L.pool_line(name, BASE_B58, tmp_path / 'c' / 'pre', tmp_path / 'c' / 'win', t0=T0, d_days=8)
    shared = next(iter(pre))
    write_pages(tmp_path / 'd' / 'pre', pre)
    write_pages(tmp_path / 'd' / 'win', dict(win, x=dict(next(iter(win.values())),
                                                         transaction=dict(signatures=[shared]))))
    with pytest.raises(L.LinesError, match='both_sides'):
        L.pool_line(name, BASE_B58, tmp_path / 'd' / 'pre', tmp_path / 'd' / 'win', t0=T0, d_days=8)
    (tmp_path / 'e' / 'win').mkdir(parents=True)
    write_pages(tmp_path / 'e' / 'pre', pre)
    with pytest.raises(L.LinesError, match='no_window_page'):
        L.pool_line(name, BASE_B58, tmp_path / 'e' / 'pre', tmp_path / 'e' / 'win', t0=T0, d_days=8)
    bad = dict(next(iter(pre.values())))
    bad.pop('blockTime')
    write_pages(tmp_path / 'f' / 'pre', dict(pre, bad=bad))
    write_pages(tmp_path / 'f' / 'win', win)
    with pytest.raises(L.LinesError, match='block_time'):
        L.pool_line(name, BASE_B58, tmp_path / 'f' / 'pre', tmp_path / 'f' / 'win', t0=T0, d_days=8)


def test_lines_for_keeps_the_sheet_order_and_needs_every_named_pool(tmp_path):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=3_600))
    selected = [dict(pool=p, base_mint=BASE_B58) for p in reversed(POOLS)]
    lines = L.lines_for(selected, tmp_path / 'pre', tmp_path / 'win', pools=POOLS, t0=T0, d_days=8)
    assert [line.pool for line in lines] == POOLS
    with pytest.raises(L.LinesError, match='missing'):
        L.lines_for(selected[:2], tmp_path / 'pre', tmp_path / 'win', pools=POOLS, t0=T0, d_days=8)
    assert hashlib.sha256('\n'.join(L.POOLS).encode()).hexdigest() == L.POOLS_SHA256 == (
        'c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da')
    assert L.T0 == 1795515686 and L.D_DAYS == 12


def test_the_one_shot_run_writes_the_report_once(tmp_path, monkeypatch, capsys):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    monkeypatch.setattr(L, 'POOLS', tuple(POOLS))
    monkeypatch.setattr(L, 'POOLS_SHA256', hashlib.sha256('\n'.join(POOLS).encode()).hexdigest())
    monkeypatch.setattr(L, 'T0', T0)
    monkeypatch.setattr(L, 'D_DAYS', 8)
    monkeypatch.setattr(L.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0, selected=[dict(pool=p, base_mint=BASE_B58)
                                                                              for p in POOLS + ['other']])))
    args = ['--u2', str(tmp_path / 'u2.json'), '--pre-root', str(tmp_path / 'pre'), '--window-root',
            str(tmp_path / 'win'), '--t0-slot', '7', '--sheet-sha', 'ab' * 32, '--g0', 'passed', '--result',
            str(tmp_path / 'r.json')]
    L.main(args)
    text = (tmp_path / 'r.json').read_text()
    doc = json.loads(text)
    assert capsys.readouterr().out.split()[0] == hashlib.sha256(text.encode()).hexdigest()
    assert doc['schema'] == 'n1verdict-v0.2.1' and doc['pools'] == POOLS and doc['n'] == 24
    assert doc['decision'] == 'INCONCLUSIF'                                   # 24 pool-days < 30
    assert doc['lines']['swaps'][POOLS[0]] == len(calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    with pytest.raises(L.LinesError, match='result_exists'):
        L.main(args)
    stop = [a if a != 'passed' else 'not_passed' for a in args[:-1]] + [str(tmp_path / 's.json')]
    L.main(stop)
    assert json.loads((tmp_path / 's.json').read_text())['decision'] == 'STOP'
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0 + 1, selected=[])))
    with pytest.raises(L.LinesError, match='t0'):
        L.main(args[:-1] + [str(tmp_path / 't.json')])
    monkeypatch.setattr(L, 'POOLS_SHA256', '0' * 64)
    with pytest.raises(L.LinesError, match='altered'):
        L.main(args[:-1] + [str(tmp_path / 'u.json')])


def test_the_run_refuses_a_window_page_after_t0_plus_d(tmp_path, monkeypatch):
    for pid in POOL_IDS:
        layout(tmp_path, pid, calm(T0 - 3_600, T0 + 8 * DAY, every=1_800))
    late = txs_of(POOL_IDS[0], [(T0 + 8 * DAY + 60, 'buy', 10 ** 8)])
    write_gz_page(tmp_path / 'win' / POOLS[0] / 'page_09999.json.gz',
                  dict(data=[dict(r, transaction=dict(signatures=['late'])) for r in late.values()]))
    monkeypatch.setattr(L, 'POOLS', tuple(POOLS))
    monkeypatch.setattr(L, 'POOLS_SHA256', hashlib.sha256('\n'.join(POOLS).encode()).hexdigest())
    monkeypatch.setattr(L, 'T0', T0)
    monkeypatch.setattr(L, 'D_DAYS', 8)
    monkeypatch.setattr(L.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(t0_time=T0, selected=[dict(pool=p, base_mint=BASE_B58)
                                                                              for p in POOLS])))
    with pytest.raises(L.LinesError, match='outside_the_window'):
        L.main(['--u2', str(tmp_path / 'u2.json'), '--pre-root', str(tmp_path / 'pre'), '--window-root',
                str(tmp_path / 'win'), '--t0-slot', '7', '--sheet-sha', 'ab' * 32, '--g0', 'passed', '--result',
                str(tmp_path / 'r.json')])
