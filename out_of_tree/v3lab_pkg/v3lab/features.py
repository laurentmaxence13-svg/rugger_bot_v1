"""Causal V3 extras next to the frozen ``native_features`` (same history slice, nothing after it).

``v3_extras(history, facts)`` reads only ``history``: the real curve events up to and including
the decision event, exactly the slice the frozen ``PolicyArm.entry`` hands to ``native_features``.
* ``fee_rate_ppm_causal``: ``bot.market.replay.causal_fee_rate(history)``, the very estimator the
  frozen executor applies to our own fills at that decision (so the policy and the fill agree);
* ``progress_gain_{30,60}s_ppm``: curve progress now minus the progress left by the last event at
  least that many seconds old (the launch state when there is none).
"""
from bot.market.replay import causal_fee_rate

GAIN_WINDOWS_S = (30, 60)


def v3_extras(history, facts):
    if not history:
        raise ValueError('empty_history')
    last = history[-1]
    now = last.block_time
    if type(now) is not int:
        raise ValueError('block_time_required')
    rate, _evidence = causal_fee_rate(history)
    progress = last.state_after().progress_ppm
    extras = dict(fee_rate_ppm_causal=rate)
    for window in GAIN_WINDOWS_S:
        base = next((e for e in reversed(history) if e.block_time <= now - window), None)
        before = base.state_after().progress_ppm if base is not None else history[0].state_before().progress_ppm
        extras[f'progress_gain_{window}s_ppm'] = progress - before
    return extras
