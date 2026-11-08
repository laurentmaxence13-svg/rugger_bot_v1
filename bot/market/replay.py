"""Causal replay of a strategy on one complete LaunchLab pool timeline.

Execution model (every assumption is explicit and reported):

* **Causality** -- at real event ``k`` the strategy receives only
  ``events[:k+1]``; it cannot read later events.
* **Latency** -- an order decided at slot ``s`` lands after every real event
  with slot ``<= s + latency_slots`` (others' transactions in those slots win).
* **Exact fills** -- integer curve arithmetic from :mod:`launchlab_curve` with
  ``fee_rate_ppm`` for our own orders. The rate is a per-pool input (10000,
  12500 and 18000 ppm are all observed): by default it is read from the last
  real event at the decision index, i.e. from pool state at decision time. An
  explicit ``fee_rate_ppm`` overrides it; the rate used and its source are
  recorded in ``TradeResult``. With ``fee_rate_estimator='causal_interval'`` the
  rate is instead the largest rate compatible with the rounded fee of every
  fee-bearing event of the longest consistent run of pool events ending at the
  decision (``causal_fee_rate``): one tiny event (a 1-lamport fee) no longer
  yields an implausibly low rate, and no event after the decision is read.
* **Own impact** -- after our buy, every later real trade is replayed with the
  same exact-in amount on the shifted curve (other traders' sizes unchanged).
  If a replayed trade becomes impossible the run stops as
  ``counterfactual_divergence`` instead of guessing.
* **Costs** -- per transaction: ``base_fee_lamports + priority_fee_lamports``;
  token account rent is assumed refunded by closing the account after exit.
* **Migration / end of data** -- a position still open when the curve reaches
  its migration boundary is ``migrated_unpriced`` (CPMM exit not modelled; no
  P&L is credited). A position open at the end of observed data is marked to
  the exact curve sell quote and flagged ``open_at_end``.

Only SOL-quoted pools (``quote_mint`` == WSOL) are accepted; any other quote raises,
because transaction costs are lamports and quote units are lamports only for SOL.
"""
from dataclasses import dataclass, field

from bot.market.launchlab_curve import FEE_DENOMINATOR, CurveError, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT, implied_fee_rate_ppm

SOLANA_BASE_FEE_LAMPORTS = 5_000
FEE_RATE_ESTIMATORS = ('event_at_decision', 'causal_interval')


@dataclass(frozen=True)
class ExecutionModel:
    latency_slots: int = 2
    fee_rate_ppm: int = None    # None: read the pool's rate at decision time
    base_fee_lamports: int = SOLANA_BASE_FEE_LAMPORTS
    priority_fee_lamports: int = 100_000
    fee_rate_estimator: str = 'event_at_decision'   # or 'causal_interval'
    # Research option, off by default: when set, a strategy exposing ``exit_deadline(position)``
    # sells at that deadline without waiting for a real trade; the sale lands after every real
    # event up to deadline + this many seconds (a bonding-curve sale needs no counterparty).
    clock_exit_latency_s: int = None

    def __post_init__(self):
        if self.fee_rate_estimator not in FEE_RATE_ESTIMATORS:
            raise ValueError('unknown_fee_rate_estimator')
        if self.clock_exit_latency_s is not None and (type(self.clock_exit_latency_s) is not int
                                                      or self.clock_exit_latency_s < 0):
            raise ValueError('invalid_clock_exit_latency_s')

    @property
    def tx_cost(self):
        return self.base_fee_lamports + self.priority_fee_lamports


@dataclass(frozen=True)
class Position:
    entry_index: int            # index of the real event after which we bought
    entry_slot: int
    entry_time: object
    spent: int                  # quote atomic units sent to the curve (fees included)
    tokens: int


@dataclass
class TradeResult:
    pool: str
    outcome: str                # closed | open_at_end | migrated_unpriced | counterfactual_divergence | no_entry
    decision_index: int = None
    entry_index: int = None
    exit_index: int = None
    spent: int = 0
    received: int = 0
    tx_costs: int = 0
    tokens: int = 0
    hold_slots: int = None
    notes: list = field(default_factory=list)
    fee_rate_ppm: int = None        # rate applied to our own fills
    fee_rate_source: str = None     # 'model' | 'pool_event_at_decision' | 'pool_events_causal_interval'
    fee_rate_evidence: dict = None  # interval and events used (causal_interval only)
    clock_exit: dict = None         # deadline, landing_time, last_index (clock exit only)

    @property
    def priced(self):
        return self.outcome in ('closed', 'open_at_end')

    @property
    def pnl(self):
        """Net quote P&L in atomic units, or None when it cannot be priced."""
        if not self.priced:
            return None
        return self.received - self.spent - self.tx_costs

    @property
    def net_return(self):
        pnl = self.pnl
        return None if pnl is None or not self.spent else pnl / (self.spent + self.tx_costs)


class Strategy:
    """Override ``entry`` and ``exit``; both receive causal history only."""

    def entry(self, history):
        """Return the quote atomic amount to spend now, or None."""
        raise NotImplementedError

    def exit(self, history, position, mark):
        """Return True to sell everything now. ``mark`` = exact net sell quote."""
        raise NotImplementedError


def _landing_index(events, start, slot_limit):
    """Index of the last real event that executes before our order."""
    index = start
    while index + 1 < len(events) and events[index + 1].slot <= slot_limit:
        index += 1
    return index


def _replay_real(state, event):
    rate = _event_rate(event)
    if event.side == 'buy':
        return buy_exact_in(state, event.amount_in, rate).after
    return sell_exact_in(state, event.amount_in, rate).after


def _event_rate(event):
    return implied_fee_rate_ppm({
        'side': event.side, 'amount_in': event.amount_in, 'amount_out': event.amount_out,
        'protocol_fee': event.protocol_fee, 'platform_fee': event.platform_fee,
        'creator_fee': event.creator_fee, 'share_fee': event.share_fee})


def fee_rate_interval(event):
    """Integer rates r with ceil(basis*r/D) == event fee, as (low, high); None if uninformative."""
    fees = event.protocol_fee + event.platform_fee + event.creator_fee + event.share_fee
    basis = event.amount_in if event.side == 'buy' else event.amount_out + fees
    if basis <= 0 or fees <= 0:
        return None
    low = ((fees - 1) * FEE_DENOMINATOR) // basis + 1
    high = min((fees * FEE_DENOMINATOR) // basis, FEE_DENOMINATOR - 1)
    return (low, high) if low <= high else None


def causal_fee_rate(events):
    """Fee rate for our own fill at the last of ``events`` (the decision), causally.

    Walk back from the decision and intersect the compatible-rate intervals of
    the fee-bearing events for as long as the intersection stays non-empty (the
    longest consistent run ending at the decision, so a past rate change does not
    poison it). Return its upper bound: the largest rate every one of those
    events allows, i.e. the conservative choice. Without any fee-bearing event the
    decision event's own implied rate is kept and labelled as such.
    """
    low, high, used, skipped = None, None, 0, 0
    for event in reversed(events):
        interval = fee_rate_interval(event)
        if interval is None:
            skipped += 1
            continue
        new_low = interval[0] if low is None else max(low, interval[0])
        new_high = interval[1] if high is None else min(high, interval[1])
        if new_low > new_high:
            break
        low, high, used = new_low, new_high, used + 1
    if high is None:
        return _event_rate(events[-1]), dict(rule='no_fee_bearing_event_decision_event_rate',
                                              interval_ppm=None, events_used=0, events_skipped=skipped)
    return high, dict(rule='largest_rate_compatible_with_the_longest_consistent_run_up_to_the_decision',
                      interval_ppm=[low, high], events_used=used, events_skipped=skipped)


def replay(timeline, strategy, model=ExecutionModel(), *, quote_mint):
    """Run ``strategy`` once (single entry, full exit) on a complete timeline."""
    if quote_mint != WSOL_MINT:
        raise ValueError('quote_not_sol_cannot_be_priced_in_sol')
    events = timeline.events
    result = TradeResult(timeline.pool, 'no_entry')
    if not events:
        return result
    # Full history from launch is required: a mid-curve start would let the
    # strategy mistake an old pool for a new one.
    if not timeline.complete:
        raise ValueError('timeline_incomplete')
    k = 0
    # --- entry -------------------------------------------------------------
    while k < len(events):
        amount = strategy.entry(events[:k + 1])
        if amount:
            break
        k += 1
    else:
        return result
    result.decision_index = k
    if model.fee_rate_ppm is None and model.fee_rate_estimator == 'causal_interval':
        rate, result.fee_rate_evidence = causal_fee_rate(events[:k + 1])
        result.fee_rate_source = 'pool_events_causal_interval'
    elif model.fee_rate_ppm is None:
        rate, result.fee_rate_source = _event_rate(events[k]), 'pool_event_at_decision'
    else:
        rate, result.fee_rate_source = model.fee_rate_ppm, 'model'
    result.fee_rate_ppm = rate
    land = _landing_index(events, k, events[k].slot + model.latency_slots)
    state = events[land].state_after()
    try:
        fill = buy_exact_in(state, amount, rate)
    except CurveError as exc:
        result.outcome = 'no_entry'
        result.notes.append(f'entry_refused:{exc}')
        return result
    position = Position(land, events[land].slot, events[land].block_time, amount, fill.amount_out)
    result.entry_index, result.spent, result.tokens = land, amount, fill.amount_out
    result.tx_costs = model.tx_cost
    state = fill.after
    # --- holding: replay later real trades on the shifted curve --------------
    j = land + 1
    pending_exit_slot = None
    while True:
        if pending_exit_slot is not None and (j >= len(events) or events[j].slot > pending_exit_slot):
            try:
                sale = sell_exact_in(state, position.tokens, rate)
            except CurveError as exc:
                result.outcome = 'counterfactual_divergence'
                result.notes.append(f'exit_refused:{exc}')
                return result
            result.outcome, result.exit_index = 'closed', j - 1
            result.received = sale.amount_out
            result.tx_costs += model.tx_cost
            result.hold_slots = events[j - 1].slot - position.entry_slot
            return result
        if pending_exit_slot is None and model.clock_exit_latency_s is not None:
            deadline_of = getattr(strategy, 'exit_deadline', None)
            deadline = deadline_of(position) if deadline_of is not None else None
            landing = None if deadline is None else deadline + model.clock_exit_latency_s
            if landing is not None and (j >= len(events) or events[j].block_time > landing):
                try:
                    sale = sell_exact_in(state, position.tokens, rate)
                except CurveError as exc:
                    result.outcome = 'counterfactual_divergence'
                    result.notes.append(f'exit_refused:{exc}')
                    return result
                result.outcome, result.exit_index = 'closed', j - 1
                result.received = sale.amount_out
                result.tx_costs += model.tx_cost
                result.hold_slots = events[j - 1].slot - position.entry_slot
                result.notes.append('clock_exit')
                result.clock_exit = dict(deadline=deadline, landing_time=landing, last_index=j - 1)
                return result
        if j >= len(events):
            break
        try:
            state = _replay_real(state, events[j])
        except CurveError as exc:
            reason = str(exc)
            result.outcome = ('migrated_unpriced' if reason == 'buy_crosses_migration_boundary'
                              else 'counterfactual_divergence')
            result.notes.append(f'replay_stopped_at:{j}:{reason}')
            return result
        if state.remaining_base == 0:
            result.outcome = 'migrated_unpriced'
            return result
        if pending_exit_slot is None:
            try:
                mark = sell_exact_in(state, position.tokens, rate).amount_out
            except CurveError:
                mark = 0
            if strategy.exit(events[:j + 1], position, mark):
                pending_exit_slot = events[j].slot + model.latency_slots
        j += 1
    # End of observed data with the position still open: mark to exact quote.
    try:
        result.received = sell_exact_in(state, position.tokens, rate).amount_out
    except CurveError as exc:
        result.outcome = 'counterfactual_divergence'
        result.notes.append(f'mark_refused:{exc}')
        return result
    result.outcome = 'open_at_end'
    result.tx_costs += model.tx_cost
    result.exit_index = len(events) - 1
    result.hold_slots = events[-1].slot - position.entry_slot
    return result
