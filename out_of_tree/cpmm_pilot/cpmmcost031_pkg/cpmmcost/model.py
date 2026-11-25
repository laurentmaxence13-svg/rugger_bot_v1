"""cpmmcost 0.3.1 = 0.3 + ERRATUM E-CF (R02 registry 11:51:11Z, R04-13, 25/11): the CREATOR FEE is charged only by a pool
that ENABLES it in its own PoolState (field enable_creator_fee, byte 390, cpmmpilot.layout.decode_pool), never by the
AmmConfig rate alone. fees_from_amm_config uses the AmmConfig creator rate ONLY when the config carries
pool_creator_fee_enabled = True (set from the pool's anchored state); otherwise the effective creator rate is 0.
Evidence (frozen decoder, anchored pages): no swap logs a creator fee on the 31 distinct pools observed (24 A2r pools,
87 249 pre-T0 swaps; 8 livesim pools, 38 273 pre-start swaps), and with a creator rate of 0 every swap of the 4 pilot
pools and of the 8 livesim pools is reproduced to the atomic unit.
A pool that does charge the fee and is given no flag is NOT mispriced: G-0 refuses it (swaps not reproduced).
Nothing else changes (no rule, threshold, criterion or other line).
cpmmcost 0.3 (0.2 PASS R02 + the CPMM BUY SLIPPAGE GUARD of R02 amendment A1 (c), R-0.3: minimum tokens = exact output at
the DECISION state x (1 - 20 000 ppm); a worse H-1 fill fails: charged, no entry, no retry; sensitivity 50 000 ppm; the sale
keeps no guard; a declared latency sensitivity of 10 slots, A1 (a), the sale and every resend shifted alike) -- cpmmcost 0.2 (0.1 + R02 audit of 6cd08e6: a failed attempt lands LATER, +4 slots per failure, with H-1; seed of G-1 =
the pilot FREEZE SHEET) -- the full cost model of one position of the CPMM pilot on ESTABLISHED Raydium CPMM pools (task P2-b of
docs/ops/ETAT_RUGGER_MASTER.md 62c4525; pilot note v0.2 b4c6562c, sections 2.1 to 2.5; protocol CPMM v1.2 a3a285a1).
Nothing here reads collected data, selects a pool or tunes anything: there is no CPMM data yet (C-1 not passed).

Every amount is computed on the RESERVES THE PROGRAM LOGGED (``cpmmx.timeline``) with the exact cp-swap arithmetic
(``cpmmx.curve``) and the rates READ in the pool's AmmConfig (never assumed; universe U-1: trade fee 2 500 ppm):
* FEES: trade fee (and creator fee, on the side the pool logs) of the buy and of the sale, exact;
* PRICE IMPACT: exact, from the curve on the landing state (no hand formula; ``bar`` only sizes the floor of CP-1);
* DELAYS: the buy lands LATENCY_SLOTS = 4 slots after the decision swap; the sale lands at the exit point (a slot for
  an event-driven exit, a block time for the clock exit); H-1: inside the landing slot (or second) the order of the real
  swaps is unknown, so the buy keeps the FEWER tokens and the sale the LOWER value of the states before and after them;
  X-1 (ii): the sale is also valued with our buy left in the pool, and the lower value is kept;
* FAILURES: each failed attempt of the buy, of the sale or of the cleanup is charged one transaction (105 000
  lamports, the conservative fee of the frozen chain); frozen hypothesis 0 failures, sensitivity 1 (closedacct 0.2);
  a failed and resent order lands LATER, on another state (R02): +LATENCY_SLOTS slots per failure of the buy or of the
  sale, with H-1 on the delayed landing slot (for the clock exit, after the slot of the last swap at the clock time);
  the cleanup comes after the total sale and moves no price;
* ACCOUNT CLOSING (C-a of R02): the base token account is CLOSED in a SEPARATE transaction after the total sale: its
  rent comes back, the cost is (failed + 1) x 105 000; after 3 failed cleanups it stays open (rent lost + 3 fees);
  the WSOL wrapper is closed in a SEPARATE transaction too (unfavourable hypothesis of the note, +105 000), until a
  close inside the sale is shown on a real public transaction.
Return on the STAKE (0.1 SOL), as in dossier B and closedacct:  r = (received - stake - transactions - wsol close -
cleanup) / stake. Declared threshold of fees + transactions, closed mode: 2 x 0.25 % + 3 x 105 000 / 10^8 = 0.815 %,
written 0.82 % (C-a); working bar with the unfavourable WSOL close and the own impact at 100 SOL: about 1.12 %.

``pool_gate``: the decoder side (G-0 per pool, exclusions U-4): every transaction decoded, every swap reproduced to the
atomic unit with the AmmConfig rates (C-1 on the pool, C-3), reserves chained with the AmmConfig shares (C-2), no
token transfer fee (Token-2022), one creator-fee side. ``pilot_verdict``: G-0, then G-1 of section 2.5 (n >= 30, >= 20
pools, upper one-sided 95 % bound of the mean net >= 0, bootstrap 10 000 draws grouped by pool). Labels:
MASTER_RESEARCH_PAPER / HISTORICAL_REPLAY; never counted for the 50 cycles / 20 creators of the operational Master.
"""
import hashlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from closedacct import model as CA
from cpmmx import curve, timeline as TL
from w2arms import ce as W

STAKE_LAMPORTS = 100_000_000
TX_FEE_LAMPORTS = CA.CLEANUP_FEE_LAMPORTS          # 105 000: 5 000 base + 100 000 priority, frozen chain
assert TX_FEE_LAMPORTS == 105_000
TOKEN_ACCOUNT_RENT_LAMPORTS = CA.SPL_RENT_LAMPORTS  # 2 039 280
UNIVERSE_TRADE_FEE_RATE = 2_500                    # U-1
LATENCY_SLOTS = 4
WSOL_SEPARATE_CLOSE = True                         # unfavourable hypothesis of the pilot note (CP-1)
CLOSED_THRESHOLD = Fraction(82, 10_000)            # C-a: 0.82 %
MIN_ENTRIES, MIN_POOLS, DRAWS, ALPHA_UPPER = 30, 20, 10_000, 0.05
TRIAL_CAP_OUTSIDE_HW1 = 170
LABELS = ('MASTER_RESEARCH_PAPER', 'HISTORICAL_REPLAY')
BUY_GUARD_PPM = 20_000                             # R02 amendment A1 (c), R-0.3
BUY_GUARD_SENSITIVITY_PPM = 50_000
ALLOWED_BUY_GUARDS = (None, BUY_GUARD_PPM, BUY_GUARD_SENSITIVITY_PPM)
SENSITIVITY_LATENCY_SLOTS = 10                     # A1 (a): CONFIRMÉ also needs a net > 0 at 10 slots
ALLOWED_LATENCIES = (LATENCY_SLOTS, SENSITIVITY_LATENCY_SLOTS)


FROZEN_CODE = dict(curve='5836f2fbac3bb8f01a3c8e91ccc8520db8e158cd21fb082d9e067128d865d899',      # cpmmx 0.1, 99c6688
                   events='2178f3fd2e1715a33d836ce0636c630d75af5e3d23baa4109a75979aee3b0c36',      # (cpmmfmt uses events)
                   timeline='13d339170dfbd4fe6d57c3658163254fab46edb8c702229794e77a8c5bc9bf36',
                   closedacct='c6b4d78cc985933115cb68a67e9266efc0f7b0f52da2473601a90b99b9b982ed')   # closedacct 0.2


class CostError(ValueError):
    pass


def frozen_check():
    """The decoder (the one cpmmfmt checks the format of) and closedacct are the audited files, byte for byte."""
    from cpmmx import events
    found = dict(curve=curve.__file__, events=events.__file__, timeline=TL.__file__, closedacct=CA.__file__)
    found = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in found.items()}
    for key, value in FROZEN_CODE.items():
        if found[key] != value:
            raise CostError('frozen_code_differs:%s' % key)
    return found


@dataclass(frozen=True)
class Failures:
    buy: int = 0
    sell: int = 0
    cleanup: int = 0

    def __post_init__(self):
        for name in ('buy', 'sell', 'cleanup'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise CostError('invalid_failures_%s' % name)
        if self.cleanup > CA.MAX_CLEANUP_ATTEMPTS:
            raise CostError('cleanup_failures_out_of_range')


FROZEN_FAILURES = Failures()
SENSITIVITY_FAILURES = Failures(1, 1, 1)


def fees_from_amm_config(config):
    """curve.Fees from the AmmConfig as READ and hashed with its slot; any other trade rate is outside U-1."""
    sha, slot = config.get('sha256'), config.get('slot')
    if type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or type(slot) is not int:
        raise CostError('amm_config_not_read_and_hashed')
    if config.get('trade_fee_rate') != UNIVERSE_TRADE_FEE_RATE:
        raise CostError('outside_universe_u1_trade_fee')
    creator = config.get('creator_fee_rate', 0) if config.get('pool_creator_fee_enabled') is True else 0   # E-CF 0.3.1
    return curve.Fees(config['trade_fee_rate'], creator, config['protocol_fee_rate'], config['fund_fee_rate'])


def fixed_cost_share():
    """Fees + transactions of a round trip at zero impact, closed mode, WSOL closed in the sale: 0.815 %."""
    return Fraction(2 * UNIVERSE_TRADE_FEE_RATE, curve.FEE_DENOMINATOR) + Fraction(3 * TX_FEE_LAMPORTS, STAKE_LAMPORTS)


def bar(reserve_sol, *, wsol_separate_close=WSOL_SEPARATE_CLOSE):
    """CP-1 sizing only (never used for a result): fixed costs + 2 x stake / reserve of own impact."""
    extra = Fraction(TX_FEE_LAMPORTS, STAKE_LAMPORTS) if wsol_separate_close else 0
    return fixed_cost_share() + extra + Fraction(2 * STAKE_LAMPORTS, reserve_sol * 10 ** 9)


def creator_side(line, last_index):
    flags = {s.event.creator_fee_on_input for s in line.swaps[:last_index + 1]}
    if len(flags) != 1:
        raise CostError('creator_fee_side_changed')
    return flags.pop()


def _state(line, fees, **limit):
    base, quote, evidence = TL.reserves_at(line, protocol_fee_rate=fees.protocol_fee_rate,
                                          fund_fee_rate=fees.fund_fee_rate, **limit)
    if evidence.get('lp_change_follows'):
        raise CostError('lp_change_at_the_landing_point')
    return base, quote


def _buy_on(state, fees, on_input):
    base, quote = state
    got = curve.swap_base_input(STAKE_LAMPORTS, quote, base, fees, on_input)
    return got


def _sell_on(state, tokens, fees, on_input):
    base, quote = state
    return curve.swap_base_input(tokens, base, quote, fees, on_input)


def _with_our_buy(state, bought, buy_state):
    """X-1 (ii): the sale state with the reserve change of our buy left in the pool."""
    q0, b0 = buy_state[1], buy_state[0]
    q1, b1 = curve.reserves_after(q0, b0, bought)
    base, quote = state[0] + (b1 - b0), state[1] + (q1 - q0)
    if base <= 0 or quote <= 0:
        raise CostError('counterfactual_state_empty')
    return base, quote


def _fee_value(result, spot, *, input_is_quote):
    """The fees of one swap in lamports: those taken in SOL as such, those taken in tokens at the spot of its state."""
    on_input = result.creator_fee_on_input
    in_fee = result.trade_fee + (result.creator_fee if on_input else 0)
    out_fee = 0 if on_input else result.creator_fee
    if input_is_quote:
        return Fraction(in_fee) + out_fee * spot
    return in_fee * spot + Fraction(out_fee)


def position(line, decision_index, config, *, exit_slot=None, exit_time=None, failures=FROZEN_FAILURES,
             wsol_separate_close=WSOL_SEPARATE_CLOSE, buy_guard_ppm=BUY_GUARD_PPM, latency_slots=LATENCY_SLOTS):
    """One round trip: buy 0.1 SOL after the decision swap, sale of every token at the exit, then the cleanup.

    With the buy guard (primary 20 000 ppm): if the H-1 fill is below the exact output at the decision state x (1 - ppm),
    the buy transaction fails: (failed attempts + 1) x 105 000 are charged, no account is created, no entry, no retry."""
    if buy_guard_ppm not in ALLOWED_BUY_GUARDS:
        raise CostError('buy_guard_not_a_declared_threshold')
    if type(latency_slots) is not int or latency_slots not in ALLOWED_LATENCIES:
        raise CostError('latency_not_a_declared_value')
    if (exit_slot is None) == (exit_time is None):
        raise CostError('exactly_one_exit_point')
    if type(decision_index) is not int or not 0 <= decision_index < len(line.swaps):
        raise CostError('invalid_decision_index')
    fees = fees_from_amm_config(config)
    frozen_check()
    decision = line.swaps[decision_index]
    land = decision.slot + latency_slots * (1 + failures.buy)
    # H-1 at the buy: the state before and after the real swaps of the landing slot; the FEWER tokens are kept
    states = [_state(line, fees, slot_limit=land - 1), _state(line, fees, slot_limit=land)]
    if exit_slot is not None:
        if type(exit_slot) is not int or exit_slot <= land:
            raise CostError('exit_before_the_buy_landed')
        sale_slot = exit_slot + latency_slots * failures.sell
        limits = [dict(slot_limit=sale_slot - 1), dict(slot_limit=sale_slot)]
        done = TL.executed(line, slot_limit=sale_slot)
    else:
        if type(exit_time) is not int or exit_time <= decision.block_time:
            raise CostError('exit_before_the_buy_landed')
        limits = [dict(time_limit=exit_time - 1), dict(time_limit=exit_time)]
        landed = TL.executed(line, slot_limit=land)
        if any(s.block_time > exit_time - 1 for s in landed):       # the sale must see every swap before our buy
            raise CostError('exit_before_the_buy_landed')
        done = TL.executed(line, time_limit=exit_time)
        if failures.sell:                                            # the resent sale: slots after the clock landing
            base_slot = max([s.slot for s in done] + [land])
            sale_slot = base_slot + latency_slots * failures.sell
            limits = [dict(slot_limit=sale_slot - 1), dict(slot_limit=sale_slot)]
            done = TL.executed(line, slot_limit=sale_slot)
    on_input = creator_side(line, len(done) - 1)
    buys = [(_buy_on(s, fees, on_input), s) for s in states]
    bought, buy_state = min(buys, key=lambda pair: pair[0].output_amount)
    tokens = bought.output_amount
    if buy_guard_ppm is not None:
        decision_state = TL.after_swap(decision, fees.protocol_fee_rate, fees.fund_fee_rate)
        expected = _buy_on(decision_state, fees, on_input).output_amount
        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:
            charged = (1 + failures.buy) * TX_FEE_LAMPORTS
            return dict(pool=line.pool, decision_index=decision_index, decision_slot=decision.slot, status='guard_failed',
                        entered=False, tokens=0, received=0, net_lamports=-charged, net_return=-charged / STAKE_LAMPORTS,
                        guard_ppm=buy_guard_ppm, latency_slots=latency_slots, expected_tokens=expected, fill_tokens=tokens,
                        failures=dict(buy=failures.buy, sell=failures.sell, cleanup=failures.cleanup),
                        amm_config_sha256=config['sha256'], labels=list(LABELS), counts_for_operational_master=False)
    candidates = []
    for limit in limits:
        real = _state(line, fees, **limit)
        for state, kind in ((real, 'real_reserves'), (_with_our_buy(real, bought, buy_state), 'with_our_buy')):
            candidates.append((_sell_on(state, tokens, fees, on_input), state, kind, limit))
    sold, sell_state, kind, limit = min(candidates, key=lambda row: row[0].output_amount)
    received = sold.output_amount
    # transactions: every attempt of the buy and the sale, the WSOL close, the token account cleanup
    tx_buy = (1 + failures.buy) * TX_FEE_LAMPORTS
    tx_sell = (1 + failures.sell) * TX_FEE_LAMPORTS
    wsol_close = TX_FEE_LAMPORTS if wsol_separate_close else 0
    if failures.cleanup == CA.MAX_CLEANUP_ATTEMPTS:          # left open: the rent is lost and every attempt paid
        cleanup, rent_lost = failures.cleanup * TX_FEE_LAMPORTS, TOKEN_ACCOUNT_RENT_LAMPORTS
    else:
        cleanup, rent_lost = (failures.cleanup + 1) * TX_FEE_LAMPORTS, 0
    net = received - STAKE_LAMPORTS - tx_buy - tx_sell - wsol_close - cleanup - rent_lost
    # exact decomposition (lamports, fractions): price move, fees and impact of each leg
    spot_buy = Fraction(buy_state[1], buy_state[0])
    spot_sell = Fraction(sell_state[1], sell_state[0])
    fees_buy = _fee_value(bought, spot_buy, input_is_quote=True)
    fees_sell = _fee_value(sold, spot_sell, input_is_quote=False)
    impact_buy = STAKE_LAMPORTS - fees_buy - tokens * spot_buy
    impact_sell = tokens * spot_sell - fees_sell - received
    move = tokens * (spot_sell - spot_buy)
    parts = dict(price_move=move, trade_and_creator_fees=-(fees_buy + fees_sell), price_impact=-(impact_buy + impact_sell),
                 transactions=-(tx_buy + tx_sell), wsol_close=-wsol_close, cleanup=-cleanup, rent_lost=-rent_lost)
    residual = sum(parts.values()) - net
    if residual != 0:
        raise CostError('cost_identity_residual')
    if impact_buy < 0 or impact_sell < 0:
        raise CostError('negative_price_impact')
    outcome = dict(migrated=False, value=received, tokens=tokens,
                   cost=STAKE_LAMPORTS + tx_buy + tx_sell + wsol_close)
    closed = CA.net_return_closed(outcome, failed_attempts=failures.cleanup)
    if abs(closed - net / STAKE_LAMPORTS) > 1e-12:
        raise CostError('net_differs_from_closedacct')
    return dict(pool=line.pool, decision_index=decision_index, decision_slot=decision.slot, status='entered',
                entered=True, guard_ppm=buy_guard_ppm, latency_slots=latency_slots, buy_landing_slot=land,
                exit=dict(rule='slot' if exit_slot is not None else 'clock', declared=exit_slot if exit_slot is not None
                          else exit_time, state_kept=limit), tokens=tokens, received=received,
                net_lamports=net, net_return=net / STAKE_LAMPORTS, sale_state=kind,
                decomposition_share_of_stake={k: float(v / STAKE_LAMPORTS) for k, v in parts.items()},
                failures=dict(buy=failures.buy, sell=failures.sell, cleanup=failures.cleanup),
                wsol_separate_close=wsol_separate_close, amm_config_sha256=config['sha256'], labels=list(LABELS),
                counts_for_operational_master=False)


def pool_gate(line, config):
    """G-0 on one pool and the U-4 exclusions; the pool is admitted only with an empty list of reasons."""
    fees = fees_from_amm_config(config)
    frozen_check()
    reasons = []
    if line.skipped:
        reasons.append('undecoded_transactions')
    if not line.swaps:
        return dict(admitted=False, reasons=reasons + ['no_swap'])
    if any(s.event.input_transfer_fee or s.event.output_transfer_fee for s in line.swaps):
        reasons.append('token_transfer_fee')
    try:
        on_input = creator_side(line, len(line.swaps) - 1)
    except CostError:
        return dict(admitted=False, reasons=reasons + ['creator_fee_side_changed'])
    report = TL.reproduce(line, {'buy': (fees, on_input), 'sell': (fees, on_input)})
    if report['exact'] != report['swaps']:
        reasons.append('swaps_not_reproduced_with_the_amm_config')       # C-1 on the pool, C-3, fee change
    breaks = [b for b in TL.continuity(line, fees.protocol_fee_rate, fees.fund_fee_rate)
              if b['reason'] != 'lp_change_between']
    if breaks:
        reasons.append('reserves_chain_broken')                          # C-2: missing swap or direct vault deposit
    return dict(admitted=not reasons, reasons=reasons, swaps=report['swaps'], exact=report['exact'],
                lp_changes=report['lp_changes'], continuity_breaks=len(breaks))


def trials(n_before):
    """R-CP1 and its placebo are ONE trial (CP-5): 168 -> 169, cap 170 outside HW1."""
    if type(n_before) is not int or n_before < 0:
        raise CostError('n_before_must_be_a_non_negative_integer')
    if n_before + 1 > TRIAL_CAP_OUTSIDE_HW1:
        raise CostError('trial_cap_exceeded')
    return dict(n_before=n_before, n_after=n_before + 1, cap_outside_hw1=TRIAL_CAP_OUTSIDE_HW1,
                left_after=TRIAL_CAP_OUTSIDE_HW1 - n_before - 1)


def pilot_verdict(positions, *, g0_passed, freeze_sheet_sha256, draws=DRAWS):
    """Section 2.5 in order: G-0 (C-1 to C-3 of the pilot swaps, an anchored input), then G-1; GO only PROPOSES a study."""
    # seed fixed by R02: int(sha256 of the pilot FREEZE SHEET[:8], 16); the sheet (anchored by R02 at the freeze) holds
    # the hashed U-2 list, R-CP1, the threshold, the code sha and the anchor of protocol v1.2 (a3a285a1)
    if (type(freeze_sheet_sha256) is not str or len(freeze_sheet_sha256) != 64
            or any(c not in '0123456789abcdef' for c in freeze_sheet_sha256)):
        raise CostError('freeze_sheet_sha256_required')
    base = dict(labels=list(LABELS), counts_for_operational_master=False, min_entries=MIN_ENTRIES, min_pools=MIN_POOLS)
    if g0_passed is not True:
        return dict(base, decision='STOP', reason='g0_decoder_not_passed', published_numbers=False)
    groups = {}
    for p in positions:
        groups.setdefault(p['pool'], []).append(p)
    n, pools = len(positions), len(groups)
    # amendment A1 (c): a guard-failed attempt stays in the mean (its fee is charged) but is NOT an entry; the floors of
    # G-1 (30 entries, 20 pools) count ENTERED positions only (stricter, never lower)
    entered = [p for p in positions if p.get('entered', True)]
    n_entered, pools_entered = len(entered), len({p['pool'] for p in entered})
    nets = [p['net_return'] for p in positions]
    mean = sum(nets) / n if n else None

    def neg_mean(rows):
        return -sum(r['net_return'] for r in rows) / len(rows) if rows else None
    upper = None
    if n:
        low = W.lower_bound(groups, neg_mean, seed=int(freeze_sheet_sha256[:8], 16), draws=draws, alpha=ALPHA_UPPER)
        upper = None if low is None else -low
    if n_entered < MIN_ENTRIES or pools_entered < MIN_POOLS:
        decision = 'INCONCLUSIF'
    elif upper is None or upper < 0:
        decision = 'NO-GO'
    else:
        decision = 'GO_PILOTE'
    return dict(base, decision=decision, n=n, pools=pools, n_entered=n_entered, pools_entered=pools_entered,
                guard_failed=n - n_entered, mean_net_return=mean, upper_bound_95_one_sided=upper,
                draws=draws, seed=int(freeze_sheet_sha256[:8], 16), published_numbers=True,
                meaning='GO_PILOTE only allows PROPOSING a pre-registered confirmation on a NEW window with the dossier '
                        'B criteria c1-c5; it never means profitable')
