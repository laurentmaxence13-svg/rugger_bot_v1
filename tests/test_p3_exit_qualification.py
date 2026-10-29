"""Inventory and availability bridge, synthetic quotes only; no provider call."""
import asyncio
from copy import deepcopy

import pytest

from bot.p3.accounting import SolFeeBreakdown, native_sol_round_trip
from bot.p3.collect import _record_quote
from bot.p3.exit_qualification import qualify_exit_quote_pair
from test_p3_quotes import RaydiumQuoteClient, Session, Response, quote_payload, SOL_MINT, USDC


FEES = SolFeeBreakdown(0, 0, (), provenance='synthetic')


def event(side, body, requested, *, available=None):
    body = deepcopy(body)
    body['data'].update(sourceTimeMs=requested-10, contextSlot=100 if side == 'buy' else 101)
    times = iter((requested, requested+20))
    ticks = iter((0, 1_000_000))
    quote = asyncio.run(RaydiumQuoteClient(Session(Response(body)), clock_ms=lambda: next(times),
        monotonic_ns=lambda: next(ticks)).quote(body['data']['inputMint'],
            body['data']['outputMint'], body['data']['inputAmount'], 100))
    receipts = []
    def append(kind, **record):
        receipts.append(dict(kind=kind, provenance='synthetic', **record,
            available_at_ms=quote['received_at_ms']+1 if available is None else available))
        return 1
    assert _record_quote(append, quote, side, 'synthetic-pair')
    return receipts[0]


def pair(sell_quantity='25000000'):
    buy = event('buy', quote_payload(), 1000)
    sell = event('sell', quote_payload(USDC, SOL_MINT, sell_quantity,
        '990000000', '980100000'), 1100)
    return buy, sell


def qualify(buy, sell, **overrides):
    args = dict(inventory_basis='expected_buy_output', entry_decision_at_ms=1030,
                exit_decision_at_ms=1130, max_source_age_ms=100, fees=FEES,
                available_cash_lamports=10_000_000_000)
    args.update(overrides)
    return qualify_exit_quote_pair(buy, sell, **args)


def test_sell_of_expected_output_is_not_guaranteed_by_buy_minimum():
    buy, sell = pair()
    # The existing arithmetic alone accepts caller-declared inventory equality.
    arithmetic = native_sol_round_trip(entry_spent_lamports=1_000_000_000,
        exit_received_lamports=990_000_000, acquired_token_atomic=25_000_000,
        sold_token_atomic=25_000_000, token_mint=USDC, fees=FEES,
        available_cash_lamports=10_000_000_000)
    assert arithmetic['status'] == 'quoted_projection_only'
    report = qualify(buy, sell, inventory_basis='minimum_buy_output')
    assert report['sell_exceeds_minimum_inventory'] is True
    assert report['selected_inventory_atomic'] == '24750000'
    assert report['qualification'] == 'UNQUALIFIED'
    assert report['reasons'] == ['sell_quote_size_does_not_match_inventory_scenario']
    assert report['conditional_accounting_projection'] is None


def test_expected_inventory_is_explicitly_conditional_and_costs_are_not_double_counted():
    buy, sell = pair()
    original = deepcopy((buy, sell))
    report = qualify(buy, sell, fees=SolFeeBreakdown(5, 7, (11,), provenance='estimate'))
    assert report['qualification'] == 'CONDITIONAL_QUOTE_SCENARIO_ONLY'
    assert report['quote_size_matches_inventory_scenario'] is True
    assert report['sell_exceeds_minimum_inventory'] is True
    projection = report['conditional_accounting_projection']
    assert projection['net_pnl_lamports'] == -10_000_023
    assert projection['total_extra_fee_lamports'] == 23
    assert projection['fees_already_in_quote_counted_again'] is False
    assert report['inventory_acquired'] is report['execution_verified'] is False
    assert report['full_position_closure_verified'] is report['model_eligible'] is False
    assert report['net_economic_pnl_sol'] is None
    assert (buy, sell) == original


def test_minimum_size_quote_cannot_close_an_unknown_larger_inventory_or_scale_its_proceeds():
    buy, sell = pair('24750000')
    report = qualify(buy, sell, inventory_basis='minimum_buy_output')
    assert report['qualification'] == 'MINIMUM_SIZE_MATCH_ONLY'
    assert report['quote_size_matches_inventory_scenario'] is True
    assert report['reasons'] == ['full_position_inventory_unknown_after_minimum_size_sale']
    assert report['conditional_accounting_projection'] is None
    assert qualify(buy, sell)['reasons'] == ['sell_quote_size_does_not_match_inventory_scenario']


@pytest.mark.parametrize('change,reason', [
    ('future_buy', 'buy_temporal_evidence_inconsistent'),
    ('early_sell_request', 'sell_quantity_requested_before_buy_inventory_known'),
    ('stale_exit', 'sell_quote_stale_at_decision'),
    ('unknown_fees', 'additional_fees_or_available_cash_unqualified'),
    ('partial_sale', 'sell_quote_size_does_not_match_inventory_scenario'),
    ('wrong_mint', 'round_trip_mint_identity_mismatch'),
    ('body_missing', 'buy_quote_body_missing'),
    ('provenance_missing', 'missing_or_mixed_observation_provenance'),
])
def test_unqualified_time_size_identity_or_costs_never_produce_profit(change, reason):
    buy, sell = pair('24000000' if change == 'partial_sale' else '25000000')
    args = {}
    if change == 'future_buy':
        buy['available_at_ms'] = 1031
    elif change == 'early_sell_request':
        sell = event('sell', quote_payload(USDC, SOL_MINT, '25000000', '990000000', '980100000'), 1025)
        args['exit_decision_at_ms'] = 1050
    elif change == 'stale_exit':
        args['exit_decision_at_ms'] = 2000
    elif change == 'unknown_fees':
        args['fees'] = SolFeeBreakdown(None, 0, ())
    elif change == 'wrong_mint':
        sell['mint'] = SOL_MINT
    elif change == 'body_missing':
        buy['payload'].pop('retained_sanitized_response')
    elif change == 'provenance_missing':
        buy.pop('provenance')
        sell.pop('provenance')
    report = qualify(buy, sell, **args)
    assert report['qualification'] == 'UNQUALIFIED'
    assert report['reasons'] == [reason]
    assert report['conditional_accounting_projection'] is None
    assert report['net_economic_pnl_sol'] is None
    assert report['execution_verified'] is False


@pytest.mark.parametrize('actual', [None, '24000000'])
def test_missing_or_adjusted_sell_actual_input_cannot_certify_full_inventory_disposal(actual):
    buy, _ = pair()
    body = quote_payload(USDC, SOL_MINT, '25000000', '990000000', '980100000')
    if actual is None:
        body['data'].pop('actualInputAmount')
    else:
        body['data']['actualInputAmount'] = actual
    sell = event('sell', body, 1100)
    assert sell['payload']['outcome'] == 'quoted'
    report = qualify(buy, sell)
    assert report['qualification'] == 'UNQUALIFIED'
    assert report['reasons'] == ['sell_actual_input_unknown' if actual is None else
                                  'sell_actual_input_adjusted_inventory_ambiguous']
    assert report['conditional_accounting_projection'] is None
    assert report['full_position_closure_verified'] is False
