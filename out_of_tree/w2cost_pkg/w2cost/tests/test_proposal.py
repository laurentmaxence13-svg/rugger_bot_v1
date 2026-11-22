"""w2cost: the proposed W2 full-cost parameter set, n_min, rtgate exclusion and the fixture impact (fixtures only)."""
import pytest

from bot.market import replay as R
from papercost import engine as PC
from paperstream.tests.test_engine import EnterAt, _timelines
from rtgate import gate as RT
from w2cost import proposal as W

MODEL = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')


def test_n_min_is_the_dossier_b_formula():
    assert W.n_min() == W.N_MIN_DOSSIER_B == 414
    assert W.n_min(delta=0.01) > 4 * 400 and W.n_min(power=0.9) > 414 and W.n_min(sigma=0.2) > 414
    for bad in (dict(sigma=0), dict(delta=-0.01), dict(alpha=0.6), dict(power=0.4)):
        with pytest.raises(ValueError, match='invalid_power_inputs'):
            W.n_min(**bad)


def test_n_min_under_full_costs_never_falls_below_the_protected_floor():
    assert W.n_min_full_cost(0.0) == dict(cycles=414, decisions=414, effect=0.02)
    assert W.n_min_full_cost(0.0, entry_share=0.5)['decisions'] == 828
    assert W.n_min_full_cost(-0.005)['cycles'] == 414                    # a favourable-looking layer: floor kept
    half = W.n_min_full_cost(0.01)
    assert half['cycles'] == W.n_min(delta=0.01) and half['effect'] == pytest.approx(0.01)
    assert W.n_min_full_cost(0.02) is None and W.n_min_full_cost(0.03) is None
    with pytest.raises(ValueError, match='invalid_entry_share'):
        W.n_min_full_cost(0.0, entry_share=0)


def test_the_single_parameter_set_is_declared_and_not_adopted():
    assert W.PARAMETERS['adopted'] is False and 'owner decision' in W.PARAMETERS['adoption']
    assert W.primary_options() == PC.Options.primary()
    assert W.PARAMETERS['primary']['account_mode'] == 'rent_lost' and W.PARAMETERS['primary']['mev_scenario'] == 'none'
    assert W.PARAMETERS['published_apart']['frozen_net'] == 'always published beside'
    assert len(W.parameters_sha256()) == 64 and W.parameters_sha256() == W.parameters_sha256()


def test_rtgate_admits_the_complete_fixture_timelines_and_excludes_a_gapped_one():
    for t in _timelines():
        ok, record = W.complete_or_excluded(t, EnterAt(2, None, None), MODEL)
        assert ok and record['status'] == RT.COMPLETE
    busy = max(_timelines(), key=lambda t: len(t.events))
    gapped = type(busy)(busy.pool, busy.events[:30] + busy.events[31:], busy.gaps, busy.rejected)
    ok, record = W.complete_or_excluded(gapped, EnterAt(2, None, None), MODEL)
    assert not ok and record['status'] == RT.INCOMPLETE


def test_the_fixture_impact_is_described_never_an_estimate():
    impact = W.fixture_impact(_timelines(), MODEL, lambda k: EnterAt(k, 5, None), range(1, 100))
    assert impact == W.fixture_impact(_timelines(), MODEL, lambda k: EnterAt(k, 5, None), range(1, 100))
    assert impact['fixtures_only'] is True and impact['estimate_for_w2'] is False
    assert impact['entries_frozen'] > 50 and 0 < impact['refused_by_guard'] < impact['entries_frozen']
    assert impact['entry_share'] == (impact['entries_frozen'] - impact['refused_by_guard']) / impact['entries_frozen']
    # against the A0 engine (rent assumed refunded for free) the full costs are heavier than the 2.04 % rent less the
    # guard's selection effect; the engine-only part is reported apart
    assert impact['mean_extra_cost_vs_frozen_engine'] > 0.01
    assert impact['mean_extra_cost_vs_frozen_engine'] - impact['mean_extra_cost_engine_only'] == pytest.approx(
        PC.RENT_LAMPORTS / W.STAKE + 0, abs=2e-3)
    with pytest.raises(ValueError, match='no_entry_on_the_fixtures'):
        W.fixture_impact(_timelines(), MODEL, lambda k: EnterAt(10 ** 6, None, None), [10 ** 6])
