"""Pre-registered age study of option B' (synthetic points; the real measurement needs an owner GO)."""
from fractions import Fraction

import pytest

from bot.market import pyth_age_study as st


def _point(i, publish, *, delay=1, conf=500_000, price=9_000_000_000):
    return dict(slot=1000 + i, transaction_index=0, publish_time=publish, block_time=publish + delay,
                price=price, confidence=conf, exponent=-8)


def test_ages_follow_the_replay_rule():
    points = [_point(0, 100), _point(1, 150)]
    assert st.ages(points, 100, 104) == [None, None, 2, 3]       # available once its block second has ended
    assert st.ages(points, 151, 154) == [51, 2, 3]                # point 1 replaces point 0 at t = 152


def test_rules_are_coherent_with_the_wait_rule_r02_d1():
    assert (1 - st.AGE_COVERAGE) + (1 - st.CONF_QUANTILE) <= st.MAX_REFUSED_SHARE == st.WAIT_SHARE / 3
    assert st.WAIT_SHARE == Fraction(1, 100) and st.ERROR_LIMIT == Fraction(5, 1000)


def test_heartbeat_of_60_s_gives_a_threshold_just_above_it():
    points = [_point(i, 1_000 + 60 * i) for i in range(400)]
    result = st.study(points, [(1_002, 1_000 + 60 * 399)])        # the window starts once a point is known
    assert result['verdict'] == 'ACCEPTED', result['reasons']
    assert result['acceptance'] == dict(max_age_ms=65_000, max_confidence_ppm=100)
    assert 0.47 < result['shares']['30'] < 0.50 and result['shares']['60'] < 0.998
    assert result['gap_s'] == dict(p50=60, p99=60, max=60) and result['refused_share'] == 0.0
    assert result['error']['p99'] == 0.0                         # constant price


def test_rejections_are_fixed_in_advance():
    sparse = [_point(i, 1_000 + 200 * i) for i in range(20)]
    result = st.study(sparse, [(1_002, 1_000 + 200 * 19)])
    assert result['verdict'] == 'REJECTED' and 'age_coverage_above_120_s' in result['reasons']
    assert result['acceptance'] is None
    wide = [_point(i, 1_000 + 30 * i, conf=60_000_000) for i in range(100)]          # 0.67 %
    assert 'confidence_above_5000_ppm' in st.study(wide, [(1_002, 3_970)])['reasons']


def test_missing_seconds_count_as_refused_and_stay_in_the_shares():
    points = [_point(i, 1_000 + 30 * i) for i in range(10)]
    result = st.study(points, [(900, 1_270)])
    assert result['missing_seconds'] == 102 and result['seconds'] == 370
    assert result['shares']['120'] == 268 / 370
    assert result['verdict'] == 'REJECTED' and 'age_coverage_above_120_s' in result['reasons']


def test_refused_share_must_stay_below_a_third_of_the_wait_rule():
    # One wide point (0.05 % of the points, so above the 99.9th percentile) held for 100 s:
    # 0.5 % of the seconds are refused although each threshold alone looks fine.
    times = [1_000 + 10 * i for i in range(1_000)] + [11_090 + 10 * i for i in range(1_000)]
    points = [_point(i, t, conf=(400_000_000 if i == 999 else 500_000)) for i, t in enumerate(times)]
    result = st.study(points, [(1_002, times[-1])])
    assert result['acceptance'] is None and 'refused_seconds_above_0_3_percent' in result['reasons']
    assert result['refused_share'] > 0.003 and 'confidence_above_5000_ppm' not in result['reasons']


def test_error_against_the_next_publication_r02_d3():
    # alternating prices 1 % apart: every accepted second is 1 % off the next publication.
    points = [_point(i, 1_000 + 30 * i, price=(9_000_000_000 if i % 2 else 9_090_000_000)) for i in range(300)]
    result = st.study(points, [(1_002, 1_000 + 30 * 299)])
    assert result['error']['p99'] > 0.005 and 'error_p99_above_0_5_percent' in result['reasons']
    calm = [_point(i, 1_000 + 30 * i, price=9_000_000_000 + (i % 2) * 9_000_000) for i in range(300)]   # 0.1 %
    ok = st.study(calm, [(1_002, 1_000 + 30 * 299)])
    assert ok['verdict'] == 'ACCEPTED' and 0.0009 < ok['error']['p99'] < 0.0011


def test_density_probe_stops_an_unaffordable_study():
    # 1.25 tx/s at 214.5 ms per slot: about 0.268 tx per slot; 3 h = about 50 350 slots.
    assert st.density_projection(4_500, 16_783, 50_350) == 1_360          # 13 501 tx -> 136 pages
    assert st.study_go_no_go(4_500, 16_783, 50_350) == ('GO', 1_360)
    assert st.study_go_no_go(9_000, 16_783, 50_350)[0] == 'STOP'
    with pytest.raises(ValueError):
        st.density_projection(1, 0, 1)
