"""Position proposals preserve native accounting and never promise a fill."""
from copy import deepcopy
import json

import pytest

from bot.master_positions import evaluate_position_plan
from bot.economic_demo import _load_api,_public_address,_quote_observation


def position(*, price=1.02, output=1050000000, quantity=1000, at=101000):
    api=_load_api();mint,creator,pool=(_public_address(i) for i in (61,62,63))
    buy=_quote_observation(api,side='buy',mint=mint,pool=pool,amount=1000000000,
        output=1000,requested=99970,index=1,case='master-position')
    buy['id']='entry'
    sell=_quote_observation(api,side='sell',mint=mint,pool=pool,amount=quantity,
        output=output,requested=at-20,index=2,case='master-position')
    sell['id']='exit'
    inventory=dict(mint=mint,acquired_atomic='1000',remaining_atomic='1000',token_decimals=6,
        entry_budget_lamports='1000000000',entry_extra_lamports='5000',
        cost_basis_total_lamports='1000005000',cost_basis_remaining_lamports='1000005000',
        entry_decision_ms=100000,entry_observation_json=json.dumps(buy),
        source_provenance='synthetic',inventory_basis='expected_buy_output',
        version=0,last_settlement_ms=None,realized_pnl_lamports='0')
    context=dict(sell_observation=sell,inventory_buy_observation_id='entry',
        requested_quantity_atomic=str(quantity),inventory_version=0,fees={
            'entry_extra_lamports':5000,'exit_extra_lamports':10000,
            'failed_attempt_lamports':[],'provenance':'synthetic'})
    frame=dict(id='frame',mint=mint,creator=creator,pool=pool,available_at_ms=at,
        features_available_at_ms=at,features={'mint':mint,'creator':creator,
            'observed_at':at//1000,'price_usd':price,'momentum_60s':1.0,
            'dev_sales':0,'relay_transfers':0,'tx_buys_5m':3,'tx_sells_5m':1},
        position_reference={'entry_price':1.0,'peak_price':max(1.0,price)},
        entry_plan={'tp_pct':10.0,'sl_pct':8.0,'trailing_stop_pct':5.0,'hold_seconds':1800},
        inventory_context=context)
    return frame,inventory


def test_take_profit_uses_full_native_net_and_leaves_inputs_unchanged():
    frame,inventory=position(price=1.2,output=1200000000)
    before=deepcopy((frame,inventory))
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='TAKE_PROFIT'
    assert result['proposed_quantity_atomic']==result['quote_quantity_atomic']=='1000'
    assert result['conditional_net_lamports']=='199985000'
    assert result['estimated_extra_fees_lamports']=='10000'
    assert result['allocated_basis_lamports']=='1000005000'
    assert result['remaining_after_atomic']=='0'
    assert result['executable_quote_qualified'] is True
    assert result['execution_verified'] is result['execution_guaranteed'] is False
    assert result['ledger_mutated'] is result['promotion_allowed'] is False
    assert before==(frame,inventory)
    json.dumps(result,allow_nan=False)


def test_positive_usd_target_does_not_become_positive_sol_profit():
    frame,inventory=position(price=1.2,output=888306249)
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='EXIT'
    assert result['conditional_net_lamports']=='-111708751'
    assert result['reasons']==['frozen_price_target_SOL_profit_unproven']


def test_frozen_stop_loss_and_trailing_survive_unhealthy_entry_permission():
    frame,inventory=position(price=.9,output=900000000)
    result=evaluate_position_plan(frame,inventory,health={'allow_new_entries':False})
    assert result['action']=='EXIT' and result['reasons']==['frozen_stop_loss_reached']
    frame,inventory=position(price=1.05)
    frame['position_reference']['peak_price']=1.2
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='EXIT' and result['reasons']==['frozen_trailing_stop_reached']


def test_frozen_stop_is_not_missed_at_exact_decimal_percentage_boundary():
    frame,inventory=position(price=.92)
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='EXIT'
    assert result['reasons']==['frozen_stop_loss_reached']
    frame,inventory=position(price=1.10,output=1200000000)
    assert evaluate_position_plan(frame,inventory)['action']=='TAKE_PROFIT'


def test_unknown_fees_do_not_suppress_emergency_intent_or_create_settlement():
    frame,inventory=position()
    frame['inventory_context']['fees']=None
    result=evaluate_position_plan(frame,inventory,health={'emergency_stop':True})
    assert result['action']=='EMERGENCY_EXIT' and result['proposed_quantity_atomic']=='1000'
    assert result['conditional_net_lamports'] is None
    assert result['executable_quote_qualified'] is False
    assert result['quote_refusals']


def test_creator_sale_changes_hold_to_emergency_without_rewriting_entry_policy():
    frame,inventory=position()
    assert evaluate_position_plan(frame,inventory)['action']=='HOLD'
    frame['features']['dev_sales']=1
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='EMERGENCY_EXIT'
    assert result['reasons']==['observed_creator_or_relay_sale_risk']
    assert frame['entry_plan']['tp_pct']==10.0


def test_exact_partial_reduction_on_flow_deterioration_never_scales_a_full_quote():
    frame,inventory=position(quantity=400,output=460000000)
    frame['features'].update(momentum_60s=-1.0,tx_buys_5m=1,tx_sells_5m=3)
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='REDUCE' and result['proposed_quantity_atomic']=='400'
    assert result['remaining_after_atomic']=='600'
    assert result['conditional_net_lamports']=='59988000'
    assert result['conditional_total_position_net_lamports'] is None
    frame['inventory_context']['requested_quantity_atomic']='1000'
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='WAIT_FOR_DATA' and result['quote_quantity_atomic'] is None


def test_unavailable_full_quote_keeps_exit_intent_and_refusal_without_zero_liquidation():
    frame,inventory=position(price=.9,output=None)
    result=evaluate_position_plan(frame,inventory)
    assert result['action']=='EXIT' and result['proposed_quantity_atomic']=='1000'
    assert result['remaining_after_atomic'] is None
    assert result['executable_quote_qualified'] is False
    assert result['quote_refusals'][0]['reasons']==['sell_quote_unavailable']


@pytest.mark.parametrize('damage',['fees','version','basis','future_quote','prior_quote','source_time'])
def test_invalid_exit_evidence_cannot_become_qualified(damage):
    frame,inventory=position(price=.9)
    if damage=='fees':frame['inventory_context']['fees']['entry_extra_lamports']=1
    elif damage=='version':frame['inventory_context']['inventory_version']=1
    elif damage=='basis':inventory['cost_basis_remaining_lamports']='1'
    elif damage=='future_quote':frame['available_at_ms']-=100
    elif damage=='prior_quote':inventory['last_settlement_ms']=frame['available_at_ms']-10
    else:
        frame['inventory_context']['sell_observation']['source_time_ms']=None
        frame['inventory_context']['sell_observation']['payload']['source_time_ms']=None
    result=evaluate_position_plan(frame,inventory)
    assert result['executable_quote_qualified'] is False
    assert result['conditional_net_lamports'] is None


def test_missing_plan_and_stale_or_future_features_do_not_fabricate_thresholds():
    frame,inventory=position();del frame['entry_plan']
    assert evaluate_position_plan(frame,inventory)['action']=='WAIT_FOR_DATA'
    frame,inventory=position();frame['features']['observed_at']-=10
    assert evaluate_position_plan(frame,inventory)['action']=='WAIT_FOR_DATA'
    frame,inventory=position();frame['features_available_at_ms']+=1
    frame['features']['dev_sales']=1
    assert evaluate_position_plan(frame,inventory)['action']=='WAIT_FOR_DATA'


def test_frozen_maximum_hold_does_not_need_price_or_new_entry_permission():
    frame,inventory=position();frame['entry_plan']['hold_seconds']=1
    del frame['features']
    result=evaluate_position_plan(frame,inventory,health={'allow_new_entries':False})
    assert result['action']=='EXIT' and result['reasons']==['frozen_maximum_hold_reached']


def test_closed_or_legacy_inventory_stays_explicit_and_never_gets_new_quantity():
    frame,inventory=position();inventory['remaining_atomic']='0'
    assert evaluate_position_plan(frame,inventory)['proposed_quantity_atomic']=='0'
    legacy={'mint':frame['mint'],'remaining_atomic':None,'legacy_inventory_unknown':True}
    result=evaluate_position_plan(frame,legacy)
    assert result['action']=='WAIT_FOR_DATA' and result['proposed_quantity_atomic'] is None
    result=evaluate_position_plan(frame,legacy,health={'emergency_stop_requested':True})
    assert result['action']=='EMERGENCY_EXIT' and result['proposed_quantity_atomic'] is None


def test_extreme_finite_price_does_not_emit_nonfinite_report_and_policy_changes_refused():
    frame,inventory=position(price=1e308)
    frame['position_reference']['entry_price']=1e-308
    result=evaluate_position_plan(frame,inventory)
    json.dumps(result,allow_nan=False)
    assert result['risk_metrics']['price_return'] is None
    with pytest.raises(ValueError):evaluate_position_plan(frame,inventory,policy={'sl_pct':100})
