"""Pre-registered age study of option B' (synthetic points; the real measurement needs an owner GO)."""
from bot.market import pyth_age_study as st


def _point(i, publish, *, delay=1, conf=500_000, price=9_000_000_000):
    return dict(slot=1000 + i, transaction_index=0, publish_time=publish, block_time=publish + delay,
                price=price, confidence=conf)


def test_ages_follow_the_replay_rule():
    points = [_point(0, 100), _point(1, 150)]
    # point 0 lands at block 101; it is available from t = 102 (its second has ended).
    assert st.ages(points, 100, 104) == [None, None, 2, 3]
    assert st.ages(points, 151, 154) == [51, 2, 3]                # point 1 replaces point 0 at t = 152


def test_heartbeat_of_60_s_gives_a_threshold_just_above_it():
    points = [_point(i, 1_000 + 60 * i) for i in range(200)]
    result = st.study(points, [(1_000, 1_000 + 60 * 199)])
    assert result['verdict'] == 'ACCEPTED' and result['acceptance']['max_age_ms'] == 65_000
    assert 0.47 < result['shares']['30'] < 0.50 and result['shares']['60'] < 0.99 and result['shares']['75'] > 0.999   # 2 seconds before the first point
    assert result['gap_s'] == dict(p50=60, p99=60, max=60) and result['delay_s']['p50'] == 1
    assert result['acceptance']['max_confidence_ppm'] == 100      # 55.6 ppm rounded up to 50-ppm steps


def test_rejections_are_fixed_in_advance():
    sparse = [_point(i, 1_000 + 200 * i) for i in range(20)]
    result = st.study(sparse, [(1_000, 1_000 + 200 * 19)])
    assert result['verdict'] == 'REJECTED' and 'age_coverage_above_120_s' in result['reasons']
    assert result['acceptance'] is None
    wide = [_point(i, 1_000 + 30 * i, conf=60_000_000) for i in range(100)]          # 0.67 %
    assert 'confidence_above_5000_ppm' in st.study(wide, [(1_000, 3_970)])['reasons']


def test_seconds_before_the_first_point_count_as_missing():
    points = [_point(i, 1_000 + 30 * i) for i in range(10)]
    result = st.study(points, [(900, 1_270)])
    assert result['missing_seconds'] == 102 and result['seconds'] == 370
    assert result['verdict'] == 'REJECTED'                       # 102/370 seconds without a point
