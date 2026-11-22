"""landslip.guard 0.1 -- the SLIPPAGE GUARD of the PAPER engine (N-5), in the form fixed by R02 BEFORE any data
(AUDIT_MODELE_COUTS_PAPER_CB_R02_v1_0.md, 0167b2d1, decision 2). Pure functions on LaunchLab curve states, exact
integer arithmetic of the frozen ``launchlab_curve``; nothing here chooses a threshold from a result.

BUY (primary): minimum tokens = exact output at the DECISION state x (1 - 20 000 ppm), floored. The fill at landing is
the worst (fewest tokens) of the given landing states (H-1). Below the minimum the transaction FAILS: 105 000 lamports
are charged, there is NO entry and NO retry (the signal is stale). Published buy sensitivity: 50 000 ppm. No other
threshold.
SALE: no guard in the primary (the exit must happen). Sensitivity: guard 50 000 ppm on the exact value at the exit
DECISION state, a failed sale is retried 4 slots later (the cpmmcost 0.2 rule), up to 3 failures, then the sale is
done without a guard.
"""
from bot.market.launchlab_curve import buy_exact_in, sell_exact_in

PPM = 1_000_000
BUY_GUARD_PPM = 20_000
BUY_GUARD_SENSITIVITY_PPM = 50_000
SELL_GUARD_SENSITIVITY_PPM = 50_000
SELL_MAX_FAILURES = 3
FAILED_TX_FEE_LAMPORTS = 105_000
ALLOWED_BUY_GUARDS = (None, BUY_GUARD_PPM, BUY_GUARD_SENSITIVITY_PPM)
ALLOWED_SELL_GUARDS = (None, SELL_GUARD_SENSITIVITY_PPM)


class GuardError(ValueError):
    pass


def minimum(expected, guard_ppm):
    return expected * (PPM - guard_ppm) // PPM


def buy(decision_state, landing_states, amount, rate, guard_ppm=BUY_GUARD_PPM):
    """('filled', fill) with the worst landing fill, or ('failed', None) when it is below the guarded minimum."""
    if guard_ppm not in ALLOWED_BUY_GUARDS:
        raise GuardError('buy_guard_not_a_declared_threshold')
    if not landing_states:
        raise GuardError('no_landing_state')
    fill = min((buy_exact_in(state, amount, rate) for state in landing_states), key=lambda f: f.amount_out)
    if guard_ppm is None:
        return 'filled', fill
    expected = buy_exact_in(decision_state, amount, rate).amount_out
    if fill.amount_out < minimum(expected, guard_ppm):
        return 'failed', None
    return 'filled', fill


def sell(decision_state, attempts, tokens, rate, guard_ppm=None):
    """Sale with retries. ``attempts``: the landing states of attempt 0, 1, 2, 3 (each a list for H-1), 4 slots apart.

    Returns ('sold', sale, failures): failures = failed guarded attempts before the sale (each costs a transaction).
    """
    if guard_ppm not in ALLOWED_SELL_GUARDS:
        raise GuardError('sell_guard_not_a_declared_threshold')
    if not attempts or any(not states for states in attempts):
        raise GuardError('no_landing_state')
    floor = None if guard_ppm is None else minimum(sell_exact_in(decision_state, tokens, rate).amount_out, guard_ppm)
    for failures, states in enumerate(attempts):
        sale = min((sell_exact_in(state, tokens, rate) for state in states), key=lambda s: s.amount_out)
        if floor is None or failures == SELL_MAX_FAILURES or sale.amount_out >= floor:
            return 'sold', sale, failures
    raise GuardError('need_an_attempt_after_the_last_failure')
