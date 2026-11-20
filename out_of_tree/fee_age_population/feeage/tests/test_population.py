"""feeage: population counts of the fee tier versus age, known answers, firewall, frozen-pack run."""
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bot
from feeage import population as F


def _event(fee, amount=1_000_000_000, side='buy'):
    return SimpleNamespace(side=side, amount_in=amount, amount_out=amount, protocol_fee=fee, platform_fee=0,
                           creator_fee=0, share_fee=0)


def test_tier_of_rounds_the_implied_rate_and_drops_small_fees():
    assert F.tier_of(_event(25_000_000)) == (25_000, True)                    # 2.5 % of 1 SOL bought
    assert F.tier_of(_event(2_500_000)) == (2_500, True)
    assert F.tier_of(_event(2_510_000)) == (2_500, True)                      # rounded to the nearest 500 ppm
    assert F.tier_of(_event(999)) == (None, False)


def test_known_answers():
    pools = [(100, [(0, 10_000), (3, 10_000), (500, 10_000)], 1),            # constant, late at 10 000
             (200, [(0, 52_500), (30, 12_500), (460, 2_500), (900, 2_500)], 0),   # decreasing, late at 2 500
             (300, [(10, 2_500), (20, 5_000)], 2),                           # increasing
             (300 + 4 * 86_400 * 1000 // 215, [(460, 2_500)], 0),           # one event: no constancy, late low
             (400, [(470, 2_000)], 0)]                                       # below 2 500 ppm: low too (<=)
    doc = F.population(pools)
    c = doc['constancy']
    assert (doc['pools'], doc['usable_events'], doc['events_fee_below_min']) == (5, 11, 3)
    assert (c['pools_with_two_usable_events'], c['constant'], c['changing'], c['changing_non_increasing']) == (3, 1, 2, 1)
    assert c['first_to_last'] == {'52500->2500': 1, '2500->5000': 1}
    assert doc['tiers_by_age_class'] == {'[0,5)': {'10000': 2, '52500': 1}, '[5,25)': {'2500': 1, '5000': 1},
                                         '[25,50)': {'12500': 1}, '>=450': {'2000': 1, '2500': 3, '10000': 1}}
    cd = doc['c_d_population']
    assert (cd['late_pools'], cd['late_pools_at_low_tier']) == (4, 3)
    assert cd['days_at_declared_clock'] == pytest.approx(4.0, abs=1e-3) and cd['late_low_per_day'] == 0.75
    narrow = F.population(pools[:2], span_slots=86_400 * 1000 // 215)
    assert narrow['c_d_population']['days_at_declared_clock'] == pytest.approx(1.0, abs=1e-3)
    assert doc['flags'] == dict(values_read=False, curve_state_read=False, counted_in_n=False)


def test_firewall_no_value_reserve_progress_or_signer_is_named():
    source = inspect.getsource(F).split('"""', 2)[2]                      # the code, without the module docstring
    for name in ('real_', 'progress', 'signer', 'signed', 'pnl', 'net_return', 'reserve', 'creator\'', 'holder'):
        assert name not in source.replace('creator_fee', ''), name


def test_frozen_pack_run_and_guards(tmp_path):
    pools = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    sha = hashlib.sha256((pools / 'MANIFEST.json').read_bytes()).hexdigest()
    with pytest.raises(F.FeeAgeError, match='manifest_is_not_the_anchored_one'):
        F.run(pools, '0' * 64, tmp_path / 'x', 'P0')
    assert F.main(['--pools', str(pools), '--manifest-sha256', sha, '--label', 'frozen-pack', '--out', str(tmp_path / 'o')]) == 0
    doc = json.loads((tmp_path / 'o' / 'FEE_AGE_POPULATION.json').read_text())
    assert doc['all']['pools'] == 3 and doc['all']['constancy']['changing'] == 0   # constant tiers in the frozen pack
    assert 'evaluation_range' not in doc
    slots = sorted(F.pool_facts(a)[0] for _e, a in F.load_fixtures_lazy(pools)[2])
    F.clear_cache()
    assert F.main(['--pools', str(pools), '--manifest-sha256', sha, '--label', 'frozen-pack', '--evaluation-min',
                   str(slots[1]), '--evaluation-max', str(slots[1] + 1), '--out', str(tmp_path / 'r')]) == 0
    ranged = json.loads((tmp_path / 'r' / 'FEE_AGE_POPULATION.json').read_text())['evaluation_range']
    assert ranged['pools'] == slots.count(slots[1]) and ranged['c_d_population']['creation_slot_span'] == 1
    with pytest.raises(F.FeeAgeError, match='invalid_evaluation_range'):
        F.run(pools, sha, tmp_path / 'z', 'P0', 5, None)
    assert doc['input'] == dict(label='frozen-pack', manifest_sha256=sha)
    with pytest.raises(F.FeeAgeError, match='output_exists'):
        F.run(pools, sha, tmp_path / 'o', 'P0')


def test_boundaries_min_fee_and_late_age_and_first_late_tier():
    assert F.tier_of(_event(1_000)) == (0, True)       # exactly the minimum fee is usable (1 ppm of 1 SOL: tier 0)
    doc = F.population([(0, [(449, 2_500), (450, 10_000), (900, 2_500)], 0),  # first late event: age 450, tier 10 000
                        (0, [(450, 2_500), (800, 2_500)], 0)])                 # first late event: age 450, tier 2 500
    # the FIRST late event decides (pool 1 would count as low with its last late event, or with a strict > 450)
    assert doc['c_d_population']['late_pools'] == 2 and doc['c_d_population']['late_pools_at_low_tier'] == 1
    assert doc['tiers_by_age_class'] == {'[150,450)': {'2500': 1}, '>=450': {'2500': 3, '10000': 1}}


def test_pool_facts_ages_are_relative_to_the_creation_slot(monkeypatch):
    events = [SimpleNamespace(slot=1_005, **vars(_event(12_500_000))), SimpleNamespace(slot=1_500, **vars(_event(500)))]
    monkeypatch.setattr(F, 'summarize', lambda archive: (None, SimpleNamespace(events=events)))
    monkeypatch.setattr(F, 'creation_facts', lambda archive: dict(creation_slot=1_000))
    assert F.pool_facts(object()) == (1_000, [(5, 12_500)], 1)


def test_one_archive_at_a_time_and_cache_cleared(tmp_path):
    from w1aux import lazy
    pools = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    sha = hashlib.sha256((pools / 'MANIFEST.json').read_bytes()).hexdigest()
    lazy.PARSES.clear()
    F.run(pools, sha, tmp_path / 'o', 'frozen-pack')
    assert lazy._CACHE['path'] is None                                      # nothing held after the run
    assert len(lazy.PARSES) == 3 and max(lazy.PARSES.values()) <= 2         # parsed per pool, not all at once
