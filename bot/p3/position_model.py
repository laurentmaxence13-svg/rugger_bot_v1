"""Exact conditional own-entry/exit arithmetic on one immutable LaunchLab bank.

The observed bank never contains our entry. A separate counterfactual bank does.
An optional *hypothetical* third-party buy changes that bank before our exit;
it is neither a forecast nor a reconstruction of a later observed bank.
No wallet, transaction, quote service, ledger, source clock or fee is created.
"""
from copy import deepcopy

from bot.p3.launchlab import (SnapshotEvidenceError, _uint, _U64_MAX,
    constant_product_projection, observed_sell_projection)
from bot.p3.quotes import SOL_MINT


_AMOUNTS = ('buy_input_lamports', 'buy_output_atomic', 'buy_curve_fee_lamports',
    'buy_effective_input_lamports', 'sell_gross_output_lamports',
    'sell_curve_fee_lamports', 'sell_output_lamports', 'curve_pnl_lamports',
    'round_trip_friction_lamports', 'modeled_additional_costs_lamports',
    'modeled_net_pnl_lamports', 'break_even_extra_proceeds_lamports')


def _bank(pool, base, quote, curve_type):
    if type(pool) is not dict:
        raise SnapshotEvidenceError('pool_facts_required')
    if (type(curve_type) is not int or curve_type != 0
            or type(pool.get('status')) is not int or pool['status'] != 0
            or pool.get('mint_b') != SOL_MINT
            or type(pool.get('decimals_b')) is not int or pool['decimals_b'] != 9):
        raise SnapshotEvidenceError('active_constant_product_native_SOL_required')
    base = _uint(base, 'base_vault_atomic')
    quote = _uint(quote, 'quote_vault_lamports')
    values = {name:_uint(pool.get(name), name) for name in (
        'supply','total_sell_a','virtual_a','virtual_b','real_a','real_b',
        'total_fundraising_b','protocol_fee_accrued','platform_fee_accrued')}
    if (not values['real_a'] <= values['total_sell_a'] <= values['supply']
            or base < values['total_sell_a']-values['real_a']
            or quote < values['real_b']+values['protocol_fee_accrued']+values['platform_fee_accrued']):
        raise SnapshotEvidenceError('observed_reserves_or_vault_inventory_inconsistent')
    return deepcopy(pool), base, quote


def _state(pool, base, quote):
    # Expose only decoded model inputs. Unrelated caller keys cannot smuggle
    # floats/objects into an otherwise exact, JSON-safe mathematical report.
    names=('status','decimals_a','decimals_b','supply','total_sell_a','virtual_a',
           'virtual_b','real_a','real_b','total_fundraising_b',
           'protocol_fee_accrued','platform_fee_accrued')
    state={key:str(pool[key]) for key in names}
    state['mint_b']=SOL_MINT
    if type(pool.get('mint_a')) is str:
        state['mint_a']=pool['mint_a']
    return dict(pool=state,
        base_vault_atomic=str(base), quote_vault_min_lamports=str(quote),
        quote_vault_basis='conservative_lower_bound_with_new_curve_fees_removed_or_reserved')


def _buy(pool, base, quote, amount, rates, share):
    # The pinned legacy primitive enforces ceil fees, floor output, migration,
    # remaining supply and uint64 limits. Its observed-bank output is unchanged.
    projection = constant_product_projection(pool, input_lamports=amount,
        fee_rates_ppm=rates, base_vault_atomic=base, quote_vault_lamports=quote,
        share_fee_rate_ppm=share)
    # Even if every new curve fee stays in the physical vault temporarily, its
    # gross incoming balance must be representable. Spendable reserves below
    # use only net input; accrued historical fees are never spent.
    if quote+amount > _U64_MAX:
        raise SnapshotEvidenceError('post_buy_gross_vault_out_of_bounds')
    bought = int(projection['buy_output_atomic'])
    effective = int(projection['buy_effective_input_lamports'])
    after = deepcopy(pool)
    after['real_a'] += bought
    after['real_b'] += effective
    return projection, after, base-bought, quote+effective


def evaluate_position(pool, *, input_lamports, fee_rates_ppm, base_vault_atomic,
                      quote_vault_lamports, curve_type=0, share_fee_rate_ppm=0,
                      additional_costs_lamports=None, external_buy_lamports=0):
    """Project one full lot through own buy, optional outside buy, own sell.

    Amounts are uint64 lamports/token atoms and return as exact decimal strings.
    ``additional_costs_lamports=None`` keeps net economic PnL unknown. An explicit
    amount is a caller's hypothetical fee scenario, never measured execution
    cost. Curve fees already in sell output are not subtracted a second time.
    The external buy is a conditional reserve sensitivity, not future evidence.
    """
    result = dict(schema='p3-conditional-position-model-v1', admissible=False,
        reason=None, **dict.fromkeys(_AMOUNTS), observed_state=None,
        counterfactual_post_buy_state=None, counterfactual_pre_sell_state=None,
        counterfactual_post_sell_state=None, external_buy=None,
        cost_basis='unknown' if additional_costs_lamports is None else 'caller_hypothetical_scenario',
        additional_costs_observed=False, model_basis='single_observed_bank_then_hypothetical_flows',
        observation_kind='MODEL_SNAPSHOT_CONDITIONAL', external_service_quote=False,
        position_acquired=False, execution_verified=False, observed_future_exit_quote=False,
        strict_economic_cycle_qualified=False, net_economic_pnl_sol=None)
    try:
        amount = _uint(input_lamports,'input_lamports',positive=True)
        external = _uint(external_buy_lamports,'external_buy_lamports')
        costs = (None if additional_costs_lamports is None else
                 _uint(additional_costs_lamports,'additional_costs_lamports'))
        observed, base, quote = _bank(pool,base_vault_atomic,quote_vault_lamports,curve_type)
        result['observed_state'] = _state(observed,base,quote)
        own, post, post_base, post_quote = _buy(observed,base,quote,amount,fee_rates_ppm,share_fee_rate_ppm)
        result['counterfactual_post_buy_state'] = _state(post,post_base,post_quote)
        if external:
            other, post, post_base, post_quote = _buy(post,post_base,post_quote,external,
                                                      fee_rates_ppm,share_fee_rate_ppm)
            result['external_buy'] = dict(input_lamports=str(external),
                output_atomic=other['buy_output_atomic'],curve_fee_lamports=other['buy_curve_fee_lamports'],
                effective_input_lamports=other['buy_effective_input_lamports'],
                basis='hypothetical_third_party_buy_after_our_entry_not_a_forecast')
        result['counterfactual_pre_sell_state'] = _state(post,post_base,post_quote)
        quantity = int(own['buy_output_atomic'])
        sell = observed_sell_projection(post,input_token_atomic=quantity,
            fee_rates_ppm=fee_rates_ppm,quote_vault_lamports=post_quote,
            curve_type=curve_type,share_fee_rate_ppm=share_fee_rate_ppm)
        gross, received = int(sell['gross_output_lamports']), int(sell['output_lamports'])
        after = deepcopy(post)
        after['real_a'] -= quantity
        after['real_b'] -= gross
        # Sell curve fees are likewise excluded from the conservative spendable
        # vault; the actual raw vault can retain those accrued fees.
        after_base, after_quote = post_base+quantity, post_quote-gross
        result.update(admissible=True,buy_input_lamports=str(amount),
            buy_output_atomic=str(quantity),buy_curve_fee_lamports=own['buy_curve_fee_lamports'],
            buy_effective_input_lamports=own['buy_effective_input_lamports'],
            sell_gross_output_lamports=str(gross),sell_curve_fee_lamports=sell['curve_fee_lamports'],
            sell_output_lamports=str(received),curve_pnl_lamports=str(received-amount),
            round_trip_friction_lamports=str(amount-int(own['sell_output_lamports'])),
            curve_cash_drag_after_sensitivity_lamports=str(amount-received),
            own_curve_fees_lamports=str(int(own['buy_curve_fee_lamports'])+int(sell['curve_fee_lamports'])),
            modeled_additional_costs_lamports=None if costs is None else str(costs),
            modeled_net_pnl_lamports=None if costs is None else str(received-amount-costs),
            break_even_extra_proceeds_lamports=None if costs is None else str(max(0,amount+costs-received)),
            buy_output_shortfall_vs_spot_without_fees=own['buy_output_shortfall_vs_spot_without_fees'],
            fee_rate_total_ppm=own['fee_rate_total_ppm'],
            counterfactual_post_sell_state=_state(after,after_base,after_quote),
            sell_inventory_atomic=str(quantity),remaining_inventory_atomic='0')
        if costs is not None:
            target = amount+costs
            rate = int(own['fee_rate_total_ppm'])
            required_gross = (target*1_000_000+(1_000_000-rate)-1)//(1_000_000-rate)
            result.update(break_even_required_net_proceeds_lamports=str(target),
                break_even_required_gross_proceeds_lamports=str(required_gross),
                break_even_required_gross_within_uint64=required_gross <= _U64_MAX,
                break_even_required_gross_growth_ratio={
                    'numerator':str(required_gross), 'denominator':str(gross)})
    except (SnapshotEvidenceError,ValueError,TypeError,KeyError,OverflowError) as error:
        result['reason'] = str(error) if isinstance(error,SnapshotEvidenceError) else 'malformed_position_model'
    return result


_HIGH_BUY_FAILURES = frozenset(('buy_crosses_fundraising_or_remaining_boundary',
    'base_vault_cannot_cover_buy','post_buy_reserves_out_of_bounds',
    'post_buy_gross_vault_out_of_bounds'))
_LOW_BUY_FAILURES = frozenset(('buy_output_rounds_to_zero','input_consumed_by_fee'))


def minimum_external_buy_for_break_even(pool, *, max_external_buy_lamports,
                                       additional_costs_lamports, **kwargs):
    """Find the smallest hypothetical outside buy covering this lot's costs.

    At most128 binary-search steps plus four boundary evaluations over uint64. Fixed
    curve fees make net input and exit proceeds nondecreasing in the outside
    buy; rounding plateaus are retained. A boundary/migration limit is a domain
    cap, not an extrapolated profitable exit. No inferred market demand is used.
    """
    answer = dict(schema='p3-conditional-break-even-flow-v1',found=False,
        minimum_external_buy_lamports=None,reason=None,evaluations=0,
        additional_costs_basis='caller_hypothetical_scenario',
        execution_verified=False,strict_economic_cycle_qualified=False)
    try:
        maximum = _uint(max_external_buy_lamports,'max_external_buy_lamports')
        _uint(additional_costs_lamports,'additional_costs_lamports')
    except SnapshotEvidenceError as error:
        answer['reason'] = str(error)
        return answer
    def trial(amount):
        answer['evaluations'] += 1
        return evaluate_position(pool,additional_costs_lamports=additional_costs_lamports,
            external_buy_lamports=amount,**kwargs)
    baseline = trial(0)
    if not baseline['admissible']:
        answer['reason'] = baseline['reason']
        return answer
    if int(baseline['modeled_net_pnl_lamports']) >= 0:
        answer.update(found=True,minimum_external_buy_lamports='0',
            modeled_net_pnl_lamports=baseline['modeled_net_pnl_lamports'])
        return answer
    if maximum == 0:
        answer['reason'] = 'break_even_not_reached_within_registered_flow_cap'
        return answer
    ceiling = trial(maximum)
    if not ceiling['admissible'] and ceiling['reason'] in _HIGH_BUY_FAILURES:
        low, high = 0, maximum
        while low < high:
            mid = (low+high+1)//2
            result = trial(mid)
            if not result['admissible'] and result['reason'] in _HIGH_BUY_FAILURES:
                high = mid-1
            else:
                low = mid
        maximum = low
        ceiling = trial(maximum)
    if not ceiling['admissible']:
        answer['reason'] = ('no_admissible_external_buy_within_registered_flow_cap'
            if ceiling['reason'] in _LOW_BUY_FAILURES else ceiling['reason'])
        return answer
    answer['largest_admissible_external_buy_lamports'] = str(maximum)
    if int(ceiling['modeled_net_pnl_lamports']) < 0:
        answer['reason'] = 'break_even_not_reached_within_registered_flow_cap'
        return answer
    low, high = 1, maximum
    while low < high:
        mid = (low+high)//2
        result = trial(mid)
        if result['admissible'] and int(result['modeled_net_pnl_lamports']) >= 0:
            high = mid
        elif result['admissible'] or result['reason'] in _LOW_BUY_FAILURES:
            low = mid+1
        else:
            answer['reason'] = result['reason']
            return answer
    final = trial(low)
    answer.update(found=True,minimum_external_buy_lamports=str(low),
        modeled_net_pnl_lamports=final['modeled_net_pnl_lamports'],
        sell_output_lamports=final['sell_output_lamports'])
    return answer
