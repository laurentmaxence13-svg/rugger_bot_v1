"""E1 0.1 tests: synthetic curves built with the frozen LaunchLab curve functions only (no W1 data)."""
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pytest

from bot.market import launchlab_curve as curve
from e1plafond import e1 as E

VB, VQ, TOTAL = 1_073_025_605_596_382, 30_000_852_951, 793_100_000_000_000
RATE = 2500


@dataclass
class Ev:
    block_time: int
    before: object
    after: object

    def state_before(self):
        return self.before

    def state_after(self):
        return self.after


def initial():
    return curve.CurveState(VB, VQ, 0, 0, TOTAL)


def path_of(trades, t0=1000):
    """trades: list of (dt from t0, side, amount). Returns events with frozen fills."""
    state, events = initial(), []
    for dt, side, amount in trades:
        fill = (curve.buy_exact_in(state, amount, RATE) if side == 'buy'
                else curve.sell_exact_in(state, amount, RATE))
        events.append(Ev(t0 + dt, state, fill.after))
        state = fill.after
    return events


def test_seed_is_the_first_8_hex_of_the_declaration_sha():
    raw = b'declaration'
    assert E.seed_of(raw) == int(hashlib.sha256(raw).hexdigest()[:8], 16)


def test_draws_are_spaced_bounded_and_deterministic():
    a = E.draw_entries(7, 'P', 0, 500 * 3600)
    assert a == E.draw_entries(7, 'P', 0, 500 * 3600) and a != E.draw_entries(7, 'Q', 0, 500 * 3600)
    assert len(a) == E.MAX_BLOCKS and a == sorted(a)
    assert all(b - x >= E.BLOCK_S - E.DRAW_S for x, b in zip(a, a[1:]))
    assert all(0 <= x <= 500 * 3600 for x in a)
    short = E.draw_entries(7, 'P', 0, 5000)
    assert len(short) == 1 and short[0] < E.DRAW_S
    assert E.draw_entries(7, 'P', 10, 5) == []
    edge = E.draw_entries(1, 'P', 0, 100)              # block 0 instant may fall after end: dropped
    assert all(x <= 100 for x in edge)


def test_price_is_the_last_event_at_or_before_and_the_initial_state_before_any():
    ev = path_of([(0, 'buy', 10**9), (10, 'buy', 10**9), (10, 'buy', 10**9), (50, 'sell', 10**12)])
    p = E.Path_(ev)
    assert p.price(999) == p.spot(initial())
    assert p.price(1000) == p.spot(ev[0].after)
    assert p.price(1010) == p.spot(ev[2].after)            # same second: the last one in timeline order
    assert p.price(1049) == p.spot(ev[2].after) and p.price(10**9) == p.spot(ev[3].after)
    assert p.count_in(1000, 1010) == 2 and p.count_in(999, 1000) == 1


def test_round_trip_cost_at_zero_move_holds_fees_tx_and_rent_and_B_is_worse_than_A():
    state = path_of([(0, 'buy', 5 * 10**9)])[-1].after
    with_rent, no_rent, conv = E.round_trip_cost(state, RATE, 210_000, curve)
    assert conv == 'B'
    assert with_rent - no_rent == pytest.approx(E.RENT_LAMPORTS / E.STAKE)
    assert no_rent > 2 * RATE / 1e6 + 210_000 / E.STAKE - 1e-9
    buy = curve.buy_exact_in(state, E.STAKE, RATE)
    a_only = (E.STAKE - curve.sell_exact_in(buy.after, buy.amount_out, RATE).amount_out + 210_000) / E.STAKE
    assert no_rent >= a_only


def test_round_trip_falls_back_to_A_when_the_curve_inventory_is_too_small_and_refuses_a_crossing_buy():
    state = initial()                                     # real_base = 0: selling without our buy is impossible
    _w, _n, conv = E.round_trip_cost(state, RATE, 0, curve)
    assert conv == 'A'
    nearly = curve.CurveState(VB, VQ, TOTAL - 10, 85 * 10**9, TOTAL)
    assert E.round_trip_cost(nearly, RATE, 0, curve) is None


def rows_for(events, migration=None, coverage=None, start=None, known=True):
    return E.pool_rows('P', events, dict(creation_known=known, start=events[0].block_time if start is None else start),
                       migration, coverage, 11, RATE, 210_000, curve)


def test_censoring_reasons_and_a_dead_pool_is_not_censored():
    ev = path_of([(i * 60, 'buy' if i % 2 else 'sell', 10**8 if i % 2 else 10**12) for i in range(1, 180)])
    end = ev[-1].block_time
    rows = rows_for(ev)                                   # end = last event: horizons beyond it are censored
    assert len(rows) >= 1
    for r in rows:
        t = r['t']
        for h, mv in r['moves'].items():
            assert (mv == dict(censored='dernier_evenement')) == (t + h > end)
    dead = rows_for(ev, coverage=end + 100 * 3600)        # collection end far after the last trade
    after = [r for r in dead if r['t'] > end]
    assert after
    for r in after:                                       # no trade after t: flat, m = 0, not censored
        assert all(mv['flat'] and mv['m'] == 0 and mv['exc'] == 0 for mv in r['moves'].values())
    migr = rows_for(ev, coverage=end + 100 * 3600, migration=end - 1800)
    assert all(mv.get('censored') in (None, 'migration') for r in migr for mv in r['moves'].values())
    assert any(mv.get('censored') == 'migration' for r in migr for mv in r['moves'].values())
    assert all(r['t'] <= end - 1800 for r in migr)


def test_move_excursion_activity_and_segments():
    trades = [(i * 5, 'buy', 5 * 10**8) for i in range(100)] + [(600, 'sell', 10**13)]
    ev = path_of(trades)
    p = E.Path_(ev)
    rows = rows_for(ev, coverage=1000 + 5000)
    r = rows[0]
    t = None
    for cand in E.draw_entries(11, 'P', 1000, 1000 + 5000):
        t = cand
        break
    for h in (30, 120, 300):
        mv = r['moves'][h]
        assert mv['m'] == pytest.approx(p.price(t + h) / p.price(t) - 1)
        assert mv['exc'] >= abs(mv['m'])
    assert r['seg']['tous'] == 'tous' and r['seg']['palier'] == '2500_ppm' and r['seg']['migration'] == 'non_migre'
    assert r['seg']['age'] == '<1h'
    assert rows_for(ev, coverage=6000, known=False)[0]['seg']['age'] == 'inconnu'


def test_classes():
    assert E.classify(0, E.AGE) == '<1h' and E.classify(3600, E.AGE) == '1-6h' and E.classify(10**9, E.AGE) == '>7j'
    assert E.classify(0.99, E.RESERVE_SOL) == '<1' and E.classify(50, E.RESERVE_SOL) == '>=50'
    assert [E.activity_class(n) for n in (0, 1, 2, 3, 9, 10)] == ['0', '1-2', '1-2', '3-9', '3-9', '>=10']


def synthetic_pools(n_pools, move, cost, per=3):
    return [[(move * (1 if (i + j) % 2 else -1), abs(move), cost, cost - 0.02) for j in range(per)]
            for i in range(n_pools)]


def test_open_needs_the_simultaneous_bound_and_the_share():
    rng = np.random.default_rng(1)
    big = E.cell_stats(synthetic_pools(40, 0.20, 0.05), rng, 3.5)
    assert big['real_cost']['plafond'] == 'OUVERT' and big['real_cost']['share_above'] == 1
    small = E.cell_stats(synthetic_pools(40, 0.01, 0.05), rng, 3.5)
    assert small['real_cost']['plafond'] == 'FERMÉ'
    few = E.cell_stats(synthetic_pools(10, 0.20, 0.05), rng, 3.5)
    assert few['real_cost']['status'] == 'n_insuffisant'
    # mean above the cost but share below 25 %: closed
    rare = [[(1.0, 1.0, 0.05, 0.03)] + [(0.0, 0.0, 0.05, 0.03)] * 9 for _ in range(40)]
    r = E.cell_stats(rare, rng, 3.5)['real_cost']
    assert r['mean_minus_cost'] > 0 and r['ci_simultaneous'][0] > 0 and r['share_above'] < 0.25 and r['plafond'] == 'FERMÉ'


def test_cluster_se_and_kish():
    groups = [[1.0, 1.0], [0.0], [2.0, 2.0, 2.0]]
    assert E.cluster_mean(groups) == pytest.approx(8 / 6)
    assert E.kish(groups) == pytest.approx(36 / 14)
    assert E.cluster_se([[1.0], [1.0]]) == 0


def test_aggregate_counts_cells_bonferroni_and_writes_no_address():
    ev = path_of([(i * 30, 'buy' if i % 3 else 'sell', 10**8 if i % 3 else 10**12) for i in range(1, 400)])
    results = []
    for k in range(35):
        rows = E.pool_rows('POOLADDRESS%02d' % k, ev, dict(creation_known=True, start=1000), None, 1000 + 30 * 3600,
                           5, RATE, 210_000, curve)
        results.append((k, rows))
    agg = E.aggregate(results, 5)
    assert agg['K_cells_real_cost'] > 0 and agg['expected_false_open_uncorrected'] == 0.025 * agg['K_cells_real_cost']
    assert agg['z_bonferroni'] > 1.96
    text = json.dumps(agg, ensure_ascii=False)
    assert 'POOLADDRESS' not in text
    assert {c['dimension'] for c in agg['cells']} == set(E.DIMENSIONS)


def test_inputs_refuse_the_holdout_and_any_other_manifest(tmp_path, monkeypatch):
    with pytest.raises(E.E1Error, match='holdout'):
        E.check_inputs(tmp_path / '9f19ccac_pack', b'{}')
    with pytest.raises(E.E1Error, match='manifest_not_the_anchored'):
        E.check_inputs(tmp_path, b'{}')
    raw = b'{"pools": []}'
    monkeypatch.setattr(E, 'W1_MANIFEST', hashlib.sha256(raw).hexdigest())
    assert E.check_inputs(tmp_path, raw) == E.W1_MANIFEST


def test_anchored_constants():
    assert E.W1_MANIFEST.startswith('ebe1959d') and E.RENT_LAMPORTS == 2_039_280 and E.STAKE == 100_000_000
    assert E.HORIZONS == (30, 120, 300, 900, 1800, 3600) and E.GRID == (0.005, 0.0095, 0.015)
    assert (E.BLOCK_S, E.DRAW_S, E.MAX_BLOCKS, E.MIN_POOLS, E.OPEN_SHARE) == (7200, 3600, 20, 30, 0.25)


def test_end_to_end_on_the_committed_repo_fixtures_through_the_frozen_chain(tmp_path, monkeypatch):
    """Smoke test of the frozen loading chain (repo test fixtures, never W1): structure only."""
    from pathlib import Path
    import bot
    pools = Path(bot.__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    raw = (pools / 'MANIFEST.json').read_bytes()
    monkeypatch.setattr(E, 'W1_MANIFEST', hashlib.sha256(raw).hexdigest())
    decl = tmp_path / 'D.md'
    decl.write_bytes(b'test declaration')
    cov = tmp_path / 'cov.json'
    cov.write_text(json.dumps({e['pool']: 1_900_000_000 for e in json.loads(raw)['pools']}))
    E.main(['--pools', str(pools), '--declaration', str(decl), '--out', str(tmp_path / 'out'), '--workers', '2',
            '--coverage-end', str(cov)])
    res = json.loads((tmp_path / 'out' / 'E1_RESULT.json').read_text())
    assert res['coverage_end_source'] == 'inventaire_R03' and res['entries'] > 0
    assert res['pool_status'].get('retenu', 0) >= 1 and sum(res['sale_convention'].values()) == res['entries']
    assert res['schema'] == E.SCHEMA and res['stamp'] == E.STAMP and res['seed'] == E.seed_of(b'test declaration')
    assert res['pools_in_manifest'] == len(json.loads(raw)['pools'])
    assert sum(res['pool_status'].values()) == res['pools_in_manifest']
    text = (tmp_path / 'out' / 'E1_RESULT.json').read_text()
    for entry in json.loads(raw)['pools']:
        assert entry['pool'] not in text
    with pytest.raises(FileExistsError):
        E.main(['--pools', str(pools), '--declaration', str(decl), '--out', str(tmp_path / 'out')])


def test_transactions_enter_the_cost_exactly():
    state = path_of([(0, 'buy', 5 * 10**9)])[-1].after
    with_tx = E.round_trip_cost(state, RATE, 210_000, curve)
    without = E.round_trip_cost(state, RATE, 0, curve)
    assert with_tx[1] - without[1] == pytest.approx(210_000 / E.STAKE, abs=1e-15)


def test_open_uses_the_simultaneous_bound_not_the_95_interval():
    rng = np.random.default_rng(2)
    pools = [[(0.10 + 0.01 * ((i * 7 + j) % 5), 0.2, 0.05, 0.03) for j in range(3)] for i in range(40)]
    r = E.cell_stats(pools, rng, 1e4)['real_cost']
    assert r['ci95'][0] > 0 and r['ci_simultaneous'][0] < 0 and r['share_above'] == 1 and r['plafond'] == 'FERMÉ'


def test_cells_under_30_pools_carry_no_figure():
    ev = path_of([(i * 30, 'buy' if i % 3 else 'sell', 10**8 if i % 3 else 10**12) for i in range(1, 400)])
    results = [(k, E.pool_rows('P%d' % k, ev, dict(creation_known=True, start=1000), None, 1000 + 30 * 3600,
                               5, RATE, 210_000, curve)) for k in range(E.MIN_POOLS - 1)]
    agg = E.aggregate(results, 5)
    assert agg['cells'] and all(c['status'] == 'n_insuffisant' and 'p50' not in c for c in agg['cells'])
    assert agg['K_cells_real_cost'] == 0 and agg['open_cells'] == 0


def test_excursion_sees_the_peak_inside_the_horizon():
    ev = path_of([(0, 'buy', 10**8), (100, 'buy', 20 * 10**9)])
    tokens = ev[-1].after.real_base - ev[0].after.real_base
    state = ev[-1].after
    back = curve.sell_exact_in(state, tokens, RATE)
    ev.append(Ev(1200, state, back.after))
    end = 1000 + 10 * 3600
    name = next(n for n in ('P%d' % i for i in range(10_000)) if E.draw_entries(11, n, 1000, end)[0] < 1100)
    r = E.pool_rows(name, ev, dict(creation_known=True, start=1000), None, end, 11, RATE, 210_000, curve)[0]
    assert r['t'] < 1100
    mv = r['moves'][3600]
    assert mv['exc'] > abs(mv['m']) + 0.1
