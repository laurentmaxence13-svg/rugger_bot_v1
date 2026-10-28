"""Exact own-state inventory and economic friction, never fills or new quotes."""
from copy import deepcopy
from fractions import Fraction

import pytest

from bot.p3 import launchlab as ll
from bot.p3.position_model import evaluate_position, minimum_external_buy_for_break_even
from test_p3_launchlab import fixture


def bank(*, empty=False):
    accounts, addresses = fixture()
    pool,_ = ll._pool(accounts[addresses['pool']])
    if empty:
        pool.update(real_a=0,real_b=0,protocol_fee_accrued=0,platform_fee_accrued=0)
    return dict(pool=pool,fee_rates_ppm=(2500,10000,5000),
        base_vault_atomic=pool['supply']-pool['real_a'],
        quote_vault_lamports=pool['real_b']+pool['protocol_fee_accrued']+pool['platform_fee_accrued'])


@pytest.mark.parametrize('amount',[50_000_000,100_000_000,250_000_000,1_000_000_000])
@pytest.mark.parametrize('empty',[False,True])
def test_same_bank_own_buy_funds_exact_entire_exit_even_when_observed_circulation_empty(amount,empty):
    values=bank(empty=empty);before=deepcopy(values)
    result=evaluate_position(input_lamports=amount,**values)
    reference=ll.constant_product_projection(input_lamports=amount,**values)
    assert values==before and result['admissible'] is True
    for name in ('buy_output_atomic','buy_curve_fee_lamports','sell_gross_output_lamports',
                 'sell_curve_fee_lamports','sell_output_lamports'):
        assert result[name]==reference[name]
    post=result['counterfactual_post_buy_state']['pool']
    after=result['counterfactual_post_sell_state']['pool']
    quantity=int(result['buy_output_atomic'])
    assert int(post['real_a'])==values['pool']['real_a']+quantity
    assert int(after['real_a'])==values['pool']['real_a']
    assert result['sell_inventory_atomic']==result['buy_output_atomic']
    assert result['remaining_inventory_atomic']=='0'
    assert int(result['sell_output_lamports'])<amount
    assert result['modeled_net_pnl_lamports'] is result['net_economic_pnl_sol'] is None
    assert result['cost_basis']=='unknown'
    assert result['position_acquired'] is result['execution_verified'] is False
    assert result['external_service_quote'] is result['strict_economic_cycle_qualified'] is False
    assert result['observation_kind']=='MODEL_SNAPSHOT_CONDITIONAL'
    if empty:
        with pytest.raises(ll.SnapshotEvidenceError,match='outstanding'):
            ll.observed_sell_projection(values['pool'],input_token_atomic=quantity,
                fee_rates_ppm=values['fee_rates_ppm'],quote_vault_lamports=0,curve_type=0)


def test_explicit_additional_costs_are_hypotheses_and_curve_fees_are_not_double_counted():
    values=bank(empty=True)
    result=evaluate_position(input_lamports=1_000_000_000,additional_costs_lamports=15000,**values)
    received=int(result['sell_output_lamports'])
    assert result['modeled_net_pnl_lamports']==str(received-1_000_000_000-15000)
    assert result['break_even_extra_proceeds_lamports']==str(1_000_000_000+15000-received)
    assert result['cost_basis']=='caller_hypothetical_scenario'
    assert result['additional_costs_observed'] is False
    required=int(result['break_even_required_gross_proceeds_lamports'])
    target=int(result['break_even_required_net_proceeds_lamports'])
    rate=int(result['fee_rate_total_ppm'])
    assert required-required*rate//1_000_000 >= target
    # The exact ceil-fee implementation reaches the threshold and one less
    # gross lamport cannot; no floating percentage approximation is used.
    proceeds=lambda q:q-(q*rate+999999)//1_000_000
    assert proceeds(required)>=target and proceeds(required-1)<target


def test_zero_fee_round_trip_has_only_integer_rounding_loss_and_conserves_reserves():
    values=bank(empty=True);values['fee_rates_ppm']=(0,0,0)
    result=evaluate_position(input_lamports=1000000000,additional_costs_lamports=0,**values)
    assert result['admissible']
    assert result['buy_curve_fee_lamports']==result['sell_curve_fee_lamports']=='0'
    assert 0<=int(result['round_trip_friction_lamports'])<=2
    assert int(result['curve_pnl_lamports'])==-int(result['round_trip_friction_lamports'])
    post=result['counterfactual_post_sell_state']
    assert int(post['pool']['real_b'])==int(result['round_trip_friction_lamports'])
    assert post['base_vault_atomic']==str(values['base_vault_atomic'])


def test_external_buy_is_a_separate_counterfactual_and_net_proceeds_increase_monotonically():
    values=bank(empty=True);previous=-1;original=deepcopy(values)
    baseline=evaluate_position(input_lamports=1_000_000_000,**values)
    for outside in (0,1000,10_000_000,1_000_000_000,5_000_000_000):
        result=evaluate_position(input_lamports=1_000_000_000,external_buy_lamports=outside,
                                 additional_costs_lamports=15000,**values)
        assert result['admissible']
        received=int(result['sell_output_lamports'])
        assert received>=previous;previous=received
        assert result['buy_output_atomic']==baseline['buy_output_atomic']
        assert result['round_trip_friction_lamports']==baseline['round_trip_friction_lamports']
        assert result['observed_state']==baseline['observed_state']
        assert int(result['counterfactual_post_sell_state']['pool']['real_a'])>=0
        assert (result['external_buy'] is None)==(outside==0)
    assert values==original
    assert result['external_buy']['basis'].startswith('hypothetical_')
    assert result['execution_verified'] is False
    tiny=evaluate_position(input_lamports=1_000_000_000,external_buy_lamports=1,**values)
    assert tiny['admissible'] is False and tiny['reason']=='input_consumed_by_fee'


def test_exact_minimum_outside_buy_break_even_and_one_lamport_less_fails():
    values=bank(empty=True)
    answer=minimum_external_buy_for_break_even(input_lamports=1_000_000_000,
        additional_costs_lamports=15000,max_external_buy_lamports=10_000_000_000,**values)
    assert answer['found'] is True and answer['evaluations']<130
    amount=int(answer['minimum_external_buy_lamports'])
    at=evaluate_position(input_lamports=1_000_000_000,external_buy_lamports=amount,
                         additional_costs_lamports=15000,**values)
    below=evaluate_position(input_lamports=1_000_000_000,external_buy_lamports=amount-1,
                            additional_costs_lamports=15000,**values)
    assert int(at['modeled_net_pnl_lamports'])>=0
    assert int(below['modeled_net_pnl_lamports'])<0
    assert answer['execution_verified'] is answer['strict_economic_cycle_qualified'] is False


def test_break_even_search_respects_migration_domain_instead_of_extrapolating():
    values=bank(empty=True);values['pool']['total_fundraising_b']=1_010_000_000
    answer=minimum_external_buy_for_break_even(input_lamports=1_000_000_000,
        additional_costs_lamports=1_000_000_000,max_external_buy_lamports=100_000_000_000,**values)
    assert answer['found'] is False
    assert answer['reason']=='break_even_not_reached_within_registered_flow_cap'
    maximum=int(answer['largest_admissible_external_buy_lamports'])
    assert evaluate_position(input_lamports=1_000_000_000,external_buy_lamports=maximum,**values)['admissible']
    assert not evaluate_position(input_lamports=1_000_000_000,external_buy_lamports=maximum+1,**values)['admissible']


@pytest.mark.parametrize('damage,reason',[
    ('inactive','active_constant_product_native_SOL_required'),
    ('unsupported','active_constant_product_native_SOL_required'),
    ('decimals','active_constant_product_native_SOL_required'),
    ('bad_base','observed_reserves_or_vault_inventory_inconsistent'),
    ('accrued_fees','observed_reserves_or_vault_inventory_inconsistent'),
    ('migration','buy_crosses_fundraising_or_remaining_boundary'),
    ('overflow','post_buy_gross_vault_out_of_bounds'),
    ('boolean_cost','invalid_additional_costs_lamports'),
    ('negative_cost','invalid_additional_costs_lamports'),
    ('bad_rate','fee_rate_not_below_denominator'),
])
def test_inadmissible_states_preserve_reason_and_never_invent_amounts(damage,reason):
    values=bank(empty=True);options={}
    if damage=='inactive':values['pool']['status']=1
    if damage=='unsupported':options['curve_type']=1
    if damage=='decimals':values['pool']['decimals_b']=8
    if damage=='bad_base':values['base_vault_atomic']=0
    if damage=='accrued_fees':values['pool']['protocol_fee_accrued']=1
    if damage=='migration':values['pool']['total_fundraising_b']=1
    if damage=='overflow':values['quote_vault_lamports']=ll._U64_MAX-990_000_000
    if damage=='boolean_cost':options['additional_costs_lamports']=True
    if damage=='negative_cost':options['additional_costs_lamports']=-1
    if damage=='bad_rate':values['fee_rates_ppm']=(1_000_000,0,0)
    result=evaluate_position(input_lamports=1_000_000_000,**values,**options)
    assert result['admissible'] is False and result['reason']==reason
    assert result['buy_output_atomic'] is result['sell_output_lamports'] is None


def test_minimum_flow_does_not_assume_unknown_costs_are_zero():
    answer=minimum_external_buy_for_break_even(input_lamports=1_000_000_000,
        additional_costs_lamports=None,max_external_buy_lamports=1_000_000_000,**bank(empty=True))
    assert answer['found'] is False
    assert answer['reason']=='invalid_additional_costs_lamports'


def test_round_trip_cash_drag_decomposes_into_explicit_fees_and_rounding():
    for amount in (1_000,50_000_001,100_000_003,250_000_000,1_000_000_007):
        result=evaluate_position(input_lamports=amount,**bank(empty=True))
        assert result['admissible']
        total_fee=int(result['buy_curve_fee_lamports'])+int(result['sell_curve_fee_lamports'])
        rounding=int(result['round_trip_friction_lamports'])-total_fee
        assert 0<=rounding<=2
        assert result['own_curve_fees_lamports']==str(total_fee)


def test_report_ignores_unrelated_caller_metadata_and_is_json_safe():
    import json
    values=bank(empty=True)
    values['pool']['unrelated_object']=object()
    result=evaluate_position(input_lamports=1_000_000_000,**values)
    assert result['admissible'] is True
    assert 'unrelated_object' not in result['observed_state']['pool']
    json.dumps(result,allow_nan=False)
