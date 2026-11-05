"""Projected inventory and exact-size exits, entirely offline."""
import asyncio
from copy import deepcopy

import pytest

from bot.p3.collect import _record_quote
from bot.p3.exit_qualification import qualify_exit_quote_pair
from bot.p3.accounting import SolFeeBreakdown
from bot.p3.replay import replay_quote_observation
from test_p3_quotes import RaydiumQuoteClient, Session, Response, quote_payload, SOL_MINT, USDC


def observation(side, quantity='25000000', *, source=True, actual=None):
    requested = 1000 if side == 'buy' else 1100
    body = (quote_payload() if side == 'buy' else
            quote_payload(USDC, SOL_MINT, quantity, '990000000', '980100000'))
    if source:
        body['data'].update(sourceTimeMs=requested-10, contextSlot=100 if side == 'buy' else 101)
    if actual is not None:
        body['data']['actualInputAmount'] = actual
    times = iter((requested, requested+20))
    ticks = iter((0, 1_000_000))
    quote = asyncio.run(RaydiumQuoteClient(Session(Response(body)), clock_ms=lambda: next(times),
        monotonic_ns=lambda: next(ticks)).quote(body['data']['inputMint'],
            body['data']['outputMint'], body['data']['inputAmount'], 100))
    events = []
    def append(kind, **event):
        events.append(dict(kind=kind, provenance='synthetic',
                           available_at_ms=quote['received_at_ms']+1, **event))
    assert _record_quote(append, quote, side, 'synthetic-'+side)
    return events[0]


def create_inventory(event=None, **overrides):
    from bot.p3.exit_qualification import inventory_from_buy
    values = dict(token_decimals=6, entry_decision_at_ms=1030, max_source_age_ms=100)
    values.update(overrides)
    return inventory_from_buy(event or observation('buy'), **values)


def qualify(inventory, event=None, **overrides):
    from bot.p3.exit_qualification import qualify_inventory_exit
    values = dict(requested_quantity_atomic='25000000', exit_decision_at_ms=1130,
                  max_source_age_ms=100)
    values.update(overrides)
    return qualify_inventory_exit(inventory, event or observation('sell'), **values)


def test_existing_pair_qualifier_can_run_inside_active_async_engine():
    buy, sell = observation('buy'), observation('sell')
    async def engine_iteration():
        return qualify_exit_quote_pair(buy, sell, inventory_basis='expected_buy_output',
            entry_decision_at_ms=1030, exit_decision_at_ms=1130, max_source_age_ms=100,
            fees=SolFeeBreakdown(0, 0, (), provenance='synthetic'),
            available_cash_lamports=10_000_000_000)
    result = asyncio.run(engine_iteration())
    assert result['qualification'] == 'CONDITIONAL_QUOTE_SCENARIO_ONLY'


@pytest.mark.parametrize('basis,selected', [
    ('expected_buy_output', '25000000'), ('minimum_buy_output', '24750000'),
])
def test_inventory_preserves_explicit_projected_basis_and_original_quantities(basis, selected):
    buy = observation('buy')
    before = deepcopy(buy)
    result = create_inventory(buy, basis=basis)
    assert result['accepted'] is True
    assert result['acquired_atomic'] == result['remaining_atomic'] == selected
    assert result['expected_atomic'] == '25000000'
    assert result['minimum_atomic'] == '24750000'
    assert result['budget_lamports'] == '1000000000'
    assert result['mint'] == USDC and result['token_decimals'] == 6
    assert result['basis'] == basis and result['provenance'] == 'synthetic'
    assert result['source_timing_qualified'] is True
    assert result['acquisition_verified'] is False
    assert buy == before


def test_unknown_source_allows_retained_projection_but_never_qualified_exit():
    inventory = create_inventory(observation('buy', source=False), token_decimals=None)
    assert inventory['accepted'] is True
    assert inventory['token_decimals'] is None
    assert inventory['source_timing_qualified'] is False
    result = qualify(inventory)
    assert result['accepted'] is False
    assert result['reason'] == 'buy_source_time_unknown'
    assert result['proceeds_lamports'] is None


@pytest.mark.parametrize('mutation,reason', [
    ('body', 'buy_quote_replay_failed'),
    ('future_available', 'buy_temporal_evidence_inconsistent'),
    ('mint', 'buy_mint_identity_mismatch'),
    ('provenance', 'buy_observation_provenance_unknown'),
    ('adjusted', 'buy_actual_input_adjusted_budget_ambiguous'),
])
def test_invalid_entry_evidence_never_creates_inventory(mutation, reason):
    buy = observation('buy', actual='999999999' if mutation == 'adjusted' else None)
    if mutation == 'body':
        buy['payload']['retained_sanitized_response']['data']['outputAmount'] = '1'
    elif mutation == 'future_available':
        buy['available_at_ms'] = 1031
    elif mutation == 'mint':
        buy['mint'] = SOL_MINT
    elif mutation == 'provenance':
        buy['provenance'] = None
    result = create_inventory(buy)
    assert result['accepted'] is False and result['reasons'] == [reason]
    assert result['acquired_atomic'] is None


@pytest.mark.parametrize('decimals', [-1, 256, True, 6.0, '6'])
def test_token_decimals_are_exact_metadata_or_unknown(decimals):
    assert create_inventory(token_decimals=decimals)['accepted'] is False


def test_partial_exit_qualifies_exact_request_without_scaling_or_mutating_inventory():
    inventory = create_inventory()
    before = deepcopy(inventory)
    result = qualify(inventory, observation('sell', '10000000'), requested_quantity_atomic='10000000')
    assert result['accepted'] is True
    assert result['quantity_atomic'] == result['q'] == '10000000'
    assert result['proceeds_lamports'] == '990000000'
    assert result['minimum_proceeds_lamports'] == '980100000'
    assert result['remaining_after_atomic'] == '15000000'
    assert result['coverage'] == 'partial_remaining'
    assert result['acquisition_verified'] is result['execution_verified'] is False
    assert inventory == before


def test_minimum_scenario_can_dispose_its_own_projected_inventory_without_claiming_fill():
    inventory = create_inventory(basis='minimum_buy_output')
    result = qualify(inventory, observation('sell', '24750000'), requested_quantity_atomic='24750000')
    assert result['accepted'] is True and result['coverage'] == 'full_remaining'
    assert result['remaining_after_atomic'] == '0'
    assert result['full_position_closure_verified'] is False


@pytest.mark.parametrize('mutation,reason', [
    ('oversell', 'requested_exit_exceeds_remaining_inventory'),
    ('zero', 'invalid_requested_exit_quantity'),
    ('mismatch', 'sell_quote_size_does_not_match_requested_inventory'),
    ('adjusted', 'sell_actual_input_adjusted_inventory_ambiguous'),
    ('remaining', 'remaining_inventory_exceeds_acquired_quantity'),
    ('acquired', 'persisted_inventory_does_not_match_buy_scenario'),
    ('basis', 'persisted_inventory_does_not_match_buy_scenario'),
    ('source', 'sell_source_time_unknown'),
    ('stale', 'sell_quote_stale_at_decision'),
])
def test_exit_refuses_unknown_stale_adjusted_or_inconsistent_inventory(mutation, reason):
    inventory = create_inventory()
    sell = observation('sell', '24000000' if mutation == 'mismatch' else '25000000',
                       source=mutation != 'source', actual='24000000' if mutation == 'adjusted' else None)
    args = {}
    if mutation == 'oversell':
        inventory['remaining_atomic'] = '24000000'
    elif mutation == 'zero':
        args['requested_quantity_atomic'] = 0
    elif mutation == 'remaining':
        inventory['remaining_atomic'] = '25000001'
    elif mutation == 'acquired':
        inventory['acquired_atomic'] = '25000001'
    elif mutation == 'basis':
        inventory['basis'] = 'minimum_buy_output'
    elif mutation == 'stale':
        args['exit_decision_at_ms'] = 1500
    result = qualify(inventory, sell, **args)
    assert result['accepted'] is False and result['reason'] == reason
    assert result['proceeds_lamports'] is None


def test_new_inventory_helpers_are_callable_inside_active_async_engine():
    buy, sell = observation('buy'), observation('sell')
    async def engine_iteration():
        return qualify(create_inventory(buy), sell)
    result = asyncio.run(engine_iteration())
    assert result['accepted'] is True and result['coverage'] == 'full_remaining'


def test_stale_buy_stays_a_projection_but_cannot_qualify_economic_exit():
    inventory = create_inventory(entry_decision_at_ms=1095, max_source_age_ms=100)
    assert inventory['accepted'] is True and inventory['source_timing_qualified'] is False
    assert inventory['reasons'] == ['buy_quote_stale_at_decision']
    assert qualify(inventory)['reason'] == 'buy_quote_stale_at_decision'


def test_qualified_sale_of_remainder_keeps_original_lot_quantity():
    inventory = create_inventory()
    inventory['remaining_atomic'] = '15000000'
    result = qualify(inventory, observation('sell', '15000000'), requested_quantity_atomic='15000000')
    assert result['accepted'] is True and result['coverage'] == 'full_remaining'
    assert result['remaining_after_atomic'] == '0'
    assert inventory['acquired_atomic'] == '25000000'
    assert result['net_economic_pnl_sol'] is None


def test_rejected_sell_leaves_inventory_untouched_and_proceeds_unknown():
    inventory, sell = create_inventory(), observation('sell')
    sell['outcome'] = sell['payload']['outcome'] = 'unavailable'
    sell['reason'] = sell['payload']['reason'] = 'provider_rejected'
    before = deepcopy(inventory)
    result = qualify(inventory, sell)
    assert result['accepted'] is False and result['reason'] == 'sell_quote_unavailable'
    assert result['proceeds_lamports'] is None and result['remaining_after_atomic'] is None
    assert inventory == before


@pytest.mark.parametrize('case', [
    'valid', 'future_source', 'unknown_source', 'missing_monotonic',
    'clock_regression', 'actual_over_budget', 'route_mismatch',
    'invalid_fee_after_output', 'provider_rejected',
])
def test_pure_replay_matches_real_normalizer_for_rejections_and_clock_flags(case):
    body = quote_payload()
    body['data'].update(sourceTimeMs=990, contextSlot=100)
    if case == 'future_source':
        body['data']['sourceTimeMs'] = 1030
    elif case == 'unknown_source':
        body['data'].pop('sourceTimeMs')
        body['data'].pop('contextSlot')
    elif case == 'actual_over_budget':
        body['data']['actualInputAmount'] = '1000000001'
    elif case == 'route_mismatch':
        body['data']['routePlan'][0]['inputMint'] = USDC
    elif case == 'invalid_fee_after_output':
        body['data']['routePlan'][0]['feeAmount'] = '-1'
    elif case == 'provider_rejected':
        body = {'success': False, 'msg': 'INSUFFICIENT_LIQUIDITY'}
    times = iter((1000, 999 if case == 'clock_regression' else 1020))
    ticks = iter((0, -1 if case == 'missing_monotonic' else 1_000_000))
    quote = asyncio.run(RaydiumQuoteClient(Session(Response(body)), clock_ms=lambda: next(times),
        monotonic_ns=lambda: next(ticks)).quote(SOL_MINT, USDC, '1000000000', 100))
    events = []
    def append(kind, **event):
        events.append(dict(kind=kind, provenance='synthetic', available_at_ms=1021, **event))
    assert _record_quote(append, quote, 'buy', 'synthetic-replay-'+case)
    async def inside_engine():
        return replay_quote_observation(events[0])
    assert asyncio.run(inside_engine())['status'] == 'REPLAYED'
    if case == 'future_source':
        result = create_inventory(events[0])
        assert result['accepted'] is False
        assert result['reasons'] == ['buy_temporal_evidence_inconsistent']
