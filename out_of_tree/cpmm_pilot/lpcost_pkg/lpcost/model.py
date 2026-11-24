"""lpcost 0.1 -- PAPER cost model of a LIQUIDITY-PROVIDER position over one pool-day on a Raydium CPMM pool of U-1
(0.25 %), decision R04-3 (24/11, 20:52Z, owner's delegation), dossier N1 b7d5d9c. Offline: synthetic pools only, nothing
reads collected data. cpmmcost 0.3 and cpmmx are reused, never modified. Labels: research only, never an operational
Master trade, never counted for 50 / 20.

THE FIVE STEPS (stake 0.1 SOL, clock decision at ``start_time``, landing after the frozen clock latency):
1. ENTRY SWAP: half the stake (0.05 SOL) buys the base token on the WORSE of the two landing states (H-1, as cpmmcost),
   with the buy guard of cpmmcost (20 000 ppm): a refused buy is charged and ends the position (no entry).
2. DEPOSIT: proportional to the landing reserves (LP-owned reserves: protocol and fund shares excluded by
   ``timeline.after_swap`` with the AmmConfig shares). Share s = min(base held / B, quote held / Q); the amounts
   deposited are rounded UP (Raydium takes the ceiling), the rest stays held.
3. HOLDING: our liquidity scales with the pool; every LP event of OTHERS between our landing and our exit rescales our
   fraction (a deposit of a fraction f of the reserves: s / (1 + f); a withdrawal: s / (1 - f)).
4. EXIT at ``end_time``: withdrawal of floor(s x reserves) (rounded DOWN), then the sale of every base token held on the
   WORSE of the exit states (two landing limits, with and without our withdrawal, as cpmmcost's X-1).
5. NET = SOL received - stake - transactions. Exact identity (integers):
       net = hold_pnl + lp_vs_hold - transactions
   hold_pnl   = value at exit of the tokens held right after the entry swap, sold by the same rule, minus the stake
                (price move, both swap legs' fees and impact);
   lp_vs_hold = LP path - hold path (fees earned by the position minus the inventory loss, i.e. the realised LVR, and
                the deposit / withdrawal rounding).
   fees_earned_estimate (descriptive): s x the LP part of every swap's trade fee in the period, valued at the spot of
   that swap; inventory_loss = fees_earned_estimate - lp_vs_hold.
TRANSACTIONS (closed account, cpmmcost frozen 105 000 lamports each): entry swap (1 + buy failures), deposit, withdrawal,
exit swap (1 + sell failures), WSOL close, cleanup of the token and LP accounts (1 + cleanup failures); after
MAX_CLEANUP_ATTEMPTS failed cleanups, the two account rents are lost.
DECLARED SIMPLIFICATIONS: our own entry swap and deposit are not replayed into the later states (our share is tiny:
0.05 SOL in a pool of >= 100 SOL); the worse-state rules take the cost of that on both legs. A day without any swap
earns no fee.
"""
from fractions import Fraction

from closedacct import model as CA
from cpmmcost import model as CC
from cpmmx import curve, timeline as TL
from bot.p4 import historical_research_replay as hrr

SCHEMA = 'lpcost-v0.1'
STAKE = CC.STAKE_LAMPORTS
HALF = STAKE // 2
TX = CC.TX_FEE_LAMPORTS
RENT = CC.TOKEN_ACCOUNT_RENT_LAMPORTS
ACCOUNTS = 2                                 # the base-token account and the LP-token account
LABELS = ('MASTER_RESEARCH_PAPER', 'HISTORICAL_REPLAY', 'LP_SIDE_RESEARCH')
DEPOSIT, WITHDRAW = 0, 1


class LpCostError(ValueError):
    pass


def _ceil(x):
    return -((-x.numerator) // x.denominator)


def _floor(x):
    return x.numerator // x.denominator


def landing_time(decision_time, latency_slots=CC.LATENCY_SLOTS):
    return decision_time + hrr.clock_exit_latency_s(latency_slots)


def _states(line, fees, t):
    return [CC._state(line, fees, time_limit=t - 1), CC._state(line, fees, time_limit=t)]


def transactions(failures=CC.FROZEN_FAILURES, wsol_separate_close=CC.WSOL_SEPARATE_CLOSE):
    """(lamports, rent lost) of the own transactions of one LP round trip."""
    n = (1 + failures.buy) + 1 + 1 + (1 + failures.sell) + (1 if wsol_separate_close else 0)
    if failures.cleanup == CA.MAX_CLEANUP_ATTEMPTS:
        return (n + failures.cleanup) * TX, ACCOUNTS * RENT
    return (n + failures.cleanup + 1) * TX, 0


def share_after_others(line, share, low_key, high_key):
    """Our pool fraction after the LP events of others with low_key < key <= high_key (proportional events)."""
    for slot, tx_index, order, event in line.lp_changes:
        key = (slot, tx_index, order)
        if not low_key < key <= high_key:
            continue
        if event.token_0_vault_before <= 0:
            raise LpCostError('lp_event_on_an_empty_vault')
        f = Fraction(event.token_0_amount, event.token_0_vault_before)
        if event.change_type == DEPOSIT:
            share = share / (1 + f)
        elif event.change_type == WITHDRAW:
            if f >= 1:
                raise LpCostError('pool_emptied_by_a_withdrawal')
            share = share / (1 - f)
        else:
            raise LpCostError('unknown_lp_change_type')
    return share


def _last_key(line, t):
    done = TL.executed(line, time_limit=t)
    return done[-1].key if done else (-1, -1, -1)


def lp_position(line, config, *, start_time, end_time, failures=CC.FROZEN_FAILURES, buy_guard_ppm=CC.BUY_GUARD_PPM,
                latency_slots=CC.LATENCY_SLOTS):
    if type(start_time) is not int or type(end_time) is not int or end_time <= start_time:
        raise LpCostError('invalid_period')
    fees = CC.fees_from_amm_config(config)                  # U-1 only (0.25 %), AmmConfig read and hashed
    CC.frozen_check()
    if not line.swaps:
        raise LpCostError('no_swap_in_the_pool')
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    land_in, land_out = landing_time(start_time, latency_slots), landing_time(end_time, latency_slots)
    tx_cost, rent_lost = transactions(failures)
    # 1. entry swap on the worse landing state, with the buy guard
    buys = [(curve.swap_base_input(HALF, s[1], s[0], fees, on_input), s) for s in _states(line, fees, land_in)]
    bought, (b0, q0) = min(buys, key=lambda pair: pair[0].output_amount)
    tokens = bought.output_amount
    if buy_guard_ppm not in CC.ALLOWED_BUY_GUARDS:
        raise LpCostError('buy_guard_not_a_declared_threshold')
    if buy_guard_ppm is not None:                          # cpmmcost rule: fill against the decision-state output
        db, dq = CC._state(line, fees, time_limit=start_time)
        expected = curve.swap_base_input(HALF, dq, db, fees, on_input).output_amount
        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:
            charged = (1 + failures.buy) * TX
            return dict(pool=line.pool, start_time=start_time, end_time=end_time, status='guard_failed',
                        entered=False, net_lamports=-charged, net_return=-charged / STAKE, guard_ppm=buy_guard_ppm,
                        expected_tokens=expected, fill_tokens=tokens, labels=list(LABELS),
                        counts_for_operational_master=False)
    # 2. proportional deposit, amounts rounded up
    share = min(Fraction(tokens, b0), Fraction(HALF, q0))
    dep_b, dep_q = min(_ceil(share * b0), tokens), min(_ceil(share * q0), HALF)
    left_b, left_q = tokens - dep_b, HALF - dep_q
    # 3. our fraction after the LP events of others during the holding
    share = share_after_others(line, share, _last_key(line, land_in), _last_key(line, land_out))
    # 4. withdrawal rounded down, then the sale of every base token on the worse exit state
    exits = _states(line, fees, land_out)
    b1, q1 = min(exits, key=lambda s: Fraction(s[1], s[0]))
    wd_b, wd_q = _floor(share * b1), _floor(share * q1)

    def sale(amount):
        if amount == 0:
            return 0
        candidates = []
        for b, q in exits:
            for bb, qq in ((b, q), (b - wd_b, q - wd_q)):
                if bb <= 0 or qq <= 0:
                    raise LpCostError('exit_state_empty')
                candidates.append(curve.swap_base_input(amount, bb, qq, fees, on_input).output_amount)
        return min(candidates)
    lp_received = wd_q + left_q + sale(wd_b + left_b)
    hold_received = HALF + sale(tokens)
    # 5. net and its exact identity
    hold_pnl = hold_received - STAKE
    lp_vs_hold = lp_received - hold_received
    net = lp_received - STAKE - tx_cost - rent_lost
    # identity by construction (integers): net = hold_pnl + lp_vs_hold - transactions - rent lost
    fees_estimate = fees_earned_estimate(line, fees, share_at_entry=Fraction(dep_q, q0), land_in=land_in,
                                         land_out=land_out)
    return dict(pool=line.pool, start_time=start_time, end_time=end_time, status='entered', entered=True,
                tokens_bought=tokens, deposited=dict(base=dep_b, quote=dep_q), left=dict(base=left_b, quote=left_q),
                share_at_exit=float(share), withdrawn=dict(base=wd_b, quote=wd_q), lp_received=lp_received,
                hold_received=hold_received, net_lamports=net, net_return=net / STAKE,
                decomposition_lamports=dict(hold_pnl=hold_pnl, lp_vs_hold=lp_vs_hold, transactions=-tx_cost,
                                            rent_lost=-rent_lost),
                fees_earned_estimate=float(fees_estimate), inventory_loss_estimate=float(fees_estimate - lp_vs_hold),
                failures=dict(buy=failures.buy, sell=failures.sell, cleanup=failures.cleanup),
                amm_config_sha256=config['sha256'], labels=list(LABELS), counts_for_operational_master=False)


def fees_earned_estimate(line, fees, *, share_at_entry, land_in, land_out):
    """DESCRIPTIVE: our fraction of the LP part of each swap's trade fee during the holding, valued at its spot."""
    lp_part = Fraction(curve.FEE_DENOMINATOR - fees.protocol_fee_rate - fees.fund_fee_rate, curve.FEE_DENOMINATOR)
    total = Fraction(0)
    for swap in line.swaps:
        if not land_in < swap.block_time <= land_out:
            continue
        base, quote = TL.after_swap(swap, fees.protocol_fee_rate, fees.fund_fee_rate)
        spot = Fraction(quote, base)
        fee = swap.event.trade_fee * lp_part
        total += share_at_entry * (fee if swap.side == 'buy' else fee * spot)
    return total
