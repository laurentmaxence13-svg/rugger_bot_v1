"""Non-operational indicative quote cycles with explicitly conditional inventory.

Missing actual-fill/source-clock fields do not erase a provider's quoted output.
They also never become a fill, a qualified position or permission to trade. This
module has no HTTP, wallet or ledger operation and does not alter strict bridges.
"""
from copy import deepcopy

from bot.p3.cohort import _verified_capture_events
from bot.p3.exit_qualification import _retained_quote
from bot.p3.quotes import SOL_MINT, _atomic, _mint


_MAX_AGE_MS = 5000
_COST_SCENARIOS = (0, 5000, 100000, 1000000)


class _Rejected(ValueError):
    pass


def _integer(value, reason):
    if type(value) is not int or value < 0:
        raise _Rejected(reason)
    return value


def _quote(event, side, decision_at_ms, *, allow_stale=False):
    try:
        quote = _retained_quote(event, side)
    except ValueError as error:
        raise _Rejected(str(error)) from None
    requested = _integer(quote.get('requested_at_ms'), side+'_request_time_unknown')
    receipt = _integer(event.get('received_at_ms'), side+'_receipt_time_unknown')
    available = _integer(event.get('available_at_ms'), side+'_availability_time_unknown')
    decision = _integer(decision_at_ms, side+'_decision_time_unknown')
    source, slot = quote.get('source_time_ms'), quote.get('source_slot')
    if (quote.get('received_at_ms') != receipt
            or event.get('source_time_ms') != source or event.get('source_slot') != slot
            or not requested <= receipt <= available <= decision
            or 'provider_source_time_invalid' in quote.get('quality_flags', ())):
        raise _Rejected(side+'_local_or_source_chronology_inconsistent')
    if event.get('provenance') not in ('live', 'synthetic', 'historical_replay'):
        raise _Rejected(side+'_provenance_unknown')
    limitations = []
    if source is None:
        limitations.append(side+'_source_time_unknown')
    else:
        source = _integer(source, side+'_source_time_unknown')
        if source > receipt:
            raise _Rejected(side+'_source_clock_in_future')
        if decision-source > _MAX_AGE_MS:
            if not allow_stale:
                raise _Rejected(side+'_source_quote_stale')
            limitations.append(side+'_source_quote_stale')
    if slot is None:
        limitations.append(side+'_source_slot_unknown')
    else:
        _integer(slot, side+'_source_slot_unknown')
    return quote, limitations


def projected_research_inventory(buy_event, *, decision_at_ms):
    """Keep the exact expected quote output without certifying any acquisition.

    The input budget remains the quoted request, not an observed spend. Missing
    actualInputAmount is an UNKNOWN about a hypothetical fill; explicit adjusted
    input is rejected because the intended exact-size scenario is ambiguous.
    """
    result = dict(schema='p3-research-projected-inventory-v1', accepted=False,
        acquired_atomic=None, remaining_atomic=None, minimum_atomic=None,
        expected_atomic=None, budget_lamports=None, mint=None,
        buy_observation_id=None, entry_decision_at_ms=decision_at_ms,
        basis='expected_quote_output_if_requested_exact_input_were_filled',
        actual_input_known=False, source_timing_qualified=False,
        acquisition_verified=False, strict_identity_verified=False,
        trade_allowed=False, execution_verified=False, economic_cycle_qualified=False,
        limitations=[], reasons=[])
    try:
        quote, limitations = _quote(buy_event, 'buy', decision_at_ms, allow_stale=True)
        identity = _integer(buy_event.get('id'), 'buy_observation_id_unknown')
        if identity == 0:
            raise _Rejected('buy_observation_id_unknown')
        mint = _mint(quote.get('output_mint'))
        if quote.get('input_mint') != SOL_MINT or mint == SOL_MINT or buy_event.get('mint') != mint:
            raise _Rejected('buy_mint_identity_mismatch')
        budget = _atomic(quote.get('input_amount_atomic'))
        expected = _atomic(quote.get('output_amount_atomic'))
        minimum = _atomic(quote.get('min_output_amount_atomic'), zero=True)
        if int(minimum) > int(expected):
            raise _Rejected('buy_minimum_exceeds_expected_output')
        actual = quote.get('actual_input_amount_atomic')
        if actual is None:
            limitations.append('buy_actual_input_unknown')
        elif _atomic(actual) != budget:
            raise _Rejected('buy_actual_input_adjusted_budget_ambiguous')
        result.update(accepted=True, acquired_atomic=expected, remaining_atomic=expected,
            minimum_atomic=minimum, expected_atomic=expected, budget_lamports=budget,
            mint=mint, buy_observation_id=identity, actual_input_known=actual is not None,
            source_timing_qualified=not any('source_' in item for item in limitations),
            limitations=limitations+['identity_not_strictly_verified',
                'additional_execution_costs_unknown', 'inventory_never_acquired'])
    except (ValueError, KeyError, TypeError) as error:
        # Validation helpers expose only fixed reason codes, not source bodies.
        result['reasons'].append(str(error) if isinstance(error, _Rejected)
            else 'invalid_retained_buy_quote_or_quantity')
    return result


def _exit_row(inventory, checkpoint, buy, sell):
    quantity = inventory['acquired_atomic']
    row = dict(buy_observation_id=buy['id'], sell_observation_id=sell.get('id'),
        inventory_checkpoint_id=checkpoint['id'], mint=inventory['mint'],
        budget_lamports=inventory['budget_lamports'], projected_quantity_atomic=quantity,
        exit_phase=sell.get('payload', {}).get('probe_phase'),
        status='REFUSED', reasons=[], limitations=list(inventory['limitations']),
        conditional_quoted_delta_lamports=None, hypothetical_cost_scenarios=[],
        unknown_additional_cost_break_even_lamports=None,
        source_timing_qualified=False, actual_inputs_explicit=False,
        observation_provenance=buy.get('provenance') if buy.get('provenance')==sell.get('provenance') else 'mixed',
        is_live_market_observation=buy.get('provenance')==sell.get('provenance')=='live',
        complete_receipt_linked_indicative_pair=False,
        retained_projected_quantity_atomic=quantity,
        modeled_remainder_atomic_if_full_quote_filled=None,
        observed_position_or_remainder_atomic=None,
        curve_or_route_fees_already_in_quote_counted_again=False,
        own_entry_market_impact_applied_to_provider_quote=False,
        strict_identity_verified=False, trade_allowed=False,
        economic_cycle_qualified=False, net_market_pnl_sol=None,
        execution_verified=False)
    try:
        if checkpoint['id'] >= sell['id'] or checkpoint['available_at_ms'] > sell['payload'].get('requested_at_ms', -1):
            raise _Rejected('sell_requested_before_projected_inventory_committed')
        if buy.get('provenance') != sell.get('provenance'):
            raise _Rejected('mixed_quote_provenance')
        if sell.get('outcome') != 'quoted':
            row['provider_refusal'] = sell.get('reason') or 'sell_quote_unavailable'
            raise _Rejected('sell_quote_unavailable')
        quote, limitations = _quote(sell, 'sell', sell.get('available_at_ms'))
        row['limitations'] += limitations
        if (quote.get('input_mint') != inventory['mint'] or quote.get('output_mint') != SOL_MINT
                or sell.get('mint') != inventory['mint']):
            raise _Rejected('sell_mint_identity_mismatch')
        if _atomic(quote.get('input_amount_atomic')) != quantity:
            raise _Rejected('sell_quote_not_for_full_projected_quantity')
        actual = quote.get('actual_input_amount_atomic')
        if actual is None:
            row['limitations'].append('sell_actual_input_unknown')
        elif _atomic(actual) != quantity:
            raise _Rejected('sell_actual_input_not_full_projected_quantity')
        buy_quote, buy_limitations = _quote(buy, 'buy', inventory['entry_decision_at_ms'])
        row['limitations'] += buy_limitations
        if (buy_quote.get('source_slot') is not None and quote.get('source_slot') is not None
                and quote['source_slot'] < buy_quote['source_slot']):
            raise _Rejected('sell_source_slot_before_buy')
        if (buy_quote.get('source_time_ms') is not None and quote.get('source_time_ms') is not None
                and quote['source_time_ms'] < buy_quote['source_time_ms']):
            raise _Rejected('sell_source_clock_before_buy')
        elapsed = quote['requested_at_ms'] - inventory['entry_decision_at_ms']
        row['elapsed_after_inventory_decision_ms'] = elapsed
        if row['exit_phase'] == 'followup' and elapsed < 15000:
            raise _Rejected('followup_before_preregistered_15000ms_horizon')
        output = _atomic(quote.get('output_amount_atomic'))
        minimum = _atomic(quote.get('min_output_amount_atomic'), zero=True)
        delta = int(output)-int(inventory['budget_lamports'])
        row.update(status='CONDITIONAL_INDICATIVE_PAIR',
            conditional_quoted_delta_lamports=str(delta),
            minimum_quote_output_lamports=minimum, expected_quote_output_lamports=output,
            minimum_output_is_not_guaranteed_execution=True,
            unknown_additional_cost_break_even_lamports=str(delta) if delta >= 0 else None,
            additional_proceeds_needed_before_unknown_costs_lamports=str(max(0, -delta)),
            modeled_remainder_atomic_if_full_quote_filled='0',
            complete_receipt_linked_indicative_pair=True,
            actual_inputs_explicit=inventory['actual_input_known'] and actual is not None,
            source_timing_qualified=not any('source_' in item for item in row['limitations']),
            hypothetical_cost_scenarios=[dict(assumed_additional_costs_lamports=str(cost),
                conditional_net_lamports=str(delta-cost), provenance='explicit_hypothesis_not_observed_cost',
                certified_profit=False) for cost in _COST_SCENARIOS])
        row['limitations'] = list(dict.fromkeys(row['limitations']))
    except (ValueError, KeyError, TypeError) as error:
        row['reasons'].append(str(error) if isinstance(error, _Rejected)
            else 'invalid_retained_sell_quote_or_quantity')
    return row


def evaluate_research_cycles(events, *, expected_tail):
    """Evaluate every retained linked exit; never select the best future quote.

    A complete receipt-linked pair can be informative while provider freshness,
    actual input, identity and additional costs remain unqualified. The pair
    count is not a count of usable P3 economic cycles or executed transactions.
    """
    events = _verified_capture_events(events, expected_tail)
    by_id = {event['id']: event for event in events}
    rows = []; inventories = []; failures = []
    checkpoints = [e for e in events if e['kind']=='checkpoint'
                   and e.get('outcome')=='research_inventory_fixed']
    seen_buys = set(); projected_buys=set()
    for checkpoint in checkpoints:
        payload = checkpoint['payload']; declared = payload.get('inventory', payload)
        if type(declared) is not dict:
            failures.append(dict(checkpoint_id=checkpoint['id'],reason='inventory_checkpoint_schema_invalid'))
            continue
        buy_id = declared.get('buy_observation_id')
        if type(buy_id) is not int or buy_id<=0:
            failures.append(dict(checkpoint_id=checkpoint['id'],reason='inventory_buy_reference_invalid_or_duplicate'))
            continue
        buy = by_id.get(buy_id)
        if (buy is None or buy_id in seen_buys or buy['id'] >= checkpoint['id']
                or buy['available_at_ms'] > checkpoint['available_at_ms']):
            failures.append(dict(checkpoint_id=checkpoint['id'],reason='inventory_buy_reference_invalid_or_duplicate'))
            continue
        seen_buys.add(buy_id)
        inventory = projected_research_inventory(buy,
            decision_at_ms=declared.get('entry_decision_at_ms'))
        if not inventory['accepted'] or inventory != declared:
            failures.append(dict(checkpoint_id=checkpoint['id'],reason='inventory_checkpoint_does_not_reproduce'))
            continue
        if (checkpoint.get('mint') != inventory['mint']
                or checkpoint.get('provenance') != buy.get('provenance')
                or not inventory['entry_decision_at_ms'] <= checkpoint['received_at_ms'] <= checkpoint['available_at_ms']):
            failures.append(dict(checkpoint_id=checkpoint['id'],reason='inventory_checkpoint_identity_or_time_inconsistent'))
            continue
        inventories.append(deepcopy(inventory))
        projected_buys.add(buy_id)
        sells = [e for e in events if e['kind']=='quote_attempt'
                 and e['payload'].get('quote_side')=='sell'
                 and e['payload'].get('inventory_buy_observation_id')==buy_id]
        if not sells:
            rows.append(dict(buy_observation_id=buy_id,mint=inventory['mint'],
                status='UNKNOWN_EXIT',reasons=['no_linked_sell_quote_retained'],
                retained_projected_quantity_atomic=inventory['acquired_atomic'],
                complete_receipt_linked_indicative_pair=False,
                economic_cycle_qualified=False,net_market_pnl_sol=None,execution_verified=False))
        rows.extend(_exit_row(inventory,checkpoint,buy,sell) for sell in sells)
    buy_attempts = [dict(observation_id=e['id'],mint=e.get('mint'),outcome=e.get('outcome'),
        reason=e.get('reason'),inventory_projected=e['id'] in projected_buys)
        for e in events if e['kind']=='quote_attempt' and e['payload'].get('quote_side')=='buy'
        and e['payload'].get('provider')=='raydium_trade_api']
    complete=[r for r in rows if r.get('complete_receipt_linked_indicative_pair')]
    return dict(schema='p3-research-conditional-cycles-v1', research_cycles=rows,
        projected_inventories=inventories,inventory_failures=failures,buy_attempts=buy_attempts,
        complete_receipt_linked_indicative_pairs=len(complete),
        complete_receipt_linked_live_market_pairs=sum(r['is_live_market_observation'] for r in complete),
        complete_receipt_linked_synthetic_pairs=sum(r['observation_provenance']=='synthetic' for r in complete),
        complete_receipt_linked_historical_pairs=sum(r['observation_provenance']=='historical_replay' for r in complete),
        prospective_economic_cycles_usable=0,strict_market_cycles=0,
        net_market_pnl_sol=None,additional_execution_costs_known=False,
        source_authenticity_or_independence_certified=False,
        acquisition_executed_by_evaluator=False,ledger_mutated=False,
        active_policy_changed=False,trade_allowed=False,execution_verified=False,
        evidence_tail=expected_tail,
        qualification='INDICATIVE_CONDITIONAL_ONLY; no_own_cost_or_strict_identity_certificate')
