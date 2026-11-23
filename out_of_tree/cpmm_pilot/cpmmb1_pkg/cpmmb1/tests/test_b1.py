"""cpmmb1: the exact momentum mirror of R-CP1, on synthetic pools; R-CP1 itself untouched."""
import hashlib
import inspect
from pathlib import Path

import pytest

from cpmmb1 import rule as B
from cpmmprereg import rule as R
from cpmmprereg.tests.test_rule import CONFIG, SOL, calm, market


def rise_then(after, size=10 * SOL):
    return calm(0, 700) + [(705, 'buy', size)] + after


def test_b1_decides_on_a_rise_and_r_cp1_does_not():
    up = market(rise_then(calm(710, 1_400)))
    assert B.decisions(up, CONFIG) == [35] and R.decisions(up, CONFIG) == []
    fees = R.CC.fees_from_amm_config(CONFIG)
    ref = max(j for j in range(35) if up.swaps[j].block_time <= 705 - 600)
    assert R.spot_after(up, 35, fees) / R.spot_after(up, ref, fees) - 1 >= B.RISE
    down = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 1_400))
    assert B.decisions(down, CONFIG) == [] and R.decisions(down, CONFIG) == [35]


def test_threshold_activity_reference_and_cooldown():
    assert B.RISE == R.DROP * -1 and (R.LOOKBACK_S, R.MIN_SWAPS_IN_LOOKBACK, R.COOLDOWN_S) == (600, 20, 3_600)
    small = market(rise_then(calm(710, 900), size=SOL // 2))          # below +3 %
    assert B.decisions(small, CONFIG) == []
    thin = market(calm(0, 700, every=60) + [(705, 'buy', 10 * SOL)])  # fewer than 20 swaps in 600 s
    assert B.decisions(thin, CONFIG) == []
    young = market(calm(0, 500) + [(505, 'buy', 10 * SOL)])            # no reference 600 s back
    assert B.decisions(young, CONFIG) == []
    twice = market(rise_then(calm(710, 1_400) + [(1_405, 'buy', 10 * SOL)] + calm(1_410, 4_400)
                             + [(4_405, 'buy', 20 * SOL)]))
    times = [twice.swaps[i].block_time for i in B.decisions(twice, CONFIG)]
    assert times[0] == 705 and len(times) >= 2 and all(t - 705 >= 3_600 for t in times[1:])


def test_exact_boundary_of_plus_3_percent(monkeypatch):
    up = market(rise_then(calm(710, 900)))

    def fake(line, index, fees):
        return fake.prices[index] if index in fake.prices else 1
    fake.prices = {}
    monkeypatch.setattr(R, 'spot_after', fake)
    i = 35
    ref = max(j for j in range(i) if up.swaps[j].block_time <= 705 - 600)
    fake.prices = {ref: R.Fraction(100), i: R.Fraction(103)}
    assert i in B.decisions(up, CONFIG)
    fake.prices = {ref: R.Fraction(100), i: R.Fraction(10_299, 100)}
    assert i not in B.decisions(up, CONFIG)


def test_causal_and_the_reference_is_the_latest_swap_600_s_back():
    base = rise_then(calm(710, 1_400))
    full, cut = market(base), market(base[:36])
    assert B.decisions(full, CONFIG)[:1] == B.decisions(cut, CONFIG)[:1] == [35]
    # the reference is the LATEST swap <= t - 600, not the oldest: a low long before must not trigger B1
    steps = [(0, 'sell', 4 * 10 ** 13), (50, 'buy', 10 * SOL)] + calm(60, 700) + [(705, 'buy', SOL // 2)]
    line = market(steps)
    fees = R.CC.fees_from_amm_config(CONFIG)
    last = len(line.swaps) - 1
    assert R.spot_after(line, last, fees) / R.spot_after(line, 0, fees) - 1 >= B.RISE      # vs the oldest: would fire
    assert last not in B.decisions(line, CONFIG)


def test_own_trigger_count_refuses_data_at_or_after_t0():
    day = 86_400
    t0 = 2 * day
    shifted = [(t + t0 - 3 * 3_600, s, a) for t, s, a in rise_then(calm(710, 1_400))]
    line = market(shifted)
    count = B.trigger_count([line], CONFIG, t0)
    assert count['triggers'] == 1 and count['outcomes_computed'] is False and count['schema'] == B.SCHEMA
    assert R.trigger_count([line], CONFIG, t0)['triggers'] == 0          # the R-CP1 count does not see a rise
    old = market([(t + 1_000, s, a) for t, s, a in rise_then(calm(710, 1_400))])
    assert B.trigger_count([old], CONFIG, 7 * day + 1_000 + 705)['triggers'] == 1
    assert B.trigger_count([old], CONFIG, 7 * day + 1_000 + 706)['triggers'] == 0
    with pytest.raises(B.PreregError, match='data_at_or_after_t0_refused'):
        B.trigger_count([line], CONFIG, shifted[-1][0])
    with pytest.raises(B.PreregError, match='pool_given_twice'):
        B.trigger_count([line, line], CONFIG, t0)
    with pytest.raises(B.PreregError, match='t0_must_be_an_integer'):
        B.trigger_count([line], CONFIG, float(t0))
    assert B.expected_entries(count, 7) == 1 and B.power_stop(1) == 'UNDERPOWERED_DECLARED_OWNER_DECIDES'


def test_own_alpha_and_the_last_trial():
    assert B.n_required() == 155 and R.ALPHA_PILOT == 0.05 and R.ALPHA_CONFIRMATION == 0.05 / 3
    assert B.confirmation_n(0.01)['n'] == 221
    assert B.trials() == dict(n_before=169, n_after=170, left=0, rule=B.trials()['rule'])
    with pytest.raises(B.PreregError, match='trial_cap_exceeded'):
        B.trials(170)


def test_same_exits_costs_and_placebo_construction_r_cp1_untouched():
    assert B.exit_point is R.exit_point and B.positions is R.positions and B.placebo is R.placebo
    assert B.confirmation_verdict is R.confirmation_verdict
    up = market(rise_then(calm(710, 2_600)))
    p = B.positions(up, CONFIG, B.decisions(up, CONFIG))[0]
    assert p['guard_ppm'] == 20_000 and p['counts_for_operational_master'] is False
    rule_py = Path(R.__file__).read_bytes()
    assert hashlib.sha256(rule_py).hexdigest() == '9f46f052a588cdb5ab3c907aae04f26ec6b2b5ed40acc8e3d1874c275c679fdd'
    assert 'DROP' not in inspect.getsource(B.decisions)


def test_a_swap_exactly_600_s_back_is_the_reference(monkeypatch):
    line = market(calm(0, 700) + [(700, 'buy', SOL // 2)])           # swaps at 0, 20, ..., 680, then 700
    i = len(line.swaps) - 1
    at_boundary = next(j for j, s in enumerate(line.swaps) if s.block_time == 100)
    before = at_boundary - 1
    assert line.swaps[i].block_time - line.swaps[at_boundary].block_time == R.LOOKBACK_S
    prices = {before: R.Fraction(90), at_boundary: R.Fraction(100), i: R.Fraction(102)}
    monkeypatch.setattr(R, 'spot_after', lambda line_, index, fees: prices.get(index, R.Fraction(1)))
    assert i not in B.decisions(line, CONFIG)        # +2 % against the swap exactly at t - 600 s (it IS the reference)
    prices[i] = R.Fraction(103)
    assert i in B.decisions(line, CONFIG)
