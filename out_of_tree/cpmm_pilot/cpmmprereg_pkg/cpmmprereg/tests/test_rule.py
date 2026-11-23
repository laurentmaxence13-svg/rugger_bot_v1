"""cpmmprereg: R-CP1, its placebo, exits, power and stop rules on synthetic CPMM pools (cpmmx simulator)."""
import pytest

from cpmmcost import model as CC
from cpmmprereg import rule as R
from cpmmx import curve, timeline as TL
from cpmmx.tests.test_cpmmx import BASE_B58, POOL_B58, Sim, logs, tx

FEES = curve.Fees(2_500, 0, 120_000, 40_000)
CONFIG = dict(trade_fee_rate=2_500, creator_fee_rate=0, protocol_fee_rate=120_000, fund_fee_rate=40_000,
              sha256='ab' * 32, slot=1)
SOL = 10 ** 9
SHEET = 'ef' * 32


def market(steps, *, quote=200 * SOL, base=10 ** 15):
    """(time_s, side, amount) real swaps; slot = time_s * 2 (two slots per second, enough for the tests)."""
    sim = Sim(base, quote, FEES, True)
    txs = {}
    for i, (t, side, amount) in enumerate(steps):
        payload, _ = sim.swap(side, amount)
        txs['s%04d' % i] = tx(t * 2, i, logs(payload), when=t)
    return TL.build(POOL_B58, txs, base_mint=BASE_B58)


def calm(start, end, every=20):
    return [(t, 'buy' if (t // every) % 2 else 'sell', (2 * 10 ** 8) if (t // every) % 2 else (10 ** 12))   # balanced
            for t in range(start, end, every)]


def drop_then(after):
    """700 s of calm trading, then a large sale (> 3 % down), then ``after`` swaps."""
    return calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + after


def test_the_rule_decides_on_a_3_percent_drop_with_activity_and_a_cooldown():
    line = market(drop_then(calm(710, 1_400)))
    found = R.decisions(line, CONFIG)
    assert found == [35]                                              # the large sale at t = 705
    fees = CC.fees_from_amm_config(CONFIG)
    ref = max(j for j in range(35) if line.swaps[j].block_time <= 705 - 600)
    assert R.spot_after(line, 35, fees) / R.spot_after(line, ref, fees) - 1 <= R.DROP
    # a second drop inside the 3 600 s cooldown gives no decision; after it, it does
    twice = market(drop_then(calm(710, 1_400) + [(1_405, 'sell', 4 * 10 ** 13)] + calm(1_410, 4_400)
                             + [(4_405, 'sell', 4 * 10 ** 13)]))
    times = [twice.swaps[i].block_time for i in R.decisions(twice, CONFIG)]
    assert times[0] == 705 and all(t - 705 >= 3_600 for t in times[1:]) and len(times) >= 2


def test_each_condition_matters():
    small = market(calm(0, 700) + [(705, 'sell', 5 * 10 ** 12)] + calm(710, 900))   # a drop below 3 %
    assert R.decisions(small, CONFIG) == []
    thin = market(calm(0, 700, every=60) + [(705, 'sell', 4 * 10 ** 13)])            # fewer than 20 swaps in 600 s
    assert R.decisions(thin, CONFIG) == []
    young = market(calm(0, 500) + [(505, 'sell', 4 * 10 ** 13)])                      # no reference 600 s earlier
    assert R.decisions(young, CONFIG) == []


def test_the_decision_is_causal():
    base = drop_then(calm(710, 1_400))
    full = market(base)
    cut = market(base[:36])                                            # the same history up to the decision swap
    assert R.decisions(full, CONFIG)[:1] == R.decisions(cut, CONFIG)[:1] == [35]


def test_exits_tp_sl_and_clock():
    rebound = market(drop_then([(710, 'buy', 30 * SOL)] + calm(720, 900)))
    slot, time = R.exit_point(rebound, 35, CONFIG)
    assert time is None and slot == rebound.swaps[36].slot + 4                    # TP on the rebound buy
    crash = market(drop_then([(710, 'sell', 2 * 10 ** 14)] + calm(720, 900)))
    slot, time = R.exit_point(crash, 35, CONFIG)
    assert time is None and slot == crash.swaps[36].slot + 4                      # SL on the crash
    flat = market(drop_then(calm(710, 2_600)))
    slot, time = R.exit_point(flat, 35, CONFIG)
    assert slot is None and time == 705 + R.CLOCK_S + R.CLOCK_LATENCY_S
    for line in (rebound, crash, flat):
        p = R.positions(line, CONFIG, [35])[0]
        assert 'net_return' in p and p['counts_for_operational_master'] is False
    assert R.positions(rebound, CONFIG, [35])[0]['net_return'] > R.positions(crash, CONFIG, [35])[0]['net_return']


def test_the_placebo_is_deterministic_paired_and_respects_the_cooldown():
    line = market(calm(0, 9_000))
    a = R.placebo(line, 2, SHEET)
    assert a == R.placebo(line, 2, SHEET) and len(a) == 2
    assert all(R.has_reference(line, i) for i in a)
    assert abs(line.swaps[a[0]].block_time - line.swaps[a[1]].block_time) >= R.COOLDOWN_S
    assert R.placebo(line, 0, SHEET) == []
    with pytest.raises(R.PreregError, match='freeze_sheet_sha256_required'):
        R.placebo(line, 1, 'x')


def test_power_and_trials_are_declared():
    assert R.n_required() == 155                                                   # pilot: alpha 0.05, sigma 2.5 %
    assert R.n_required(alpha=R.ALPHA_CONFIRMATION) == 221                         # confirmation: alpha 0.05 / 3
    assert R.n_required(delta=0.01) == 39
    assert R.trials() == dict(n_before=168, n_after=169, left=1, rule=R.trials()['rule'])
    with pytest.raises(R.PreregError, match='trial_cap_exceeded'):
        R.trials(170)


def test_the_stop_rules():
    assert R.eligibility_stop(19) == dict(decision='STOP_INCONCLUSIF', trial_consumed=False, pools=19)
    assert R.eligibility_stop(20)['decision'] == 'PROCEED_ALL_NO_REPLACEMENT'
    assert R.eligibility_stop(23)['pools'] == 23
    assert R.eligibility_stop(24) == dict(decision='PROCEED_DRAW_24', trial_consumed=False, pools=24)
    assert R.eligibility_stop(500)['pools'] == 24
    assert R.power_stop(29) == 'UNDERPOWERED_DECLARED_OWNER_DECIDES'
    assert R.power_stop(30) == R.power_stop(154) == 'BELOW_POWER_TARGET_PUBLISHED_AS_SUCH'
    assert R.power_stop(155) == 'POWERED'
    for bad in (-1, 2.0, None):
        with pytest.raises(R.PreregError):
            R.eligibility_stop(bad)
        with pytest.raises(R.PreregError):
            R.power_stop(bad)


def test_halves_by_decision_time():
    line = market(drop_then(calm(710, 4_400) + [(4_405, 'sell', 4 * 10 ** 13)] + calm(4_410, 6_400)))
    found = R.decisions(line, CONFIG)
    first, second = R.halves(line, R.positions(line, CONFIG, found), cut_time=3_000)
    assert len(first) == 1 and len(second) >= 1


def test_the_reference_is_the_latest_swap_600_s_back_not_an_older_one():
    # a pump at t = 305, calm after; a 3.5 % drop at t = 1 005 relative to the post-pump price, but only about +1.5 %
    # relative to the pre-pump price: R-CP1 decides (latest reference) and an oldest-reference rule would not
    steps = calm(0, 300) + [(305, 'buy', 10 * SOL)] + calm(310, 1_000) + [(1_005, 'sell', 4 * 10 ** 13)]
    line = market(steps)
    found = R.decisions(line, CONFIG)
    assert [line.swaps[i].block_time for i in found] == [1_005]
    fees = CC.fees_from_amm_config(CONFIG)
    i = found[0]
    assert R.spot_after(line, i, fees) / R.spot_after(line, 0, fees) - 1 > R.DROP          # the oldest would not


def test_the_placebo_never_draws_a_swap_without_reference_whatever_the_sheet():
    line = market(calm(0, 7_300))
    assert any(not R.has_reference(line, i) for i in range(len(line.swaps)))
    for k in range(30):
        sheet = ('%02x' % k) * 32
        drawn = R.placebo(line, 2, sheet)
        assert drawn and all(R.has_reference(line, i) for i in drawn)
