"""Liquidation value of a position on a bonding-curve state (protocol V4 v2, section 3).

A position always has a computed value: no fallback to 0, no conventional -1.
  rule 1  full sale accepted by the frozen ``sell_exact_in``             -> exact net output
  rule 2  sale limited by the quote reserve                              -> largest sellable quantity (exact search)
  rule 3  sale limited by the curve inventory (external inventory only)  -> rule 2 with q <= real_base
  rule 4  output rounds to zero                                          -> 0, flagged ``dust``
"""
from bot.market.launchlab_curve import CurveError, fee_for, sell_exact_in

PARTIAL, EXTERNAL, DUST = 'partial_liquidation', 'external_inventory_limited', 'dust'


def _gross(state, base_in):
    return base_in * state.quote_reserve // (state.base_reserve + base_in)


def max_sellable(state, tokens):
    """Largest q <= tokens that the curve can buy back: q <= real_base and gross(q) <= real_quote."""
    high = min(tokens, state.real_base)
    if high <= 0:
        return 0
    if _gross(state, high) <= state.real_quote:
        return high
    low = 0                                   # gross is non-decreasing in q: exact integer bisection
    while low < high:
        middle = (low + high + 1) // 2
        if _gross(state, middle) <= state.real_quote:
            low = middle
        else:
            high = middle - 1
    return low


def liquidation(state, tokens, rate_ppm):
    """Return ``(value, sold, flags, after)``: net quote received by selling as much of ``tokens`` as possible."""
    if tokens <= 0:
        return 0, 0, (DUST,), state
    try:
        fill = sell_exact_in(state, tokens, rate_ppm)
        return fill.amount_out, tokens, (), fill.after
    except CurveError as exc:
        reason = str(exc)
    if reason == 'output_rounds_to_zero':
        return 0, 0, (DUST,), state
    if reason not in ('sell_exceeds_quote_reserve', 'sell_exceeds_curve_inventory'):
        raise
    flags = [EXTERNAL] if reason == 'sell_exceeds_curve_inventory' else []
    sold = max_sellable(state, tokens)
    if sold < tokens:
        flags.append(PARTIAL)
    if sold <= 0 or _gross(state, sold) - fee_for(_gross(state, sold), rate_ppm) <= 0:
        return 0, 0, tuple(flags + [DUST]), state
    fill = sell_exact_in(state, sold, rate_ppm)
    return fill.amount_out, sold, tuple(flags), fill.after
