"""barmap 0.1 -- T-R01-2: BREAK-EVEN MAP, the minimal GROSS edge a position needs for a zero net, from the cost models
only (cpmmx.curve exact swaps as in cpmmcost 0.3; LaunchLab fee_for and the frozen-chain constants as in papercost).
NO DATA IS READ: every input is a declared grid; the numbers are reproducible bit for bit.

DEFINITION (CPMM, exact on the curve): buy STAKE (0.1 SOL) on a pool of quote reserve Q SOL and base reserve Q x 10^6
(the price level is irrelevant to the shares), with the trade fee of the tier and the protocol / fund shares of U-1;
the market then moves the PRE-BUY mid by a factor (1 + g) at constant k, our own buy being arbitraged away (the
unfavourable X-1 state that cpmmcost keeps: the sale is valued on the real reserves, without our buy, so our impact is
paid on both legs; the other traders' fees are ignored, declared); we sell every token on that state.
gross = tokens x (mid before our sale - mid before our buy) / stake (cpmmcost price_move). Costs: (1 + p / (1 - p)) x (base 5 000 + priority) per own transaction (p = failure rate, every failed
attempt charged, cpmmcost rule), buy + sale + WSOL close (separate tx, cpmmcost unfavourable default) + cleanup in
CLOSED mode, or the SPL rent 2 039 280 lost in RENT_LOST mode (no cleanup). The minimal gross is the g of zero net, by
bisection on exact integer swaps, reported as a share of the stake.

LAUNCHLAB (papercost constants, curve impact NOT included -- it needs the curve state, i.e. data): 2 x fee_for(stake,
rate) + 2 transactions + rent lost or cleanup, as a share of the stake.

LATENCY is not a fee: on a static pool it costs nothing; its cost is the adverse price drift during the 4 slots, which
needs price data (measured by PAPER_LIVE S-3 and the H-1 worst case of cpmmcost), so the map gives it NON MESURÉ.
"""
from fractions import Fraction

from cpmmx import curve

SCHEMA = 'barmap-v0.1'
STAKE = 100_000_000
BASE_FEE, FROZEN_PRIORITY = 5_000, 100_000
RENT = 2_039_280
PROTOCOL, FUND = 120_000, 40_000                      # shares of the trade fee in the U-1 AmmConfig (cpmmcost tests)
CPMM_TIERS_PPM = (2_500, 10_000, 20_000, 40_000)      # DECLARED Raydium CPMM tiers; 0.25 % is U-1, the others to be read
RESERVES_SOL = (10, 20, 50, 100, 500, 1_000)
PRIORITIES = (0, 10_000, 100_000, 500_000, 1_000_000)
FAILURE_RATES = (0, Fraction(1, 10), Fraction(3, 10), Fraction(1, 2), Fraction(3, 5))
RENT_MODES = ('closed', 'rent_lost')
LAUNCHLAB_TIERS_PPM = (2_500, 12_500, 16_700, 17_500, 37_500)  # P0 / W1 tiers; 16 700 = W1 mean (3.34 % round trip)
LAUNCHLAB_W1_MEAN_PPM = 16_700
BASELINE = dict(tier=2_500, reserve_sol=100, priority=FROZEN_PRIORITY, failure=0, rent='closed', wsol_separate=True)
NM = 'NON MESURÉ'


class MapError(ValueError):
    pass


def fees(tier):
    return curve.Fees(tier, 0, PROTOCOL, FUND)


def transactions(*, rent, wsol_separate):
    """Own transactions of a closed round trip: buy, sale, WSOL close (if separate), cleanup (closed mode only)."""
    return 2 + (1 if wsol_separate else 0) + (1 if rent == 'closed' else 0)


def fixed_costs(*, priority, failure, rent, wsol_separate):
    """Lamports of transactions (with expected failed attempts) and of rent, per round trip."""
    if not 0 <= failure < 1:
        raise MapError('failure_rate_must_be_in_[0,1)')
    if rent not in RENT_MODES:
        raise MapError('unknown_rent_mode')
    per_tx = Fraction(BASE_FEE + priority) * (1 + Fraction(failure) / (1 - Fraction(failure)))
    return per_tx * transactions(rent=rent, wsol_separate=wsol_separate) + (RENT if rent == 'rent_lost' else 0)


def _round_trip(tier, reserve_sol, g_num, g_den):
    """(received, market_move) for a mid moved by g = g_num / g_den between our buy and our sale (constant k)."""
    quote, base = reserve_sol * 10 ** 9, reserve_sol * 10 ** 15
    f = fees(tier)
    bought = curve.swap_base_input(STAKE, quote, base, f, True)
    tokens = bought.output_amount
    mid_before_buy = Fraction(quote, base)
    # constant k, pre-buy mid x (1 + g), our buy arbitraged away: quote' = Q sqrt(1 + g), base' = B / sqrt(1 + g)
    scale = 10 ** 12
    root = _isqrt(scale * scale * (g_den + g_num) // g_den)
    q2, b2 = quote * root // scale, base * scale // root
    sold = curve.swap_base_input(tokens, b2, q2, f, True)
    mid_before_sale = Fraction(q2, b2)
    return sold.output_amount, tokens * (mid_before_sale - mid_before_buy)


def _isqrt(n):
    x = int(n ** 0.5) if n < 2 ** 1000 else 1 << ((n.bit_length() + 1) // 2)
    while x * x > n:
        x = (x + n // x) // 2
    while (x + 1) * (x + 1) <= n:
        x += 1
    return x


def cpmm_gross_required(*, tier, reserve_sol, priority, failure, rent, wsol_separate=True):
    """Minimal gross (share of the stake) for a zero net, by bisection on g in [0, 1]."""
    costs = fixed_costs(priority=priority, failure=failure, rent=rent, wsol_separate=wsol_separate)

    def net(g):
        received, _move = _round_trip(tier, reserve_sol, g.numerator, g.denominator)
        return received - STAKE - costs
    low, high = Fraction(0), Fraction(1)
    if net(high) <= 0:
        raise MapError('break_even_above_100_percent')
    if net(low) >= 0:
        return 0.0
    for _ in range(60):
        mid = (low + high) / 2
        mid = Fraction(round(mid * 10 ** 15), 10 ** 15)
        if net(mid) >= 0:
            high = mid
        else:
            low = mid
    _received, move = _round_trip(tier, reserve_sol, high.numerator, high.denominator)
    return float(move / STAKE)


def launchlab_gross_required(*, rate, priority, failure, rent):
    from bot.market.launchlab_curve import fee_for
    costs = fixed_costs(priority=priority, failure=failure, rent=rent, wsol_separate=False)
    return float((2 * fee_for(STAKE, rate) + costs) / STAKE)         # costs: buy + sale (+ cleanup) (+ rent lost)


def table():
    """The full declared grid, one variable moved at a time around BASELINE, plus the LaunchLab rows."""
    b = BASELINE
    base_value = cpmm_gross_required(tier=b['tier'], reserve_sol=b['reserve_sol'], priority=b['priority'],
                                     failure=b['failure'], rent=b['rent'], wsol_separate=b['wsol_separate'])
    rows = dict(baseline=dict(BASELINE, failure=float(b['failure']), gross_required=base_value))

    def one(name, values, key):
        out = []
        for v in values:
            args = dict(tier=b['tier'], reserve_sol=b['reserve_sol'], priority=b['priority'], failure=b['failure'],
                        rent=b['rent'], wsol_separate=b['wsol_separate'])
            args[key] = v
            out.append(dict(value=float(v) if isinstance(v, Fraction) else v,
                            gross_required=cpmm_gross_required(**args)))
        rows[name] = out
    one('fee_tier_ppm', CPMM_TIERS_PPM, 'tier')
    one('reserve_sol', RESERVES_SOL, 'reserve_sol')
    one('priority_lamports', PRIORITIES, 'priority')
    one('failure_rate', FAILURE_RATES, 'failure')
    one('rent_mode', RENT_MODES, 'rent')
    one('wsol_separate_close', (True, False), 'wsol_separate')
    rows['latency'] = dict(value=NM, reason='not a fee: adverse drift over the latency needs price data (S-3, H-1)')
    rows['launchlab'] = [dict(rate_ppm=r, rent=m, gross_required=launchlab_gross_required(
        rate=r, priority=FROZEN_PRIORITY, failure=0, rent=m)) for r in LAUNCHLAB_TIERS_PPM for m in RENT_MODES]
    return rows


def levers(rows):
    """Range of the barrier over each lever's grid (max - min), largest first: the 3 strongest are the answer."""
    spans = []
    for name in ('fee_tier_ppm', 'reserve_sol', 'priority_lamports', 'failure_rate', 'rent_mode', 'wsol_separate_close'):
        values = [r['gross_required'] for r in rows[name]]
        spans.append((max(values) - min(values), name))
    w1 = [r['gross_required'] for r in rows['launchlab'] if r['rate_ppm'] == LAUNCHLAB_W1_MEAN_PPM and r['rent'] == 'closed']
    spans.append((w1[0] - rows['baseline']['gross_required'], 'venue_launchlab_w1_mean_vs_cpmm_025'))
    return [dict(lever=name, span=span) for span, name in sorted(spans, reverse=True)]


def document():
    rows = table()
    return dict(schema=SCHEMA, data_read=False, baseline=BASELINE | dict(failure=0), rows=rows, levers=levers(rows),
                declared=dict(tiers='Raydium CPMM tiers other than 0.25 % are DECLARED, to be confirmed on read AmmConfig',
                              external_move='constant k, the other traders\' fees ignored',
                              launchlab_impact='curve impact NOT included (needs the curve state)'))
