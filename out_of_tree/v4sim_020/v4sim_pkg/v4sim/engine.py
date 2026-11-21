"""v4sim replay engine (protocol V4 v2). Same interface and same conventions as the frozen
``bot.market.replay.replay``; in mode ``M-L`` with default execution options it reproduces it exactly.

What changes in the other modes (M-P principal, M-C capped, M-A behavioural stress):
  * section 2: the other holders' trades are replayed through per-actor ledgers (``v4sim.ledger``);
  * section 3: marks and sales use the computed liquidation value (``v4sim.valuation``);
  * section 4.3: a position open at the (counterfactual) migration stays ``migrated_unpriced`` and
    only carries a descriptive ``last_curve_value``.
Execution options (section 5), off by default: slippage tolerance, non-inclusion draws, retries,
maximum share of the curve, order inside the landing slot.
"""
import hashlib
from dataclasses import dataclass

from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import ExecutionModel, Position, TradeResult, _event_rate, causal_fee_rate

from v4sim.ledger import MODES, CounterfactualMigration, Others
from v4sim.valuation import PARTIAL, liquidation

TOKEN_ACCOUNT_RENT_LAMPORTS = 2_039_280        # not recovered when tokens are left in the account
NON_INCLUSION_RULES = ('base_fee', 'zero')     # 'zero' needs the archived official reference (C-1)


@dataclass(frozen=True)
class Execution:
    slippage_bps: int = None                   # None: no limit
    p_fail: float = 0.0                        # probability that an order is not included
    salt: str = 'v4'
    max_retries: int = 0
    max_curve_share_bps: int = None            # refuse an entry above this share of the remaining supply
    slot_order: str = 'after'                  # our order lands after ('after') or before the landing slot's real trades
    non_inclusion_fee: str = 'base_fee'        # prudent hypothesis until the official reference is archived
    fee_reference: dict = None                 # {url, read_at, sha256}: required by non_inclusion_fee='zero'

    def __post_init__(self):
        if self.slot_order not in ('after', 'before') or self.non_inclusion_fee not in NON_INCLUSION_RULES:
            raise ValueError('invalid_execution_options')
        if self.non_inclusion_fee == 'zero' and not (self.fee_reference or {}).get('sha256'):
            raise ValueError('zero_fee_on_non_inclusion_needs_the_archived_official_reference')
        if not 0 <= self.p_fail < 1 or type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError('invalid_execution_options')


def not_included(execution, pool, side, decision_index, attempt):
    """Deterministic pseudo-random draw: sha256(salt, pool, side, decision index, attempt) < p_fail."""
    if not execution.p_fail:
        return False
    digest = hashlib.sha256(f'{execution.salt}|{pool}|{side}|{decision_index}|{attempt}'.encode()).hexdigest()
    return int(digest[:16], 16) / 2 ** 64 < execution.p_fail


def landing_index(events, start, slot_limit, slot_order='after'):
    """Index of the last real event that executes before our order (frozen rule when 'after')."""
    limit = slot_limit if slot_order == 'after' else slot_limit - 1
    index = start
    while index + 1 < len(events) and events[index + 1].slot <= limit:
        index += 1
    return index


def _minimum(reference, slippage_bps):
    return -(-reference * (10_000 - slippage_bps) // 10_000)


TRACKED_CLIPPED = 'tracked_sale_clipped'      # D-2: such a position counts in the 5 % guard of section 3


def replay(timeline, strategy, model=ExecutionModel(), *, quote_mint, mode='M-P', execution=Execution(),
           actors=None):
    """Run ``strategy`` once (single entry, full exit) on a complete timeline; return a ``TradeResult``
    carrying a ``v4`` dict (mode, flags, counters, failed attempts)."""
    result = _replay(timeline, strategy, model, quote_mint=quote_mint, mode=mode, execution=execution, actors=actors)
    counters = result.v4['counters']
    if mode != 'M-L' and counters and (counters['tracked_sale_clipped_external']
                                       or counters['tracked_sale_clipped_quote_reserve']):
        result.v4['flags'] = list(result.v4['flags']) + [TRACKED_CLIPPED]
    return result


def _replay(timeline, strategy, model, *, quote_mint, mode, execution, actors):
    if quote_mint != WSOL_MINT:
        raise ValueError('quote_not_sol_cannot_be_priced_in_sol')
    if mode not in MODES:
        raise ValueError('unknown_mode')
    events = timeline.events
    result = TradeResult(timeline.pool, 'no_entry')
    info = result.v4 = dict(mode=mode, flags=[], failed_attempts=[], counters=None, last_curve_value=None,
                            sold_tokens=None, non_inclusion_fee=execution.non_inclusion_fee)
    if not events:
        return result
    if not timeline.complete:
        raise ValueError('timeline_incomplete')
    legacy = mode == 'M-L'
    lost = model.base_fee_lamports if execution.non_inclusion_fee == 'base_fee' else 0

    def failed(side, decision, attempt, kind, cost):
        info['failed_attempts'].append(dict(side=side, decision_index=decision, attempt=attempt, kind=kind, cost=cost))
        result.tx_costs += cost

    # --- entry -----------------------------------------------------------------------------------
    k = 0
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
    decision, attempt = k, 0
    while True:
        land = landing_index(events, decision, events[decision].slot + model.latency_slots, execution.slot_order)
        expected = None
        if execution.slippage_bps is not None or execution.max_curve_share_bps is not None:
            try:
                expected = buy_exact_in(events[decision].state_after(), amount, rate).amount_out
            except CurveError:
                expected = None
        if (execution.max_curve_share_bps is not None and expected is not None and expected * 10_000
                > execution.max_curve_share_bps * events[decision].state_after().remaining_base):
            result.notes.append('entry_refused:max_curve_share')        # decided before sending: no cost
            return result
        if not_included(execution, timeline.pool, 'buy', decision, attempt):
            failed('buy', decision, attempt, 'not_included', lost)
        else:
            state = events[land].state_after()
            try:
                fill = buy_exact_in(state, amount, rate)
            except CurveError as exc:
                result.outcome = 'no_entry'
                result.notes.append(f'entry_refused:{exc}')
                return result
            if (execution.slippage_bps is not None and expected is not None
                    and fill.amount_out < _minimum(expected, execution.slippage_bps)):
                failed('buy', decision, attempt, 'slippage', model.tx_cost)
            else:
                break
        attempt += 1
        if attempt > execution.max_retries:
            result.notes.append('entry_failed')
            return result
        decision = land
    others = Others(mode, events, actors)
    if not legacy:
        for event in events[:land + 1]:
            others.observe(event)
    position = Position(land, events[land].slot, events[land].block_time, amount, fill.amount_out)
    result.entry_index, result.spent, result.tokens = land, amount, fill.amount_out
    result.tx_costs += model.tx_cost
    state = fill.after
    if not legacy:
        others.enter(fill.amount_out)
        others.check(state)
    info['counters'] = others.counters

    def value(current):
        if legacy:
            try:
                return sell_exact_in(current, position.tokens, rate).amount_out
            except CurveError:
                return 0
        return liquidation(current, position.tokens, rate)[0]

    def close(current, last_index):
        """Sell everything now. Return True when the result is final (closed or legacy divergence)."""
        if legacy:
            try:
                received = sell_exact_in(current, position.tokens, rate).amount_out
            except CurveError as exc:
                result.outcome = 'counterfactual_divergence'
                result.notes.append(f'exit_refused:{exc}')
                return None
            sold, flags = position.tokens, ()
        else:
            received, sold, flags, _after = liquidation(current, position.tokens, rate)
        result.outcome, result.exit_index = 'closed', last_index
        result.received = received
        result.tx_costs += model.tx_cost
        result.hold_slots = events[last_index].slot - position.entry_slot
        info['flags'], info['sold_tokens'] = list(flags), sold
        if PARTIAL in flags and sold < position.tokens:
            result.tx_costs += TOKEN_ACCOUNT_RENT_LAMPORTS       # tokens left: the account cannot be closed
            result.notes.append('token_account_rent_not_recovered')
        return True

    def attempt_exit(current, last_index, trigger_index, reference, number):
        """One exit attempt with the execution options; 'done', 'retry' or 'blocked'."""
        if not_included(execution, timeline.pool, 'sell', trigger_index, number):
            failed('sell', trigger_index, number, 'not_included', lost)
        elif (execution.slippage_bps is not None and reference
              and value(current) < _minimum(reference, execution.slippage_bps)):
            failed('sell', trigger_index, number, 'slippage', model.tx_cost)
        else:
            close(current, last_index)
            return 'done'
        return 'retry' if number < execution.max_retries else 'blocked'

    # --- holding: replay later real trades on the counterfactual curve ---------------------------
    j = land + 1
    pending_exit_slot, trigger_index, reference, attempts = None, None, None, 0
    clock_extra, blocked = 0, False
    last_mark = value(state) if execution.slippage_bps is not None else None   # reference of a clock exit
    while True:
        if pending_exit_slot is not None and (j >= len(events) or events[j].slot > pending_exit_slot):
            status = attempt_exit(state, j - 1, trigger_index, reference, attempts)
            if status == 'done':
                if result.outcome == 'closed':
                    result.exit_landing_slot = pending_exit_slot
                return result
            attempts += 1
            pending_exit_slot = None if status == 'blocked' else events[j - 1].slot + model.latency_slots
            blocked = status == 'blocked'
            if j >= len(events) and not blocked:
                continue
        if pending_exit_slot is None and not blocked and model.clock_exit_latency_s is not None:
            deadline_of = getattr(strategy, 'exit_deadline', None)
            deadline = deadline_of(position) if deadline_of is not None else None
            landing = None if deadline is None else deadline + model.clock_exit_latency_s + clock_extra
            if landing is not None and (j >= len(events) or events[j].block_time > landing):
                status = attempt_exit(state, j - 1, j - 1, last_mark, attempts)
                if status == 'done':
                    if result.outcome == 'closed':
                        result.notes.append('clock_exit')
                        result.clock_exit = dict(deadline=deadline, landing_time=landing, last_index=j - 1)
                    return result
                attempts += 1
                blocked = status == 'blocked'
                clock_extra += model.clock_exit_latency_s or 1
                if j >= len(events) and not blocked:
                    continue
        if j >= len(events):
            break
        before = state
        try:
            state = others.replay(state, events[j])
        except CounterfactualMigration:
            result.outcome = 'migrated_unpriced'
            result.notes.append(f'replay_stopped_at:{j}:buy_crosses_migration_boundary')
            info['last_curve_value'] = value(before)
            return result
        except CurveError as exc:                      # only the frozen mode can get here
            reason = str(exc)
            result.outcome = ('migrated_unpriced' if reason == 'buy_crosses_migration_boundary'
                              else 'counterfactual_divergence')
            result.notes.append(f'replay_stopped_at:{j}:{reason}')
            return result
        if state.remaining_base == 0:
            result.outcome = 'migrated_unpriced'
            if not legacy:
                info['last_curve_value'] = value(state)
            return result
        if pending_exit_slot is None and not blocked:
            mark = last_mark = value(state)
            if strategy.exit(events[:j + 1], position, mark):
                pending_exit_slot, trigger_index, reference = events[j].slot + model.latency_slots, j, mark
        j += 1
    # End of observed data with the position still open: mark to the liquidation value.
    if legacy:
        try:
            result.received = sell_exact_in(state, position.tokens, rate).amount_out
        except CurveError as exc:
            result.outcome = 'counterfactual_divergence'
            result.notes.append(f'mark_refused:{exc}')
            return result
    else:
        result.received, info['sold_tokens'], flags, _after = liquidation(state, position.tokens, rate)
        info['flags'] = list(flags)
    if blocked:
        info['flags'].append('exit_retries_exhausted')
    result.outcome = 'open_at_end'
    result.tx_costs += model.tx_cost
    result.exit_index = len(events) - 1
    result.hold_slots = events[-1].slot - position.entry_slot
    return result


def identity_replay(timeline, mode, actors=None):
    """I-3 / A-1: with no order of ours, replay every real event through the ledgers and compare the
    counterfactual state with ``event.state_after()`` field by field. Return the number of events."""
    events = timeline.events
    if not events:
        return 0
    others = Others(mode, events, actors)
    others.enter(0)
    state = events[0].state_before()
    for index, event in enumerate(events):
        state = others.replay(state, event)
        if state != event.state_after():
            raise AssertionError(f'identity_replay_differs:{timeline.pool}:{index}:{mode}')
    return len(events)
