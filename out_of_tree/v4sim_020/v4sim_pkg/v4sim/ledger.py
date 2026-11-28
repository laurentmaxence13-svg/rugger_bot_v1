"""Causal replay of the other holders' trades on the counterfactual curve (protocol V4 v2, section 2).

Per-actor token ledgers in the real world (R) and in the counterfactual world (C). Before our entry
R = C. After it, every real event is replayed on the counterfactual state:
  * buy  : same quote budget (the real ``amount_in``), tokens from the exact curve;
  * sell : M-P  the same FRACTION of the actor's ledger (phi = covered_R / bal_R);
           M-C  the real amount, capped by the actor's counterfactual ledger;
           M-A  as M-P, but the actor's first sale after our entry sells 100 % of its ledger;
           M-L  the frozen engine: the real token amount, unchanged (no ledger).
Tokens sold beyond an actor's real ledger are EXTERNAL inventory: sold as they are.
Invariants are checked after every event; a violation is an error, never a result.
"""
from bot.market.launchlab_curve import CurveError, buy_exact_in, sell_exact_in
from bot.market.replay import _event_rate

from v4sim.valuation import max_sellable

MODES = ('M-P', 'M-C', 'M-L', 'M-A')
DUST_REASONS = ('output_rounds_to_zero', 'input_consumed_by_fee')


class InvariantError(RuntimeError):
    """I-1, I-2 or I-4 violated: a defect of the simulator or of its input, never a result."""


class CounterfactualMigration(Exception):
    """A replayed buy crosses the migration boundary of the counterfactual curve."""


class Others:
    """Ledgers of the other holders and the replay of their trades on the counterfactual state."""

    def __init__(self, mode, events, actors=None):
        if mode not in MODES:
            raise ValueError('unknown_mode')
        self.mode, self.actors = mode, actors or {}
        self.real, self.cf = {}, {}                    # actor -> tokens, worlds R and C
        self.sum_real, self.sum_cf = 0, 0
        # Tokens in circulation that no ledger explains: outstanding before the first event (negative
        # contribution) and external inventory sold to the curve (positive). I-1 uses the net figure.
        self.external_real = self.external_cf = -(events[0].real_base_before if events else 0)
        self.ours, self.entered, self.stress = 0, False, False
        self.sold_after_entry = set()                  # M-A: actors that already sold after our entry
        self.counters = dict(skipped_dust_events=0, skipped_zero_sales=0, external_sale_clipped=0,
                             tracked_sale_clipped_external=0, tracked_sale_clipped_quote_reserve=0,
                             external_real_minus_cf=0, exact_out_replayed_as_budget=0,
                             external_tokens_sold=0, tokens_sold_after_entry=0, events_replayed=0)

    def actor(self, event):
        return self.actors.get(event.key, event.fee_payer)

    # ---- world R (also world C before our entry) ------------------------------------------------
    def observe(self, event):
        """Record a real event in the real ledger; return (actor, covered, external) for a sell."""
        actor = self.actor(event)
        balance = self.real.get(actor, 0)
        if event.side == 'buy':
            self.real[actor] = balance + event.amount_out
            self.sum_real += event.amount_out
            covered = external = 0
        else:
            covered = min(event.amount_in, balance)
            external = event.amount_in - covered
            self.real[actor] = balance - covered
            self.sum_real -= covered
            self.external_real += external
        if self.sum_real - self.external_real != event.real_base_after:
            raise InvariantError('I-1_real_ledger_differs_from_real_base')
        if not self.entered:                           # R = C until we enter
            self.cf[actor] = self.real[actor]
            self.sum_cf, self.external_cf = self.sum_real, self.external_real
        return actor, balance, covered, external

    def enter(self, tokens):
        """Our entry: worlds R and C separate. The M-A stress only starts with a real order of ours."""
        self.ours, self.entered, self.stress = tokens, True, tokens > 0

    def leave(self, tokens):
        self.ours -= tokens

    def check(self, state):
        if self.sum_cf + self.ours - self.external_cf != state.real_base:
            raise InvariantError('I-1_counterfactual_ledger_differs_from_real_base')
        if state.real_quote < 0 or not 0 <= state.real_base <= state.total_base_sell:
            raise InvariantError('I-2_invalid_counterfactual_state')

    # ---- world C after our entry ----------------------------------------------------------------
    def replay(self, state, event):
        """Replay one real event on the counterfactual ``state``; return the new state."""
        rate = _event_rate(event)
        if self.mode == 'M-L':                         # frozen behaviour, errors included
            if event.side == 'buy':
                return buy_exact_in(state, event.amount_in, rate).after
            return sell_exact_in(state, event.amount_in, rate).after
        actor, balance_real, covered, external = self.observe(event)
        self.counters['events_replayed'] += 1
        if event.side == 'buy':
            if not event.exact_in:
                self.counters['exact_out_replayed_as_budget'] += 1
            try:
                fill = buy_exact_in(state, event.amount_in, rate)
            except CurveError as exc:
                if str(exc) == 'buy_crosses_migration_boundary':
                    raise CounterfactualMigration() from None
                if str(exc) in DUST_REASONS:
                    self.counters['skipped_dust_events'] += 1
                    return state
                raise
            self.cf[actor] = self.cf.get(actor, 0) + fill.amount_out
            self.sum_cf += fill.amount_out
            self.check(fill.after)
            return fill.after
        held = self.cf.get(actor, 0)
        if self.mode == 'M-C':
            tracked = min(covered, held)
        elif self.mode == 'M-A' and self.stress and actor not in self.sold_after_entry:
            tracked = held
        else:                                          # M-P: the same fraction of the ledger
            tracked = held if covered == balance_real else covered * held // balance_real if balance_real else 0
        self.sold_after_entry.add(actor)
        if tracked > held:
            raise InvariantError('I-2_sale_larger_than_the_actor_ledger')
        wanted = tracked + external
        if wanted == 0:
            self.counters['skipped_zero_sales'] += 1
            return state
        sold = wanted
        try:
            fill = sell_exact_in(state, sold, rate)
        except CurveError as exc:
            reason = str(exc)
            if reason in DUST_REASONS:
                self.counters['skipped_dust_events'] += 1
                return state
            if reason not in ('sell_exceeds_curve_inventory', 'sell_exceeds_quote_reserve'):
                raise
            if external == 0 and self.external_cf <= 0 and reason == 'sell_exceeds_curve_inventory':
                raise InvariantError('I-4_tracked_sale_exceeds_curve_inventory') from None
            sold = max_sellable(state, wanted)
            self.counters['external_sale_clipped' if external else 'tracked_sale_clipped_quote_reserve'
                          if reason == 'sell_exceeds_quote_reserve' else 'tracked_sale_clipped_external'] += 1
            if sold == 0:
                return state
            try:
                fill = sell_exact_in(state, sold, rate)
            except CurveError as inner:
                if str(inner) in DUST_REASONS:
                    self.counters['skipped_dust_events'] += 1
                    return state
                raise
        tracked_sold = min(tracked, sold)              # the ledger part is served first
        external_sold = sold - tracked_sold
        self.cf[actor] = held - tracked_sold
        self.sum_cf -= tracked_sold
        self.external_cf += external_sold
        self.counters['external_tokens_sold'] += external_sold
        self.counters['tokens_sold_after_entry'] += sold
        self.counters['external_real_minus_cf'] = self.external_real - self.external_cf     # D-1: E_R - E_C
        self.check(fill.after)
        return fill.after
