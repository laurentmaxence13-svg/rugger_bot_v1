"""cpmmgen2: executable rules of generation 2 on synthetic pools (routed depth and fee payers set by hand)."""
import dataclasses
import hashlib
from pathlib import Path

import pytest

from cpmmgen2 import rule as G
from cpmmprereg import rule as R
from cpmmprereg.tests.test_rule import CONFIG, FEES, SOL
from cpmmx import timeline as TL
from cpmmx.tests.test_cpmmx import BASE_B58, POOL_B58, Sim, logs, tx

ROUTER = 'Router1111111111111111111111111111111111111'
SHEET = 'ab' * 32


def market(steps, *, quote=200 * SOL, base=10 ** 15):
    """steps: (time_s, side, amount[, routed[, payer]]); slot = 2 x time."""
    sim, txs = Sim(base, quote, FEES, True), {}
    for i, step in enumerate(steps):
        t, side, amount = step[:3]
        routed = step[3] if len(step) > 3 else False
        payer = step[4] if len(step) > 4 else 'P%d' % i
        payload, _ = sim.swap(side, amount)
        raw = tx(t * 2, i, logs(payload, outer=ROUTER if routed else None), when=t)
        raw['transaction'] = dict(message=dict(accountKeys=[payer, 'Other']))
        txs['s%05d' % i] = raw
    return TL.build(POOL_B58, txs, base_mint=BASE_B58), txs


def shift(steps, dt):
    return [(st[0] + dt,) + tuple(st[1:]) for st in steps]


def calm(start, end, every=20, payer=None):
    return [(t, 'buy' if (t // every) % 2 else 'sell', (2 * 10 ** 8) if (t // every) % 2 else (10 ** 12), False,
             payer or 'C%d' % t) for t in range(start, end, every)]


# -- G2-1 --------------------------------------------------------------------------------------------------------------
def test_g21_keeps_a_direct_drop_and_refuses_a_routed_one():
    direct, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13, False)] + calm(710, 900))
    routed, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13, True)] + calm(710, 900))
    assert R.decisions(direct, CONFIG) == R.decisions(routed, CONFIG) == [35]          # the R-CP1 trigger is the same
    assert G.routed_share(direct, 35) == 0 and G.routed_share(routed, 35) > 0.6
    assert G.decisions_g21(direct, CONFIG, 0.5) == [35] and G.decisions_g21(routed, CONFIG, 0.5) == []
    assert G.decisions_g21(routed, CONFIG, 1.0) == [35]                               # share <= m1, boundary included
    share = G.routed_share(routed, 35)
    assert G.decisions_g21(routed, CONFIG, share) == [35] and G.decisions_g21(routed, CONFIG, share - 1e-12) == []


def test_g21_cooldown_and_no_sale_window():
    twice, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 1_400) + [(1_405, 'sell', 4 * 10 ** 13)]
                      + calm(1_410, 4_400) + [(4_405, 'sell', 4 * 10 ** 13)])
    times = [twice.swaps[i].block_time for i in G.decisions_g21(twice, CONFIG, 1.0)]
    assert times[0] == 705 and all(t - 705 >= 3_600 for t in times[1:]) and len(times) >= 2
    buys_only, _ = market([(t, 'buy', 10 ** 8) for t in range(0, 700, 20)])
    assert G.routed_share(buys_only, len(buys_only.swaps) - 1) is None


def test_population_m1_before_t0_only():
    day = 86_400
    t0 = 2 * day
    lines = []
    for routed in (False, True, True):
        steps = calm(0, 700) + [(705, 'sell', 4 * 10 ** 13, routed)] + calm(710, 900)
        line, _ = market(shift(steps, t0 - 3_600))
        lines.append(dataclasses.replace(line, pool=line.pool + str(len(lines))))
    m1 = G.population_m1(lines, CONFIG, t0)
    fees = R.CC.fees_from_amm_config(CONFIG)
    population = sorted(G.routed_share(ln, i) for ln in lines for i in range(len(ln.swaps))
                        if G.drop_event(ln, i, fees) and G.routed_share(ln, i) is not None)
    assert len(population) > 3 and population.count(0) >= 1           # every drop event counts, not only the first
    mid = len(population) // 2
    assert m1 == (population[mid] if len(population) % 2 else (population[mid - 1] + population[mid]) / 2)
    assert 0 < m1 < 1
    with pytest.raises(G.PreregError, match='data_at_or_after_t0_refused'):
        G.population_m1(lines, CONFIG, t0 - 3_000)
    calm_only, _ = market(shift(calm(0, 900), t0 - 3_600))
    with pytest.raises(G.PreregError, match='no_drop_event_before_t0'):
        G.population_m1([calm_only], CONFIG, t0)
    with pytest.raises(G.PreregError, match='t0_must_be_an_integer'):
        G.population_m1(lines, CONFIG, float(t0))


# -- G2-2 --------------------------------------------------------------------------------------------------------------
def test_g22_waits_for_a_positive_flow_without_a_new_low():
    selling = [(t, 'sell', 2 * 10 ** 12) for t in range(710, 1_000, 10)]          # the pressure goes on: new lows
    calm_buys = [(t, 'buy', 3 * 10 ** 8) for t in range(1_000, 1_400, 10)]         # flow turns positive, no new low
    line, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + selling + calm_buys)
    entries, empty = G.decisions_g22(line, CONFIG)
    assert len(entries) == 1 and empty == 0
    t1 = line.swaps[entries[0]].block_time
    assert 1_000 < t1 <= 705 + G.WAIT_S and t1 - 300 >= 1_000 - 10          # the 300 s window holds buys only
    recent = G._window(line, entries[0], G.CALM_S)
    assert sum(G.quote_flow(line.swaps[k]) for k in recent) > 0
    # the same day without the buys: the wait ends empty, counted
    line2, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + selling + [(t, 'sell', 10 ** 11) for t in range(1_000, 2_600, 30)])
    assert G.decisions_g22(line2, CONFIG) == ([], 1)


def test_g22_a_new_low_blocks_the_entry_and_the_trigger_alone_is_never_an_entry():
    after = [(t, 'buy', 3 * 10 ** 8) for t in range(710, 1_000, 10)] + [(1_005, 'sell', 9 * 10 ** 13)] \
        + [(t, 'buy', 10 ** 8) for t in range(1_010, 1_300, 10)]
    line, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + after)
    entries, _ = G.decisions_g22(line, CONFIG)
    fees = R.CC.fees_from_amm_config(CONFIG)
    assert R.spot_after(line, 65, fees) < min(R.spot_after(line, k, fees) for k in range(65))   # 1 005: a new low
    for e in entries:
        t = line.swaps[e].block_time
        assert line.swaps[e].block_time > 705
        low_recent = min(R.spot_after(line, k, fees) for k in G._window(line, e, G.CALM_S))
        before = [k for k in range(e + 1) if 105 < line.swaps[k].block_time <= t - G.CALM_S]
        assert low_recent >= min(R.spot_after(line, k, fees) for k in before)
        assert not 1_005 <= t < 1_305                                               # within 300 s of the new low


def test_g22_placebo_within_the_waits():
    line, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 4_000))
    p = G.placebo_g22(line, 1, SHEET, CONFIG)
    assert len(p) == 1 and 705 < line.swaps[p[0]].block_time <= 705 + G.WAIT_S
    assert p == G.placebo_g22(line, 1, SHEET, CONFIG)
    with pytest.raises(G.PreregError, match='freeze_sheet_sha256_required'):
        G.placebo_g22(line, 1, 'x', CONFIG)


# -- G2-3 --------------------------------------------------------------------------------------------------------------
def test_fee_payer_forms():
    assert G.fee_payer(dict(transaction=dict(message=dict(accountKeys=['A', 'B'])))) == 'A'
    assert G.fee_payer(dict(transaction=dict(message=dict(accountKeys=[dict(pubkey='A', signer=True)])))) == 'A'
    for bad in (dict(), dict(transaction=dict(message=dict(accountKeys=[])))):
        with pytest.raises(G.PreregError, match='transaction_without_account_keys'):
            G.fee_payer(bad)
    with pytest.raises(G.PreregError, match='invalid_fee_payer'):
        G.fee_payer(dict(transaction=dict(message=dict(accountKeys=[dict(pubkey='')]))))


def test_g23_distinct_buyers_against_the_pool_baseline():
    t0 = 7 * 86_400
    steady = [(k * 600 + 7, 'buy', 10 ** 8, False, 'B%d' % (k % 3)) for k in range(1_008)]    # one buyer per window
    base_line, base_txs = market(steady)
    assert G.baseline_b3(base_line, base_txs, t0) == 1
    sparse = [(k * 1_200 + 7, 'buy', 10 ** 8, False, 'B') for k in range(504)]               # half the windows empty
    sp_line, sp_txs = market(sparse)
    assert G.baseline_b3(sp_line, sp_txs, t0) == 0.5
    with pytest.raises(G.PreregError, match='data_at_or_after_t0_refused'):
        G.baseline_b3(base_line, base_txs, 600)
    one = [(t, 'buy', 10 ** 8, False, 'Same') for t in range(0, 600, 60)]
    burst = [(t, 'buy', 10 ** 8, False, 'Q%d' % t) for t in range(600, 800, 50)]
    line, txs = market(one + burst + [(t, 'sell', 10 ** 11, False, 'S') for t in range(800, 900, 20)])
    found = G.decisions_g23(line, txs, 1)
    assert [line.swaps[i].block_time for i in found] == [600]                 # 'Same' + 'Q600': 2 distinct >= 2 x 1
    assert [line.swaps[i].block_time for i in G.decisions_g23(line, txs, 2)] == [700]   # Same, Q600, Q650, Q700
    assert G.decisions_g23(line, txs, 0) == []                                # b3 = 0: excluded pool
    sells_ignored = G.buyers(line, txs)
    assert all(b is None for b, s in zip(sells_ignored, line.swaps) if s.side == 'sell')


# -- counts, trials, confirmation ------------------------------------------------------------------------------------------
def test_trigger_count_trials_and_confirmation():
    day = 86_400
    t0 = 2 * day
    steps = calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 1_400)
    line, _ = market(shift(steps, t0 - 3_600))
    count = G.trigger_count(lambda ln: G.decisions_g21(ln, CONFIG, 1.0), [line], t0)
    assert count['triggers'] == 1 and count['outcomes_computed'] is False
    with pytest.raises(G.PreregError, match='data_at_or_after_t0_refused'):
        G.trigger_count(lambda ln: [], [line], t0 - 3_000)
    with pytest.raises(G.PreregError, match='pool_given_twice'):
        G.trigger_count(lambda ln: [], [line, line], t0)
    assert G.trials('G2-1', 170)['n_after'] == 171 and G.trials('G2-3', 172)['n_after'] == 173
    for bad in (169, 173):
        with pytest.raises(G.PreregError, match='trial_cap'):
            G.trials('G2-2', bad)
    with pytest.raises(G.PreregError, match='unknown_hypothesis'):
        G.trials('G2-9', 170)
    assert G.confirmation_n(0.01, 'holm')['n'] == 262 and G.confirmation_n(0.01, 'bonferroni')['n'] == 221
    assert G.confirmation_n(0.04, 'holm')['n'] > 262
    with pytest.raises(G.PreregError, match='confirmation_choice'):
        G.confirmation_n(0.01, 'none')


def test_holm_step_down_and_bonferroni():
    assert G.holm(dict(a=0.008, b=0.012, c=0.02)) == dict(a=True, b=True, c=True)      # 0.025/3, /2, /1
    assert G.holm(dict(a=0.013, b=0.001, c=0.02)) == dict(a=False, b=True, c=False)   # 0.013 > 0.025/2: stop there
    assert G.holm(dict(a=0.0084, b=0.001, c=0.5)) == dict(a=True, b=True, c=False)
    assert G.holm(dict(a=0.009, b=0.02, c=0.03)) == dict(a=False, b=False, c=False)   # 0.009 > 0.025/3
    assert G.holm(dict(a=0.01, b=0.02, c=0.03), 'bonferroni') == dict(a=True, b=False, c=False)
    assert G.holm(dict(a=None, b=0.001)) == dict(a=False, b=True)


def test_bootstrap_p_and_the_elimination_rule():
    pos = {f'p{i}': [0.02, 0.03] for i in range(20)}
    neg = {f'p{i}': [-0.02, -0.01] for i in range(20)}
    assert G.bootstrap_p(pos, seed=1, draws=300) == 0 and G.bootstrap_p(neg, seed=1, draws=300) == 1
    mixed = {f'p{i}': [0.03 if i % 2 else -0.025] for i in range(20)}
    assert G.bootstrap_p(mixed, seed=7, draws=500) == G.bootstrap_p(mixed, seed=7, draws=500)
    assert 0 < G.bootstrap_p(mixed, seed=7, draws=500) < 1 and G.bootstrap_p({}, seed=1) is None
    assert G.withdrawn_if_family_negative('NO-GO', 'NO-GO') == dict(kept=('G2-3',), withdrawn=('G2-1', 'G2-2'), k=1)
    assert G.withdrawn_if_family_negative('NO-GO', 'GO_PILOTE')['k'] == 3
    assert G.withdrawn_if_family_negative('INCONCLUSIF', 'NO-GO')['k'] == 3


def test_frozen_imports_untouched():
    assert G.positions is R.positions and G.placebo is R.placebo and G.pilot_verdict is R.CC.pilot_verdict
    assert hashlib.sha256(Path(R.__file__).read_bytes()).hexdigest() == \
        '9f46f052a588cdb5ab3c907aae04f26ec6b2b5ed40acc8e3d1874c275c679fdd'
    assert G.WINDOWS_BEFORE_T0 == 1_008 and (G.WAIT_S, G.CALM_S, G.BUYERS_MULTIPLIER) == (1_800, 300, 2)


# -- targeted tests (mutation survivors) ---------------------------------------------------------------------------------
from types import SimpleNamespace as NS  # noqa: E402


def fake_line(times, sides=None):
    sides = sides or ['buy'] * len(times)
    return NS(pool='F', swaps=[NS(block_time=t, side=s, depth=1, signature='x%d' % k,
                                  event=NS(input_amount=1, output_amount=1)) for k, (t, s) in enumerate(zip(times, sides))])


def test_drop_event_reference_boundary_activity_and_threshold(monkeypatch):
    times = list(range(0, 700, 20)) + [700]                     # 0, 20, ..., 680, then 700: a swap exactly at t - 600
    line = fake_line(times)
    i, at, before = len(times) - 1, times.index(100), times.index(80)
    prices = {before: R.Fraction(100), at: R.Fraction(110), i: R.Fraction(1066, 10)}
    monkeypatch.setattr(R, 'spot_after', lambda ln, k, f: prices.get(k, R.Fraction(1)))
    assert G.drop_event(line, i, None)                          # -3.1 % against the swap exactly at t - 600 s
    prices[i] = R.Fraction(1068, 10)                             # -2.9 %: not a drop (and not a 1.5 % one either)
    assert not G.drop_event(line, i, None)
    thin = fake_line(list(range(0, 700, 60)) + [700])            # 12 swaps in ]100 ; 700]: fewer than 20
    j, ref = len(thin.swaps) - 1, [k for k, s in enumerate(thin.swaps) if s.block_time <= 100][-1]
    prices.clear()
    prices.update({ref: R.Fraction(100), j: R.Fraction(50)})
    assert not G.drop_event(thin, j, None)


def g22_line(monkeypatch, times, flows, spots, trigger):
    line = fake_line(times)
    monkeypatch.setattr(G, 'drop_event', lambda ln, k, f: k in trigger)
    monkeypatch.setattr(G, 'quote_flow', lambda s: flows[int(s.signature[1:])])
    monkeypatch.setattr(R, 'spot_after', lambda ln, k, f: R.Fraction(spots[k]))
    monkeypatch.setattr(R.CC, 'fees_from_amm_config', lambda c: None)
    return line


def test_g22_wait_boundary_flow_sign_and_empty_count(monkeypatch):
    times = [0, 100, 200, 1_800, 1_801]
    spots = [100, 90, 95, 96, 96]
    # trigger at index 1 (t0 = 100); positive flow only at the end: t = 1 800 is <= t0 + 1 800 -> entry
    line = g22_line(monkeypatch, times, [0, -5, -1, 3, 3], spots, {1})
    assert G.decisions_g22(line, None) == ([3], 0)
    late = g22_line(monkeypatch, [0, 100, 200, 1_901, 1_950], [0, -5, -1, 3, 3], spots, {1})
    assert G.decisions_g22(late, None) == ([], 1)                # t0 + 1 801: the wait has expired, counted once
    negative = g22_line(monkeypatch, times, [0, -5, -1, -3, -3], spots, {1})
    assert G.decisions_g22(negative, None) == ([], 1)            # flow never positive: no entry, the last wait counted
    zero = g22_line(monkeypatch, times, [0, -5, 0, 0, 0], spots, {1})
    assert G.decisions_g22(zero, None) == ([], 1)                # net flow 0 is not > 0
    lower = g22_line(monkeypatch, times, [0, -5, -1, 3, 3], [100, 90, 95, 89, 96], {1})
    assert G.decisions_g22(lower, None) == ([], 1)               # 89 < 90 within the last 300 s: no entry, wait ends
    equal = g22_line(monkeypatch, times, [0, -5, -1, 3, 3], [100, 90, 95, 90, 96], {1})
    assert G.decisions_g22(equal, None) == ([3], 0)              # equal to the low is not below it


def test_m1_counts_only_the_seven_days_before_t0():
    day = 86_400
    t0 = 20 * day
    old = shift(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 900), t0 - 9 * day)
    old2 = shift(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 900), t0 - 8 * day)
    recent = shift(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13, True)] + calm(710, 900), t0 - 3_600)
    line, _ = market(old + old2 + recent)
    fees = R.CC.fees_from_amm_config(CONFIG)
    start = t0 - 7 * day
    inside = [G.routed_share(line, i) for i in range(len(line.swaps))
              if line.swaps[i].block_time >= start and G.drop_event(line, i, fees)]
    everything = [G.routed_share(line, i) for i in range(len(line.swaps)) if G.drop_event(line, i, fees)]
    import statistics
    assert G.population_m1([line], CONFIG, t0) == statistics.median([s for s in inside if s is not None])
    assert statistics.median([s for s in everything if s is not None]) != statistics.median([s for s in inside if s is not None])
    count = G.trigger_count(lambda ln: G.decisions_g21(ln, CONFIG, 1.0), [line], t0)
    assert count['triggers'] == 1                                 # the two old drops are outside [T0 - 7 d ; T0)


def test_g22_placebo_always_inside_a_wait():
    line, _ = market(calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 20_000, every=40))
    fees = R.CC.fees_from_amm_config(CONFIG)
    triggers = [s.block_time for k, s in enumerate(line.swaps) if G.drop_event(line, k, fees)]
    assert triggers and max(triggers) + G.WAIT_S < 10_000                # most of the day lies outside every wait
    for k in range(30):
        sheet = hashlib.sha256(b'%d' % k).hexdigest()
        for i in G.placebo_g22(line, 1, sheet, CONFIG):
            assert any(t0 < line.swaps[i].block_time <= t0 + G.WAIT_S for t0 in triggers)


def test_b3_is_the_median_of_distinct_buyers():
    t0 = 7 * 86_400
    steps = []
    for k in range(1_008):
        steps.append((k * 600 + 7, 'buy', 10 ** 8, False, 'Same%d' % k))
        steps.append((k * 600 + 9, 'buy', 10 ** 8, False, 'Same%d' % k))           # same buyer twice: 1 distinct
        if k % 10 == 0:
            steps += [(k * 600 + 11 + j, 'buy', 10 ** 8, False, 'X%d_%d' % (k, j)) for j in range(8)]   # 9 distinct
    line, txs = market(steps)
    assert G.baseline_b3(line, txs, t0) == 1                       # median 1 (mean would be 1.8; a count would be 2)


def test_bootstrap_p_counts_a_zero_mean_as_not_positive():
    zeros = {f'p{i}': [0.0, 0.0] for i in range(10)}
    assert G.bootstrap_p(zeros, seed=3, draws=200) == 1


def test_quote_flow_sign():
    line, _ = market([(0, 'buy', 3 * 10 ** 8), (10, 'sell', 10 ** 12)])
    buy, sale = line.swaps
    assert G.quote_flow(buy) == buy.event.input_amount > 0
    assert G.quote_flow(sale) == -sale.event.output_amount < 0
