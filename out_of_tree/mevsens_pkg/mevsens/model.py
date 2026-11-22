"""mevsens 0.1 -- a SENSITIVITY model of N-6 (MEV: sandwich, Jito tip) for the PAPER engine (task P3-d, design).
Parametrised on the public fixtures only, NOT calibrated on W1 or on any collected data: every parameter is a DECLARED
scenario, never an estimate. Exact integer arithmetic of the frozen ``launchlab_curve``; nothing is sent.

SANDWICH OF OUR BUY. An attacker buys F lamports just before our buy (front-run) and sells after it. Our fill is the
exact output on the state after the front-run. With the slippage guard (``landslip.guard``, primary 20 000 ppm) the
attacker's best front-run is the LARGEST F that keeps our fill at or above the guarded minimum (beyond it our buy fails
and the attacker earns nothing): the worst case under a guard is a fill AT the minimum, i.e. a loss bounded by the
guard band. Without a guard the loss is bounded only by the attacker's capital (F_max, declared).
SANDWICH OF OUR SALE. An attacker sells T tokens just before our sale (no guard in the primary): our value is the
exact output on the state after that sale; T is a declared multiple of our tokens.
JITO TIP. A declared tip per own transaction that buys protection (bundle) is a pure cost; the model does not claim that
a tip removes the sandwich, it publishes both lines.
EXPECTED COST of a scenario = probability (declared) x sandwich loss + tip x own transactions. Scenarios are a fixed
grid declared here (``SCENARIOS``); no grid value may be chosen after seeing a result.
"""
from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from landslip import guard as G

SCHEMA = 'mevsens-v0.1'
SOL = 1_000_000_000
F_MAX_LAMPORTS = 1_000 * SOL                 # declared attacker capital bound (no guard case)
SCENARIOS = (                                # declared, not calibrated: (name, probability_ppm, buy front-run, sale front-run x our tokens, tip)
    dict(name='none', probability_ppm=0, buy_front='none', sale_front_multiple=0, tip_lamports=0),
    dict(name='guarded_worst_case', probability_ppm=1_000_000, buy_front='guard_bound', sale_front_multiple=0,
         tip_lamports=0),
    dict(name='quarter_of_trades', probability_ppm=250_000, buy_front='guard_bound', sale_front_multiple=1,
         tip_lamports=0),
    dict(name='always_with_sale', probability_ppm=1_000_000, buy_front='guard_bound', sale_front_multiple=5,
         tip_lamports=0),
    dict(name='tip_10k_per_tx', probability_ppm=0, buy_front='none', sale_front_multiple=0, tip_lamports=10_000),
    dict(name='tip_100k_per_tx', probability_ppm=0, buy_front='none', sale_front_multiple=0, tip_lamports=100_000),
)


class MevError(ValueError):
    pass


def fill_after_front_run(state, amount, rate, front):
    """Our tokens after an attacker's buy of ``front`` lamports, or None when that front-run is impossible."""
    if type(front) is not int or front < 0:
        raise MevError('invalid_front_run')
    try:
        shifted = buy_exact_in(state, front, rate).after if front else state
        return buy_exact_in(shifted, amount, rate).amount_out
    except CurveError:
        return None


def worst_buy_front_run(state, amount, rate, guard_ppm=G.BUY_GUARD_PPM, f_max=F_MAX_LAMPORTS):
    """(front, tokens): the largest front-run that leaves our buy at or above the guarded minimum (binary search, exact).

    Without a guard (None): the front-run f_max (or the largest possible below it)."""
    expected = buy_exact_in(state, amount, rate).amount_out
    floor = 0 if guard_ppm is None else G.minimum(expected, guard_ppm)

    def ok(front):
        tokens = fill_after_front_run(state, amount, rate, front)
        return tokens is not None and tokens >= floor and (guard_ppm is not None or tokens > 0)
    low, high = 0, f_max
    if ok(high):
        return high, fill_after_front_run(state, amount, rate, high)
    while high - low > 1:                                  # invariant: ok(low) and not ok(high)
        middle = (low + high) // 2
        if ok(middle):
            low = middle
        else:
            high = middle
    return low, fill_after_front_run(state, amount, rate, low)


def sale_after_front_run(state, tokens, rate, front_tokens):
    if type(front_tokens) is not int or front_tokens < 0:
        raise MevError('invalid_front_run')
    try:
        shifted = sell_exact_in(state, front_tokens, rate).after if front_tokens else state
        return sell_exact_in(shifted, tokens, rate).amount_out
    except CurveError:
        return None


def scenario_cost(scenario, buy_state, sale_state, amount, rate, guard_ppm=G.BUY_GUARD_PPM, own_transactions=2):
    """Expected extra cost in lamports of one round trip under a declared scenario, with its parts."""
    if scenario not in SCENARIOS:
        raise MevError('scenario_not_declared')
    tokens = buy_exact_in(buy_state, amount, rate).amount_out
    clean_sale = sell_exact_in(sale_state, tokens, rate).amount_out
    attacked_tokens = tokens
    if scenario['buy_front'] == 'guard_bound':
        _front, attacked_tokens = worst_buy_front_run(buy_state, amount, rate, guard_ppm)
    sale_value = sell_exact_in(sale_state, attacked_tokens, rate).amount_out
    if scenario['sale_front_multiple']:
        attacked = sale_after_front_run(sale_state, attacked_tokens, rate, attacked_tokens * scenario['sale_front_multiple'])
        sale_value = 0 if attacked is None else attacked
    sandwich_loss = clean_sale - sale_value
    expected = sandwich_loss * scenario['probability_ppm'] // 1_000_000
    tip = scenario['tip_lamports'] * own_transactions
    return dict(scenario=scenario['name'], sandwich_loss_lamports=sandwich_loss, expected_loss_lamports=expected,
                tip_lamports=tip, total_lamports=expected + tip, buy_tokens_clean=tokens,
                buy_tokens_attacked=attacked_tokens, calibrated=False)
