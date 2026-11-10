"""The post-migration sale of a position v4sim 0.2 leaves ``migrated_unpriced``.

``replay`` calls ``v4sim.engine.replay`` with the same arguments and returns its result unchanged,
plus one attribute, ``result.cpmm`` (the block built by ``settle``). A position is priced only when
every input was read: the pool's creation point, a pool state at the landing point, and the fee
rates (given from the pool's AmmConfig, or read causally from swaps logged before the landing).
Otherwise the block carries an ``unpriced_*`` status and no number.
"""
from bot.market.launchlab_curve import fee_for
from bot.market.replay import ExecutionModel, Position

from cpmmx import curve, timeline as cpmm_timeline
from v4sim import engine
from v4sim.engine import Execution

from v4cpmm import VERSION

SCHEMA = 'v4cpmm-exit-v0.1-experimental'
RULES = ('at_open', 'strategy_clock')
APPROXIMATIONS = (
    'X-1 the real CPMM reserves are used as observed; the value with the demand our curve purchase displaced onto '
    'the pool is published next to it and the lower of the two is kept',
    'X-2 after the migration two exits exist: sell when the pool opens, or at the clock deadline of the strategy; '
    'stop and trailing exits are not evaluated on CPMM prices',
    'X-3 our sale is our only trade on the pool: no real swap is replayed after it',
    'X-4 fee rates are given from the AmmConfig or read causally from logged swaps; with an unknown creator-fee '
    'side or unknown protocol and fund shares, the value that is worse for the seller is kept',
    'X-5 event layouts and arithmetic are checked on synthetic data only: A-12 is not passed on real swaps',
    'X-6 the order inside the landing slot is unknown: the value before and after that slot\'s real swaps are both '
    'published and the lower is kept',
)


def _minimum(reference, slippage_bps):                       # same rounding as v4sim.engine
    return -(-reference * (10_000 - slippage_bps) // 10_000)


def _fee_candidates(done, given):
    """[(Fees, creator_fee_on_input)] a sale may face, and where they were read."""
    if given is not None:
        return [tuple(given)], 'given'
    try:
        fees, on_input, _ = cpmm_timeline.infer_fees(done, 'sell')
        return [(fees, on_input)], 'sell_swaps_before_landing'
    except cpmm_timeline.TimelineError as exc:
        if not str(exc).startswith(('no_exact_input_swap', 'no_fee_bearing_swap')):
            raise
    fees, _, _ = cpmm_timeline.infer_fees(done, 'buy')         # one AmmConfig: same rates in both directions
    if not fees.creator_fee_rate:
        return [(fees, True)], 'buy_swaps_before_landing'
    return [(fees, True), (fees, False)], 'buy_swaps_before_landing_creator_fee_side_unknown'


def settle(result, events, cpmm, model, *, execution=Execution(), rule='at_open', strategy=None, fees=None,
           protocol_fee_rate=None, fund_fee_rate=None):
    """The ``cpmm`` block of a v4sim result. ``cpmm``: a ``cpmmx.timeline.Timeline`` built with ``opened``.

    The execution options are those of the v4sim run (``execution``, ``model``): nothing is tuned for CPMM.
    rule 'at_open'        the order is sent when the pool is created and lands ``latency_slots`` later;
    rule 'strategy_clock' it lands at ``strategy.exit_deadline(position) + clock_exit_latency_s``; when the
                          deadline is already past at the creation of the pool, as 'at_open'.
    ``fees``: (cpmmx.curve.Fees, creator_fee_on_input) of a sale, read from the pool's on-chain config.
    """
    if rule not in RULES:
        raise ValueError('unknown_rule')
    block = dict(schema=SCHEMA, version=VERSION, rule=rule, status=None, validated_on_real_swaps=False,
                 approximations=list(APPROXIMATIONS), failed_attempts=[], added_tx_costs=0)

    def stop(status, **more):
        block.update(status=status, **more)
        return block

    if result.outcome != 'migrated_unpriced' or not result.tokens:
        return stop('not_applicable')
    if cpmm is None:
        return stop('unpriced_no_cpmm_timeline')
    if cpmm.opened is None:
        return stop('unpriced_pool_creation_unknown')
    if any(s.event.input_transfer_fee or s.event.output_transfer_fee for s in cpmm.swaps):
        return stop('unpriced_token_transfer_fee')
    opened_slot, opened_time = cpmm.opened
    if opened_slot < events[-1].slot:
        raise ValueError('cpmm_pool_opens_before_the_curve_ends')
    entry = events[result.entry_index]
    position = Position(result.entry_index, entry.slot, entry.block_time, result.spent, result.tokens)
    deadline = None
    if rule == 'strategy_clock':
        if getattr(strategy, 'exit_deadline', None) is None or model.clock_exit_latency_s is None:
            raise ValueError('strategy_clock_needs_exit_deadline_and_clock_exit_latency_s')
        deadline = strategy.exit_deadline(position)
        if type(deadline) is not int:
            raise ValueError('strategy_has_no_clock_deadline')
    if deadline is not None and deadline >= opened_time:
        name, trigger, landing, step = 'time_limit', deadline, deadline + model.clock_exit_latency_s, \
            model.clock_exit_latency_s or 1
    else:
        name, trigger, landing, step = 'slot_limit', opened_slot, opened_slot + model.latency_slots, \
            model.latency_slots

    net_curve_quote = result.spent - fee_for(result.spent, result.fee_rate_ppm)

    def one(limit):
        """Value at one landing limit: the lowest over the fee candidates, and over X-1's two variants."""
        done = cpmm_timeline.executed(cpmm, **{name: limit})
        candidates, source = _fee_candidates(done, fees)
        best = None
        for candidate, on_input in candidates:
            value, evidence = cpmm_timeline.sell_value(cpmm, result.tokens, candidate, on_input, **{name: limit},
                                                       protocol_fee_rate=protocol_fee_rate,
                                                       fund_fee_rate=fund_fee_rate)
            # X-1 (H-5): the quote we put on the curve reaches the pool as a purchase by the buyers we displaced.
            base, quote = evidence['base_reserve'], evidence['quote_reserve']
            displaced = curve.swap_base_input(net_curve_quote, quote, base, candidate, on_input)
            quote_after, base_after = curve.reserves_after(quote, base, displaced)
            other = curve.swap_base_input(result.tokens, base_after, quote_after, candidate, on_input).output_amount
            kept = min(value, other)
            if best is None or kept < best[0]:
                best = kept, dict(evidence, fee_source=source, value_on_real_reserves=value,
                                  value_with_displaced_demand=other)
        return best

    def value_at(limit):
        """H-1: our order may execute before or after the real swaps of its landing slot; the lower value is kept."""
        after, before = one(limit), one(limit - 1)
        kept = before if before[0] < after[0] else after
        return kept[0], dict(kept[1], value_by_order_in_landing_slot=dict(after=after[0], before=before[0]),
                             kept_order='before' if kept is before else 'after')

    reference = None
    if execution.slippage_bps is not None:
        try:
            reference = one(trigger)[0]                       # what the order expected when it was sent
        except (cpmm_timeline.TimelineError, curve.CurveError) as exc:
            # No value could be expected when the order was sent: the limit cannot be applied, and it is said.
            block['slippage_limit_not_applied'] = str(exc)
        block['slippage_reference'] = reference
    lost = model.base_fee_lamports if execution.non_inclusion_fee == 'base_fee' else 0
    for number in range(execution.max_retries + 1):
        kind = cost = None
        if engine.not_included(execution, result.pool, 'cpmm_sell', result.entry_index, number):
            kind, cost = 'not_included', lost
        else:
            try:
                value, evidence = value_at(landing)
            except (cpmm_timeline.TimelineError, curve.CurveError) as exc:
                reason = str(exc)
                status = ('unpriced_fee_rate_not_observable_yet' if reason.startswith(('no_exact_input_swap',
                                                                                         'no_fee_bearing_swap'))
                          else 'unpriced_no_cpmm_state')
                return stop(status, reason=reason, landing={name: landing})
            if reference and value < _minimum(reference, execution.slippage_bps):
                kind, cost = 'slippage', model.tx_cost
        if kind is None:
            added = block['added_tx_costs'] + model.tx_cost
            costs = result.tx_costs + added
            pnl = value - result.spent - costs
            spot = result.tokens * evidence['quote_reserve'] // evidence['base_reserve']
            blockers = ['a12_not_passed_on_real_swaps']
            if evidence['fee_source'] != 'given' or protocol_fee_rate is None:
                blockers.append('fee_rates_not_read_from_the_amm_config')
            block.update(creditable=False, credit_blockers=blockers)
            return stop('sold', received=value, added_tx_costs=added, total_tx_costs=costs, pnl_lamports=pnl,
                        net_return=pnl / (result.spent + costs), landing={name: landing}, attempt=number,
                        evidence=evidence, value_without_impact_or_fee=spot,
                        own_share_of_base_reserve_ppm=result.tokens * 1_000_000 // evidence['base_reserve'],
                        last_curve_value=(getattr(result, 'v4', None) or {}).get('last_curve_value'))
        block['failed_attempts'].append(dict(attempt=number, kind=kind, cost=cost, landing={name: landing}))
        block['added_tx_costs'] += cost
        landing += step
    return stop('unsold_exit_retries_exhausted')


def replay(timeline, strategy, model=ExecutionModel(), *, quote_mint, mode='M-P', execution=Execution(), actors=None,
           cpmm=None, rule='at_open', fees=None, protocol_fee_rate=None, fund_fee_rate=None):
    """``v4sim.engine.replay`` unchanged, then ``result.cpmm`` for a position it leaves ``migrated_unpriced``."""
    result = engine.replay(timeline, strategy, model, quote_mint=quote_mint, mode=mode, execution=execution,
                           actors=actors)
    result.cpmm = settle(result, timeline.events, cpmm, model, execution=execution, rule=rule, strategy=strategy,
                         fees=fees, protocol_fee_rate=protocol_fee_rate, fund_fee_rate=fund_fee_rate)
    return result
