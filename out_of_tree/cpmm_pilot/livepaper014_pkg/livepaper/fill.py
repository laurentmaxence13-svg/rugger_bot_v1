"""The LIVE anchor of a position (R04-17, dossier T-R01-12): cpmmprereg.exit_point and cpmmcost.position (frozen) with
ONE change, the anchor. Frozen: the buy lands LATENCY_SLOTS after the TRIGGER swap, the clock runs from its block time,
the buy guard reads the state after it. Live: the order leaves at the RECEIPT of the data, so
  - the buy lands LATENCY_SLOTS (x (1 + buy failures)) after the RECEIPT SLOT (getSlot after the fetch);
  - the 30-min clock runs from the RECEIPT TIME;
  - the guard reads the state after the LAST SWAP KNOWN at the receipt (no later datum).
Everything else is the frozen arithmetic, through the frozen helpers (cpmmcost._state, _buy_on, _sell_on,
_with_our_buy, _fee_value, closedacct), unchanged: H-1 at the landing, TP / SL +-2 % of the stake on the exact sale
value, the sale 4 slots after a TP / SL trigger or at the clock + its latency, worst sale state, transactions, WSOL
close, cleanup, exact decomposition with a zero residual. With the anchor ON the trigger (receipt slot = trigger slot,
receipt time = trigger block time, last known swap = the trigger) both functions equal the frozen ones (tested)."""
from dataclasses import dataclass
from fractions import Fraction

from bot.p4 import historical_research_replay as hrr
from closedacct import model as CA
from cpmmcost import model as CC
from cpmmprereg import rule as R
from cpmmx import timeline as TL


@dataclass(frozen=True)
class Anchor:
    key: tuple          # swap key (slot, tx_index, order) of the last swap known at the receipt
    slot: int           # receipt slot
    time: int           # receipt time (whole seconds, block-time scale)


def anchor_index(line, anchor):
    for i, s in enumerate(line.swaps):
        if s.key == tuple(anchor.key):
            return i
    raise CC.CostError('anchor_swap_not_in_the_line')


def exit_point(line, anchor, config, *, latency_slots=CC.LATENCY_SLOTS, buy_failures=0):
    """cpmmprereg.exit_point with the live anchor."""
    if latency_slots not in CC.ALLOWED_LATENCIES or type(latency_slots) is not int:
        raise R.PreregError('latency_not_a_declared_value')
    fees = CC.fees_from_amm_config(config)
    ai = anchor_index(line, anchor)
    land = anchor.slot + latency_slots * (1 + buy_failures)
    on_input = CC.creator_side(line, ai)
    states = [CC._state(line, fees, slot_limit=land - 1), CC._state(line, fees, slot_limit=land)]
    tokens = min(CC._buy_on(s, fees, on_input).output_amount for s in states)
    deadline = anchor.time + R.CLOCK_S
    for swap in line.swaps:
        if swap.slot <= land or swap.block_time > deadline:
            continue
        base, quote = TL.after_swap(swap, fees.protocol_fee_rate, fees.fund_fee_rate)
        value = CC._sell_on((base, quote), tokens, fees, on_input).output_amount
        ratio = Fraction(value - CC.STAKE_LAMPORTS, CC.STAKE_LAMPORTS)
        if ratio >= R.TP or ratio <= R.SL:
            return swap.slot + latency_slots, None
    return None, deadline + hrr.clock_exit_latency_s(latency_slots)


def position(line, anchor, config, *, exit_slot=None, exit_time=None, failures=CC.FROZEN_FAILURES,
             wsol_separate_close=CC.WSOL_SEPARATE_CLOSE, buy_guard_ppm=CC.BUY_GUARD_PPM, latency_slots=CC.LATENCY_SLOTS):
    """cpmmcost.position with the live anchor; the same keys, decision_index = the index of the anchor swap."""
    if buy_guard_ppm not in CC.ALLOWED_BUY_GUARDS:
        raise CC.CostError('buy_guard_not_a_declared_threshold')
    if type(latency_slots) is not int or latency_slots not in CC.ALLOWED_LATENCIES:
        raise CC.CostError('latency_not_a_declared_value')
    if (exit_slot is None) == (exit_time is None):
        raise CC.CostError('exactly_one_exit_point')
    ai = anchor_index(line, anchor)
    fees = CC.fees_from_amm_config(config)
    CC.frozen_check()
    known = line.swaps[ai]
    land = anchor.slot + latency_slots * (1 + failures.buy)
    states = [CC._state(line, fees, slot_limit=land - 1), CC._state(line, fees, slot_limit=land)]
    if exit_slot is not None:
        if type(exit_slot) is not int or exit_slot <= land:
            raise CC.CostError('exit_before_the_buy_landed')
        sale_slot = exit_slot + latency_slots * failures.sell
        limits = [dict(slot_limit=sale_slot - 1), dict(slot_limit=sale_slot)]
        done = TL.executed(line, slot_limit=sale_slot)
    else:
        if type(exit_time) is not int or exit_time <= anchor.time:
            raise CC.CostError('exit_before_the_buy_landed')
        limits = [dict(time_limit=exit_time - 1), dict(time_limit=exit_time)]
        landed = TL.executed(line, slot_limit=land)
        if any(s.block_time > exit_time - 1 for s in landed):
            raise CC.CostError('exit_before_the_buy_landed')
        done = TL.executed(line, time_limit=exit_time)
        if failures.sell:
            base_slot = max([s.slot for s in done] + [land])
            sale_slot = base_slot + latency_slots * failures.sell
            limits = [dict(slot_limit=sale_slot - 1), dict(slot_limit=sale_slot)]
            done = TL.executed(line, slot_limit=sale_slot)
    on_input = CC.creator_side(line, len(done) - 1)
    buys = [(CC._buy_on(s, fees, on_input), s) for s in states]
    bought, buy_state = min(buys, key=lambda pair: pair[0].output_amount)
    tokens = bought.output_amount
    common = dict(pool=line.pool, decision_index=ai, decision_slot=anchor.slot, anchor_key=list(anchor.key),
                  receipt_time=anchor.time, guard_ppm=buy_guard_ppm, latency_slots=latency_slots,
                  failures=dict(buy=failures.buy, sell=failures.sell, cleanup=failures.cleanup),
                  amm_config_sha256=config['sha256'], labels=list(CC.LABELS), counts_for_operational_master=False)
    if buy_guard_ppm is not None:
        decision_state = TL.after_swap(known, fees.protocol_fee_rate, fees.fund_fee_rate)
        expected = CC._buy_on(decision_state, fees, on_input).output_amount
        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:
            charged = (1 + failures.buy) * CC.TX_FEE_LAMPORTS
            return dict(common, status='guard_failed', entered=False, tokens=0, received=0, net_lamports=-charged,
                        net_return=-charged / CC.STAKE_LAMPORTS, expected_tokens=expected, fill_tokens=tokens)
    candidates = []
    for limit in limits:
        real = CC._state(line, fees, **limit)
        for state, kind in ((real, 'real_reserves'), (CC._with_our_buy(real, bought, buy_state), 'with_our_buy')):
            candidates.append((CC._sell_on(state, tokens, fees, on_input), state, kind, limit))
    sold, sell_state, kind, limit = min(candidates, key=lambda row: row[0].output_amount)
    received = sold.output_amount
    tx_buy = (1 + failures.buy) * CC.TX_FEE_LAMPORTS
    tx_sell = (1 + failures.sell) * CC.TX_FEE_LAMPORTS
    wsol_close = CC.TX_FEE_LAMPORTS if wsol_separate_close else 0
    if failures.cleanup == CA.MAX_CLEANUP_ATTEMPTS:
        cleanup, rent_lost = failures.cleanup * CC.TX_FEE_LAMPORTS, CC.TOKEN_ACCOUNT_RENT_LAMPORTS
    else:
        cleanup, rent_lost = (failures.cleanup + 1) * CC.TX_FEE_LAMPORTS, 0
    net = received - CC.STAKE_LAMPORTS - tx_buy - tx_sell - wsol_close - cleanup - rent_lost
    spot_buy = Fraction(buy_state[1], buy_state[0])
    spot_sell = Fraction(sell_state[1], sell_state[0])
    fees_buy = CC._fee_value(bought, spot_buy, input_is_quote=True)
    fees_sell = CC._fee_value(sold, spot_sell, input_is_quote=False)
    impact_buy = CC.STAKE_LAMPORTS - fees_buy - tokens * spot_buy
    impact_sell = tokens * spot_sell - fees_sell - received
    move = tokens * (spot_sell - spot_buy)
    parts = dict(price_move=move, trade_and_creator_fees=-(fees_buy + fees_sell), price_impact=-(impact_buy + impact_sell),
                 transactions=-(tx_buy + tx_sell), wsol_close=-wsol_close, cleanup=-cleanup, rent_lost=-rent_lost)
    if sum(parts.values()) - net != 0:
        raise CC.CostError('cost_identity_residual')
    if impact_buy < 0 or impact_sell < 0:
        raise CC.CostError('negative_price_impact')
    outcome = dict(migrated=False, value=received, tokens=tokens, cost=CC.STAKE_LAMPORTS + tx_buy + tx_sell + wsol_close)
    closed = CA.net_return_closed(outcome, failed_attempts=failures.cleanup)
    if abs(closed - net / CC.STAKE_LAMPORTS) > 1e-12:
        raise CC.CostError('net_differs_from_closedacct')
    return dict(common, status='entered', entered=True, buy_landing_slot=land,
                exit=dict(rule='slot' if exit_slot is not None else 'clock',
                          declared=exit_slot if exit_slot is not None else exit_time, state_kept=limit),
                tokens=tokens, received=received, net_lamports=net, net_return=net / CC.STAKE_LAMPORTS, sale_state=kind,
                decomposition_share_of_stake={k: float(v / CC.STAKE_LAMPORTS) for k, v in parts.items()},
                wsol_separate_close=wsol_separate_close)


def entry_tokens(line, anchor, config, *, latency_slots=CC.LATENCY_SLOTS, buy_failures=0):
    """The tokens of the buy (H-1: the fewer of the two landing states), as exit_point computes them."""
    fees = CC.fees_from_amm_config(config)
    land = anchor.slot + latency_slots * (1 + buy_failures)
    on_input = CC.creator_side(line, anchor_index(line, anchor))
    states = [CC._state(line, fees, slot_limit=land - 1), CC._state(line, fees, slot_limit=land)]
    return min(CC._buy_on(s, fees, on_input).output_amount for s in states)


def mark_value(line, anchor, config):
    """DESCRIPTIVE mark: exact sale value of the position's tokens on the state after the last swap of `line`."""
    fees = CC.fees_from_amm_config(config)
    tokens = entry_tokens(line, anchor, config)
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    state = TL.after_swap(line.swaps[-1], fees.protocol_fee_rate, fees.fund_fee_rate)
    return CC._sell_on(state, tokens, fees, on_input).output_amount
