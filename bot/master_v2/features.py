"""Native-SOL causal features of one LaunchLab pool at a decision event (no USD, no future).

``native_features(history, facts)`` reads only ``history`` (the real curve events up
to and including the decision event, as handed to a replay strategy) and the
creation facts of the pool. Every amount is in lamports or token atoms, so no
SOL/USD rate is needed; prices are curve spot prices (lamports per token atom).

Limits, stated rather than hidden:
* wallets are the transaction fee payers of the events; a relayer or bot paying
  fees for someone else is counted as the trader;
* positions are net tokens bought minus sold on this curve by each payer; transfers
  between wallets are invisible here;
* nothing about creators' other pools is known here (see creator history inputs).
"""
from fractions import Fraction

WINDOWS_S = (10, 30, 60)


def _spot(state):
    return Fraction(state.quote_reserve, state.base_reserve)


def _ratio(numerator, denominator):
    return float(Fraction(numerator, denominator)) if denominator else 0.0


def native_features(history, facts, windows=WINDOWS_S):
    """Feature dict at ``history[-1]``; deterministic, causal by construction."""
    if not history:
        raise ValueError('empty_history')
    last = history[-1]
    creator = facts.get('creator')
    created = facts['creation_block_time']
    if type(created) is not int or type(last.block_time) is not int:
        raise ValueError('block_time_required')
    now = last.block_time
    state = last.state_after()
    spot = _spot(state)
    launch_spot = _spot(history[0].state_before())
    positions, payers_buy, payers_sell = {}, set(), set()
    creator_bought = creator_sold = 0
    buy_volume = sell_volume = 0
    peak = launch_spot
    for event in history:
        quote = event.amount_in if event.side == 'buy' else event.amount_out + event.total_fee
        if event.side == 'buy':
            positions[event.fee_payer] = positions.get(event.fee_payer, 0) + event.amount_out
            payers_buy.add(event.fee_payer)
            buy_volume += quote
            if event.fee_payer == creator:
                creator_bought += quote
        else:
            positions[event.fee_payer] = positions.get(event.fee_payer, 0) - event.amount_in
            payers_sell.add(event.fee_payer)
            sell_volume += quote
            if event.fee_payer == creator:
                creator_sold += quote
        peak = max(peak, _spot(event.state_after()))
    sold = state.real_base
    others = sorted((amount for payer, amount in positions.items() if payer != creator and amount > 0),
                    reverse=True)
    creation_slot = facts.get('creation_slot')
    early_payers = {e.fee_payer for e in history
                    if creation_slot is not None and e.slot <= creation_slot + 1 and e.fee_payer != creator}
    features = dict(
        age_s=now - created,
        trades=len(history),
        buys=sum(e.side == 'buy' for e in history),
        sells=sum(e.side == 'sell' for e in history),
        unique_buyers=len(payers_buy - {creator}),
        unique_sellers=len(payers_sell - {creator}),
        quote_raised_lamports=state.real_quote,
        progress_ppm=state.progress_ppm,
        buy_volume_lamports=buy_volume,
        sell_volume_lamports=sell_volume,
        price_vs_launch=float(spot / launch_spot),
        drawdown_from_peak=float(1 - spot / peak) if peak else 0.0,
        creator_bought_lamports=creator_bought,
        creator_sold_lamports=creator_sold,
        creator_token_share=_ratio(max(positions.get(creator, 0), 0), sold),
        top1_token_share=_ratio(others[0] if others else 0, sold),
        top5_token_share=_ratio(sum(others[:5]), sold),
        early_slot_payers=len(early_payers),
        seconds_since_previous_trade=(now - history[-2].block_time) if len(history) > 1 else None,
    )
    for window in windows:
        recent = [e for e in history if e.block_time > now - window]
        base = next((e for e in reversed(history) if e.block_time <= now - window), None)
        reference = _spot(base.state_after()) if base is not None else launch_spot
        bought = sum(e.amount_in for e in recent if e.side == 'buy')
        sold_quote = sum(e.amount_out + e.total_fee for e in recent if e.side == 'sell')
        features[f'trades_{window}s'] = len(recent)
        features[f'buyers_{window}s'] = len({e.fee_payer for e in recent if e.side == 'buy'} - {creator})
        features[f'net_flow_{window}s_lamports'] = bought - sold_quote
        features[f'price_change_{window}s'] = float(spot / reference - 1)
    return features
