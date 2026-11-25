"""livesim 0.2 on synthetic CPMM pools only (pages written in the cpmmpilot.store layout); no collected page.
The local cpmmpilot is 0.1.6 (f934bd2), not 0.2.8: its MANIFEST check is exercised on a copy and dropped from the CLI
test only (declared); every other frozen package is checked as it is."""
import hashlib
import importlib
import json
import shutil

import pytest

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmprereg import rule as R
from g23run import run as GR
from g23run.tests.test_run import BASE_B58, CONFIG_A, IDS, NAMES, raw_txs, steps, write_pages
from livesim import sim as L
from lpcost import continuous as K
from n1rot import rotation as N1R

DAY, HOUR = 86_400, 3_600
START = 20 * DAY
SEED = 'ab' * 32


def pages(tmp_path, pid, rows, name='p'):
    txs = raw_txs(pid, rows)
    pre = {s: r for s, r in txs.items() if r['blockTime'] < START}
    sim = {s: r for s, r in txs.items() if r['blockTime'] >= START}
    pool = NAMES[IDS.index(pid)]
    write_pages(tmp_path / name / 'pre' / pool, pre)
    write_pages(tmp_path / name / 'sim' / pool, sim)
    return pool


def pair(tmp_path, pool, now, name='p'):
    pre, pre_txs = GR.window_line(pool, BASE_B58, tmp_path / name / 'pre' / pool, start=START - 7 * DAY, end=START)
    sim, sim_txs = GR.window_line(pool, BASE_B58, tmp_path / name / 'sim' / pool, start=START, end=now + 1)
    return pre, pre_txs, sim, sim_txs


def market(tmp_path, now, name='p'):
    """Two pools: 7 days before the start (b3 = 2) then the simulated period with a burst of 6 distinct buyers every
    hour (2 x b3 = 4 reached)."""
    out = []
    for pid in IDS[:2]:
        rows = [(t + 75,) + r[1:] for r in steps(START - 7 * DAY, now - 75, every=150) for t in [r[0]]]
        for h in range(0, int((now - START) // HOUR)):
            rows += [(START + h * HOUR + 400 + 7 * k, 'buy', 2 * 10 ** 8, 'P%d_%d' % (h, k)) for k in range(6)]
        pool = pages(tmp_path, pid, sorted(rows), name)
        out.append(pair(tmp_path, pool, now, name))
    return out


def test_the_universe_excludes_the_pilot_pools():
    for pools in ([GR.POOLS[0]], ['x', GR.POOLS[2]], [], ['x', 'x']):
        with pytest.raises(L.SimError):
            L.check_universe(pools)
    L.check_universe(['x', 'y'])


def test_six_hour_bilan_end_to_end(tmp_path):
    now = START + 6 * HOUR
    pairs = market(tmp_path, now)
    b3 = {p[2].pool: G2.baseline_b3(p[0], p[1], START) for p in pairs}
    doc = L.simulate(pairs, CONFIG_A, b3=b3, seed_sha=SEED, start=START, now=now)
    g = doc['g23']['primary']
    assert doc['hours'] == 6 and doc['trial'] is None and doc['counts_for_operational_master'] is False
    assert g['signals'] > 0 and g['signals'] == g['exits'] + g['open_positions']
    closed = [r for p in doc['journal'].values() for r in p['primary']['closed']]
    assert g['net_pnl_sol'] == pytest.approx(sum(r['net_lamports'] for r in closed) / 1e9)
    assert g['gross_pnl_sol'] - g['costs_sol'] == pytest.approx(g['net_pnl_sol'])
    assert g['capital_end_sol'] == pytest.approx(g['net_pnl_sol'])
    assert g['capital_curve'][0]['capital_sol'] == 0 and len(g['capital_curve']) == g['exits'] + 1
    assert g['win_rate'] == pytest.approx(sum(1 for r in closed if r['net_lamports'] > 0) / len(closed))
    assert [h['time'] for h in g['capital_by_hour']] == [START + h * HOUR for h in range(1, 7)]
    assert g['capital_by_hour'][-1]['capital_sol'] == pytest.approx(g['capital_end_sol'])
    assert doc['g23']['placebo_merged'] is False and set(doc['g23']) == {
        'primary', 'placebo', 'stake_sol', 'placebo_merged', 'capital_rule'}
    assert doc['g23']['stake_sol'] == 0.1
    assert all(r['exit_time'] <= now for r in closed)
    # the journal is the frozen functions
    pre, pre_txs, sim, sim_txs = pairs[0]
    known = L.truncated(sim, now)
    idx = [i for i in G2.decisions_g23(known, sim_txs, b3[sim.pool]) if known.swaps[i].block_time >= START]
    assert doc['journal'][sim.pool]['primary']['signals'] == len(idx)
    first = doc['journal'][sim.pool]['primary']['closed'][0]
    direct = GR.converted(known, GR.positions_each(known, CONFIG_A, [first['decision_index']]))[0]
    assert first['net_lamports'] == direct['net_lamports']
    # paired placebo: as many draws as signals (fewer only if candidates run out)
    assert 0 < doc['g23']['placebo']['signals'] <= g['signals']
    md = L.render(doc)
    assert '| G2-3 |' in md and '| témoin apparié |' in md and 'Résultat 12 jours : NON MESURÉ.' in md
    assert 'jamais additionné' in md and '| %d | %.6f |' % (START + 6 * HOUR, g['capital_end_sol']) in md


def test_open_positions_are_never_valued(tmp_path):
    now = START + 6 * HOUR
    pairs = market(tmp_path, now)
    b3 = {p[2].pool: G2.baseline_b3(p[0], p[1], START) for p in pairs}
    pre, pre_txs, sim, sim_txs = pairs[0]
    last = max(i for i in G2.decisions_g23(L.truncated(sim, now), sim_txs, b3[sim.pool]))
    t_last = sim.swaps[last].block_time
    early = L.g23_rows(sim, sim_txs, CONFIG_A, b3[sim.pool], SEED, start=START, now=t_last + 60)
    assert any(r['decision_index'] == last for r in early['primary']['open'])            # 1 minute after: open
    assert all(r['decision_index'] != last for r in early['primary']['closed'])
    later = L.g23_rows(sim, sim_txs, CONFIG_A, b3[sim.pool], SEED, start=START, now=t_last + 2 * HOUR)
    assert any(r['decision_index'] == last for r in later['primary']['closed'])           # 2 hours after: closed


def test_zero_signal_shows_zero_operations(tmp_path):
    now = START + 6 * HOUR
    sells = [(t, 'sell', 10 ** 12, 'S%d' % t) for t in range(START - 7 * DAY, now + 1, 600)]
    buys = [(t, 'buy', 2 * 10 ** 8, 'B%d' % t) for t in range(START - 7 * DAY + 300, START, 600)]
    pool = pages(tmp_path, IDS[2], sorted(sells + buys), 'z')
    pairs = [pair(tmp_path, pool, now, 'z')]
    doc = L.simulate(pairs, CONFIG_A, b3={pool: 1}, seed_sha=SEED, start=START, now=now)
    g = doc['g23']['primary']
    assert g['signals'] == g['entries'] == g['exits'] == 0 and g['win_rate'] == L.NM
    assert g['net_pnl_sol'] == 0 and g['capital_end_sol'] == 0 and g['max_drawdown_sol'] == 0
    assert g['net_return_per_position'] == L.NM and all(h['capital_sol'] == 0 for h in g['capital_by_hour'])
    assert 'Aucun signal G2-3 sur la fenêtre : 0 opération.' in L.render(doc)


def test_n1_hourly_observations_are_the_frozen_position(tmp_path):
    now = START + 5 * HOUR
    pairs = market(tmp_path, now)
    b3 = {p[2].pool: G2.baseline_b3(p[0], p[1], START) for p in pairs}
    doc = L.simulate(pairs, CONFIG_A, b3=b3, seed_sha=SEED, start=START, now=now)
    pre, _a, sim, _b = pairs[0]
    obs = doc['n1']['observations'][sim.pool]
    assert [o['time'] for o in obs] == [START + h * HOUR for h in range(1, 6)]
    union = L.replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)))
    direct = K.continuous_position(L.truncated(union, START + 3 * HOUR), CONFIG_A, start_time=START,
                                   end_time=START + DAY)
    assert obs[2]['status'] == 'observée'
    assert obs[2]['gap_return'] == pytest.approx(float(direct['gap_lamports'] / direct['stake_lamports']))


def test_metrics_drawdown_and_order():
    rows = [dict(pool='p', decision_index=k, exit_time=t, status='entered', net_lamports=n,
                 decomposition_share_of_stake=dict(price_move=(n + 500_000) / CC.STAKE_LAMPORTS))
            for k, (t, n) in enumerate([(30, -2 * 10 ** 9), (10, 1 * 10 ** 9), (20, 1 * 10 ** 9)])]
    m = L.metrics(rows, [dict(status='open')], signals=4)
    assert [c['capital_sol'] for c in m['capital_curve']] == [0, 1, 2, 0]                 # cumulative net, by exit
    assert [c['time'] for c in m['capital_curve']] == [None, 10, 20, 30]
    assert m['max_drawdown_sol'] == pytest.approx(2) and m['max_drawdown_stakes'] == pytest.approx(20)
    assert m['win_rate'] == pytest.approx(2 / 3) and m['wins'] == 2 and m['capital_end_sol'] == 0
    assert m['net_return_per_position'] == 0 and m['entries'] == 3 and m['exits'] == 3
    assert m['costs_sol'] == pytest.approx(3 * 0.0005) and m['open_positions'] == 1 and m['signals'] == 4
    assert m['gross_pnl_sol'] == pytest.approx(3 * 0.0005)
    down = L.metrics(rows[:1], [], signals=1)                                            # a first loss from 0
    assert down['max_drawdown_sol'] == pytest.approx(2) and down['net_return_per_position'] == pytest.approx(-20)
    assert L.by_hour(m['capital_curve'], start=0, now=2 * L.HOUR_S) == [dict(time=3_600, capital_sol=0),
                                                                        dict(time=7_200, capital_sol=0)]
    assert L.by_hour([dict(time=None, capital_sol=0.0), dict(time=3_600, capital_sol=1.0)], start=0,
                     now=7_199) == [dict(time=3_600, capital_sol=1.0)]
    zero = L.metrics(rows + [dict(pool='p', decision_index=9, exit_time=40, status='entered', net_lamports=0,
                                  decomposition_share_of_stake=dict(price_move=0.0))], [], signals=4)
    assert zero['win_rate'] == pytest.approx(2 / 4)                                       # a zero net is not a win
    refused = L.metrics([dict(pool='p', decision_index=0, exit_time=1, status='guard_failed', net_lamports=-105_000)],
                        [], signals=1)
    assert refused['entries'] == 0 and refused['guard_refusals'] == 1 and refused['costs_sol'] == pytest.approx(105e-6)
    assert refused['win_rate'] == 0 and refused['exits'] == 1                            # share of ALL closed rows
    zs = L.metrics([dict(pool='p', decision_index=0, exit_time=1, status='unpriced_zero_sale', net_lamports=-10)],
                   [], signals=1)
    assert zs['entries'] == 1 and zs['guard_refusals'] == 0
    mixed = L.metrics(rows[1:2] + [dict(pool='p', decision_index=8, exit_time=1, status='guard_failed',
                                        net_lamports=-105_000)], [], signals=2)
    assert mixed['win_rate'] == pytest.approx(1 / 2) and mixed['entries'] == 1          # refusals count as closed


def test_cli_writes_json_and_markdown(tmp_path, capsys, monkeypatch):
    now = START + 3 * HOUR
    for pid in IDS[:2]:
        pages(tmp_path, pid, steps(START - 7 * DAY, now + 1, every=150), 'c')
    monkeypatch.setattr(GR.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    monkeypatch.setattr(L, 'FROZEN', {k: v for k, v in L.FROZEN.items() if k != 'cpmmpilot'})   # local 0.1.6
    (tmp_path / 'pools.json').write_text(json.dumps(NAMES[:2]))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(selected=[dict(pool=p, base_mint=BASE_B58) for p in NAMES])))
    args = ['--pools', str(tmp_path / 'pools.json'), '--u2', str(tmp_path / 'u2.json'), '--pre-root',
            str(tmp_path / 'c' / 'pre'), '--root', str(tmp_path / 'c' / 'sim'), '--t0-slot', '1', '--start',
            str(START), '--now', str(now), '--out', str(tmp_path / 'out')]
    L.main(args)
    printed = json.loads(capsys.readouterr().out)
    for name in ('LIVESIM.json', 'LIVESIM.md'):
        assert printed[name] == hashlib.sha256((tmp_path / 'out' / name).read_bytes()).hexdigest()
    doc = json.loads((tmp_path / 'out' / 'LIVESIM.json').read_text())
    assert doc['frozen_code']['manifests']['g23run']['manifest_sha256'].startswith('3e3cb105')
    assert doc['frozen_code']['trees'] == {'cpmmx': {'git_tree': L.FROZEN_TREES['cpmmx']}}
    pre = GR.window_line(NAMES[0], BASE_B58, tmp_path / 'c' / 'pre' / NAMES[0], start=START - 7 * DAY, end=START)
    assert doc['b3'][NAMES[0]] == G2.baseline_b3(pre[0], pre[1], START)                  # frozen rule, 7 days
    assert doc['placebo_seed_sha256'] == hashlib.sha256(('livesim|%d|' % START + '\n'.join(NAMES[:2])).encode()
                                                        ).hexdigest()
    with pytest.raises(L.SimError, match='out_exists'):
        L.main(args)
    (tmp_path / 'pools.json').write_text(json.dumps([GR.POOLS[0]]))
    with pytest.raises(L.SimError, match='pilot'):
        L.main(args[:-1] + [str(tmp_path / 'out2')])


def test_now_is_respected_and_the_start_filters_signals(tmp_path):
    now = START + 6 * HOUR
    pairs = market(tmp_path, now)
    pre, pre_txs, sim, sim_txs = pairs[0]
    b3 = G2.baseline_b3(pre, pre_txs, START)
    cut = START + 3 * HOUR
    full = L.g23_rows(sim, sim_txs, CONFIG_A, b3, SEED, start=START, now=cut)
    short = L.replace(sim, swaps=tuple(s for s in sim.swaps if s.block_time <= cut))
    assert full == L.g23_rows(short, sim_txs, CONFIG_A, b3, SEED, start=START, now=cut)   # nothing after now is seen
    union = L.replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda x: x.key)))
    txs = dict(pre_txs, **sim_txs)
    on_union = L.g23_rows(union, txs, CONFIG_A, b3, SEED, start=START, now=cut)
    assert on_union['primary']['signals'] == full['primary']['signals']                    # signals of [start ; now)
    assert all(r['decision_time'] >= START for r in on_union['primary']['closed'] + on_union['primary']['open'])
    late = L.g23_rows(sim, sim_txs, CONFIG_A, b3, SEED, start=START + 2 * HOUR, now=cut)
    assert 0 < late['primary']['signals'] < full['primary']['signals']
    assert all(r['decision_time'] >= START + 2 * HOUR for r in late['primary']['closed'] + late['primary']['open'])
    with pytest.raises(L.SimError, match='now'):
        L.simulate(pairs, CONFIG_A, b3={p[2].pool: 2 for p in pairs}, seed_sha=SEED, start=START, now=START)


def test_n1_after_one_day_and_without_pre_state(tmp_path):
    now = START + 26 * HOUR
    pairs = market(tmp_path, now)
    pre, _a, sim, _b = pairs[0]
    union = L.replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda x: x.key)))
    obs = L.n1_observations(union, CONFIG_A, start=START, now=now)
    assert len(obs) == 26
    direct = K.continuous_position(L.truncated(union, START + 25 * HOUR), CONFIG_A, start_time=START,
                                   end_time=START + 2 * DAY)
    assert obs[24]['gap_return'] == pytest.approx(float(direct['gap_lamports'] / direct['stake_lamports']))
    alone = L.n1_observations(sim, CONFIG_A, start=START, now=START + HOUR)                  # no state before START
    assert alone[0]['status'] == 'non valorisable'


def test_gate_and_vocabulary(tmp_path, monkeypatch):
    now = START + 3 * HOUR
    pairs = market(tmp_path, now)
    b3 = {p[2].pool: G2.baseline_b3(p[0], p[1], START) for p in pairs}
    real = CC.pool_gate
    monkeypatch.setattr(CC, 'pool_gate', lambda line, cfg: dict(admitted=False, reasons=['undecoded_transactions'])
                        if line.pool == pairs[1][2].pool else real(line, cfg))
    doc = L.simulate(pairs, CONFIG_A, b3=b3, seed_sha=SEED, start=START, now=now)
    assert pairs[1][2].pool not in doc['journal'] and pairs[1][2].pool not in doc['n1']['observations']
    assert 'undecoded_transactions' in L.render(doc)
    monkeypatch.setattr(CC, 'pool_gate', real)
    from g1ind import report as G1
    bad = [(p[0], p[1], L.replace(p[2], pool=p[2].pool + ' ' + G1.FORBIDDEN_WORDS[0]), p[3]) for p in pairs[:1]]
    with pytest.raises(G1.ReportError, match='forbidden'):
        L.simulate(bad, CONFIG_A, b3={bad[0][2].pool: 2}, seed_sha=SEED, start=START, now=now)


def test_pre_window_is_the_seven_days_required(tmp_path, capsys, monkeypatch):
    seen = []
    real = GR.window_line
    monkeypatch.setattr(GR, 'window_line', lambda *a, **kw: seen.append((kw['start'], kw['end'])) or real(*a, **kw))
    now = START + 3 * HOUR
    for pid in IDS[:2]:
        pages(tmp_path, pid, steps(START - 7 * DAY, now + 1, every=50), 'w')
    monkeypatch.setattr(GR.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    monkeypatch.setattr(L, 'FROZEN', {k: v for k, v in L.FROZEN.items() if k != 'cpmmpilot'})
    (tmp_path / 'pools.json').write_text(json.dumps(NAMES[:2]))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(selected=[dict(pool=p, base_mint=BASE_B58) for p in NAMES])))
    L.main(['--pools', str(tmp_path / 'pools.json'), '--u2', str(tmp_path / 'u2.json'), '--pre-root',
            str(tmp_path / 'w' / 'pre'), '--root', str(tmp_path / 'w' / 'sim'), '--t0-slot', '1', '--start', str(START),
            '--now', str(now), '--out', str(tmp_path / 'out')])
    assert seen == [(START - 7 * DAY, START), (START, now + 1)] * 2
    doc = json.loads((tmp_path / 'out' / 'LIVESIM.json').read_text())
    pre = real(NAMES[0], BASE_B58, tmp_path / 'w' / 'pre' / NAMES[0], start=START - 7 * DAY, end=START)
    assert doc['b3'][NAMES[0]] == G2.baseline_b3(pre[0], pre[1], START) == 6               # recomputed, not 2/1/6/1
    assert L.PRE_DAYS == N1R.DAYS == R.COUNT_DAYS == 7


def test_cli_checks_the_frozen_code_before_and_after(tmp_path, capsys, monkeypatch):
    now = START + 2 * HOUR
    for pid in IDS[:2]:
        pages(tmp_path, pid, steps(START - 7 * DAY, now + 1, every=150), 'f')
    monkeypatch.setattr(GR.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'pools.json').write_text(json.dumps(NAMES[:2]))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(selected=[dict(pool=p, base_mint=BASE_B58) for p in NAMES])))
    args = ['--pools', str(tmp_path / 'pools.json'), '--u2', str(tmp_path / 'u2.json'), '--pre-root',
            str(tmp_path / 'f' / 'pre'), '--root', str(tmp_path / 'f' / 'sim'), '--t0-slot', '1', '--start',
            str(START), '--now', str(now), '--out', str(tmp_path / 'out')]
    read = []
    real = GR.window_line
    monkeypatch.setattr(GR, 'window_line', lambda *a, **kw: read.append(1) or real(*a, **kw))
    with pytest.raises(L.SimError, match='manifest_missing:cpmmpilot'):                   # the full list, as anchored
        L.main(args)
    assert read == [] and not (tmp_path / 'out').exists()                                # no page read
    ok = {k: v for k, v in L.FROZEN.items() if k != 'cpmmpilot'}
    monkeypatch.setattr(L, 'FROZEN', dict(ok, lpcost=(ok['lpcost'][0], '0' * 64)))
    with pytest.raises(L.SimError, match='manifest_sha_differs:lpcost'):
        L.main(args)
    monkeypatch.setattr(L, 'FROZEN', ok)
    monkeypatch.setattr(L, 'FROZEN_TREES', {'cpmmx': '0' * 40})
    with pytest.raises(L.SimError, match='frozen_tree_differs:cpmmx'):
        L.main(args)
    assert read == []
    monkeypatch.setattr(L, 'FROZEN_TREES', dict(cpmmx=L.git_tree(L._package_dir('cpmmx'))))
    calls = []
    real_check = L.check_frozen
    monkeypatch.setattr(L, 'check_frozen', lambda: calls.append(1) or dict(real_check(), n=len(calls)))
    with pytest.raises(L.SimError, match='changed_during_the_run'):
        L.main(args)
    assert len(calls) == 2 and read and not (tmp_path / 'out').exists()


def _copy(tmp_path, name):
    dst = tmp_path / (name + '_pkg')
    shutil.copytree(L._package_dir(name), dst, ignore=shutil.ignore_patterns('__pycache__'))
    return dst


def test_manifest_check_detects_every_change(tmp_path):
    ok = {k: v for k, v in L.FROZEN.items() if k != 'cpmmpilot'}
    got = L.check_frozen(ok)
    assert set(got) == set(ok) and all(v['files_checked'] > 0 for v in got.values())
    assert set(L.FROZEN) == {'cpmmcost', 'cpmmgen2', 'cpmmprereg', 'g1ind', 'g23run', 'lpcost', 'n1rot', 'cpmmpilot'}
    assert L.FROZEN['cpmmpilot'][1].startswith('7251d4fe') and L.FROZEN['g23run'][1].startswith('3e3cb105')
    assert L.FROZEN['n1rot'][1].startswith('2a17791d') and L.FROZEN['lpcost'][1].startswith('ee9c144c')
    name, (manifest, sha) = 'lpcost', ok['lpcost']
    one = {name: (manifest, sha)}
    copy = _copy(tmp_path, name)
    assert L.check_frozen(one, locate=lambda n: copy)[name]['manifest_sha256'] == sha
    target = copy / 'lpcost' / 'continuous.py'
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(L.SimError, match='frozen_file_differs:lpcost:lpcost/continuous.py'):
        L.check_frozen(one, locate=lambda n: copy)
    (copy / 'lpcost' / 'continuous.py').unlink()
    with pytest.raises(L.SimError, match='frozen_file_differs'):
        L.check_frozen(one, locate=lambda n: copy)
    with pytest.raises(L.SimError, match='manifest_sha_differs:lpcost'):
        L.check_frozen({name: (manifest, '1' * 64)}, locate=lambda n: copy)
    with pytest.raises(L.SimError, match='manifest_missing:lpcost'):
        L.check_frozen({name: ('MANIFEST_absent.txt', sha)}, locate=lambda n: copy)
    # a LOADED file that the MANIFEST does not list
    copy2 = _copy(tmp_path / 'b', name)
    kept = [r for r in (copy2 / manifest).read_text().splitlines() if not r.endswith('./lpcost/continuous.py')]
    assert len(kept) == len((copy2 / manifest).read_text().splitlines()) - 1
    (copy2 / manifest).write_text('\n'.join(kept) + '\n')
    new = hashlib.sha256((copy2 / manifest).read_bytes()).hexdigest()
    with pytest.raises(L.SimError, match='loaded_file_not_in_manifest:lpcost:lpcost/continuous.py'):
        L.check_frozen({name: (manifest, new)}, locate=lambda n: copy2)


def test_git_tree_of_cpmmx(tmp_path):
    assert L.check_trees() == {'cpmmx': {'git_tree': 'e103437142c74830e6ddc293d84529501f6b1162'}}
    copy = _copy(tmp_path, 'cpmmx')
    assert L.git_tree(copy) == L.FROZEN_TREES['cpmmx']
    (copy / 'cpmmx' / '__pycache__').mkdir(exist_ok=True)
    (copy / 'cpmmx' / '__pycache__' / 'x.pyc').write_bytes(b'x')
    assert L.git_tree(copy) == L.FROZEN_TREES['cpmmx']                                   # ignored
    f = sorted((copy / 'cpmmx').glob('*.py'))[0]
    f.chmod(0o755)
    assert L.git_tree(copy) != L.FROZEN_TREES['cpmmx']                                   # mode counts
    f.chmod(0o644)
    (copy / 'cpmmx' / 'extra.py').write_text('')
    with pytest.raises(L.SimError, match='frozen_tree_differs'):
        L.check_trees(locate=lambda n: copy)


def _thin(line, every):
    return L.replace(line, swaps=line.swaps[::every])


def test_n1_universe_is_n1rot_rule_on_another_list(tmp_path, monkeypatch):
    pairs = market(tmp_path, START + 2 * HOUR)
    pres = [pairs[0][0], pairs[1][0], _thin(pairs[0][0], 4), _thin(pairs[1][0], 9)]
    named = [L.replace(x, pool=p) for x, p in zip(pres, N1R.NAMED_POOLS)]
    ref = N1R.select_n1(named, CONFIG_A, START, threshold='r04_6_break_even')
    mine = L.n1_universe(named, CONFIG_A, START)
    assert mine['kept'] == ref['kept'] and mine['list_sha256'] == ref['list_sha256']
    assert 0 < len(mine['kept']) < 4                                                     # both outcomes occur
    for a, b in zip(mine['pools'], ref['pools']):
        assert (a['pool'], a['kept'], a['median_rotation_exact'], a['threshold_exact'], a['days']) == (
            b['pool'], b['kept'], b['median_rotation_exact'], b['threshold_exact'], b['days'])
    assert mine['min_pools'] == 3 and mine['min_pools_met'] is (len(mine['kept']) >= 3)
    assert mine['window'] == [START - 7 * DAY, START]
    # the same rule on non-pilot names, n1rot untouched
    other = L.n1_universe(pres, CONFIG_A, START)
    assert [r['kept'] for r in other['pools']] == [r['kept'] for r in ref['pools']]
    empty = L.n1_universe([L.replace(pres[0], swaps=(), lp_changes=())], CONFIG_A, START)
    assert empty['kept'] == [] and empty['pools'][0]['threshold_value'] == L.NM
    assert empty['pools'][0]['reason'].startswith('seuil non calculable')
    med = N1R.median_rotation(N1R.daily_rotation(pres[0], START))
    monkeypatch.setattr(N1R, 'break_even_rotation_r04_6', lambda line, cfg, t0: med)       # equality is kept
    assert L.n1_universe(pres[:1], CONFIG_A, START)['kept'] == [pres[0].pool]
    monkeypatch.undo()
    with pytest.raises(N1R.RotationError, match='after_t0'):                             # history before start only
        L.n1_universe([pairs[0][2]], CONFIG_A, START)


def test_n1_marks_only_for_kept_pools_and_12_days_not_measured(tmp_path):
    now = START + 3 * HOUR
    pairs = market(tmp_path, now)
    thin = (_thin(pairs[1][0], 9),) + pairs[1][1:]
    pairs = [pairs[0], thin]
    b3 = {p[2].pool: G2.baseline_b3(p[0], p[1], START) for p in pairs}
    doc = L.simulate(pairs, CONFIG_A, b3=b3, seed_sha=SEED, start=START, now=now)
    u = doc['n1']['universe']
    assert u['kept'] == [pairs[0][2].pool]
    assert list(doc['n1']['observations']) == [pairs[0][2].pool] and doc['n1']['result_12_days'] == 'NON MESURÉ'
    assert pairs[1][2].pool in doc['journal']                                            # G2-3 still runs there
    md = L.render(doc)
    assert 'Résultat 12 jours : NON MESURÉ.' in md and '| non | — | non retenu |' in md
    assert 'plancher de 3 pools de n1rot : non atteint' in md
    assert len(doc['limits']) == 7 and md.count('\n- L') == 7 and '## Limites (7)' in md
    assert all(x in md for x in doc['limits'])


def test_frozen_constants_are_checked_at_import(monkeypatch):
    monkeypatch.setattr(N1R, 'DAYS', 6)
    with pytest.raises(ValueError, match='frozen_constants'):
        importlib.reload(L)
    monkeypatch.undo()
    for mod, attr, value in ((CC, 'STAKE_LAMPORTS', 10 ** 9), (R, 'COUNT_DAYS', 8), (N1R, 'R046_STAKE_PPM', 1)):
        monkeypatch.setattr(mod, attr, value)
        with pytest.raises(ValueError, match='frozen_constants'):
            importlib.reload(L)
        monkeypatch.undo()
    importlib.reload(L)
