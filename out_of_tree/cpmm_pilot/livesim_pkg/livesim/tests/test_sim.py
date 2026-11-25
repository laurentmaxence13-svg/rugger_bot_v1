"""livesim 0.1 on synthetic CPMM pools only (pages written in the cpmmpilot.store layout); no collected page."""
import hashlib
import json

import pytest

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmprereg import rule as R
from g23run import run as GR
from g23run.tests.test_run import BASE_B58, CONFIG_A, IDS, NAMES, raw_txs, steps, write_pages
from livesim import sim as L
from lpcost import continuous as K

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
    assert g['capital_end_sol'] == pytest.approx(10 + g['net_pnl_sol'])
    assert g['capital_curve'][0]['capital_sol'] == 10 and len(g['capital_curve']) == g['exits'] + 1
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
    assert '| G2-3 |' in md and '| témoin apparié |' in md and 'pas le résultat 12 jours' in md


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
    assert g['net_pnl_sol'] == 0 and g['capital_end_sol'] == 10 and g['max_drawdown'] == 0
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
    assert [c['capital_sol'] for c in m['capital_curve']] == [10, 11, 12, 10]             # ordered by exit time
    assert m['max_drawdown'] == pytest.approx(2 / 12) and m['win_rate'] == pytest.approx(2 / 3)
    assert m['costs_sol'] == pytest.approx(3 * 0.0005) and m['open_positions'] == 1 and m['signals'] == 4
    zero = L.metrics(rows + [dict(pool='p', decision_index=9, exit_time=40, status='entered', net_lamports=0,
                                  decomposition_share_of_stake=dict(price_move=0.0))], [], signals=4)
    assert zero['win_rate'] == pytest.approx(2 / 4)                                       # a zero net is not a win
    refused = L.metrics([dict(pool='p', decision_index=0, exit_time=1, status='guard_failed', net_lamports=-105_000)],
                        [], signals=1)
    assert refused['entries'] == 0 and refused['guard_refusals'] == 1 and refused['costs_sol'] == pytest.approx(105e-6)


def test_cli_writes_json_and_markdown(tmp_path, capsys, monkeypatch):
    now = START + 3 * HOUR
    for pid in IDS[:2]:
        pages(tmp_path, pid, steps(START - 7 * DAY, now + 1, every=150), 'c')
    monkeypatch.setattr(GR.PILOT, 'amm_config_for_rules', lambda rows, slot: dict(CONFIG_A, slot=slot))
    (tmp_path / 'pools.json').write_text(json.dumps(NAMES[:2]))
    (tmp_path / 'u2.json').write_text(json.dumps(dict(selected=[dict(pool=p, base_mint=BASE_B58) for p in NAMES])))
    args = ['--pools', str(tmp_path / 'pools.json'), '--u2', str(tmp_path / 'u2.json'), '--pre-root',
            str(tmp_path / 'c' / 'pre'), '--root', str(tmp_path / 'c' / 'sim'), '--t0-slot', '1', '--start',
            str(START), '--now', str(now), '--out', str(tmp_path / 'out')]
    L.main(args)
    printed = json.loads(capsys.readouterr().out)
    for name in ('LIVESIM.json', 'LIVESIM.md'):
        assert printed[name] == hashlib.sha256((tmp_path / 'out' / name).read_bytes()).hexdigest()
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
