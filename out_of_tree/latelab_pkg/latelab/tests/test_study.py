"""latelab: grid, returns, ranking, screen guards, firewall and output whitelist; frozen-pack smoke run."""
import hashlib
import inspect
import json
from pathlib import Path

import pytest

import bot
from latelab import study as L


def _o(value, *, migrated=False, reason='clock', cost=100_210_000):
    return dict(migrated=migrated, value=None if migrated else value, reason=reason, cost=cost)


def test_net_return_rent_lost_and_migrated():
    cost, rent = 100_210_000, L.SPL_RENT_LAMPORTS
    assert L.net_return(_o(cost + rent)) == 0.0
    assert L.net_return(_o(110_000_000)) == pytest.approx((110_000_000 - cost - rent) / (cost + rent))
    assert L.net_return(_o(110_000_000), rent=0) == pytest.approx((110_000_000 - cost) / cost)
    assert L.net_return(_o(None, migrated=True)) == -1.0


def test_halves_and_cells():
    assert L.half_of(L.EVAL_MIN) == 'discovery' and L.half_of(L.CUT_SLOT - 1) == 'discovery'
    assert L.half_of(L.CUT_SLOT) == 'screen' and L.half_of(L.EVAL_MAX - 1) == 'screen'
    assert L.half_of(L.EVAL_MIN - 1) is None and L.half_of(L.EVAL_MAX) is None
    assert L.CUT_SLOT == 468_484_945 and (L.EVAL_MIN, L.EVAL_MAX) == (467_678_545, 469_291_345)
    pools = [('discovery', 'A', [('age:120', _o(1)), ('age:300', _o(2)), ('placebo:0', _o(3))]),
             ('discovery', 'B', [('age:120', _o(4))]), ('screen', 'C', [('age:120', _o(5))])]
    assert [o['value'] for _c, o in L.cell_items(pools, 'discovery', 'L1')] == [1, 4]
    assert [o['value'] for _c, o in L.cell_items(pools, 'discovery', 'L3')] == [2]
    assert [o['value'] for _c, o in L.placebo_items(pools, 'discovery')] == [3]
    assert [o['value'] for _c, o in L.cell_items(pools, 'screen', 'L1')] == [5]
    assert L.RULE == dict(id='CLOCK60', clock_s=60) and set(L.CELLS) == {'L1', 'L3'}      # R02 04ecafed
    with pytest.raises(KeyError):
        L.cell_items(pools, 'discovery', 'L2')                                         # never evaluated


def _pools(n_good, n_bad, clusters):
    good, bad = _o(130_000_000), _o(80_000_000)
    pools = []
    for i in range(n_good + n_bad):
        o = good if i < n_good else bad
        pools.append(('discovery', f'c{i % clusters}', [('age:120', o), ('age:300', bad)]))
    return pools


def test_discovery_ranks_interpretable_cells_by_the_lower_bound():
    doc = L.discover(_pools(30, 10, 25))
    cells = doc['cells']
    assert set(cells) == {'L1', 'L3'}
    assert cells['L1']['n'] == 40 and cells['L1']['clusters'] == 25 and cells['L1']['interpretable']
    assert doc['top1'] == ['L1'] and cells['L3']['interval_95']['low'] < cells['L1']['interval_95']['low']
    assert doc['trials_added'] == 2 and cells['L1']['win_rate'] == 0.75 and 'placebo_descriptive' in doc
    small = L.discover(_pools(5, 5, 3))
    assert small['top1'] == [] and not small['cells']['L1']['interpretable']                # n < 30 / clusters < 20


def test_bootstrap_is_reproducible_and_uses_ranks():
    clusters = {f'k{i}': [float(i)] for i in range(40)}
    a, b = L.bootstrap(clusters), L.bootstrap(clusters)
    assert a == b and a['clusters'] == 40 and a['low'] < 19.5 < a['high'] and a['seed'] == 20261120


def test_screen_requires_the_anchored_top1(tmp_path):
    disc = tmp_path / 'd.json'
    disc.write_text(json.dumps(dict(top1=['L3'])))
    sha = hashlib.sha256(disc.read_bytes()).hexdigest()
    base = ['screen', '--pools', str(tmp_path), '--manifest-sha256', '0' * 64, '--out', str(tmp_path / 'o')]
    with pytest.raises(L.LateLabError, match='anchored_discovery_required'):
        L.main(base + ['--cell', 'L3'])
    with pytest.raises(L.LateLabError, match='discovery_is_not_the_anchored_one'):
        L.main(base + ['--cell', 'L3', '--discovery', str(disc), '--discovery-sha256', '1' * 64])
    with pytest.raises(L.LateLabError, match='screen_cell_must_be_the_anchored_top1'):
        L.main(base + ['--cell', 'L1', '--discovery', str(disc), '--discovery-sha256', sha])
    screen_pools = [('screen', p[1], p[2]) for p in _pools(30, 10, 25)]
    good = L.screen(screen_pools, 'L1')
    assert good['cells']['L1']['passes'] is True and good['trials_added'] == 1 and list(good['cells']) == ['L1']
    assert L.screen(screen_pools, 'L3')['cells']['L3']['passes'] is False


def test_firewall_no_hw1_variable_or_trigger_in_the_code():
    code = inspect.getsource(L).split('"""', 2)[2]
    for name in ('real_quote', 'real_base', 'progress', 'signer', 'signed', 'first_sale', 'flow_window', "'sell'",
                 'fee_rate', 'tier', 'take_profit', 'stop_loss',
                 'peak', 'dip', 'purge', 'maximum', 'age:600', 'state_after', 'state_before'):
        assert name not in code, name
    assert L.AGES == (120, 300) and max(L.AGES) < 600


def test_frozen_pack_smoke_run_and_output_whitelist(tmp_path, monkeypatch):
    pools = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    sha = hashlib.sha256((pools / 'MANIFEST.json').read_bytes()).hexdigest()
    monkeypatch.setattr(L, 'EVAL_MIN', 1)
    monkeypatch.setattr(L, 'CUT_SLOT', 2)                                   # every frozen pool in the screen half
    monkeypatch.setattr(L, 'EVAL_MAX', 10 ** 12)
    dossier = tmp_path / 'dossier_a.md'
    dossier.write_text('## 10. C-D FIGÉ (test)\n', encoding='utf-8')
    dsha = hashlib.sha256(dossier.read_bytes()).hexdigest()
    anchored = ['--dossier-a', str(dossier), '--dossier-a-sha256', dsha]
    with pytest.raises(L.LateLabError, match='anchored_dossier_a_required'):
        L.main(['discover', '--pools', str(pools), '--manifest-sha256', sha, '--out', str(tmp_path / 'x')])
    with pytest.raises(L.LateLabError, match='dossier_a_is_not_the_anchored_one'):
        L.main(['discover', '--pools', str(pools), '--manifest-sha256', sha, '--dossier-a', str(dossier),
                '--dossier-a-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    other = tmp_path / 'other.md'
    other.write_text('no freeze here', encoding='utf-8')
    with pytest.raises(L.LateLabError, match='dossier_a_does_not_freeze_c_d'):
        L.main(['discover', '--pools', str(pools), '--manifest-sha256', sha, '--dossier-a', str(other),
                '--dossier-a-sha256', hashlib.sha256(other.read_bytes()).hexdigest(), '--out', str(tmp_path / 'x')])
    assert not (tmp_path / 'x').exists()
    with pytest.raises(L.LateLabError, match='manifest_is_not_the_anchored_one'):
        L.main(['discover', '--pools', str(pools), '--manifest-sha256', '0' * 64, *anchored, '--out', str(tmp_path / 'x')])
    assert L.main(['discover', '--pools', str(pools), '--manifest-sha256', sha, *anchored, '--out', str(tmp_path / 'o')]) == 0
    text = (tmp_path / 'o' / 'LATELAB.json').read_text()
    doc = json.loads(text)
    assert doc['half'] == 'discovery' and all(c['n'] == 0 for c in doc['cells'].values())   # short pools: no late point
    for name in json.loads((pools / 'MANIFEST.json').read_text())['pools']:
        assert name['pool'] not in text
    assert doc['input']['dossier_a_sha256'] == dsha
    with pytest.raises(L.LateLabError, match='output_exists'):
        L.main(['discover', '--pools', str(pools), '--manifest-sha256', sha, *anchored, '--out', str(tmp_path / 'o')])


def test_pool_points_replays_the_real_exit_rule_without_reading_any_tier(monkeypatch):
    """A real event of the frozen pack labelled age:120 (and one labelled progress, which must be ignored)."""
    from statelab import points as P
    from v3lab import plan
    from w1aux.lazy import clear_cache, load_fixtures_lazy
    pools = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    entries = {e['pool']: a for e, a in load_fixtures_lazy(pools)[2]}
    archive = next(a for name, a in entries.items() if name.startswith('C7F9'))
    monkeypatch.setattr(L, 'EVAL_MIN', 1)
    monkeypatch.setattr(L, 'CUT_SLOT', 10 ** 12)
    monkeypatch.setattr(L, 'EVAL_MAX', 10 ** 12 + 1)
    original = P.decision_points

    def fake(events, created, pool):
        whole = [k for k in range(len(events)) if P.whole(events, k)]
        return [(whole[3], [['age', 120]]), (whole[5], [['progress', 650_000]]), (whole[7], [['age', 120], ['age', 300]])]
    monkeypatch.setattr(L, 'decision_points', fake)
    try:
        half, cluster, points = L.pool_points(archive, L.hrr.ReplayParams(latency_slots=plan.REPLAY['latency_slots']))
    finally:
        clear_cache()
    assert half == 'discovery' and cluster
    assert [p[0] for p in points] == ['age:120', 'age:120', 'age:300']               # the progress label is dropped
    assert all(len(p) == 2 for p in points)                                          # no tier is read or kept
    for _label, outcome in points:
        assert outcome['cost'] == 100_000_000 + 2 * 105_000 and outcome['reason'] == 'clock' \
            or outcome['migrated']
    assert points[1][1] == points[2][1]                                              # one event, one replay
    assert original is P.decision_points


def test_ranking_uses_the_lower_bound_not_the_mean_and_the_floors():
    pools = []
    for i in range(30):                          # L1: high mean, wide interval ; L3: lower mean, tight interval
        v1 = 200_000_000 if i % 2 else 60_000_000
        pools.append(('discovery', f'c{i % 20}', [('age:120', _o(v1)), ('age:300', _o(120_000_000))]))
    doc = L.discover(pools)
    c = doc['cells']
    assert c['L1']['mean_net_return'] > c['L3']['mean_net_return']
    assert c['L1']['interval_95']['low'] < c['L3']['interval_95']['low'] and doc['top1'] == ['L3']
    few_clusters = L.discover([('discovery', f'c{i % 10}', [('age:120', _o(130_000_000))]) for i in range(40)])
    assert few_clusters['cells']['L1']['n'] == 40 and few_clusters['cells']['L1']['interpretable'] is False
    assert L.screen([('screen', f'c{i % 10}', [('age:120', _o(130_000_000))]) for i in range(40)], 'L1')['cells']['L1']['passes'] is False
    small = L.screen([('screen', f'c{i}', [('age:120', _o(130_000_000))]) for i in range(29)], 'L1')
    assert small['cells']['L1']['mean_net_return'] > 0 and small['cells']['L1']['passes'] is False      # n < 30


def test_no_cell_can_filter_on_the_tier_or_slice_l1_l3():
    """R02 04ecafed conditions 1 and 4: L2/L4 absent; a cell is defined by its age only; no breakdown exists."""
    assert L.CELLS == {'L1': {'age': 120}, 'L3': {'age': 300}}
    pools = [('discovery', f'c{i}', [('age:120', _o(100_000_000 + i))]) for i in range(5)]
    items = L.cell_items(pools, 'discovery', 'L1')
    assert len(items) == 5                                                            # every pool, no selection
    keys = set(L.summary(items))
    assert not keys & {'tiers', 'by_tier', 'by_age', 'slices', 'thirds'}
    params = inspect.signature(L.cell_items).parameters
    assert list(params) == ['pools', 'half', 'cell']                                   # nothing to filter with


def test_a_migrated_position_is_written_under_the_key_migrated(tmp_path):
    """R02 0d0ffd06: run_rule gives reason=None for a migrated position; the summary must still be writable."""
    items = [('c1', _o(None, migrated=True, reason=None)), ('c2', _o(101_000_000)), ('c3', _o(None, migrated=True, reason=None))]
    doc = L.summary(items)
    assert doc['exit_reasons'] == {'clock': 1, 'migrated': 2}
    sha = L._write(tmp_path / 'out', dict(cells=dict(L1=doc)))
    written = json.loads((tmp_path / 'out' / 'LATELAB.json').read_text())
    assert written['cells']['L1']['exit_reasons'] == {'clock': 1, 'migrated': 2}
    assert sha == hashlib.sha256((tmp_path / 'out' / 'LATELAB.json').read_bytes()).hexdigest()
