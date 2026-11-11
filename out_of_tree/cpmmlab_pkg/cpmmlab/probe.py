"""A buy then a clock sale on the CPMM pool of a migrated token: the "after migration" probe (HW1-M2).

``probe(timeline, delay_s=..., hold_s=..., window_end_time=...)`` values ONE position of 0.1 SOL:
  the buy order is sent ``delay_s`` seconds after the creation of the pool and lands ``latency_s`` later;
  the sale is sent ``hold_s`` seconds after that landing and lands ``latency_s`` later.
Both are clock orders: nothing is decided from what happens after the creation of the pool, so the
probe has no selection of its own (it measures the drift an unconditional buyer meets).

Arithmetic: ``cpmmx.curve`` (the program's integer rules) on the reserves the program logged
(``cpmmx.timeline.reserves_at``). Fee rates: given from the pool's AmmConfig, else read causally
from the swaps executed before each landing; when something is not known the choice that is worse
for us is kept, and when a value cannot be established the block carries an ``unpriced_*`` status
and NO number.

Approximations (each one lowers or leaves unchanged the value kept):
  P-1 the sale is valued on the real reserves: the lift our own purchase gave to the price is not carried
      (first order: about twice our share of the quote reserve is lost in the round trip);
  P-2 the order inside the landing second is unknown: before and after that second's real swaps are both
      computed, for the buy (fewer tokens kept) and for the sale (lower value kept);
  P-3 our two orders are our only trades; the other traders' swaps are taken as they happened;
  P-4 unknown creator-fee side or unknown protocol and fund shares: the worse bound is kept;
  P-5 layouts and arithmetic are checked on synthetic data and on 280 public swaps only: criterion A-12
      is not passed on a real sample, so nothing here can be credited to a strategy.
"""
from cpmmx import curve, timeline as ct

from cpmmlab import VERSION

SCHEMA = 'cpmmlab-probe-v0.1-experimental'
STAKE_LAMPORTS = 100_000_000
TX_COST_LAMPORTS = 105_000
APPROXIMATIONS = ('P-1 own price impact not carried to the sale', 'P-2 lower of the two orders inside each landing second',
                  'P-3 our two orders only; real swaps as observed', 'P-4 worse bound for unknown fee side or shares',
                  'P-5 not validated on a real sample (A-12 open)')
_FEE_NOT_READABLE = ('no_exact_input_swap', 'no_fee_bearing_swap')


def fee_candidates(done, side, given):
    """([(Fees, creator_fee_on_input)], source) our ``side`` may face, from the swaps already executed."""
    if given is not None:
        return [tuple(given)], 'given'
    try:
        fees, on_input, _ = ct.infer_fees(done, side)
        return [(fees, on_input)], f'{side}_swaps_before_landing'
    except ct.TimelineError as exc:
        if not str(exc).startswith(_FEE_NOT_READABLE):
            raise
    other = 'sell' if side == 'buy' else 'buy'
    fees, _on_input, _ = ct.infer_fees(done, other)             # one AmmConfig: the same rates in both directions
    if not fees.creator_fee_rate:
        return [(fees, True)], f'{other}_swaps_before_landing'
    return [(fees, True), (fees, False)], f'{other}_swaps_before_landing_creator_fee_side_unknown'


def _state(timeline, limit, protocol_fee_rate, fund_fee_rate):
    base, quote, evidence = ct.reserves_at(timeline, time_limit=limit, protocol_fee_rate=protocol_fee_rate,
                                           fund_fee_rate=fund_fee_rate)
    if evidence.get('lp_change_follows'):
        raise ct.TimelineError('lp_change_at_the_landing_point')
    return base, quote, evidence


def buy_tokens(timeline, stake, limit, given=None, *, protocol_fee_rate=None, fund_fee_rate=None):
    """(tokens, evidence) for ``stake`` lamports landing once every swap with block_time <= limit has executed."""
    done = ct.executed(timeline, time_limit=limit)
    candidates, source = fee_candidates(done, 'buy', given)
    base, quote, evidence = _state(timeline, limit, protocol_fee_rate, fund_fee_rate)
    slack = evidence.get('input_side_overstated_by_at_most', 0)
    if slack and evidence['last_side'] == 'sell':
        base -= slack                                           # the base reserve may be lower: fewer tokens for us
    best = None
    for fees, on_input in candidates:
        got = curve.swap_base_input(stake, quote, base, fees, on_input)
        if best is None or got.output_amount < best[0]:
            best = got.output_amount, dict(evidence, fee_source=source, base_reserve=base, quote_reserve=quote,
                                           trade_fee=got.trade_fee, creator_fee=got.creator_fee,
                                           creator_fee_on_input=on_input, trade_fee_rate=fees.trade_fee_rate,
                                           creator_fee_rate=fees.creator_fee_rate)
    return best


def sell_value(timeline, tokens, limit, given=None, *, protocol_fee_rate=None, fund_fee_rate=None):
    """(lamports, evidence) for selling ``tokens`` at that landing limit; the lowest over the fee candidates."""
    done = ct.executed(timeline, time_limit=limit)
    candidates, source = fee_candidates(done, 'sell', given)
    _state(timeline, limit, protocol_fee_rate, fund_fee_rate)
    best = None
    for fees, on_input in candidates:
        value, evidence = ct.sell_value(timeline, tokens, fees, on_input, time_limit=limit,
                                        protocol_fee_rate=protocol_fee_rate, fund_fee_rate=fund_fee_rate)
        if best is None or value < best[0]:
            best = value, dict(evidence, fee_source=source)
    return best


def _lower(function, limit):
    """P-2: the lower result of the two orders inside the landing second, both published."""
    after, before = function(limit), function(limit - 1)
    kept = before if before[0] < after[0] else after
    return kept[0], dict(kept[1], by_order_in_landing_second=dict(after=after[0], before=before[0]),
                         kept_order='before' if kept is before else 'after')


def probe(timeline, *, delay_s, hold_s, window_end_time, stake=STAKE_LAMPORTS, latency_s=1,
          tx_cost=TX_COST_LAMPORTS, buy_fees=None, sell_fees=None, protocol_fee_rate=None, fund_fee_rate=None):
    """The block of one probe; ``status`` 'closed' carries the numbers, any other status carries none."""
    for name, value in (('delay_s', delay_s), ('hold_s', hold_s), ('latency_s', latency_s), ('stake', stake),
                        ('tx_cost', tx_cost), ('window_end_time', window_end_time)):
        if type(value) is not int or value < 0:
            raise ValueError(f'invalid_{name}')
    if latency_s < 1 or hold_s < 1 or stake < 1:
        raise ValueError('latency_hold_and_stake_are_at_least_one')
    if (protocol_fee_rate is None) != (fund_fee_rate is None):
        raise ValueError('protocol_and_fund_rates_go_together')
    block = dict(schema=SCHEMA, version=VERSION, status=None, delay_s=delay_s, hold_s=hold_s, latency_s=latency_s,
                 stake=stake, validated_on_real_swaps=False, creditable=False, approximations=list(APPROXIMATIONS))

    def stop(status, **more):
        block.update(status=status, **more)
        return block

    if timeline.opened is None:
        return stop('unpriced_pool_creation_unknown')
    if any(s.event.input_transfer_fee or s.event.output_transfer_fee for s in timeline.swaps):
        return stop('unpriced_token_transfer_fee')
    if timeline.skipped:
        return stop('unpriced_undecoded_transactions', undecoded=len(timeline.skipped))
    buy_landing = timeline.opened[1] + delay_s + latency_s
    sell_landing = buy_landing + hold_s + latency_s
    block.update(buy_landing_time=buy_landing, sell_landing_time=sell_landing)
    if sell_landing > window_end_time:
        return stop('outside_the_collected_window')
    rates = dict(protocol_fee_rate=protocol_fee_rate, fund_fee_rate=fund_fee_rate)
    try:
        tokens, bought = _lower(lambda limit: buy_tokens(timeline, stake, limit, buy_fees, **rates), buy_landing)
        value, sold = _lower(lambda limit: sell_value(timeline, tokens, limit, sell_fees, **rates), sell_landing)
        instant, _ = sell_value(timeline, tokens, buy_landing, sell_fees, **rates)
    except (ct.TimelineError, curve.CurveError) as exc:
        reason = str(exc)
        status = ('unpriced_fee_rate_not_observable_yet' if reason.startswith(_FEE_NOT_READABLE)
                  else 'unpriced_lp_change' if reason.startswith('lp_change') else 'unpriced_no_cpmm_state')
        return stop(status, reason=reason)
    cost = stake + 2 * tx_cost
    return stop('closed', tokens=tokens, value=value, cost=cost, pnl_before_rent=value - cost,
                instant_round_trip_value=instant, drift_lamports=value - instant, buy=bought, sell=sold,
                own_share_of_quote_reserve_ppm=stake * 1_000_000 // bought['quote_reserve'])


def net_return(block, rent_lamports):
    """(proceeds - cost - rent lost) / (cost + rent lost); None when the probe is not closed."""
    if block['status'] != 'closed':
        return None
    return (block['value'] - block['cost'] - rent_lamports) / (block['cost'] + rent_lamports)
