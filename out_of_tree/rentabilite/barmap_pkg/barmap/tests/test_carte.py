"""barmap: break-even map from the cost models only; consistency with cpmmcost, monotonicity, reproducibility."""
from fractions import Fraction

import pytest

from barmap import carte as C
from bot.market.launchlab_curve import fee_for


def g(**kw):
    args = dict(tier=2_500, reserve_sol=100, priority=100_000, failure=0, rent='closed', wsol_separate=True)
    args.update(kw)
    return C.cpmm_gross_required(**args)


def test_agrees_with_the_audited_cpmmcost_sizing_bar():
    # cpmmcost.bar(R) = 2 x 0.25 % + 3 tx + WSOL tx + 2 x stake / R: 1.12 % at 100 SOL, 2.92 % at 10 SOL
    assert g() == pytest.approx(0.0112, abs=0.0002)
    assert g(reserve_sol=10) == pytest.approx(0.0292, abs=0.0002)
    assert g(reserve_sol=1_000) == pytest.approx(0.0112 - 0.0018, abs=0.0002)


def test_the_bisection_lands_on_a_zero_net():
    costs = C.fixed_costs(priority=100_000, failure=0, rent='closed', wsol_separate=True)
    assert costs == 4 * 105_000
    low_g = Fraction(1, 1000)
    received, move = C._round_trip(2_500, 100, low_g.numerator, low_g.denominator)
    assert received - C.STAKE - costs < 0                    # a 0.1 % move does not pay the costs
    assert C.cpmm_gross_required(tier=2_500, reserve_sol=100, priority=0, failure=0, rent='closed',
                                 wsol_separate=False) > 0.005                  # 2 x 0.25 % at least


def test_monotone_in_each_lever():
    assert g(tier=2_500) < g(tier=10_000) < g(tier=20_000) < g(tier=40_000)
    assert g(reserve_sol=10) > g(reserve_sol=50) > g(reserve_sol=100) > g(reserve_sol=1_000)
    assert g(priority=0) < g(priority=10_000) < g(priority=100_000) < g(priority=1_000_000)
    assert g(failure=0) < g(failure=Fraction(1, 10)) < g(failure=Fraction(1, 2)) < g(failure=Fraction(3, 5))
    assert g(rent='rent_lost') - g(rent='closed') == pytest.approx((2_039_280 - 105_000) / C.STAKE, abs=2e-4)
    assert g(wsol_separate=True) - g(wsol_separate=False) == pytest.approx(105_000 / C.STAKE, abs=2e-4)


def test_failure_cost_is_geometric_and_bounded():
    assert C.fixed_costs(priority=100_000, failure=Fraction(1, 2), rent='closed', wsol_separate=True) == 2 * 4 * 105_000
    assert C.fixed_costs(priority=0, failure=Fraction(3, 5), rent='rent_lost', wsol_separate=False) == \
        Fraction(5_000) * Fraction(5, 2) * 2 + 2_039_280
    for bad in (1, Fraction(3, 2), -Fraction(1, 10)):
        with pytest.raises(C.MapError, match='failure_rate'):
            C.fixed_costs(priority=0, failure=bad, rent='closed', wsol_separate=True)
    with pytest.raises(C.MapError, match='unknown_rent_mode'):
        C.fixed_costs(priority=0, failure=0, rent='other', wsol_separate=True)


def test_launchlab_rows_and_the_w1_mean():
    ll = C.launchlab_gross_required(rate=16_700, priority=100_000, failure=0, rent='closed')
    assert ll == pytest.approx((2 * fee_for(C.STAKE, 16_700) + 3 * 105_000) / C.STAKE)
    assert ll == pytest.approx(0.03655, abs=0.0001)                       # the ~3.66 % of R02 (closed account)
    lost = C.launchlab_gross_required(rate=16_700, priority=100_000, failure=0, rent='rent_lost')
    assert lost == pytest.approx((2 * fee_for(C.STAKE, 16_700) + 2 * 105_000 + 2_039_280) / C.STAKE)


def test_document_is_reproducible_and_ranks_the_levers():
    a, b = C.document(), C.document()
    assert a == b and a['data_read'] is False
    spans = [lv['span'] for lv in a['levers']]
    assert spans == sorted(spans, reverse=True)
    assert [lv['lever'] for lv in a['levers'][:3]] == ['fee_tier_ppm', 'priority_lamports',
                                                       'venue_launchlab_w1_mean_vs_cpmm_025']
    assert a['rows']['latency']['value'] == C.NM
    assert len(a['rows']['reserve_sol']) == len(C.RESERVES_SOL) and len(a['rows']['launchlab']) == 10
