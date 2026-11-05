"""Bind an indicative sell quote to the earlier buy's inventory scenario.

This is an offline evidence bridge, not an entry policy or a fill simulator.
The caller must verify journal integrity. A current provider sell quote neither
acquires inventory nor applies our hypothetical buy to the provider's bank.
"""
from copy import deepcopy

from bot.p3.accounting import InsufficientAccountingData, native_sol_round_trip
from bot.p3.quotes import SOL_MINT, _atomic, _mint
from bot.p3.replay import replay_quote_observation


class _Unqualified(ValueError):
    pass


def _integer(value, reason):
    if type(value) is not int or value < 0:
        raise _Unqualified(reason)
    return value


def _retained_quote(event, side):
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
    return quote


def _observation(event, side, decision_at_ms, max_age_ms):
    quote = _retained_quote(event, side)
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


def inventory_from_buy(buy_event, *, basis='expected_buy_output', token_decimals,
                       entry_decision_at_ms, max_source_age_ms):
    """Retain a projected PAPER lot; never attest an executed acquisition.

    Unknown/stale provider source context does not erase a valid quoted amount.
    It is retained as an explicitly unqualified projection and cannot pass the
    strict exit bridge. Locally inconsistent chronology is always rejected.
    The caller must separately verify journal integrity and persist the result.
    """
    result = dict(schema='p3-projected-inventory-v1', accepted=False, mint=None,
        acquired_atomic=None, remaining_atomic=None, expected_atomic=None,
        minimum_atomic=None, budget_lamports=None, buy_observation=None,
        entry_decision_at_ms=None, basis=basis if type(basis) is str else None,
        token_decimals=None, provenance=None, source_timing_qualified=False,
        acquisition_verified=False, execution_verified=False, reasons=[])
    try:
        if basis not in ('expected_buy_output', 'minimum_buy_output'):
            raise _Unqualified('inventory_scenario_must_be_explicit')
        if token_decimals is not None and (type(token_decimals) is not int or not 0 <= token_decimals <= 255):
            raise _Unqualified('invalid_token_decimals')
        entry = _integer(entry_decision_at_ms, 'entry_decision_time_unknown')
        age = _integer(max_source_age_ms, 'source_age_policy_missing')
        buy = _retained_quote(buy_event, 'buy')
        requested = _integer(buy.get('requested_at_ms'), 'buy_request_time_unknown')
        receipt = _integer(buy_event.get('received_at_ms'), 'buy_receipt_time_unknown')
        available = _integer(buy_event.get('available_at_ms'), 'buy_availability_time_unknown')
        source, slot = buy.get('source_time_ms'), buy.get('source_slot')
        if (receipt != buy.get('received_at_ms') or source != buy_event.get('source_time_ms')
                or slot != buy_event.get('source_slot')
                or not requested <= receipt <= available <= entry
                or 'provider_source_time_invalid' in buy.get('quality_flags', ())):
            raise _Unqualified('buy_temporal_evidence_inconsistent')
        limitations = []
        if source is None:
            limitations.append('buy_source_time_unknown')
        else:
            _integer(source, 'buy_source_time_unknown')
            if source > receipt:
                raise _Unqualified('buy_temporal_evidence_inconsistent')
            if entry-source > age:
                limitations.append('buy_quote_stale_at_decision')
        if slot is None:
            limitations.append('buy_source_slot_unknown')
        else:
            _integer(slot, 'buy_source_slot_unknown')
        try:
            mint = _mint(buy['output_mint'])
            expected = int(_atomic(buy['output_amount_atomic']))
            minimum = int(_atomic(buy['min_output_amount_atomic'], zero=True))
            budget = int(_atomic(buy['input_amount_atomic']))
        except (ValueError, KeyError, TypeError):
            raise _Unqualified('invalid_quote_inventory_or_amount') from None
        if buy.get('input_mint') != SOL_MINT or mint == SOL_MINT or buy_event.get('mint') != mint:
            raise _Unqualified('buy_mint_identity_mismatch')
        provenance = buy_event.get('provenance')
        if provenance not in ('live', 'synthetic', 'historical_replay'):
            raise _Unqualified('buy_observation_provenance_unknown')
        if buy.get('actual_input_amount_atomic') is None:
            raise _Unqualified('buy_actual_input_unknown')
        try:
            actual = int(_atomic(buy['actual_input_amount_atomic']))
        except (ValueError, TypeError):
            raise _Unqualified('invalid_quote_inventory_or_amount') from None
        if actual != budget:
            raise _Unqualified('buy_actual_input_adjusted_budget_ambiguous')
        if minimum > expected:
            raise _Unqualified('buy_minimum_exceeds_expected_output')
        acquired = expected if basis == 'expected_buy_output' else minimum
        if acquired == 0:
            raise _Unqualified('buy_has_no_positive_minimum_inventory')
        result.update(accepted=True, mint=mint, acquired_atomic=str(acquired),
            remaining_atomic=str(acquired), expected_atomic=str(expected),
            minimum_atomic=str(minimum), budget_lamports=str(budget),
            buy_observation=deepcopy(buy_event), entry_decision_at_ms=entry,
            token_decimals=token_decimals, provenance=provenance,
            source_timing_qualified=not limitations, reasons=limitations)
    except _Unqualified as error:
        result['reasons'].append(str(error))
    return result


def qualify_inventory_exit(inventory, sell_event, *, requested_quantity_atomic,
                           exit_decision_at_ms, max_source_age_ms):
    """Qualify one exact-size exit against a retained projected lot/remainder.

    A partial quote is never rescaled. Acceptance only describes a conditional
    PAPER scenario, not a fill, disposal or ledger mutation. The caller must
    serialize/recheck the remaining inventory before applying a unique receipt.
    Additional execution fees are deliberately left to the existing accounting
    layer; no net P&L is computed here.
    """
    result = dict(schema='p3-inventory-exit-qualification-v1', accepted=False,
        qualification='UNQUALIFIED', quantity_atomic=None, q=None,
        proceeds_lamports=None, minimum_proceeds_lamports=None,
        remaining_after_atomic=None, coverage=None, mint=None, provenance=None,
        acquisition_verified=False, execution_verified=False,
        full_position_closure_verified=False, net_economic_pnl_sol=None,
        reason=None, reasons=[])
    try:
        if type(inventory) is not dict:
            raise _Unqualified('persisted_inventory_missing')
        entry = _integer(inventory.get('entry_decision_at_ms'), 'entry_decision_time_unknown')
        exit_at = _integer(exit_decision_at_ms, 'exit_decision_time_unknown')
        age = _integer(max_source_age_ms, 'source_age_policy_missing')
        if exit_at < entry:
            raise _Unqualified('exit_decision_precedes_entry_decision')
        restored = inventory_from_buy(inventory.get('buy_observation'),
            basis=inventory.get('basis'), token_decimals=inventory.get('token_decimals'),
            entry_decision_at_ms=entry, max_source_age_ms=age)
        if not restored['accepted']:
            raise _Unqualified(restored['reasons'][0])
        try:
            acquired = int(_atomic(inventory.get('acquired_atomic')))
            remaining = int(_atomic(inventory.get('remaining_atomic'), zero=True))
        except (ValueError, TypeError):
            raise _Unqualified('invalid_persisted_inventory_quantity') from None
        if (str(acquired) != restored['acquired_atomic']
                or inventory.get('mint', restored['mint']) != restored['mint']
                or inventory.get('provenance', restored['provenance']) != restored['provenance']):
            raise _Unqualified('persisted_inventory_does_not_match_buy_scenario')
        if remaining > acquired:
            raise _Unqualified('remaining_inventory_exceeds_acquired_quantity')
        try:
            quantity = int(_atomic(requested_quantity_atomic))
        except (ValueError, TypeError):
            raise _Unqualified('invalid_requested_exit_quantity') from None
        if quantity > remaining:
            raise _Unqualified('requested_exit_exceeds_remaining_inventory')
        buy, _, buy_available, buy_slot = _observation(
            inventory['buy_observation'], 'buy', entry, age)
        sell, sell_requested, _, sell_slot = _observation(sell_event, 'sell', exit_at, age)
        if buy_available > sell_requested or entry > sell_requested:
            raise _Unqualified('sell_quantity_requested_before_buy_inventory_known')
        if sell_slot < buy_slot:
            raise _Unqualified('sell_source_context_precedes_buy_context')
        mint, provenance = restored['mint'], restored['provenance']
        if (sell.get('input_mint') != mint or sell.get('output_mint') != SOL_MINT
                or sell_event.get('mint') != mint):
            raise _Unqualified('round_trip_mint_identity_mismatch')
        if sell_event.get('provenance') != provenance:
            raise _Unqualified('missing_or_mixed_observation_provenance')
        try:
            sold = int(_atomic(sell['input_amount_atomic']))
            proceeds = int(_atomic(sell['output_amount_atomic']))
            minimum_proceeds = int(_atomic(sell['min_output_amount_atomic'], zero=True))
        except (ValueError, KeyError, TypeError):
            raise _Unqualified('invalid_quote_inventory_or_amount') from None
        if sold != quantity:
            raise _Unqualified('sell_quote_size_does_not_match_requested_inventory')
        if sell.get('actual_input_amount_atomic') is None:
            raise _Unqualified('sell_actual_input_unknown')
        try:
            actual = int(_atomic(sell['actual_input_amount_atomic']))
        except (ValueError, TypeError):
            raise _Unqualified('invalid_quote_inventory_or_amount') from None
        if actual != quantity:
            raise _Unqualified('sell_actual_input_adjusted_inventory_ambiguous')
        result.update(accepted=True, qualification='CONDITIONAL_INVENTORY_QUOTE_ONLY',
            quantity_atomic=str(quantity), q=str(quantity), proceeds_lamports=str(proceeds),
            minimum_proceeds_lamports=str(minimum_proceeds),
            remaining_after_atomic=str(remaining-quantity),
            coverage='full_remaining' if quantity == remaining else 'partial_remaining',
            mint=mint, provenance=provenance)
    except _Unqualified as error:
        result['reason'] = str(error)
        result['reasons'].append(str(error))
    return result


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
