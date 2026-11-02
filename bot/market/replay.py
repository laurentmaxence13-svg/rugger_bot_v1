"""Causal replay of a strategy on one complete LaunchLab pool timeline.

Execution model (every assumption is explicit and reported):

* **Causality** -- at real event ``k`` the strategy receives only
  ``events[:k+1]``; it cannot read later events.
* **Latency** -- an order decided at slot ``s`` lands after every real event
  with slot ``<= s + latency_slots`` (others' transactions in those slots win).
* **Exact fills** -- integer curve arithmetic from :mod:`launchlab_curve` with
  ``fee_rate_ppm`` for our own orders.
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

from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT, implied_fee_rate_ppm

DEFAULT_FEE_RATE_PPM = 12_500
SOLANA_BASE_FEE_LAMPORTS = 5_000


@dataclass(frozen=True)
class ExecutionModel:
    latency_slots: int = 2
    fee_rate_ppm: int = DEFAULT_FEE_RATE_PPM
    base_fee_lamports: int = SOLANA_BASE_FEE_LAMPORTS
    priority_fee_lamports: int = 100_000

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
    land = _landing_index(events, k, events[k].slot + model.latency_slots)
    state = events[land].state_after()
    try:
        fill = buy_exact_in(state, amount, model.fee_rate_ppm)
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
                sale = sell_exact_in(state, position.tokens, model.fee_rate_ppm)
            except CurveError as exc:
                result.outcome = 'counterfactual_divergence'
                result.notes.append(f'exit_refused:{exc}')
                return result
            result.outcome, result.exit_index = 'closed', j - 1
            result.received = sale.amount_out
            result.tx_costs += model.tx_cost
            result.hold_slots = events[j - 1].slot - position.entry_slot
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
                mark = sell_exact_in(state, position.tokens, model.fee_rate_ppm).amount_out
            except CurveError:
                mark = 0
            if strategy.exit(events[:j + 1], position, mark):
                pending_exit_slot = events[j].slot + model.latency_slots
        j += 1
    # End of observed data with the position still open: mark to exact quote.
    try:
        result.received = sell_exact_in(state, position.tokens, model.fee_rate_ppm).amount_out
    except CurveError as exc:
        result.outcome = 'counterfactual_divergence'
        result.notes.append(f'mark_refused:{exc}')
        return result
    result.outcome = 'open_at_end'
    result.tx_costs += model.tx_cost
    result.exit_index = len(events) - 1
    result.hold_slots = events[-1].slot - position.entry_slot
    return result
