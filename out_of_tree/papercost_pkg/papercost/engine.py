"""papercost 0.1 -- a NEW full-cost PAPER engine (task P3-c), the frozen code untouched (paperstream 0.4 StreamTrade is
SUBCLASSED, the frozen ``hrr.run_replay`` is called as is, with its trade engine swapped as paperstream does).
Definitions and decisions of R02 (text of 22/11 20:28Z, audit AUDIT_MODELE_COUTS_PAPER_CB_R02_v1_0.md 0167b2d1).
HISTORICAL_REPLAY only; nothing is sent or signed; NOTHING here is applied to W1 (fixtures only until R02 says so).

TRADE ENGINE (``CostedTrade``, options ``Options``):
* N-5 slippage guard (``landslip.guard``, PRIMARY 20 000 ppm, sensitivity 50 000): minimum tokens from the DECISION
  state; below it the buy fails: charged, no entry, no retry;
* H-1 at both legs: inside the landing slot the order is unknown: the buy keeps the fewer tokens and the sale the
  lower value of the states before and after the real events of that slot (the frozen engine takes the state after);
* N-3 / N-4 failures: deterministic counts per own transaction (primary 0; sensitivity 1) or a declared failure
  probability with deterministic draws (sha256 of pool, leg, index, attempt), at most 3 per leg; a failed and resent
  order lands latency slots LATER (+4 per failure), on that later state; every failure is charged;
* sale guard (sensitivity only, 50 000 ppm on the exact value at the exit decision state): a failed guarded sale is
  resent 4 slots later, at most 3 times, then sold without guard; at the end of the data a pending sale lands
  there unguarded and an open position is marked (the frozen ``_hold_end``), never guarded;
* a failed attempt (N-3 or the guard) is a transaction that did not land: its fee only; a failed BUY reverts its
  account creation (no rent) and, for the guard, there is no entry at all.
COSTS (``row_costs``, on the frozen trade rows):
* N-1 / N-2: two modes published side by side: 'rent_lost' (PRIMARY, as C-B: the token account rent 2 039 280 is
  lost) and 'closed' (closedacct 0.2: separate cleanup transaction, (failures + 1) x 105 000, rent back; after 3
  failures it stays open: rent lost + 3 fees); a migrated or unpriced position never sells: rent lost in both modes;
* N-3: failed attempts x 105 000;  N-7: WSOL wrapper rent given back in the same transaction; its extra compute is a
  DECLARED flat amount per own transaction that moves SOL (WSOL_FLAT_LAMPORTS, sensitivity 105 000 = a separate close);
* N-8: a position open at the end of the data or of the window is MARKED at its exact sale value minus the exit
  transaction and the rent of the mode, and COUNTED in the net (never excluded);
* a position the frozen replay cannot price (migrated, counterfactual divergence) is counted at ZERO value (worst);
* N-6 (MEV, Jito): not modelled offline, declared limit.
Return on the STAKE. Decomposition with a zero residual. With every option neutral (``Options.neutral()``) the bundle is
the frozen one byte for byte, and the cost mode 'frozen_assumption' gives the frozen value.
"""
import contextlib
import hashlib
from dataclasses import dataclass

from bot.market import replay as R
from bot.market.launchlab_curve import buy_exact_in, sell_exact_in
from bot.p4 import historical_research_replay as hrr
from closedacct import model as CA
from landslip import guard as G
from paperstream import engine as PS

SCHEMA = 'papercost-v0.1'
TX_FEE_LAMPORTS = 105_000                      # one own transaction of the frozen chain (5 000 + 100 000)
RENT_LAMPORTS = CA.SPL_RENT_LAMPORTS           # 2 039 280
WSOL_FLAT_LAMPORTS = 5_000                     # DECLARED: extra compute of create / sync / close WSOL in the same tx
WSOL_SEPARATE_CLOSE_LAMPORTS = 105_000         # sensitivity: the wrapper closed in a separate transaction
MAX_FAILURES = 3
MODES = ('rent_lost', 'closed')                # published; 'frozen_assumption' exists for the identity proof only
PRICED = ('closed', 'open_at_end', 'open_at_window_end')
NOTE = 'papercost:'


class CostError(ValueError):
    pass


@dataclass(frozen=True)
class Options:
    buy_guard_ppm: object = G.BUY_GUARD_PPM
    sell_guard_ppm: object = None
    h1: bool = True
    buy_failures: int = 0
    sell_failures: int = 0
    fail_ppm: int = 0

    def __post_init__(self):
        if self.buy_guard_ppm not in G.ALLOWED_BUY_GUARDS or self.sell_guard_ppm not in G.ALLOWED_SELL_GUARDS:
            raise CostError('guard_not_a_declared_threshold')
        for name in ('buy_failures', 'sell_failures'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= MAX_FAILURES:
                raise CostError('invalid_%s' % name)
        if type(self.fail_ppm) is not int or not 0 <= self.fail_ppm < 1_000_000:
            raise CostError('invalid_fail_ppm')
        if self.fail_ppm and (self.buy_failures or self.sell_failures):
            raise CostError('counts_or_probability_not_both')
        if type(self.h1) is not bool:
            raise CostError('invalid_h1')

    @classmethod
    def primary(cls):
        return cls()

    @classmethod
    def sensitivity(cls):
        return cls(buy_guard_ppm=G.BUY_GUARD_SENSITIVITY_PPM, sell_guard_ppm=G.SELL_GUARD_SENSITIVITY_PPM,
                   buy_failures=1, sell_failures=1)

    @classmethod
    def neutral(cls):
        return cls(buy_guard_ppm=None, sell_guard_ppm=None, h1=False)

    @property
    def is_neutral(self):
        return self == Options.neutral()

    def failures(self, pool, leg, index):
        if not self.fail_ppm:
            return self.buy_failures if leg == 'buy' else self.sell_failures
        count = 0
        while count < MAX_FAILURES:
            digest = hashlib.sha256(('%s:%s:%d:%d' % (pool, leg, index, count)).encode()).hexdigest()
            if int(digest[:8], 16) % 1_000_000 >= self.fail_ppm:
                break
            count += 1
        return count


class CostedTrade(PS.StreamTrade):
    """The audited StreamTrade with the options above; every option neutral = StreamTrade itself."""

    def __init__(self, pool, strategy, model, *, quote_mint, options):
        super().__init__(pool, strategy, model, quote_mint=quote_mint)
        self.options, self.pool = options, pool
        self.failed = dict(buy=0, sell=0)
        self.guard_failed, self.sale_decision_state, self.pre_slot_state = False, None, None
        self.ending, self.resent = False, False
        self.n3_sell_left, self.guard_sell_failures = None, 0

    def _note(self):
        if not self.options.is_neutral:
            notes = [n for n in self.result.notes if not n.startswith(NOTE)]
            notes.append('%sfailed:buy=%d,sell=%d' % (NOTE, self.failed['buy'], self.failed['sell']))
            if self.guard_failed:
                notes.append(NOTE + 'buy_slippage_guard_failed')
            self.result.notes[:] = notes

    def _decide(self, k, amount):
        super()._decide(k, amount)
        self.decision_state = self.events[k].state_after()
        resent = self.options.failures(self.pool, 'buy', k)
        self.failed['buy'] = resent
        self.limit = self.events[k].slot + self.model.latency_slots * (1 + resent)
        self._note()

    def _land(self, land):
        if self.options.is_neutral:
            return super()._land(land)
        events, limit = self.events, self.limit
        candidates = [land]
        if self.options.h1:
            before = max((i for i in range(self.result.decision_index, land + 1) if events[i].slot < limit),
                         default=None)
            if before is not None and before != land:
                candidates.append(before)
        states = [events[i].state_after() for i in candidates]
        status, fill = G.buy(self.decision_state, states, self.amount, self.rate, self.options.buy_guard_ppm)
        if status == 'failed':
            self.failed['buy'] += 1
            self.guard_failed = True
            self.result.outcome = 'no_entry'
            self._note()
            self._stop()
            return False
        chosen = min(candidates, key=lambda i: buy_exact_in(events[i].state_after(), self.amount,
                                                            self.rate).amount_out)
        assert buy_exact_in(events[chosen].state_after(), self.amount, self.rate).amount_out == fill.amount_out
        return super()._land(chosen)

    def _hold(self, j):
        if self.options.is_neutral:
            return super()._hold(j)
        while True:
            pending = self.pending_exit_slot
            if (self.options.h1 and pending is not None and self.pre_slot_state is None
                    and self.events[j].slot == pending):
                self.pre_slot_state = self.state                    # before the real events of the sale slot
            self.resent = False
            out = super()._hold(j)
            if self.resent:
                continue                                            # the resent sale is checked against event j
            if pending is None and self.pending_exit_slot is not None and self.sale_decision_state is None:
                self.sale_decision_state = self.state               # the strategy decided the exit on this state
            return out

    def _resend(self, exit_index):
        base = self.pending_exit_slot if self.pending_exit_slot is not None else self.events[exit_index].slot
        self.pending_exit_slot = base + self.model.latency_slots
        self.pre_slot_state, self.resent = None, True
        self._note()
        return None

    def _sell(self, exit_index, *, clock=None):
        if self.options.is_neutral or self.ending:
            return super()._sell(exit_index, clock=clock)
        tokens = self.position.tokens
        state = self.state
        if self.options.h1 and self.pre_slot_state is not None:
            if sell_exact_in(self.pre_slot_state, tokens, self.rate).amount_out < sell_exact_in(
                    state, tokens, self.rate).amount_out:
                state = self.pre_slot_state
        if self.sale_decision_state is None:
            self.sale_decision_state = self.state                   # clock exit: the state at the first attempt
        if self.n3_sell_left is None:
            self.n3_sell_left = self.options.failures(self.pool, 'sell', exit_index)
        if self.n3_sell_left > 0:                                  # N-3 / N-4: this attempt is not included
            self.n3_sell_left -= 1
            self.failed['sell'] += 1
            return self._resend(exit_index)
        guard = self.options.sell_guard_ppm
        if guard is not None and self.guard_sell_failures < G.SELL_MAX_FAILURES:
            floor = G.minimum(sell_exact_in(self.sale_decision_state, tokens, self.rate).amount_out, guard)
            if sell_exact_in(state, tokens, self.rate).amount_out < floor:
                self.guard_sell_failures += 1
                self.failed['sell'] += 1
                return self._resend(exit_index)
        self.state = state
        self._note()
        return super()._sell(exit_index, clock=clock)

    def finish(self):
        self.ending = True
        return super().finish()


OPTIONS = []
PAPERSTREAM_ENGINE_SHA256 = 'e86f66b009444c0ed97af11ae89a1e965e9437674a17f5f1c3aa0027bddc9f4a'   # paperstream 0.4


def frozen_check():
    from pathlib import Path
    if hashlib.sha256(Path(PS.__file__).read_bytes()).hexdigest() != PAPERSTREAM_ENGINE_SHA256:
        raise CostError('paperstream_engine_is_not_the_audited_0_4')


def costed_replay(timeline, strategy, model=R.ExecutionModel(), *, quote_mint):
    """Drop-in for the frozen ``replay``: StreamTrade with the options of the enclosing ``costed_engine``."""
    if not timeline.events:
        return R.TradeResult(timeline.pool, 'no_entry')
    if not timeline.complete:
        raise ValueError('timeline_incomplete')
    trade = CostedTrade(timeline.pool, strategy, model, quote_mint=quote_mint, options=OPTIONS[-1])
    for event in timeline.events:
        if trade.phase == 'stopped':
            break
        trade.push(event)
    return trade.finish()


@contextlib.contextmanager
def costed_engine(options):
    if not isinstance(options, Options):
        raise CostError('options_required')
    frozen_check()
    original = hrr.replay
    OPTIONS.append(options)
    hrr.replay = costed_replay
    try:
        yield
    finally:
        hrr.replay = original
        OPTIONS.pop()


# -- costs on the frozen trade rows ------------------------------------------------------------------------------
def failures_of(row):
    for note in row.get('notes') or ():
        if note.startswith(NOTE + 'failed:'):
            parts = dict(item.split('=') for item in note[len(NOTE + 'failed:'):].split(','))
            return int(parts['buy']), int(parts['sell'])
    return 0, 0


def row_costs(row, mode, *, wsol=WSOL_FLAT_LAMPORTS, cleanup_failures=CA.FROZEN_FAILED_ATTEMPTS,
              stake=100_000_000):
    """Net lamports of one frozen trade row under the full costs, with its decomposition (zero residual)."""
    if mode not in MODES + ('frozen_assumption',):
        raise CostError('unknown_mode')
    if type(cleanup_failures) is not int or not 0 <= cleanup_failures <= CA.MAX_CLEANUP_ATTEMPTS:
        raise CostError('invalid_cleanup_failures')
    failed_buy, failed_sell = failures_of(row)
    guard_failed = NOTE + 'buy_slippage_guard_failed' in (row.get('notes') or ())
    outcome = row['outcome']
    if outcome == 'no_entry' and row.get('entry_index') is None:
        failed_fees = TX_FEE_LAMPORTS * failed_buy if guard_failed or failed_buy else 0
        parts = dict(sale_or_mark=0, stake=0, transactions=0, failed_attempts=-failed_fees, wsol=0, account=0)
        status = 'guard_failed' if guard_failed else 'no_entry'
        return dict(status=status, counted=bool(failed_fees), net_lamports=-failed_fees,
                    net_return=-failed_fees / stake if failed_fees else None, parts=parts)
    entered = row.get('entry_index') is not None
    if not entered:
        raise CostError('row_without_entry')
    priced = outcome in PRICED
    sold = priced                                                      # closed, or marked at its liquidation value
    own_tx = 2 if sold else 1
    received = row['received'] if priced else 0
    failed_fees = TX_FEE_LAMPORTS * (failed_buy + failed_sell) + row.get('failed_attempt_costs', 0)
    wsol_cost = 0 if mode == 'frozen_assumption' else wsol * own_tx
    if mode == 'frozen_assumption':
        account = 0
    elif mode == 'rent_lost' or not sold:
        account = RENT_LAMPORTS
    elif cleanup_failures == CA.MAX_CLEANUP_ATTEMPTS:
        account = RENT_LAMPORTS + cleanup_failures * TX_FEE_LAMPORTS
    else:
        account = (cleanup_failures + 1) * TX_FEE_LAMPORTS
    tx = row['tx_costs'] if priced else min(row['tx_costs'], TX_FEE_LAMPORTS)
    parts = dict(sale_or_mark=received, stake=-row['spent'], transactions=-tx, failed_attempts=-failed_fees,
                 wsol=-wsol_cost, account=-account)
    net = sum(parts.values())
    status = ('closed' if outcome == 'closed' else 'marked_and_counted' if priced else 'unpriced_counted_at_zero')
    return dict(status=status, counted=True, net_lamports=net, net_return=net / stake, parts=parts)


def costed_bundle_summary(bundle, mode, **kwargs):
    """Totals per arm, every counted row included (closed, marked, unpriced at zero, failed guards)."""
    out = {}
    for pool in bundle['pools']:
        for arm, trade in pool['arms'].items():
            block = out.setdefault(arm, dict(rows=0, counted=0, net_lamports=0, statuses={}))
            c = row_costs(trade, mode, **kwargs)
            block['rows'] += 1
            block['statuses'][c['status']] = block['statuses'].get(c['status'], 0) + 1
            if c['counted']:
                block['counted'] += 1
                block['net_lamports'] += c['net_lamports']
    return dict(schema=SCHEMA, mode=mode, label='HISTORICAL_REPLAY', counts_for_operational_master=False, arms=out)
