"""Pure helpers to measure seconds per Solana slot from (slot, block_time) pairs.

No network access and no I/O. ``block_time`` is a whole number of seconds
(Unix time), so every pair carries a quantisation error of less than one
second; short spans are therefore unreliable and ``span_rate`` reports the
resulting bound explicitly.
"""


def unique_pairs(pairs):
    """Sort and deduplicate ``(slot, block_time)`` pairs, keyed by slot.

    Pairs with a missing slot or block_time are dropped. Two different
    block_times for one slot raise ``ValueError`` (inconsistent data).
    """
    seen = {}
    for slot, block_time in pairs:
        if slot is None or block_time is None:
            continue
        slot, block_time = int(slot), int(block_time)
        if seen.setdefault(slot, block_time) != block_time:
            raise ValueError("conflicting block_time for slot %d" % slot)
    return sorted(seen.items())


def span_rate(pairs):
    """Seconds per slot over the whole span of ``pairs``.

    Returns ``None`` when fewer than two distinct slots exist, else a dict
    with ``seconds_per_slot``, ``slots`` (span), ``seconds`` (span) and
    ``quantisation_bound`` (the +/- seconds-per-slot error implied by 1-second
    block-time rounding at both ends, i.e. 1 / slots).
    """
    ordered = unique_pairs(pairs)
    if len(ordered) < 2:
        return None
    slots = ordered[-1][0] - ordered[0][0]
    seconds = ordered[-1][1] - ordered[0][1]
    return {
        "seconds_per_slot": seconds / slots,
        "slots": slots,
        "seconds": seconds,
        "quantisation_bound": 1.0 / slots,
    }


def consecutive_rates(pairs):
    """Per-interval seconds per slot between consecutive distinct slots."""
    ordered = unique_pairs(pairs)
    return [
        (b_time - a_time) / (b_slot - a_slot)
        for (a_slot, a_time), (b_slot, b_time) in zip(ordered, ordered[1:])
    ]


def slots_to_seconds(slots, seconds_per_slot):
    """Convert a latency expressed in slots to seconds."""
    return slots * seconds_per_slot
