"""Bind an indicative sell quote to the earlier buy's inventory scenario.

This is an offline evidence bridge, not an entry policy or a fill simulator.
The caller must verify journal integrity. A current provider sell quote neither
acquires inventory nor applies our hypothetical buy to the provider's bank.
"""
from bot.p3.accounting import InsufficientAccountingData, native_sol_round_trip
from bot.p3.quotes import SOL_MINT, _atomic, _mint
from bot.p3.replay import replay_quote_observation


class _Unqualified(ValueError):
    pass


def _integer(value, reason):
    if type(value) is not int or value < 0:
        raise _Unqualified(reason)
    return value


def _observation(event, side, decision_at_ms, max_age_ms):
    if type(event) is not dict or event.get('kind') != 'quote_attempt':
        raise _Unqualified(side+'_observation_missing')
    quote = event.get('payload')
    if type(quote) is not dict or quote.get('quote_side') != side:
        raise _Unqualified(side+'_observation_side_mismatch')
    if event.get('outcome') != 'quoted' or quote.get('outcome') != 'quoted':
        raise _Unqualified(side+'_quote_unavailable')
    if quote.get('provider') != 'raydium_trade_api':
        raise _Unqualified(side+'_quote_provider_unsupported')
    try:
        replay = replay_quote_observation(event)
    except (ValueError, KeyError, TypeError):
        raise _Unqualified(side+'_quote_replay_failed') from None
    if replay['status'] != 'REPLAYED':
        raise _Unqualified(side+'_quote_body_missing')
    requested = _integer(quote.get('requested_at_ms'), side+'_request_time_unknown')
    receipt = _integer(event.get('received_at_ms'), side+'_receipt_time_unknown')
    available = _integer(event.get('available_at_ms'), side+'_availability_time_unknown')
    source = _integer(quote.get('source_time_ms'), side+'_source_time_unknown')
    slot = _integer(quote.get('source_slot'), side+'_source_slot_unknown')
    if (receipt != quote.get('received_at_ms') or source != event.get('source_time_ms')
            or slot != event.get('source_slot')
            or not requested <= receipt <= available <= decision_at_ms
            or source > receipt):
        raise _Unqualified(side+'_temporal_evidence_inconsistent')
    if decision_at_ms-source > max_age_ms:
        raise _Unqualified(side+'_quote_stale_at_decision')
    return quote, requested, available, slot


def qualify_exit_quote_pair(buy_observation, sell_observation, *, inventory_basis,
                            entry_decision_at_ms, exit_decision_at_ms,
                            max_source_age_ms, fees, available_cash_lamports):
    """Qualify an expected/minimum inventory scenario without assuming a fill.

    ``expected_buy_output`` is explicitly conditional on receiving that expected
    quantity. ``minimum_buy_output`` checks the slippage floor; when it differs
    from expected output, selling it cannot certify closure of the whole
    position, and no full-position P&L is emitted. A size-mismatched sell is never
    scaled linearly to another quantity. Unknown source times/costs fail closed.
    """
    result = {'schema': 'p3-exit-quote-qualification-v1', 'qualification': 'UNQUALIFIED',
              'inventory_basis': inventory_basis if type(inventory_basis) is str else None, 'quote_size_matches_inventory_scenario': False,
              'inventory_acquired': False, 'full_position_closure_verified': False,
              'hypothetical_entry_impact_applied': False, 'execution_verified': False,
              'model_eligible': False, 'economic_verdict': 'INSUFFICIENT DATA',
              'net_economic_pnl_sol': None, 'conditional_accounting_projection': None,
              'reasons': []}
    try:
        if inventory_basis not in ('expected_buy_output', 'minimum_buy_output'):
            raise _Unqualified('inventory_scenario_must_be_explicit')
        entry = _integer(entry_decision_at_ms, 'entry_decision_time_unknown')
        exit_at = _integer(exit_decision_at_ms, 'exit_decision_time_unknown')
        age = _integer(max_source_age_ms, 'source_age_policy_missing')
        if exit_at < entry:
            raise _Unqualified('exit_decision_precedes_entry_decision')
        buy, _, buy_available, buy_slot = _observation(buy_observation, 'buy', entry, age)
        sell, sell_requested, _, sell_slot = _observation(sell_observation, 'sell', exit_at, age)
        if buy_available > sell_requested or entry > sell_requested:
            raise _Unqualified('sell_quantity_requested_before_buy_inventory_known')
        if sell_slot < buy_slot:
            raise _Unqualified('sell_source_context_precedes_buy_context')
        try:
            token = _mint(buy['output_mint'])
            expected = int(_atomic(buy['output_amount_atomic']))
            minimum = int(_atomic(buy['min_output_amount_atomic'], zero=True))
            sold = int(_atomic(sell['input_amount_atomic']))
            proceeds = int(_atomic(sell['output_amount_atomic']))
            budget = int(_atomic(buy['input_amount_atomic']))
        except (ValueError, KeyError, TypeError):
            raise _Unqualified('invalid_quote_inventory_or_amount') from None
        if (buy['input_mint'] != SOL_MINT or sell['input_mint'] != token
                or sell['output_mint'] != SOL_MINT
                or buy_observation.get('mint') != token or sell_observation.get('mint') != token):
            raise _Unqualified('round_trip_mint_identity_mismatch')
        if (buy_observation.get('provenance') not in ('live', 'synthetic', 'historical_replay')
                or buy_observation.get('provenance') != sell_observation.get('provenance')):
            raise _Unqualified('missing_or_mixed_observation_provenance')
        if minimum > expected:
            raise _Unqualified('buy_minimum_exceeds_expected_output')
        quantity = expected if inventory_basis == 'expected_buy_output' else minimum
        result.update(expected_buy_output_atomic=str(expected), minimum_buy_output_atomic=str(minimum),
                      sell_input_atomic=str(sold), selected_inventory_atomic=str(quantity),
                      sell_exceeds_minimum_inventory=sold > minimum,
                      quantity_fixed_before_sell_request=True,
                      source_context_relation='same_reported_slot' if sell_slot == buy_slot else 'later_reported_slot',
                      entry_spend_basis='requested_buy_budget_upper_bound',
                      provenance=buy_observation.get('provenance'),
                      source_time_basis='retained_provider_claim_not_independent_clock_certification')
        if quantity == 0:
            raise _Unqualified('buy_has_no_positive_minimum_inventory')
        if sold != quantity:
            raise _Unqualified('sell_quote_size_does_not_match_inventory_scenario')
        result['quote_size_matches_inventory_scenario'] = True
        # An adjusted actualInputAmount may denote transfer mechanics or unused
        # input. Without that reconciliation it cannot establish disposal of the
        # selected full inventory, even when inputAmount echoes our request.
        if sell.get('actual_input_amount_atomic') is None:
            raise _Unqualified('sell_actual_input_unknown')
        if int(_atomic(sell['actual_input_amount_atomic'])) != sold:
            raise _Unqualified('sell_actual_input_adjusted_inventory_ambiguous')
        if inventory_basis == 'minimum_buy_output' and minimum != expected:
            result['qualification'] = 'MINIMUM_SIZE_MATCH_ONLY'
            raise _Unqualified('full_position_inventory_unknown_after_minimum_size_sale')
        try:
            projection = native_sol_round_trip(entry_spent_lamports=budget,
                exit_received_lamports=proceeds, acquired_token_atomic=quantity,
                sold_token_atomic=sold, token_mint=token, fees=fees,
                available_cash_lamports=available_cash_lamports)
        except InsufficientAccountingData:
            raise _Unqualified('additional_fees_or_available_cash_unqualified') from None
        result['qualification'] = 'CONDITIONAL_QUOTE_SCENARIO_ONLY'
        result['conditional_accounting_projection'] = projection
    except _Unqualified as error:
        result['reasons'].append(str(error))
    return result
