"""livesim 0.3 on synthetic CPMM pools only, written in R03's collection layout (CONFIG, QUALIFIED, POLLS, pages
collect/pre and collect/live_NNN) with a synthetic LIST_L; no collected page.
The Python path carries cpmmpilot 0.2.8 extracted from R03's commit 8c4a022 (R02 erratum 09:53:41Z, option (ii)): every
frozen check runs as it is, cpmmpilot included."""
import hashlib
import importlib
import json
import shutil

import pytest

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmgen3.tests.test_gen3 import CONFIG_A, FEES_A, Pool
from cpmmpilot import step1 as PILOT
from cpmmprereg import rule as R
from cpmmx import curve, events
from cpmmx.tests.test_cpmmx import BASE_B58, logs, tx
from g23run import run as GR
from g23run.tests.test_run import steps, write_pages
from livesim import sim as L
from lpcost import continuous as K
from n1rot import rotation as N1R

DAY, HOUR = 86_400, 3_600
START = 20 * DAY
SEED = 'ab' * 32
IDS = [bytes(range(k, k + 32)) for k in (1, 41, 81, 121)]
NAMES = [events.b58encode(p) for p in IDS]
CFG_A = dict(trade_fee_rate=2_500, creator_fee_rate=0, protocol_fee_rate=120_000, fund_fee_rate=40_000,
             raw_sha256='ab' * 32)
CFG_B = dict(CFG_A, creator_fee_rate=10_000, raw_sha256='cd' * 32)           # as CRRS5i: creator fee 1 % declared
FEES_B = curve.Fees(2_500, 0, 120_000, 40_000)   # ... but not charged: enable_creator_fee = 0 (cpmmcost 0.3.1, E-CF)
OK_FROZEN = dict(L.FROZEN)                                                       # nothing dropped


def raw_txs(pid, rows, fees):
    sim, out = Pool(pid, 10 ** 15, 200 * 10 ** 9, fees), {}
    for k, (t, side, amount, payer) in enumerate(rows):
        sig = '%s%06d' % (pid[:2].hex(), k)
        payload = sim.deposit(1, 10) if side == 'lp' else sim.swap(side, amount)
        raw = tx(t * 2, 0, logs(payload), when=t)
        raw['transaction'] = dict(signatures=[sig], message=dict(accountKeys=[payer, 'Other']))
        out[sig] = raw
    return out


def market_rows(now, *, bursts=True, every=150, pre_every=None):
    """7 days before the start (alternating buys / sales: b3 = 2 at every = 150) then the live period, with a burst of
    6 distinct buyers every hour (2 x b3 = 4 reached)."""
    pre_every = pre_every or every
    rows = [(r[0] + 75,) + r[1:] for r in steps(START - 7 * DAY, START - 75, every=pre_every)]
    rows += [(r[0] + 75,) + r[1:] for r in steps(START, now - 75, every=every)]
    if bursts:
        for h in range(int((now - START) // HOUR)):
            rows += [(START + h * HOUR + 400 + 7 * k, 'buy', 2 * 10 ** 8, 'P%d_%d' % (h, k)) for k in range(6)]
    return sorted(rows)


def collection(tmp_path, now, specs, *, done_until=None, monkeypatch=None):
    """R03's layout under tmp/OUT for pools [(pid, fees, cfg, rows)], LIST_L beside; returns (out, list_l path)."""
    out = tmp_path / 'OUT'
    done_until = now if done_until is None else done_until
    n_chunks = -(-(now - START) // L.CHUNK_S)
    polls = [dict(name='live_%03d' % i, window=[START + i * L.CHUNK_S, START + (i + 1) * L.CHUNK_S],
                  done=START + (i + 1) * L.CHUNK_S <= done_until) for i in range(n_chunks)]
    configs, rows_l = {}, []
    for pid, fees, cfg, rows in specs:
        pool = events.b58encode(pid)
        txs = raw_txs(pid, rows, fees)
        write_pages(out / 'collect' / 'pre' / pool, {s: r for s, r in txs.items() if r['blockTime'] < START})
        for c in polls:
            write_pages(out / 'collect' / c['name'] / pool,
                        {s: r for s, r in txs.items() if c['window'][0] <= r['blockTime'] < c['window'][1]})
        key = 'CFG_%s' % cfg['raw_sha256'][:2]
        configs[key] = cfg
        rows_l.append(dict(pool=pool, base_mint=BASE_B58, config=key, reserve_lamports=1, wsol_vault='W'))
    pools = [events.b58encode(s[0]) for s in specs]
    out.mkdir(parents=True, exist_ok=True)
    (out / 'CONFIG.json').write_text(json.dumps(dict(t_start=START, cap=1000, universe_list_sha256='x', k=8)))
    (out / 'QUALIFIED.json').write_text(json.dumps(dict(pools=pools, k=len(pools), k_target=8, complete=False,
                                                        list_sha256=hashlib.sha256('\n'.join(pools).encode())
                                                        .hexdigest(), tested=[])))
    (out / 'POLLS.json').write_text(json.dumps(polls))
    list_l = tmp_path / 'LIST_L.json'
    list_l.write_text(json.dumps(dict(list=rows_l, configs=configs, t0_slot=7, t0_time=0, schema='x', sha256='x',
                                      counts={})))
    if monkeypatch is not None:
        monkeypatch.setattr(L, 'LIST_L_SHA256', hashlib.sha256(list_l.read_bytes()).hexdigest())
    return out, list_l


def three(tmp_path, now, monkeypatch, **kw):
    """Three pools: two on config A, one on config B (creator fee 1 % declared, not charged), all with hourly bursts."""
    specs = [(IDS[0], FEES_A, CFG_A, market_rows(now)), (IDS[1], FEES_A, CFG_A, market_rows(now)),
             (IDS[2], FEES_B, CFG_B, market_rows(now))]
    return collection(tmp_path, now, specs, monkeypatch=monkeypatch, **kw)


def eligible_doc(out, list_l):
    return L.eligibility(out, L.list_l_doc(list_l))


def run_bilan(out, list_l, now):
    return L.bilan(out, L.list_l_doc(list_l), eligible_doc(out, list_l), now)


def test_the_universe_excludes_the_pilot_and_forbidden_pools():
    for pools in ([GR.POOLS[0]], ['x', GR.POOLS[2]], [], ['x', 'x'], ['2yLFomCTck19BqK7EzJqsUWXPWP3uWGNBSrfKvJzNzp2']):
        with pytest.raises(L.SimError):
            L.check_universe(pools)
    L.check_universe(['x', 'y'])


def test_six_hour_bilan_end_to_end(tmp_path, monkeypatch):
    now = START + 6 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    doc = run_bilan(out, list_l, now)
    g = doc['g23']['primary']
    assert doc['hours'] == 6 and doc['trial'] is None and doc['counts_for_operational_master'] is False
    assert doc['eligible'] == NAMES[:3] and doc['chunks'] == ['live_000', 'live_001', 'live_002']
    assert doc['amm_config_sha256'] == {NAMES[0]: 'ab' * 32, NAMES[1]: 'ab' * 32, NAMES[2]: 'cd' * 32}
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
    assert doc['g23']['stake_sol'] == 0.1 and all(r['exit_time'] <= now for r in closed)
    assert 0 < doc['g23']['placebo']['signals'] <= g['signals']
    assert doc['placebo_seed_sha256'] == hashlib.sha256(('livesim|%d|' % START + '\n'.join(NAMES[:3])).encode()
                                                        ).hexdigest()
    md = L.render(doc)
    assert g['exits'] < 30 and g['n_insufficient'] is True
    assert '| G2-3 (n insuffisant : %d < 30) |' % g['exits'] in md and '| témoin apparié (n insuffisant' in md
    assert 'Résultat 12 jours : NON MESURÉ.' in md
    assert doc['n1']['status'] == 'marques intermédiaires' and doc['n1']['pool_days'] == 3   # 3 kept pools x 1 day
    assert doc['n1']['n_insufficient'] is True and 'Pool-jours marqués : 3 — n insuffisant (< 30).' in md
    assert 'jamais additionné' in md and '| %d | %.6f |' % (START + 6 * HOUR, g['capital_end_sol']) in md
    assert 'retiré à chaque « now »' in md                                                # F5 declared


def test_one_config_per_pool(tmp_path, monkeypatch):
    now = START + 4 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    doc = run_bilan(out, list_l, now)
    ll = L.list_l_doc(list_l)
    rows = [dict(r, amm_config=ll['configs'][r['config']]) for r in ll['list']]
    with pytest.raises(PILOT.Step1Stop):                                                  # why 0.1 failed (F1)
        PILOT.amm_config_for_rules(rows, 7)
    cfg_b = L.pool_config(ll, NAMES[2])
    assert cfg_b == dict(CFG_B, sha256='cd' * 32, slot=7)
    pre = L.pre_pair(out, NAMES[2], BASE_B58, START)
    chunks = L.chunks_until(out, START, now)
    sim, sim_txs, _ = L.live_pair(out, NAMES[2], BASE_B58, chunks)
    assert CC.pool_gate(L.truncated(sim, now), cfg_b)['admitted']                         # 0.3.1: rate not charged
    assert not CC.pool_gate(L.truncated(sim, now), dict(cfg_b, pool_creator_fee_enabled=True))['admitted']  # 0.3
    b3 = G2.baseline_b3(pre[0], pre[1], START)
    direct = L.g23_rows(sim, sim_txs, cfg_b, b3, doc['placebo_seed_sha256'], start=START, now=now)
    assert doc['journal'][NAMES[2]] == direct
    with pytest.raises(L.SimError, match='one_config'):
        L.simulate([(pre[0], pre[1], sim, sim_txs)] * 1, {}, b3={NAMES[2]: b3}, seed_sha=SEED, start=START, now=now)
    with pytest.raises(L.SimError, match='pool_not_once'):
        L.pool_config(dict(ll, list=ll['list'] + ll['list'][:1]), NAMES[0])


def test_open_positions_are_never_valued(tmp_path, monkeypatch):
    now = START + 6 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    pre = L.pre_pair(out, NAMES[0], BASE_B58, START)
    sim, sim_txs, _ = L.live_pair(out, NAMES[0], BASE_B58, L.chunks_until(out, START, now))
    b3 = G2.baseline_b3(pre[0], pre[1], START)
    last = max(G2.decisions_g23(L.truncated(sim, now), sim_txs, b3))
    t_last = sim.swaps[last].block_time
    early = L.g23_rows(sim, sim_txs, CONFIG_A, b3, SEED, start=START, now=t_last + 60)
    assert any(r['decision_index'] == last for r in early['primary']['open'])
    assert all(r['decision_index'] != last for r in early['primary']['closed'])
    later = L.g23_rows(sim, sim_txs, CONFIG_A, b3, SEED, start=START, now=t_last + 2 * HOUR)
    assert any(r['decision_index'] == last for r in later['primary']['closed'])


def test_zero_signal_shows_zero_operations(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    specs = [(pid, FEES_A, CFG_A, market_rows(now, bursts=False)) for pid in IDS[:3]]
    out, list_l = collection(tmp_path, now, specs, monkeypatch=monkeypatch)
    doc = run_bilan(out, list_l, now)
    g = doc['g23']['primary']
    assert g['signals'] == g['entries'] == g['exits'] == 0 and g['win_rate'] == L.NM
    assert g['net_pnl_sol'] == 0 and g['capital_end_sol'] == 0 and g['max_drawdown_sol'] == 0
    assert g['net_return_per_position'] == L.NM and all(h['capital_sol'] == 0 for h in g['capital_by_hour'])
    assert 'Aucun signal G2-3 sur la fenêtre : 0 opération.' in L.render(doc)


def test_fewer_than_three_eligible_is_non_evaluable(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    dead = [(t, 'sell', 10 ** 12, 'S%d' % t) for t in range(START - 7 * DAY + 50, now - 10, 600)]  # b3 = 0
    specs = [(IDS[0], FEES_A, CFG_A, market_rows(now)), (IDS[1], FEES_A, CFG_A, market_rows(now)),
             (IDS[3], FEES_A, CFG_A, dead)]
    out, list_l = collection(tmp_path, now, specs, monkeypatch=monkeypatch)
    el = eligible_doc(out, list_l)
    assert el['pools'] == NAMES[:2] and el['evaluable'] is False and 'NON ÉVALUABLE' in el['conduct']
    assert [r['b3'] for r in el['rows']][2] == 0 and el['rows'][2]['g0_admitted'] is True
    with pytest.raises(L.SimError, match='non_evaluable'):
        L.bilan(out, L.list_l_doc(list_l), el, now)
    # at `now`, the same rule: b3 = 0 or G-0 not admitted makes a pool non eligible
    ll = L.list_l_doc(list_l)
    chunks = L.chunks_until(out, START, now)
    pairs, configs, b3 = [], {}, {}
    for x in NAMES[:2] + [NAMES[3]]:
        pre = L.pre_pair(out, x, BASE_B58, START)
        sim = L.live_pair(out, x, BASE_B58, chunks)
        pairs.append((pre[0], pre[1], sim[0], sim[1]))
        configs[x], b3[x] = L.pool_config(ll, x), G2.baseline_b3(pre[0], pre[1], START)
    doc = L.simulate(pairs, configs, b3=b3, seed_sha=SEED, start=START, now=now)
    assert doc['status'] == 'NON ÉVALUABLE' and doc['g23'] is None and doc['n1'] is None and doc['journal'] is None
    md = L.render(doc)
    assert 'P&L brut' not in md and 'Capital fictif par heure' not in md and 'NON ÉVALUABLE' in md
    assert '| non |' in md and len(doc['limits']) == 7
    doc3 = L.simulate(pairs, configs, b3=dict(b3, **{NAMES[3]: 2}), seed_sha=SEED, start=START, now=now)
    assert doc3['status'] != 'NON ÉVALUABLE' and doc3['eligible'] == NAMES[:2] + [NAMES[3]]
    real = CC.pool_gate
    monkeypatch.setattr(CC, 'pool_gate', lambda line, cfg: dict(admitted=False, reasons=['undecoded_transactions'])
                        if line.pool == NAMES[0] else real(line, cfg))
    gated = L.simulate(pairs, configs, b3=dict(b3, **{NAMES[3]: 2}), seed_sha=SEED, start=START, now=now)
    assert gated['g23'] is None and NAMES[0] not in gated['eligible']
    assert 'undecoded_transactions' in L.render(gated)


def all_a(tmp_path, now, monkeypatch):
    return collection(tmp_path, now, [(pid, FEES_A, CFG_A, market_rows(now)) for pid in IDS[:3]],
                      monkeypatch=monkeypatch)


def test_n1_hourly_observations_are_the_frozen_position(tmp_path, monkeypatch):
    now = START + 4 * HOUR
    out, list_l = all_a(tmp_path, now, monkeypatch)
    doc = run_bilan(out, list_l, now)
    assert doc['n1']['pools'] == NAMES[:3] and doc['n1']['status'] == 'marques intermédiaires'
    pre = L.pre_pair(out, NAMES[2], BASE_B58, START)
    sim = L.live_pair(out, NAMES[2], BASE_B58, L.chunks_until(out, START, now))[0]
    obs = doc['n1']['observations'][NAMES[2]]
    assert [o['time'] for o in obs] == [START + h * HOUR for h in range(1, 5)]
    union = L.replace(sim, swaps=tuple(sorted(pre[0].swaps + sim.swaps, key=lambda s: s.key)))
    direct = K.continuous_position(L.truncated(union, START + 3 * HOUR), L.pool_config(L.list_l_doc(list_l),
                                                                                      NAMES[2]),
                                   start_time=START, end_time=START + DAY)
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
    assert refused['win_rate'] == 0 and refused['exits'] == 1
    zs = L.metrics([dict(pool='p', decision_index=0, exit_time=1, status='unpriced_zero_sale', net_lamports=-10)],
                   [], signals=1)
    assert zs['entries'] == 1 and zs['guard_refusals'] == 0
    assert m['n_insufficient'] is True
    many = [dict(rows[1], decision_index=k, exit_time=k) for k in range(30)]
    assert L.metrics(many, [], signals=30)['n_insufficient'] is False
    assert L.metrics(many[:29], [], signals=29)['n_insufficient'] is True
    mixed = L.metrics(rows[1:2] + [dict(pool='p', decision_index=8, exit_time=1, status='guard_failed',
                                        net_lamports=-105_000)], [], signals=2)
    assert mixed['win_rate'] == pytest.approx(1 / 2) and mixed['entries'] == 1


def test_now_is_respected_and_the_start_filters_signals(tmp_path, monkeypatch):
    now = START + 6 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    pre = L.pre_pair(out, NAMES[0], BASE_B58, START)
    sim, sim_txs, _ = L.live_pair(out, NAMES[0], BASE_B58, L.chunks_until(out, START, now))
    b3 = G2.baseline_b3(pre[0], pre[1], START)
    cut = START + 3 * HOUR
    full = L.g23_rows(sim, sim_txs, CONFIG_A, b3, SEED, start=START, now=cut)
    short = L.replace(sim, swaps=tuple(s for s in sim.swaps if s.block_time <= cut))
    assert full == L.g23_rows(short, sim_txs, CONFIG_A, b3, SEED, start=START, now=cut)
    union = L.replace(sim, swaps=tuple(sorted(pre[0].swaps + sim.swaps, key=lambda x: x.key)))
    on_union = L.g23_rows(union, dict(pre[1], **sim_txs), CONFIG_A, b3, SEED, start=START, now=cut)
    assert on_union['primary']['signals'] == full['primary']['signals']
    assert all(r['decision_time'] >= START for r in on_union['primary']['closed'] + on_union['primary']['open'])
    late = L.g23_rows(sim, sim_txs, CONFIG_A, b3, SEED, start=START + 2 * HOUR, now=cut)
    assert 0 < late['primary']['signals'] < full['primary']['signals']
    with pytest.raises(L.SimError, match='now'):
        L.simulate([(pre[0], pre[1], sim, sim_txs)], {NAMES[0]: CONFIG_A}, b3={NAMES[0]: 2}, seed_sha=SEED,
                   start=START, now=START)


def test_chunks_and_pre_window(tmp_path, monkeypatch):
    now = START + 6 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch, done_until=START + 4 * HOUR)
    assert [c['name'] for c in L.chunks_until(out, START, START + 4 * HOUR)] == ['live_000', 'live_001']
    for bad, why in ((START + 5 * HOUR, 'end_of_a_done_chunk'), (START + 6 * HOUR, 'chunk_not_done:live_002'),
                     (START, 'end_of_a_done_chunk')):
        with pytest.raises(L.SimError, match=why):
            L.chunks_until(out, START, bad)
    polls = json.loads((out / 'POLLS.json').read_text())
    (out / 'POLLS.json').write_text(json.dumps([dict(polls[0], window=[START, START + 3_000])] + polls[1:]))
    with pytest.raises(L.SimError, match='fixed_chunks'):
        L.chunks_until(out, START, START + 4 * HOUR)
    (out / 'POLLS.json').write_text(json.dumps(polls))
    many = [dict(name='live_%03d' % i, window=[START + i * L.CHUNK_S, START + (i + 1) * L.CHUNK_S], done=True)
            for i in range(13)]
    (out / 'POLLS.json').write_text(json.dumps(many))
    with pytest.raises(L.SimError, match='end_of_a_done_chunk'):
        L.chunks_until(out, START, START + 26 * HOUR)                                    # beyond 24 h
    seen = []
    real = GR.window_line
    monkeypatch.setattr(GR, 'window_line', lambda *a, **kw: seen.append((kw['start'], kw['end'])) or real(*a, **kw))
    L.pre_pair(out, NAMES[0], BASE_B58, START)
    assert seen == [(START - 7 * DAY, START)] and L.PRE_DAYS == N1R.DAYS == R.COUNT_DAYS == 7


def test_n1_after_one_day_and_without_pre_state(tmp_path, monkeypatch):
    now = START + 26 * HOUR
    specs = [(IDS[0], FEES_A, CFG_A, market_rows(now))]
    out, list_l = collection(tmp_path, now, specs, monkeypatch=monkeypatch)
    pre = L.pre_pair(out, NAMES[0], BASE_B58, START)[0]
    txs = {}
    for c in json.loads((out / 'POLLS.json').read_text()):
        txs.update(GR.window_line(NAMES[0], BASE_B58, out / 'collect' / c['name'] / NAMES[0], start=c['window'][0],
                                  end=c['window'][1])[1])
    sim = L.TL.build(NAMES[0], txs, base_mint=BASE_B58)
    union = L.replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda x: x.key)))
    obs = L.n1_observations(union, CONFIG_A, start=START, now=now)
    assert len(obs) == 26
    direct = K.continuous_position(L.truncated(union, START + 25 * HOUR), CONFIG_A, start_time=START,
                                   end_time=START + 2 * DAY)
    assert obs[24]['gap_return'] == pytest.approx(float(direct['gap_lamports'] / direct['stake_lamports']))
    alone = L.n1_observations(sim, CONFIG_A, start=START, now=START + HOUR)
    assert alone[0]['status'] == 'non valorisable'


def test_vocabulary(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    doc = run_bilan(out, list_l, now)
    from g1ind import report as G1
    bad = dict(doc, limits=doc['limits'] + [G1.FORBIDDEN_WORDS[0]])
    with pytest.raises(G1.ReportError, match='forbidden'):
        L.render(bad)
    ll = L.list_l_doc(list_l)
    chunks = L.chunks_until(out, START, now)
    pairs, configs, b3 = [], {}, {}
    for x in NAMES[:3]:
        pre = L.pre_pair(out, x, BASE_B58, START)
        sim = L.live_pair(out, x, BASE_B58, chunks)
        name = x + ' ' + G1.FORBIDDEN_WORDS[0] if x == NAMES[0] else x
        pairs.append((L.replace(pre[0], pool=name), pre[1], L.replace(sim[0], pool=name), sim[1]))
        configs[name], b3[name] = L.pool_config(ll, x), 2
    with pytest.raises(G1.ReportError, match='forbidden'):
        L.simulate(pairs, configs, b3=b3, seed_sha=SEED, start=START, now=now)


def _copy(tmp_path, name):
    dst = tmp_path / (name + '_pkg')
    shutil.copytree(L._package_dir(name), dst, ignore=shutil.ignore_patterns('__pycache__'))
    return dst


def test_manifest_check_detects_every_change(tmp_path):
    got = L.check_frozen(OK_FROZEN)
    assert set(got) == set(OK_FROZEN) and all(v['files_checked'] > 0 for v in got.values())
    assert set(L.FROZEN) == {'cpmmcost', 'cpmmgen2', 'cpmmprereg', 'g1ind', 'g23run', 'lpcost', 'n1rot', 'cpmmpilot',
                            'cpmmrecon'}
    assert L.FROZEN['cpmmpilot'] == ('MANIFEST_cpmmpilot_v0_2_8.txt',
                                     '7251d4fe27355d066d33e08f0c9e42dffa04f890646cc50de07e2a0acc442058')
    assert L.FROZEN['g23run'][1].startswith('3e3cb105') and L.check_frozen()['cpmmpilot']['files_checked'] == 18
    assert L.FROZEN['n1rot'][1].startswith('2a17791d') and L.FROZEN['lpcost'][1].startswith('ee9c144c')
    name, (manifest, sha) = 'lpcost', OK_FROZEN['lpcost']
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
    assert L.git_tree(copy) == L.FROZEN_TREES['cpmmx']
    f = sorted((copy / 'cpmmx').glob('*.py'))[0]
    f.chmod(0o755)
    assert L.git_tree(copy) != L.FROZEN_TREES['cpmmx']
    f.chmod(0o644)
    (copy / 'cpmmx' / 'extra.py').write_text('')
    with pytest.raises(L.SimError, match='frozen_tree_differs'):
        L.check_trees(locate=lambda n: copy)


def _thin(line, every):
    return L.replace(line, swaps=line.swaps[::every])


def _pre_lines(tmp_path, monkeypatch, now=START + 2 * HOUR):
    out, list_l = three(tmp_path, now, monkeypatch)
    return [L.pre_pair(out, x, BASE_B58, START)[0] for x in NAMES[:2]], out, list_l


def test_n1_universe_is_n1rot_rule_on_another_list(tmp_path, monkeypatch):
    pre, _out, _ll = _pre_lines(tmp_path, monkeypatch)
    pres = [pre[0], pre[1], _thin(pre[0], 4), _thin(pre[1], 9)]
    named = [L.replace(x, pool=p) for x, p in zip(pres, N1R.NAMED_POOLS)]
    ref = N1R.select_n1(named, CONFIG_A, START, threshold='r04_6_break_even')
    mine = L.n1_universe(named, {p: CONFIG_A for p in N1R.NAMED_POOLS}, START)
    assert mine['kept'] == ref['kept'] and mine['list_sha256'] == ref['list_sha256']
    assert 0 < len(mine['kept']) < 4
    for a, b in zip(mine['pools'], ref['pools']):
        assert (a['pool'], a['kept'], a['median_rotation_exact'], a['threshold_exact'], a['days']) == (
            b['pool'], b['kept'], b['median_rotation_exact'], b['threshold_exact'], b['days'])
    assert mine['min_pools'] == 3 and mine['min_pools_met'] is (len(mine['kept']) >= 3)
    assert mine['window'] == [START - 7 * DAY, START]
    other = L.n1_universe(pres, {x.pool: CONFIG_A for x in pres}, START)
    assert [r['kept'] for r in other['pools']] == [r['kept'] for r in ref['pools']]
    empty = L.n1_universe([L.replace(pres[0], swaps=(), lp_changes=())], {pres[0].pool: CONFIG_A}, START)
    assert empty['kept'] == [] and empty['pools'][0]['threshold_value'] == L.NM
    assert empty['pools'][0]['reason'].startswith('seuil non calculable')
    med = N1R.median_rotation(N1R.daily_rotation(pres[0], START))
    monkeypatch.setattr(N1R, 'break_even_rotation_r04_6', lambda line, cfg, t0: med)
    assert L.n1_universe(pres[:1], {pres[0].pool: CONFIG_A}, START)['kept'] == [pres[0].pool]
    monkeypatch.undo()
    late = L.replace(pres[0], swaps=pres[0].swaps + (L.replace(pres[0].swaps[-1], block_time=START),))
    with pytest.raises(N1R.RotationError, match='after_t0'):
        L.n1_universe([late], {late.pool: CONFIG_A}, START)


def test_n1_needs_three_kept_and_eligible_pools(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    real = N1R.break_even_rotation_r04_6
    monkeypatch.setattr(N1R, 'break_even_rotation_r04_6', lambda line, cfg, t0: real(line, cfg, t0) * (
        1000 if line.pool == NAMES[2] else 1))                            # pool B below n1rot's threshold
    doc = run_bilan(out, list_l, now)
    u = doc['n1']['universe']
    assert u['kept'] == NAMES[:2] and doc['n1']['pools'] == NAMES[:2] and doc['eligible'] == NAMES[:3]
    assert u['pools'][2]['threshold_value'] > u['pools'][0]['threshold_value']
    monkeypatch.setattr(N1R, 'break_even_rotation_r04_6', real)
    assert doc['n1']['status'] == 'NON ÉVALUABLE' and doc['n1']['observations'] == {}
    assert doc['n1']['pool_days'] == 0 and doc['n1']['n_insufficient'] is True     # 2 kept pools: nothing marked
    assert doc['n1']['result_12_days'] == 'NON MESURÉ' and NAMES[2] in doc['journal']   # G2-3 still runs there
    md = L.render(doc)
    assert 'Résultat 12 jours : NON MESURÉ.' in md and '| non | — | non retenu |' in md
    assert '| oui | — | NON ÉVALUABLE |' in md and 'au moins 3 exigés : NON ÉVALUABLE' in md
    assert len(doc['limits']) == 7 and md.count('\n- L') == 7 and '## Limites (7)' in md
    assert all(x in md for x in doc['limits'])
    ok = run_bilan(*all_a(tmp_path / 'b', now, monkeypatch), now)
    assert ok['n1']['pools'] == NAMES[:3] and set(ok['n1']['observations']) == set(NAMES[:3])
    assert ok['n1']['pool_days'] == 3 and ok['n1']['n_insufficient'] is True
    assert L.N_MIN == 30 and len(L.LIMITS) == 7
    assert [x[:3] for x in L.LIMITS] == ['L%d ' % k for k in range(1, 8)]
    assert 'liste 5c4fefb6' in L.LIMITS[1] and '« n insuffisant » est publié' in L.LIMITS[2]
    assert 'verdicts du 6 décembre' in L.LIMITS[4] and 'NON MESURÉ' in L.LIMITS[6]
    # a kept pool that is not eligible (b3 = 0 at `now`) gets no mark, and N1 falls below 3
    out3, list_l3 = all_a(tmp_path / 'c', now, monkeypatch)
    ll = L.list_l_doc(list_l3)
    chunks = L.chunks_until(out3, START, now)
    pairs, configs, b3 = [], {}, {}
    for x in NAMES[:3]:
        pre = L.pre_pair(out3, x, BASE_B58, START)
        sim = L.live_pair(out3, x, BASE_B58, chunks)
        pairs.append((pre[0], pre[1], sim[0], sim[1]))
        configs[x], b3[x] = L.pool_config(ll, x), 2
    pairs.append((L.replace(pairs[0][0], pool=NAMES[3]), pairs[0][1], L.replace(pairs[0][2], pool=NAMES[3]),
                   pairs[0][3]))
    configs[NAMES[3]], b3[NAMES[3]] = configs[NAMES[0]], 0
    four = L.simulate(pairs, configs, b3=b3, seed_sha=SEED, start=START, now=now)
    assert NAMES[3] in four['n1']['universe']['kept'] and four['n1']['pools'] == NAMES[:3]
    assert NAMES[3] not in four['n1']['observations'] and NAMES[3] not in four['journal']
    assert '| oui | — | non éligible |' in L.render(four)


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


def test_eligible_command(tmp_path, monkeypatch, capsys):
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    args = ['eligible', '--collect', str(out), '--list-l', str(list_l), '--out', str(tmp_path / 'ELIGIBLE.json')]
    read = []
    real = GR.window_line
    monkeypatch.setattr(GR, 'window_line', lambda *a, **kw: read.append(1) or real(*a, **kw))
    monkeypatch.setattr(L, 'FROZEN', dict(OK_FROZEN, cpmmpilot=(OK_FROZEN['cpmmpilot'][0], '0' * 64)))
    with pytest.raises(L.SimError, match='manifest_sha_differs:cpmmpilot'):              # refused before any read
        L.main(args)
    assert read == [] and not (tmp_path / 'ELIGIBLE.json').exists()
    monkeypatch.setattr(L, 'FROZEN', OK_FROZEN)
    doc = L.main(args)
    printed = json.loads(capsys.readouterr().out)
    assert printed == {'ELIGIBLE.json': hashlib.sha256((tmp_path / 'ELIGIBLE.json').read_bytes()).hexdigest()}
    saved = json.loads((tmp_path / 'ELIGIBLE.json').read_text())
    assert saved['pools'] == NAMES[:3] and saved['evaluable'] and saved['list_l_sha256'] == L.LIST_L_SHA256
    assert [r['b3'] for r in saved['rows']] == [2, 2, 2] and saved['t_start'] == START
    assert saved['rows'][2]['amm_config_sha256'] == 'cd' * 32 and doc['frozen_code']['manifests']
    assert saved['rows'][0]['pre_pages_sha256'] == L.pages_sha(out / 'collect' / 'pre' / NAMES[0])
    with pytest.raises(L.SimError, match='out_exists'):
        L.main(args)
    monkeypatch.setattr(L, 'LIST_L_SHA256', '0' * 64)
    with pytest.raises(L.SimError, match='list_l_not_anchored'):
        L.main(args[:-1] + [str(tmp_path / 'E2.json')])
    q = json.loads((out / 'QUALIFIED.json').read_text())
    (out / 'QUALIFIED.json').write_text(json.dumps(dict(q, pools=q['pools'][::-1])))
    with pytest.raises(L.SimError, match='qualified_list_corrupt'):
        L.collection(out)


def test_bilan_command(tmp_path, monkeypatch, capsys):
    now = START + 4 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    monkeypatch.setattr(L, 'FROZEN', OK_FROZEN)
    L.main(['eligible', '--collect', str(out), '--list-l', str(list_l), '--out', str(tmp_path / 'E.json')])
    sha = hashlib.sha256((tmp_path / 'E.json').read_bytes()).hexdigest()
    capsys.readouterr()
    args = ['bilan', '--collect', str(out), '--list-l', str(list_l), '--eligible', str(tmp_path / 'E.json'),
            '--eligible-sha', sha, '--now', str(now), '--out', str(tmp_path / 'B')]
    L.main(args)
    printed = json.loads(capsys.readouterr().out)
    for name in ('LIVESIM.json', 'LIVESIM.md'):
        assert printed[name] == hashlib.sha256((tmp_path / 'B' / name).read_bytes()).hexdigest()
    doc = json.loads((tmp_path / 'B' / 'LIVESIM.json').read_text())
    assert doc['frozen_code']['trees'] == {'cpmmx': {'git_tree': L.FROZEN_TREES['cpmmx']}}
    assert doc['b3_by_pool'] == {x: 2 for x in NAMES[:3]} and len(doc['pages_sha256'][NAMES[0]]['live']) == 2
    with pytest.raises(L.SimError, match='out_exists'):
        L.main(args)
    with pytest.raises(L.SimError, match='eligible_not_anchored'):
        L.main(args[:8] + ['0' * 64] + args[9:-1] + [str(tmp_path / 'B2')])
    el = json.loads((tmp_path / 'E.json').read_text())
    with pytest.raises(L.SimError, match='not_the_qualified_order'):
        L.bilan(out, L.list_l_doc(list_l), dict(el, pools=el['pools'][::-1]), now)
    with pytest.raises(L.SimError, match='another_collection'):
        L.bilan(out, L.list_l_doc(list_l), dict(el, t_start=START + 1), now)
    with pytest.raises(L.SimError, match='another_collection'):
        L.bilan(out, L.list_l_doc(list_l), dict(el, qualified_sha256='0' * 64), now)
    bad_b3 = dict(el, rows=[dict(r, b3=3) if r['pool'] == NAMES[1] else r for r in el['rows']])
    with pytest.raises(L.SimError, match='pre_pages_or_b3_differ_from_eligible:' + NAMES[1]):
        L.bilan(out, L.list_l_doc(list_l), bad_b3, now)
    page = sorted((out / 'collect' / 'pre' / NAMES[0]).glob('page_*.json.gz'))[0]
    page.write_bytes(page.read_bytes() + b'')
    shutil.copy(page, page.with_name('page_99999.json.gz'))
    with pytest.raises(L.SimError, match='pre_pages_or_b3_differ_from_eligible:' + NAMES[0]):
        L.bilan(out, L.list_l_doc(list_l), el, now)
    page.with_name('page_99999.json.gz').unlink()
    calls = []
    real_check = L.check_frozen
    monkeypatch.setattr(L, 'check_frozen', lambda: calls.append(1) or dict(real_check(), n=len(calls)))
    with pytest.raises(L.SimError, match='changed_during_the_run'):
        L.main(args[:-1] + [str(tmp_path / 'B3')])
    assert len(calls) == 2 and not (tmp_path / 'B3').exists()


def test_identity_with_the_anchored_n1rot_output(tmp_path, monkeypatch, capsys):
    pre, _out, _ll = _pre_lines(tmp_path, monkeypatch)
    named = [L.replace(x, pool=p) for x, p in zip([pre[0], pre[1], _thin(pre[0], 4), _thin(pre[1], 9)],
                                                   N1R.NAMED_POOLS)]
    ref = N1R.select_n1(named, CONFIG_A, START, threshold='r04_6_break_even')
    result = tmp_path / 'N1ROT_RESULT.json'
    result.write_text(json.dumps(ref, indent=1, sort_keys=True, ensure_ascii=False) + '\n')
    monkeypatch.setattr(L, 'N1ROT_RESULT_SHA256', hashlib.sha256(result.read_bytes()).hexdigest())
    u2 = dict(selected=[dict(pool=p, base_mint=BASE_B58) for p in reversed(N1R.NAMED_POOLS)] +
              [dict(pool='other', base_mint=BASE_B58)])
    (tmp_path / 'u2.json').write_text(json.dumps(u2))
    seen = []
    monkeypatch.setattr(GR.PILOT, 'timelines', lambda out, phase, rows: seen.append((out, phase, len(rows))) or
                        [x for x in named[::-1]])
    monkeypatch.setattr(GR.PILOT, 'amm_config_for_rules', lambda rows, slot: CONFIG_A)
    monkeypatch.setattr(L, 'FROZEN', OK_FROZEN)
    args = ['identity', '--a2r', str(tmp_path / 'A2R'), '--u2', str(tmp_path / 'u2.json'), '--result', str(result),
            '--t0-time', str(START), '--t0-slot', '5', '--out', str(tmp_path / 'ID.json')]
    doc = L.main(args)
    assert doc['identical'] is True and doc['differences'] == [] and doc['kept'] == ref['kept']
    assert seen == [(tmp_path / 'A2R', 'pre', 4)]
    broken = dict(ref, pools=[dict(ref['pools'][0], threshold_exact='1/2')] + ref['pools'][1:])
    result.write_text(json.dumps(broken))
    monkeypatch.setattr(L, 'N1ROT_RESULT_SHA256', hashlib.sha256(result.read_bytes()).hexdigest())
    got = L.identity(tmp_path / 'A2R', u2, result, START, 5)
    assert got['identical'] is False and got['differences'] == ['%s:threshold_exact' % N1R.NAMED_POOLS[0]]
    result.write_text(json.dumps(dict(ref, kept=ref['kept'][:1])))
    monkeypatch.setattr(L, 'N1ROT_RESULT_SHA256', hashlib.sha256(result.read_bytes()).hexdigest())
    assert L.identity(tmp_path / 'A2R', u2, result, START, 5)['differences'] == ['kept']
    monkeypatch.setattr(L, 'N1ROT_RESULT_SHA256', '0' * 64)
    with pytest.raises(L.SimError, match='n1rot_result_not_the_anchored_one'):
        L.identity(tmp_path / 'A2R', u2, result, START, 5)
    assert L.N1ROT_LIST_SHA256.startswith('c72bd586')


def test_each_pool_gets_its_own_config_everywhere(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    cfgs = [dict(CFG_A, raw_sha256=h * 32) for h in ('a1', 'a2', 'a3')]            # same fees, distinct accounts
    specs = [(pid, FEES_A, c, market_rows(now)) for pid, c in zip(IDS[:3], cfgs)]
    out, list_l = collection(tmp_path, now, specs, monkeypatch=monkeypatch)
    seen = {'gate': {}, 'n1': {}, 'exit': {}}
    real_gate, real_n1, real_exit = CC.pool_gate, K.continuous_position, R.exit_point
    monkeypatch.setattr(CC, 'pool_gate', lambda line, cfg: seen['gate'].setdefault(line.pool, set()).add(
        cfg['sha256']) or real_gate(line, cfg))
    monkeypatch.setattr(K, 'continuous_position', lambda line, cfg, **kw: seen['n1'].setdefault(line.pool, set()).add(
        cfg['sha256']) or real_n1(line, cfg, **kw))
    monkeypatch.setattr(R, 'exit_point', lambda line, i, cfg, *a, **kw: seen['exit'].setdefault(line.pool, set()).add(
        cfg['sha256']) or real_exit(line, i, cfg, *a, **kw))
    doc = run_bilan(out, list_l, now)
    assert doc['n1']['pools'] == NAMES[:3]
    want = {x: {c['raw_sha256']} for x, c in zip(NAMES[:3], cfgs)}
    assert seen['gate'] == want and seen['n1'] == want and seen['exit'] == want


def test_chunk_pages_stay_in_their_window_and_gate_counts_for_eligibility(tmp_path, monkeypatch):
    now = START + 4 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    real = CC.pool_gate
    monkeypatch.setattr(CC, 'pool_gate', lambda line, cfg: dict(admitted=False, reasons=['reserves_chain_broken'])
                        if line.pool == NAMES[1] else real(line, cfg))
    el = eligible_doc(out, list_l)
    assert el['pools'] == [NAMES[0], NAMES[2]] and el['rows'][1]['b3'] == 2 and el['rows'][1]['eligible'] is False
    assert el['rows'][1]['g0_reasons'] == ['reserves_chain_broken'] and el['evaluable'] is False
    monkeypatch.setattr(CC, 'pool_gate', real)
    from cpmmpilot.store import read_gz_page, write_gz_page
    src = sorted((out / 'collect' / 'live_001' / NAMES[0]).glob('page_*.json.gz'))[0]
    first = min(read_gz_page(src)['data'], key=lambda t: t['blockTime'])
    assert START + 2 * HOUR <= first['blockTime'] < START + 2 * HOUR + 600            # just after live_000 ends
    write_gz_page(out / 'collect' / 'live_000' / NAMES[0] / 'page_77777.json.gz', dict(data=[first]))
    with pytest.raises(GR.RunError, match='page_outside_the_window'):
        L.live_pair(out, NAMES[0], BASE_B58, L.chunks_until(out, START, now))


def test_vocabulary_when_non_evaluable(tmp_path, monkeypatch):
    now = START + 2 * HOUR
    out, list_l = three(tmp_path, now, monkeypatch)
    from g1ind import report as G1
    ll = L.list_l_doc(list_l)
    pre = L.pre_pair(out, NAMES[0], BASE_B58, START)
    sim = L.live_pair(out, NAMES[0], BASE_B58, L.chunks_until(out, START, now))
    name = NAMES[0] + ' ' + G1.FORBIDDEN_WORDS[1]
    pairs = [(L.replace(pre[0], pool=name), pre[1], L.replace(sim[0], pool=name), sim[1])]
    with pytest.raises(G1.ReportError, match='forbidden'):
        L.simulate(pairs, {name: L.pool_config(ll, NAMES[0])}, b3={name: 2}, seed_sha=SEED, start=START, now=now)


def test_limits_are_r02_wording_verbatim():
    assert L.LIMITS[0] == ('L1 : démonstration descriptive. Aucun essai, aucun test ni verdict, jamais un trade du '
                           'Master. Le résultat ne peut servir ni à choisir ni à modifier une stratégie.')
    assert L.LIMITS[2] == ('L3 : horizon de 6 h et de 24 h, au lieu des 12 jours. Le n est faible ; « n insuffisant » '
                           'est publié quand il le faut.')
    assert L.LIMITS[3] == ('L4 : collecte rétrospective par blocs de 2 h, donc une latence de 2 h au plus. Données '
                           'tronquées à now. L-FIN. Seules les positions fermées sont valorisées.')
    assert L.LIMITS[5].endswith('La config de chaque pool est celle lue à U-1, à un slot antérieur.')
    assert L.LIMITS[6] == ('L7 : N1 en marques intermédiaires seulement ; le résultat à 12 jours est NON MESURÉ. Coûts '
                           'du modèle gelé : pas de MEV, latence gelée. PAPER seulement.')
