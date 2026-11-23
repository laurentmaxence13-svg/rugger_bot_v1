"""cpmmgen3 0.1 on synthetic CPMM pools only (cpmmx simulator): G3-1 inter-pool gap, G3-2 LP deepening, population
counts before T0, placebo, trials, confirmation. No collected datum is read."""
import hashlib
import json
import random
import struct
from pathlib import Path

import pytest

from barmap import carte as MAP
from cpmmcost import model as CC
from cpmmgen3 import rule as G
from cpmmprereg import rule as R
from cpmmx import curve, events, timeline as TL
from cpmmx.tests.test_cpmmx import BASE, BASE_B58, QUOTE, Sim, logs, swap_payload, tx

SOL = 10 ** 9
FEES_A = curve.Fees(2_500, 0, 120_000, 40_000)
FEES_B = curve.Fees(10_000, 0, 120_000, 40_000)
CONFIG_A = dict(trade_fee_rate=2_500, creator_fee_rate=0, protocol_fee_rate=120_000, fund_fee_rate=40_000,
                sha256='ab' * 32, slot=1)
CONFIG_B = dict(CONFIG_A, trade_fee_rate=10_000, sha256='cd' * 32)
POOL_A, POOL_B = bytes(range(101, 133)), bytes(range(141, 173))
SHEET = 'ef' * 32
T0 = 1_000_000


class Pool(Sim):
    """The cpmmx simulator for a given pool id, logging swaps and LP deposits."""

    def __init__(self, pool, base, quote, fees):
        super().__init__(base, quote, fees, True)
        self.pool = pool

    def swap(self, side, amount, *, exact_in=True):
        x, y = (self.quote, self.base) if side == 'buy' else (self.base, self.quote)
        got = curve.swap_base_input(amount, x, y, self.fees, True)
        mints = (QUOTE, BASE) if side == 'buy' else (BASE, QUOTE)
        payload = swap_payload(x, y, got.input_amount, got.output_amount, True, *mints, got.trade_fee,
                               got.creator_fee, True, pool=self.pool)
        new_x, new_y = curve.reserves_after(x, y, got)
        self.quote, self.base = (new_x, new_y) if side == 'buy' else (new_y, new_x)
        return payload

    def deposit(self, factor_num, factor_den, *, change_type=0):
        """LP event adding factor x the reserves (token_0 = quote: WSOL sorts before BASE)."""
        dq, db = self.quote * factor_num // factor_den, self.base * factor_num // factor_den
        payload = events.LP_DISCRIMINATOR + struct.pack('<32s7QB', self.pool, 1, self.quote, self.base, dq, db, 0, 0,
                                                        change_type)
        sign = 1 if change_type == 0 else -1
        self.quote, self.base = self.quote + sign * dq, self.base + sign * db
        return payload


def line_of(pool, steps, *, quote=200 * SOL, base=10 ** 15, fees=FEES_A, index=0):
    """steps: (time_s, kind, amount): kind 'buy' / 'sell' (amount) or 'lp' (factor as (num, den)) or 'lp1' (withdraw).
    slot = 2 x time; tx_index ``index`` lets two pools share a slot in a known order."""
    sim, txs = Pool(pool, base, quote, fees), {}
    for k, step in enumerate(steps):
        t, kind, amount = step[:3]
        ix = step[3] if len(step) > 3 else index
        if kind == 'lp':
            payload = sim.deposit(*amount)
        elif kind == 'lp1':
            payload = sim.deposit(*amount, change_type=1)
        else:
            payload = sim.swap(kind, amount)
        txs['%s%05d' % (pool[:2].hex(), k)] = tx(t * 2, ix, logs(payload), when=t)
    return TL.build(events.b58encode(pool), txs, base_mint=BASE_B58)


def calm(start, end, every=20):
    return [(t, 'buy' if (t // every) % 2 else 'sell', (2 * 10 ** 8) if (t // every) % 2 else (10 ** 12))
            for t in range(start, end, every)]


# -- barrier, pairs and population ------------------------------------------------------------------------------------
def test_the_barrier_is_the_map_value_never_retyped():
    anchored = json.loads((Path(MAP.__file__).parents[1] / 'CARTE_SEUIL_v0_1.json').read_text())
    assert G.barrier() == anchored['rows']['baseline']['gross_required']
    assert 0.0112 < G.barrier() < 0.0113


def rec(pool, mint, reserve_sol, tier=2_500, program='cpmm', quote=TL.WSOL):
    return dict(pool=pool, base_mint=mint, quote_mint=quote, program=program, trade_fee_rate=tier,
                quote_reserve_lamports=reserve_sol * SOL)


def test_pairs_take_the_deepest_other_qualifying_cpmm_wsol_pool_of_the_same_mint():
    records = [rec('a1', 'm1', 150), rec('b1', 'm1', 500, tier=10_000), rec('c1', 'm1', 300, tier=2_500),
               rec('a2', 'm2', 120), rec('b2', 'm2', 99, tier=10_000),                   # B under 100 SOL: no pair
               rec('a3', 'm3', 200), rec('b3', 'm3', 900, program='amm_v4'),              # B not CPMM: no pair
               rec('a4', 'm4', 200), rec('b4', 'm4', 900, quote='USDC'),                  # B not WSOL: no pair
               rec('a5', 'm5', 200, tier=10_000), rec('b5', 'm5', 900, tier=10_000),      # no A at 0.25 %
               rec('a6', 'm6', 100), rec('b6', 'm6', 100, tier=10_000)]                  # exactly 100 SOL: kept
    found = G.pairs(records)
    assert found == {'a1': 'b1', 'c1': 'b1', 'a6': 'b6'}
    tie = G.pairs([rec('x', 'm', 200), rec('z', 'm', 300, tier=10_000), rec('y', 'm', 300, tier=10_000)])
    assert tie == {'x': 'y'}
    pop = G.population_pairs(records)
    assert (pop['directed_pairs'], pop['paired_mints'], pop['evaluable']) == (3, 2, False)
    assert pop['conduct'].startswith('NON ÉVALUABLE') and pop['outcomes_computed'] is False
    doubled = [r for k in range(5) for r in (rec('a%d' % k, 'mm%d' % k, 200), rec('c%d' % k, 'mm%d' % k, 300),
                                             rec('b%d' % k, 'mm%d' % k, 900, 10_000))]
    assert G.population_pairs(doubled)['directed_pairs'] == 10 and G.population_pairs(doubled)['evaluable'] is False
    many = [r for k in range(10) for r in (rec('a%d' % k, 'mm%d' % k, 200), rec('b%d' % k, 'mm%d' % k, 200, 10_000))]
    assert G.population_pairs(many)['evaluable'] is True and G.population_pairs(many[:-2])['evaluable'] is False


# -- G3-1 --------------------------------------------------------------------------------------------------------------
def two_pools(sale_at=705, size=4 * 10 ** 13, b_lag=0):
    """A and B trade the same mint in step; at ``sale_at`` a large sale moves A only (B unchanged)."""
    steps_a = calm(0, 700) + [(sale_at, 'sell', size)] + calm(710, 1_400)
    steps_b = calm(b_lag, 700) + calm(710, 1_400)
    return (line_of(POOL_A, steps_a, index=1), line_of(POOL_B, steps_b, fees=FEES_B, index=0))


def test_g31_enters_in_a_when_a_is_cheaper_than_its_sibling_by_the_barrier():
    a, b = two_pools()
    found = G.decisions_g31(a, b, CONFIG_A, CONFIG_B)
    sale = next(i for i, s in enumerate(a.swaps) if s.block_time == 705)
    assert found == [sale]
    fa, fb = CC.fees_from_amm_config(CONFIG_A), G.sibling_fees(CONFIG_B)
    j = max(k for k, s in enumerate(b.swaps) if (s.slot, s.tx_index) <= (a.swaps[sale].slot, a.swaps[sale].tx_index))
    assert G.gap(a, sale, fa, b, j, fb) <= -G.barrier()
    # just under the barrier: no entry (a barrier at the exact gap enters, a hair above does not)
    exact = -G.gap(a, sale, fa, b, j, fb)
    assert G.decisions_g31(a, b, CONFIG_A, CONFIG_B, b=exact) == [sale]
    assert G.decisions_g31(a, b, CONFIG_A, CONFIG_B, b=exact * 1.000001) == []
    small, sb = two_pools(size=10 ** 12)
    assert G.decisions_g31(small, sb, CONFIG_A, CONFIG_B) == []


def test_g31_default_barrier_is_the_map_value():
    # a sale whose gap lies between half and the whole barrier: no entry with the map's b, one with b / 2
    fa, fb = CC.fees_from_amm_config(CONFIG_A), G.sibling_fees(CONFIG_B)
    for size in range(2 * 10 ** 12, 12 * 10 ** 12, 10 ** 12):
        a, b = two_pools(size=size)
        sale = next(i for i, s in enumerate(a.swaps) if s.block_time == 705)
        j = max(k for k, s in enumerate(b.swaps) if (s.slot, s.tx_index) <= (a.swaps[sale].slot, a.swaps[sale].tx_index))
        g = -G.gap(a, sale, fa, b, j, fb)
        if G.barrier() / 2 < g < G.barrier():
            break
    else:
        raise AssertionError('no size in the band')
    assert G.decisions_g31(a, b, CONFIG_A, CONFIG_B) == [] and G.decisions_g31(a, b, CONFIG_A, CONFIG_B, b=G.barrier() / 2)


def test_g31_reads_only_the_sibling_state_known_at_the_decision():
    a, b = two_pools()
    sale = next(i for i, s in enumerate(a.swaps) if s.block_time == 705)
    # B moves down by the same sale AFTER A's swap (later slot): A's decision must not see it
    later = line_of(POOL_B, calm(0, 700) + [(706, 'sell', 4 * 10 ** 13)] + calm(710, 1_400), fees=FEES_B)
    assert G.decisions_g31(a, later, CONFIG_A, CONFIG_B) == [sale]
    # the same move in the same slot but an EARLIER transaction is known: no gap left
    same = line_of(POOL_B, calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 1_400), fees=FEES_B, index=0)
    assert G.decisions_g31(a, same, CONFIG_A, CONFIG_B) == []
    # a B swap of the same slot but a LATER transaction is not known yet
    after = line_of(POOL_B, calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 1_400), fees=FEES_B, index=2)
    assert G.decisions_g31(a, after, CONFIG_A, CONFIG_B) == [sale]
    # ... and in the SAME transaction (same slot and index, e.g. an arbitrage touching both pools) too
    same_tx = line_of(POOL_B, calm(0, 700) + [(705, 'sell', 4 * 10 ** 13)] + calm(710, 1_400), fees=FEES_B, index=1)
    assert G.decisions_g31(a, same_tx, CONFIG_A, CONFIG_B) == []
    # no sibling state yet: no decision possible before B's first swap (the sale at 705 is skipped)
    young = line_of(POOL_B, calm(800, 1_400), fees=FEES_B)
    late = G.decisions_g31(a, young, CONFIG_A, CONFIG_B)
    assert sale not in late and all(a.swaps[i].block_time >= 800 for i in late) and late


def test_g31_cooldown_tier_and_pair_checks():
    steps_a = calm(0, 700) + [(705, 'sell', 4 * 10 ** 13), (1_000, 'sell', 2 * 10 ** 13)] + calm(1_010, 4_400) + [
        (4_405, 'sell', 4 * 10 ** 13)] + calm(4_410, 5_000)
    a = line_of(POOL_A, steps_a, index=1)
    b = line_of(POOL_B, calm(0, 5_000), fees=FEES_B)
    times = [a.swaps[i].block_time for i in G.decisions_g31(a, b, CONFIG_A, CONFIG_B)]
    assert times[0] == 705 and all(t - times[0] >= R.COOLDOWN_S for t in times[1:]) and len(times) >= 2
    with pytest.raises(G.PreregError, match='0_25'):
        G.decisions_g31(a, b, CONFIG_B, CONFIG_B)
    # the sibling's fees: read and hashed, a DECLARED tier, spot only (cpmmcost still refuses B for a trade)
    with pytest.raises(CC.CostError):
        CC.fees_from_amm_config(CONFIG_B)
    assert G.sibling_fees(CONFIG_B) == FEES_B and G.sibling_fees(CONFIG_A) == FEES_A
    for bad in (dict(CONFIG_B, trade_fee_rate=3_000), dict(CONFIG_B, sha256='x'), dict(CONFIG_B, slot=None),
                dict(CONFIG_B, sha256='AB' * 32)):
        with pytest.raises(G.PreregError, match='sibling'):
            G.decisions_g31(a, b, CONFIG_A, bad)
    with pytest.raises(G.PreregError, match='itself'):
        G.decisions_g31(a, a, CONFIG_A, CONFIG_A)
    other = TL.build(b.pool, {}, base_mint=TL.WSOL, quote_mint=TL.WSOL)
    with pytest.raises(G.PreregError, match='same_mint'):
        G.decisions_g31(a, other, CONFIG_A, CONFIG_B)


def test_g31_placebo_and_trigger_count_before_t0():
    a, b = two_pools()
    chosen = G.placebo_g31(a, b, 3, SHEET)
    assert chosen == G.placebo_g31(a, b, 3, SHEET) and len(chosen) == 1        # 1 400 s of data, cooldown 3 600 s
    # only swaps of A where B already has a state, drawn with the seed of the sheet and of pool A
    young = line_of(POOL_B, calm(800, 1_400), fees=FEES_B)
    for sheet in (SHEET, '12' * 32, '0a' * 32):
        draw = G.placebo_g31(a, young, 1, sheet)
        candidates = [i for i, s in enumerate(a.swaps) if s.block_time >= 800]
        rng = random.Random(int(hashlib.sha256((sheet + a.pool).encode()).hexdigest()[:8], 16))
        rng.shuffle(candidates)
        assert draw == [candidates[0]]
    assert G.placebo_g31(a, b, 3, '12' * 32) is not None
    with pytest.raises(G.PreregError):
        G.placebo_g31(a, b, 1, 'x')
    with pytest.raises(G.PreregError):
        G.placebo_g31(a, b, 1, 'E' * 64)
    count = G.trigger_count_g31([(a, b)], {a.pool: CONFIG_A, b.pool: CONFIG_B}, t0=5_000)
    assert count['triggers'] == 1 and count['outcomes_computed'] is False
    assert G.trigger_count_g31([(a, b)], {a.pool: CONFIG_A, b.pool: CONFIG_B}, t0=705 + 7 * 86_400 + 1)['triggers'] == 0
    with pytest.raises(G.PreregError, match='after_t0'):
        G.trigger_count_g31([(a, b)], {a.pool: CONFIG_A, b.pool: CONFIG_B}, t0=1_000)
    late_b = line_of(POOL_B, calm(0, 2_000), fees=FEES_B)
    with pytest.raises(G.PreregError, match='after_t0'):                      # the SIBLING's data too
        G.trigger_count_g31([(a, late_b)], {a.pool: CONFIG_A, b.pool: CONFIG_B}, t0=1_500)
    with pytest.raises(G.PreregError, match='twice'):
        G.trigger_count_g31([(a, b), (a, b)], {a.pool: CONFIG_A, b.pool: CONFIG_B}, t0=5_000)
    with pytest.raises(G.PreregError, match='integer'):
        G.trigger_count_g31([(a, b)], {}, t0=5_000.0)


# -- G3-2 --------------------------------------------------------------------------------------------------------------
def test_quote_index_follows_the_cpmm_mint_order():
    a, _b = two_pools()
    assert G.quote_index(a) == 0 and G.b58decode(TL.WSOL) < G.b58decode(BASE_B58)
    high = TL.build('p', {}, base_mint=TL.WSOL, quote_mint=BASE_B58)
    assert G.quote_index(high) == 1
    assert G.b58decode(events.b58encode(POOL_A)) == POOL_A
    with pytest.raises(G.PreregError):
        G.b58decode('0OIl')
    with pytest.raises(G.PreregError):
        G.b58decode('1111')


def test_g32_enters_at_the_first_swap_after_a_doubling_deposit_only():
    steps = calm(0, 300) + [(305, 'lp', (1, 1))] + calm(310, 600)                   # quote R -> 2 R
    line = line_of(POOL_A, steps)
    first = next(i for i, s in enumerate(line.swaps) if s.block_time > 305)
    assert G.decisions_g32(line) == [first]
    almost = line_of(POOL_A, calm(0, 300) + [(305, 'lp', (999, 1_000))] + calm(310, 600))
    assert G.decisions_g32(almost) == []                                             # 1.999 R: not doubled
    withdraw = line_of(POOL_A, calm(0, 300) + [(305, 'lp1', (1, 2))] + calm(310, 600))
    assert G.decisions_g32(withdraw) == []                                           # a withdrawal never enters
    # a swap of the same slot but an EARLIER transaction than the deposit is not 'after' it
    order = line_of(POOL_A, calm(0, 300) + [(305, 'buy', 10 ** 8, 0), (305, 'lp', (1, 1), 1), (310, 'buy', 10 ** 8, 0)])
    assert [order.swaps[i].block_time for i in G.decisions_g32(order)] == [310]
    last = line_of(POOL_A, calm(0, 300) + [(305, 'lp', (1, 1))])
    assert G.decisions_g32(last) == []                                               # no swap after it
    # two deposits before the same swap, and a second one within the cooldown: one entry
    twice = line_of(POOL_A, calm(0, 300) + [(301, 'lp', (1, 1)), (302, 'lp', (3, 1))] + calm(310, 1_000)
                    + [(1_005, 'lp', (1, 1))] + calm(1_010, 5_000) + [(5_005, 'lp', (2, 1))] + calm(5_010, 5_100))
    times = [twice.swaps[i].block_time for i in G.decisions_g32(twice)]
    assert times[0] == 310 and times[1] >= 5_005 and len(times) == 2


def test_g32_reads_the_quote_side_of_the_deposit():
    line = line_of(POOL_A, calm(0, 300) + [(305, 'lp', (1, 1))] + calm(310, 600))
    q = G.quote_index(line)
    _slot, _ix, _order, ev = line.lp_changes[0]
    assert G.eligible(ev, q) and G.eligible(ev, 1 - q)
    lopsided = events.LpChangeEvent('p', 1, 100, 100, 100, 99, 0, 0, 0)       # quote (token 0) doubles, base not
    assert G.eligible(lopsided, 0) and not G.eligible(lopsided, 1)
    empty = events.LpChangeEvent('p', 1, 0, 100, 5, 100, 0, 0, 0)
    assert not G.eligible(empty, 0)
    assert not G.eligible(events.LpChangeEvent('p', 1, 1_000, 1_000, 999, 999, 0, 0, 0), 0)   # 1.999 R
    assert G.eligible(events.LpChangeEvent('p', 1, 1_000, 1_000, 1_000, 1_000, 0, 0, 0), 0)    # exactly 2 R
    out = events.LpChangeEvent('p', 1, 100, 100, 100, 100, 0, 0, 1)            # a withdrawal of the same size
    assert not G.eligible(out, 0) and not G.eligible(out, 1)


def deposits_line(n):
    steps = calm(0, 100)
    for k in range(n):
        steps += ([(200 + 4_000 * k, 'lp', (1, 1))] + calm(210 + 4_000 * k, 260 + 4_000 * k)
                  + [(270 + 4_000 * k, 'lp1', (1, 2))])
    return line_of(POOL_A, steps)


def test_g32_threshold_of_30_deposits_exactly():
    t0 = 200 + 4_000 * 31
    assert G.population_deposits([deposits_line(30)], t0)['evaluable'] is True
    assert G.population_deposits([deposits_line(29)], t0)['evaluable'] is False
    assert G.population_deposits([deposits_line(29)], t0)['deposits'] == 29


def test_g32_population_of_deposits_before_t0_and_the_non_evaluable_conduct():
    steps = calm(0, 100)
    for k in range(31):                     # deposit x2, a few swaps, then a withdrawal of half: reserves stay bounded
        steps += ([(200 + 4_000 * k, 'lp', (1, 1))] + calm(210 + 4_000 * k, 260 + 4_000 * k)
                  + [(270 + 4_000 * k, 'lp1', (1, 2))])
    line = line_of(POOL_A, steps)
    t0 = 200 + 4_000 * 31
    pop = G.population_deposits([line], t0)
    assert pop['deposits'] == 31 and pop['evaluable'] is True and pop['outcomes_computed'] is False
    assert G.trigger_count_g32([line], t0)['triggers'] == 31
    short = G.population_deposits([line_of(POOL_A, steps[:-45])], t0)
    assert short['deposits'] < 30 and short['evaluable'] is False
    assert short['conduct'].startswith('NON ÉVALUABLE') and 'aucun essai' in short['conduct']
    # only [T0 - 7 d ; T0) counts
    far = G.population_deposits([line], t0 + 7 * 86_400 - 30_000)
    assert far['deposits'] < 31
    with pytest.raises(G.PreregError, match='after_t0'):
        G.population_deposits([line], 300)
    with pytest.raises(G.PreregError, match='twice'):
        G.population_deposits([line, line], t0)
    with pytest.raises(G.PreregError, match='after_t0'):
        G.trigger_count_g32([line], 300)


# -- trials, confirmation, shared pieces --------------------------------------------------------------------------------
def test_trials_need_the_new_tranche_and_stop_at_175():
    assert G.trials('G3-1', 173)['n_after'] == 174 and G.trials('G3-2', 174)['n_after'] == 175
    for bad in (172, 175, 173.0):
        with pytest.raises(G.PreregError):
            G.trials('G3-1', bad)
    with pytest.raises(G.PreregError):
        G.trials('G2-1', 173)
    assert 'distinct from text D' in G.trials('G3-1', 173)['rule']


def test_confirmation_n_and_holm_at_alpha_3():
    assert G.ALPHA_GENERATION == 0.0125
    assert G.confirmation_n(0.01)['n'] == 279 and G.confirmation_n(0.01, kept=1)['n'] == 238
    assert G.confirmation_n(0.05)['n'] > 279 and G.confirmation_n(0.01)['sigma_c'] == 0.025
    for bad in (-1, float('inf'), float('nan'), '0.02'):
        with pytest.raises(G.PreregError):
            G.confirmation_n(bad)
    with pytest.raises(G.PreregError):
        G.confirmation_n(0.02, kept=3)
    assert G.holm({'G3-1': 0.006, 'G3-2': 0.012}) == {'G3-1': True, 'G3-2': True}
    assert G.holm({'G3-1': 0.0063, 'G3-2': 0.001}) == {'G3-1': True, 'G3-2': True}
    assert G.holm({'G3-1': 0.007, 'G3-2': 0.008}) == {'G3-1': False, 'G3-2': False}
    assert G.holm({'G3-1': 0.006, 'G3-2': None}) == {'G3-1': True, 'G3-2': False}     # no p counts as 1, stays in K
    assert G.holm({'G3-1': 0.0125}) == {'G3-1': True} and G.holm({'G3-1': 0.0126}) == {'G3-1': False}


def test_exits_costs_and_verdict_are_r_cp1s():
    assert G.positions is R.positions and G.placebo_g32 is R.placebo and G.pilot_verdict is CC.pilot_verdict
    assert G.power_stop is R.power_stop and G.expected_entries is R.expected_entries
    a, b = two_pools()
    idx = G.decisions_g31(a, b, CONFIG_A, CONFIG_B)
    rows = G.positions(a, CONFIG_A, idx)
    assert len(rows) == 1 and rows[0]['pool'] == a.pool and rows[0]['counts_for_operational_master'] is False
