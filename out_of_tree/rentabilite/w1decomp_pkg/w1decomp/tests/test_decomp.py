"""w1decomp: descriptive decomposition on hand-made documents and timelines with known answers."""
import gzip
import hashlib
import inspect
import json
from types import SimpleNamespace

import pytest

from w1decomp import decomp as D

SPENT, TX = 100_000_000, 210_000
START, END = 1_000, 2_000


class Ev:
    def __init__(self, slot, quote, base=1_000_000):
        self.slot, self._state = slot, SimpleNamespace(quote_reserve=quote, base_reserve=base)

    def state_after(self):
        return self._state


def _row(pool, arm, *, gross, fees=(1_000_000, 1_000_000), slippage=300_000, rate=10_000, buy=(2, 1_010),
         sell=(5, 1_050), trial='L1', outcome='closed', verified=True):
    pnl = gross - slippage - sum(fees) - TX
    return dict(trial=trial, arm=arm, pool=pool, outcome=outcome, verified=verified, pnl_lamports=pnl,
                net_return=pnl / (SPENT + TX),
                buy=dict(index=buy[0], slot=buy[1], block_time=10_000, spent_lamports=SPENT, fee_rate_ppm=rate),
                sell=dict(index=sell[0], slot=sell[1], block_time=10_030, trigger=dict(reason='stop_loss')),
                decomposition=dict(market_move=gross, slippage=slippage, launchlab_buy_fee=fees[0],
                                   launchlab_sell_fee=fees[1], tx_costs=TX, failed_attempt_costs=0, pnl=pnl))


def _bundle(names, created=1_000):
    slots = dict(out=START - 1, late=END)
    return dict(pools=[dict(pool=n, creation_slot=slots.get(n, created), creator='C' + n,
                            arms=dict(master=dict(exit_conditions=dict(tp_pct=10, sl_pct=5)))) for n in names])


def _timeline(quotes, slots, *, migrated=False, hour=3):
    return dict(events=[Ev(s, q) for s, q in zip(slots, quotes)], migrated=migrated,
                creation_block_time=1_700_000_000 - (1_700_000_000 % 86_400) + hour * 3_600)


LEDGER = dict(verdict='PASS', mismatches=[], w1_report=None, entries=[
    _row('a', 'master', gross=-4_000_000), _row('b', 'master', gross=2_000_000, buy=(0, 1_001), sell=(3, 1_020)),
    _row('a', 'placebo_random', gross=-1_000_000),
    _row('out', 'master', gross=9 * SPENT),                                   # created outside the range
    _row('late', 'master', gross=9 * SPENT),                                  # created at evaluation_max: outside
    _row('a', 'reference', gross=9 * SPENT), _row('a', 'master', gross=9 * SPENT, trial='L1_event_horizon'),
    _row('b', 'master', gross=9 * SPENT, outcome='open_at_end')])
TIMELINES = dict(
    # a: entry at index 2 (slot 1 010, spot 100); then 102 at 1 011, 99 at 1 030, 95 at 1 050 (sale), 200 after
    a=_timeline([90, 95, 100, 102, 99, 95, 200], [1_000, 1_005, 1_010, 1_011, 1_030, 1_050, 1_060], hour=3),
    b=_timeline([50, 49, 60, 70, 10], [1_001, 1_002, 1_003, 1_020, 1_030], migrated=True, hour=13))


def _population():
    return D.positions(LEDGER, _bundle(['a', 'b', 'out', 'late']), evaluation_min=START, evaluation_max=END)


def test_population_is_the_w1loss_rule():
    pop = _population()
    assert sorted(p['pool'] for p in pop['master']) == ['a', 'b'] and [p['pool'] for p in pop['placebo_random']] == ['a']
    assert set(pop) == {'master', 'placebo_random'}
    with pytest.raises(D.DecompError, match='ledger_is_not_a_pass'):
        D.positions(dict(LEDGER, verdict='FAIL'), _bundle(['a', 'b', 'out']), evaluation_min=START, evaluation_max=END)
    bad = dict(LEDGER, entries=[dict(_row('a', 'master', gross=0), verified=False)])
    with pytest.raises(D.DecompError, match='not_verified'):
        D.positions(bad, _bundle(['a']), evaluation_min=START, evaluation_max=END)
    no_index = _row('a', 'master', gross=0)
    del no_index['sell']['index']
    with pytest.raises(D.DecompError, match='without_sell_index'):
        D.positions(dict(LEDGER, entries=[no_index]), _bundle(['a']), evaluation_min=START, evaluation_max=END)


def test_d1_costs_shares_and_both_cost_regimes():
    from statelab.exits import SPL_RENT_LAMPORTS
    assert D.RENT_LAMPORTS == SPL_RENT_LAMPORTS
    c = D.costs(_population()['master'])
    share = c['mean_share_of_stake']
    assert share['gross'] == pytest.approx(-0.01) and share['curve_fees'] == pytest.approx(0.02)
    assert share['impact'] == pytest.approx(0.003) and share['tx'] == pytest.approx(0.0021)
    assert share['rent'] == pytest.approx(0.0203928) and share['failed'] == 0
    assert c['total_cost_share_of_stake'] == pytest.approx(0.003 + 0.02 + 0.0021 + 0.0203928)
    assert sum(c['share_of_total_cost'].values()) == pytest.approx(1)
    pnl = [-4_000_000 - 2_510_000, 2_000_000 - 2_510_000]
    assert c['mean_net_return_frozen_SL'] == pytest.approx(sum(pnl) / 2 / (SPENT + TX))
    assert c['mean_net_return_rent_lost_LP_additive'] == pytest.approx(
        sum(v - D.RENT_LAMPORTS for v in pnl) / 2 / (SPENT + TX))
    assert c['interval_95_mean_net_return_SL']['interpretable'] is False and D.costs([]) == dict(n=0)


def test_d2_profile_and_turning_points():
    a = [p for p in _population()['master'] if p['pool'] == 'a'][0]
    x = D.path(a, TIMELINES['a']['events'])
    assert x['profile'][0] == 0 and x['profile'][1] == pytest.approx(0.02) and x['profile'][16] == pytest.approx(0.02)
    assert x['profile'][32] == pytest.approx(-0.01)               # slot 1 042: last event 1 030, spot 99
    assert 64 not in x['profile']                                 # 1 074 > sale slot 1 050: no longer held
    assert x['peak_offset'] == 1 and x['first_adverse_offset'] == 20
    b = [p for p in _population()['master'] if p['pool'] == 'b'][0]
    y = D.path(b, TIMELINES['b']['events'])                       # entry spot 50; 49 at 1 002 is the first adverse
    assert y['first_adverse_offset'] == 1 and y['peak_offset'] == 19 and y['profile'][16] == pytest.approx(0.2) and 32 not in y['profile']
    agg = D.price_path(_population()['master'], TIMELINES)
    assert agg['relative_spot_by_slot_offset']['1'] == dict(n=2, mean=pytest.approx(0.0), median=pytest.approx(-0.02),
                                                             share_below_entry=0.5)
    assert agg['relative_spot_by_slot_offset']['32']['n'] == 1 and agg['share_without_adverse_crossing'] == 0
    with pytest.raises(D.DecompError, match='indices_do_not_match'):
        D.path(dict(a, buy_index=5), TIMELINES['a']['events'])
    with pytest.raises(D.DecompError, match='indices_do_not_match'):
        D.path(dict(a, sell_index=99), TIMELINES['a']['events'])


def test_d3_pool_types_fixed_classes():
    t = D.pool_types(_population()['master'], TIMELINES)
    assert set(t['D3a_events_before_entry']) == {'[0,10)'} and t['D3a_events_before_entry']['[0,10)']['n'] == 2
    assert set(t['D3b_creation_hour_utc']) == {'00-04h', '12-16h'}
    assert t['D3c_reached_migration']['migration']['n'] == 1 and t['D3c_reached_migration']['no_migration']['n'] == 1
    assert t['D3c_reached_migration']['migration']['interpretable'] is False
    assert [D.trade_class(v) for v in (0, 9, 10, 29, 30, 99, 100, 5_000)] == [
        '[0,10)', '[0,10)', '[10,30)', '[10,30)', '[30,100)', '[30,100)', '>=100', '>=100']


def _files(tmp_path):
    bundle = gzip.compress(json.dumps(_bundle(['a', 'b', 'out', 'late'])).encode(), mtime=0)
    (tmp_path / 'L1.json.gz').write_bytes(bundle)
    raw = json.dumps(dict(LEDGER, bundles_sha256=dict(L1=hashlib.sha256(bundle).hexdigest()))).encode()
    (tmp_path / 'ledger.json').write_bytes(raw)
    return tmp_path / 'ledger.json', hashlib.sha256(raw).hexdigest(), tmp_path / 'L1.json.gz'


def test_run_checks_every_anchor_and_writes_only_counts(tmp_path, monkeypatch):
    ledger, sha, bundle = _files(tmp_path)
    seen = {}

    def fake(pools_dir, manifest_sha256, wanted):
        seen.update(wanted=set(wanted), manifest=manifest_sha256)
        return TIMELINES
    monkeypatch.setattr(D, 'load_timelines', fake)
    with pytest.raises(D.DecompError, match='ledger_is_not_the_anchored_one'):
        D.run(ledger, '0' * 64, bundle, 'p', 'm', tmp_path / 'x', evaluation_min=START, evaluation_max=END)
    (tmp_path / 'other.gz').write_bytes(b'x')
    with pytest.raises(D.DecompError, match='bundle_is_not_the_one'):
        D.run(ledger, sha, tmp_path / 'other.gz', 'p', 'm', tmp_path / 'x', evaluation_min=START, evaluation_max=END)
    doc = D.run(ledger, sha, bundle, 'pools', 'm' * 64, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    assert seen == dict(wanted={'a', 'b'}, manifest='m' * 64)
    assert doc['E'] == 5 and doc['flags']['rule_or_parameter_selected'] is False
    text = (tmp_path / 'out' / 'DECOMPOSITION_W1.json').read_text() + (tmp_path / 'out' / 'DECOMPOSITION_W1.md').read_text()
    for name in ('"a"', '"b"', 'Ca', 'Cb'):
        assert name not in text
    assert 'EXPLORATOIRE' in text and not any(w in text.lower() for w in ('rentable', 'profitable', 'gagnant'))
    with pytest.raises(D.DecompError, match='output_exists'):
        D.run(ledger, sha, bundle, 'pools', 'm' * 64, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    monkeypatch.setattr(D, 'load_timelines', lambda *_a: dict(a=TIMELINES['a']))
    with pytest.raises(D.DecompError, match='pool_without_timeline'):
        D.run(ledger, sha, bundle, 'pools', 'm' * 64, tmp_path / 'o2', evaluation_min=START, evaluation_max=END)


def test_firewall_no_hw1_state_variable_and_frozen_imports():
    source = inspect.getsource(D)
    for name in ('progress', 'quote_raised', 'real_quote', 'signed_creator', 'drawdown', 'top5', 'reserve_ratio'):
        assert name not in source
    assert D.OFFSETS[0] == 0 and D.BREAKDOWNS == ('D1', 'D2', 'D3a', 'D3b', 'D3c')


def test_load_timelines_on_the_repository_fixture_pack():
    from pathlib import Path
    import bot
    pack = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    sha = hashlib.sha256((pack / 'MANIFEST.json').read_bytes()).hexdigest()
    names = sorted(e['pool'] for e in json.loads((pack / 'MANIFEST.json').read_bytes())['pools'])
    got, failures = {}, []
    for name in names:
        try:
            got.update(D.load_timelines(pack, sha, {name}))
        except D.DecompError as exc:
            failures.append(str(exc))
    assert got, failures
    for t in got.values():
        assert t['events'] and type(t['migrated']) is bool and type(t['creation_block_time']) is int
        assert all(hasattr(e, 'slot') and e.state_after().base_reserve > 0 for e in t['events'])
    with pytest.raises(D.DecompError, match='manifest_is_not_the_anchored_one'):
        D.load_timelines(pack, '0' * 64, {names[0]})
    with pytest.raises(D.DecompError, match='absent_from_the_export'):
        D.load_timelines(pack, sha, {'no_such_pool'})


def test_turning_points_ties_and_strictness_and_class_edges():
    events = [Ev(10, 100), Ev(11, 105), Ev(12, 100), Ev(13, 105), Ev(14, 99), Ev(15, 50)]
    p = dict(pool='z', buy_index=0, sell_index=4, buy_slot=10, sell_slot=14)
    x = D.path(p, events)
    assert x['peak_offset'] == 1                       # the earliest of two equal maxima
    assert x['first_adverse_offset'] == 4               # 100 at slot 12 equals the reference: not adverse
    assert 5 not in [k for k in x['profile']] and x['profile'][4] == pytest.approx(-0.01)
    pos = [dict(pool='z', buy_index=k, pnl=1, gross_return=0.0, net_return=0.0, cluster='z') for k in (8, 9, 28, 29, 98, 99)]
    t = D.pool_types(pos, dict(z=dict(events=events, migrated=False, creation_block_time=0)))
    assert {k: v['n'] for k, v in t['D3a_events_before_entry'].items()} == {'[0,10)': 1, '[10,30)': 2, '[30,100)': 2,
                                                                            '>=100': 1}
    assert t['D3b_creation_hour_utc']['00-04h']['n'] == 6
    t2 = D.pool_types(pos[:1], dict(z=dict(events=events, migrated=False, creation_block_time=4 * 3600 - 1)))
    assert set(t2['D3b_creation_hour_utc']) == {'00-04h'}
