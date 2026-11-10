"""Timeline of one CPMM pool from its raw transactions, and the exact value of a sale on it.

``build`` orders the swaps of a pool by (slot, transaction index, order in the transaction) and
keeps, for each, the reserves BEFORE it exactly as the program logged them (base = the launched
token, quote = wrapped SOL). ``reserves_at`` gives the reserves once every swap up to a landing
point has executed: the next swap's logged reserves when one follows (exact), otherwise the
logged amounts of the last swap applied to its logged reserves. ``reproduce`` recomputes every
observed swap from its logged reserves and the pool's fee rates and reports each difference
(criterion A-12).

Fee rates: ``infer_fees`` reads them causally from the fees the program logged (current layout),
as the largest rates compatible with every exact-input swap seen (the conservative choice, the
rule of the frozen ``causal_fee_rate``). The protocol and fund shares of the trade fee are not in
the events (they leave the reserve of the input token): pass them from the pool's AmmConfig
account; without them the last swap's input-side reserve is known within its trade fee, and
``sell_value`` keeps the bound that is worse for the seller.
"""
from dataclasses import dataclass

from cpmmx import curve
from cpmmx.events import LpChangeEvent, SwapEvent, transaction_events

WSOL = 'So11111111111111111111111111111111111111112'


class TimelineError(ValueError):
    pass


@dataclass(frozen=True)
class Swap:
    signature: str
    slot: int
    block_time: int
    tx_index: int
    order: int                 # position among the pool's events of its transaction
    side: str                  # 'buy' (quote in, base out) or 'sell' (base in, quote out)
    base_before: int
    quote_before: int
    event: SwapEvent

    @property
    def key(self):
        return self.slot, self.tx_index, self.order


@dataclass(frozen=True)
class Timeline:
    pool: str
    base_mint: str
    quote_mint: str
    swaps: tuple
    lp_changes: tuple          # (slot, tx_index, order, LpChangeEvent)
    skipped: tuple             # (signature, reason): transactions that could not be decoded
    opened: tuple = None       # (slot, block_time) of the pool's creation, given by the caller


def _position(tx):
    slot, index, when = tx.get('slot'), tx.get('transactionIndex'), tx.get('blockTime')
    if type(slot) is not int or type(index) is not int or type(when) is not int:
        raise TimelineError('transaction_slot_index_or_block_time_missing')
    return slot, index, when


def build(pool, transactions, *, base_mint, quote_mint=WSOL, opened=None):
    """Timeline of ``pool`` from ``{signature: raw transaction}``; undecodable transactions are listed, not guessed.

    ``opened``: (slot, block_time) of the transaction that created the pool, when the caller has it;
    it only lets ``reserves_at`` answer between the creation and the first swap.
    """
    if opened is not None and (len(opened) != 2 or any(type(v) is not int for v in opened)):
        raise TimelineError('invalid_opened')
    swaps, lps, skipped = [], [], []
    for signature, tx in transactions.items():
        slot, index, when = _position(tx)
        try:
            events = transaction_events(tx, pool)
        except ValueError as exc:
            skipped.append((signature, str(exc)))
            continue
        for order, event in enumerate(events):
            if isinstance(event, LpChangeEvent):
                lps.append((slot, index, order, event))
                continue
            if event.layout != 'current':
                skipped.append((signature, 'legacy_swap_event_without_mints'))
                break
            if (event.input_mint, event.output_mint) == (quote_mint, base_mint):
                side, base, quote = 'buy', event.output_vault_before, event.input_vault_before
            elif (event.input_mint, event.output_mint) == (base_mint, quote_mint):
                side, base, quote = 'sell', event.input_vault_before, event.output_vault_before
            else:
                raise TimelineError('pool_mints_differ:%s' % signature)
            swaps.append(Swap(signature, slot, when, index, order, side, base, quote, event))
    swaps.sort(key=lambda swap: swap.key)
    if opened is not None and swaps and swaps[0].slot < opened[0]:
        raise TimelineError('swap_before_the_pool_creation')
    return Timeline(pool, base_mint, quote_mint, tuple(swaps), tuple(sorted(lps, key=lambda row: row[:3])),
                    tuple(sorted(skipped)), None if opened is None else tuple(opened))


def _interval(fee, basis):
    """Integer rates r with ceil(basis * r / D) == fee, as (low, high); None when uninformative."""
    if basis <= 0 or fee <= 0:
        return None
    low = ((fee - 1) * curve.FEE_DENOMINATOR) // basis + 1
    high = min((fee * curve.FEE_DENOMINATOR) // basis, curve.FEE_DENOMINATOR - 1)
    return (low, high) if low <= high else None


def infer_fees(swaps, side, *, protocol_fee_rate=0, fund_fee_rate=0):
    """(Fees, creator_fee_on_input, evidence) for ``side`` from the exact-input swaps given (pass a causal prefix).

    The trade rate (and the creator rate) is the largest one every swap allows. With the creator
    fee on the input, the program logs only the split of one combined fee: the combined rate is
    inferred the same way and the creator share is the largest one consistent with every split.
    """
    rows = [s.event for s in swaps if s.side == side and s.event.base_input]
    if not rows:
        raise TimelineError('no_exact_input_swap_to_read_fees_from:%s' % side)
    flags = {e.creator_fee_on_input for e in rows}
    if len(flags) != 1:
        raise TimelineError('creator_fee_side_changed')
    on_input = flags.pop()
    low = high = None
    used = 0

    def meet(interval):
        nonlocal low, high, used
        if interval is None:
            return
        new_low = interval[0] if low is None else max(low, interval[0])
        new_high = interval[1] if high is None else min(high, interval[1])
        if new_low > new_high:
            raise TimelineError('fee_rate_changed_within_the_swaps')
        low, high, used = new_low, new_high, used + 1

    if on_input:
        for e in rows:
            meet(_interval(e.trade_fee + e.creator_fee, e.input_amount))
        if high is None:
            raise TimelineError('no_fee_bearing_swap')
        total = high
        # floor(fee * c / total) == creator_fee  <=>  c in [ceil(k*total/fee), ceil((k+1)*total/fee) - 1]
        c_low, c_high = 0, total
        for e in rows:
            fee = e.trade_fee + e.creator_fee
            if fee <= 0:
                continue
            c_low = max(c_low, -(-e.creator_fee * total // fee))
            c_high = min(c_high, -(-(e.creator_fee + 1) * total // fee) - 1)
        if c_low > c_high:
            raise TimelineError('creator_fee_split_not_explained')
        creator = c_high if any(e.creator_fee for e in rows) else 0
        fees = curve.Fees(total - creator, creator, protocol_fee_rate, fund_fee_rate)
        return fees, True, dict(combined_rate_interval=[low, high], swaps_used=used,
                                creator_rate_interval=[c_low, c_high])
    for e in rows:
        meet(_interval(e.trade_fee, e.input_amount))
    if high is None:
        raise TimelineError('no_fee_bearing_swap')
    trade, trade_interval, trade_used = high, [low, high], used
    low = high = None
    used = 0
    for e in rows:
        meet(_interval(e.creator_fee, e.output_amount + e.creator_fee))
    creator = high if high is not None else 0
    fees = curve.Fees(trade, creator, protocol_fee_rate, fund_fee_rate)
    return fees, False, dict(trade_rate_interval=trade_interval, swaps_used=trade_used,
                             creator_rate_interval=None if high is None else [low, high])


def recompute(swap, fees, on_input):
    """The program's arithmetic applied to the logged reserves and the trader's exact amount."""
    e = swap.event
    if e.base_input:
        return curve.swap_base_input(e.input_amount, e.input_vault_before, e.output_vault_before, fees, on_input)
    return curve.swap_base_output(e.output_amount, e.input_vault_before, e.output_vault_before, fees, on_input)


def reproduce(timeline, fees_by_side):
    """A-12: every observed swap recomputed; returns counts and each difference, explained field by field.

    ``fees_by_side``: {'buy': (Fees, on_input), 'sell': (Fees, on_input)}.
    """
    differences = []
    for index, swap in enumerate(timeline.swaps):
        fees, on_input = fees_by_side[swap.side]
        e = swap.event
        try:
            got = recompute(swap, fees, on_input)
        except curve.CurveError as exc:
            differences.append(dict(index=index, signature=swap.signature, error=str(exc)))
            continue
        fields = dict(input_amount=(got.input_amount, e.input_amount), output_amount=(got.output_amount, e.output_amount),
                      trade_fee=(got.trade_fee, e.trade_fee), creator_fee=(got.creator_fee, e.creator_fee))
        wrong = {name: dict(recomputed=a, observed=b) for name, (a, b) in fields.items() if a != b}
        if wrong:
            differences.append(dict(index=index, signature=swap.signature, base_input=e.base_input, fields=wrong))
    total = len(timeline.swaps)
    return dict(swaps=total, exact=total - len(differences), differences=differences,
                share_exact=None if not total else (total - len(differences)) / total,
                skipped_transactions=len(timeline.skipped), lp_changes=len(timeline.lp_changes))


def after_swap(swap, protocol_fee_rate=0, fund_fee_rate=0):
    """(base, quote) reserves once ``swap`` is applied, from the amounts and fees the program logged."""
    e = swap.event
    skim = (e.trade_fee * protocol_fee_rate // curve.FEE_DENOMINATOR
            + e.trade_fee * fund_fee_rate // curve.FEE_DENOMINATOR)
    new_in = e.input_vault_before + e.input_amount - skim - (e.creator_fee if e.creator_fee_on_input else 0)
    new_out = e.output_vault_before - e.output_amount - (0 if e.creator_fee_on_input else e.creator_fee)
    return (new_out, new_in) if swap.side == 'buy' else (new_in, new_out)


def _lp_between(timeline, low, high):
    return any((low is None or low < row[:3]) and row[:3] < high for row in timeline.lp_changes)


def continuity(timeline, protocol_fee_rate=0, fund_fee_rate=0):
    """Indices k where the reserves after swap k differ from those logged before swap k+1.

    With the pool's true protocol and fund rates the equality is exact (a swap missing from the
    collection shows here). ``skim`` is what left the input-side reserve beyond the logged amounts:
    with rates 0 it is the protocol + fund fee the program took on swap k, to compare with AmmConfig.
    """
    breaks = []
    for k in range(len(timeline.swaps) - 1):
        a, b = timeline.swaps[k], timeline.swaps[k + 1]
        after = after_swap(a, protocol_fee_rate, fund_fee_rate)
        if after != (b.base_before, b.quote_before):
            column = 1 if a.side == 'buy' else 0                 # the input side of swap k
            only_input = after[1 - column] == (b.base_before, b.quote_before)[1 - column]
            breaks.append(dict(index=k, expected=list(after), logged=[b.base_before, b.quote_before],
                               skim=after[column] - (b.base_before, b.quote_before)[column] if only_input else None,
                               trade_fee=a.event.trade_fee,
                               reason='lp_change_between' if _lp_between(timeline, a.key, b.key)
                               else 'reserves_discontinuity'))
    return breaks


def executed(timeline, *, slot_limit=None, time_limit=None):
    """Swaps that have executed at the landing point (exactly one limit; see ``reserves_at``)."""
    if (slot_limit is None) == (time_limit is None):
        raise TimelineError('exactly_one_landing_limit')
    if slot_limit is not None:
        return [s for s in timeline.swaps if s.slot <= slot_limit]
    return [s for s in timeline.swaps if s.block_time <= time_limit]


def reserves_at(timeline, *, slot_limit=None, time_limit=None, protocol_fee_rate=None, fund_fee_rate=None):
    """(base, quote, evidence) once every swap up to the landing point has executed.

    Exactly one of ``slot_limit`` (swaps with slot <= it have executed: an event-driven order with
    latency) and ``time_limit`` (block_time <= it: a clock order). Sources, by preference:
      next_swap_logged_reserves   what the program logged before the following swap (exact);
      first_swap_logged_reserves  between the pool's creation (``opened``) and its first swap (exact);
      logged_amounts_of_last_swap no swap follows: exact with the AmmConfig shares, otherwise the
                                  input-side reserve of the last swap is overstated by at most its
                                  trade fee (``input_side_overstated_by_at_most``).
    An LP change after the last executed swap is never bridged by a later swap's reserves.
    """
    done = executed(timeline, slot_limit=slot_limit, time_limit=time_limit)
    if (protocol_fee_rate is None) != (fund_fee_rate is None):
        raise TimelineError('protocol_and_fund_rates_go_together')
    if not done:
        opened = timeline.opened
        reached = opened is not None and (opened[0] <= slot_limit if slot_limit is not None else opened[1] <= time_limit)
        if not reached or not timeline.swaps:
            raise TimelineError('no_pool_state_at_the_landing_point')
        first = timeline.swaps[0]
        if _lp_between(timeline, None, first.key):
            raise TimelineError('lp_change_before_the_first_swap')
        return first.base_before, first.quote_before, dict(source='first_swap_logged_reserves', last_index=-1)
    last, index = done[-1], len(done) - 1
    lp_follows = False
    if index + 1 < len(timeline.swaps):
        nxt = timeline.swaps[index + 1]
        lp_follows = _lp_between(timeline, last.key, nxt.key)
        if not lp_follows:
            return nxt.base_before, nxt.quote_before, dict(source='next_swap_logged_reserves', last_index=index)
    else:
        lp_follows = any(last.key < row[:3] for row in timeline.lp_changes)
    known = protocol_fee_rate is not None
    base, quote = after_swap(last, protocol_fee_rate or 0, fund_fee_rate or 0)
    return base, quote, dict(source='logged_amounts_of_last_swap', last_index=index, lp_change_follows=lp_follows,
                             last_side=last.side, input_side_overstated_by_at_most=0 if known else last.event.trade_fee)


def sell_value(timeline, tokens, fees, on_input, *, slot_limit=None, time_limit=None, protocol_fee_rate=None,
               fund_fee_rate=None):
    """Exact quote (lamports of wrapped SOL) received for selling ``tokens`` at the landing point, fees deducted.

    When the AmmConfig shares are unknown and no later swap fixes the reserves, the bound that is
    worse for the seller is used (after a buy: the quote reserve minus that buy's trade fee; after
    a sale the base reserve is already the highest possible).
    """
    base, quote, evidence = reserves_at(timeline, slot_limit=slot_limit, time_limit=time_limit,
                                        protocol_fee_rate=protocol_fee_rate, fund_fee_rate=fund_fee_rate)
    slack = evidence.get('input_side_overstated_by_at_most', 0)
    if slack and evidence['last_side'] == 'buy':
        quote -= slack
    result = curve.swap_base_input(tokens, base, quote, fees, on_input)
    return result.output_amount, dict(evidence, base_reserve=base, quote_reserve=quote, trade_fee=result.trade_fee,
                                      creator_fee=result.creator_fee, creator_fee_on_input=on_input,
                                      trade_fee_rate=fees.trade_fee_rate, creator_fee_rate=fees.creator_fee_rate)
