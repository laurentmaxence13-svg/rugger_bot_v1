"""Indicative research quotes never relax or mutate strict PAPER accounting."""
import asyncio
from copy import deepcopy

import pytest

from bot.p3.collect import _record_quote
from bot.p3.exit_qualification import inventory_from_buy
from bot.p3.research_cycles import projected_research_inventory,evaluate_research_cycles
from bot.p3.store import CaptureStore
from test_p3_quotes import quote_payload,RaydiumQuoteClient,Session,Response,SOL_MINT,USDC


def quote_event(store,side,*,requested,amount,output,actual=True,clocks=True,
                source_slot=None,source_time=None,metadata=None,refused=False,provenance='synthetic'):
    input_mint,output_mint=(SOL_MINT,USDC) if side=='buy' else (USDC,SOL_MINT)
    body=quote_payload(input_mint,output_mint,amount,output,str(int(output)*99//100))
    if not actual:body['data'].pop('actualInputAmount')
    elif type(actual) is str:body['data']['actualInputAmount']=actual
    if clocks:
        body['data'].update(sourceTimeMs=requested-10 if source_time is None else source_time,
            contextSlot=(100 if side=='buy' else 101) if source_slot is None else source_slot)
    if refused:body={'success':False,'msg':'INSUFFICIENT_LIQUIDITY'}
    times=iter((requested,requested+20));ticks=iter((0,1000000))
    value=asyncio.run(RaydiumQuoteClient(Session(Response(body)),
        clock_ms=lambda:next(times),monotonic_ns=lambda:next(ticks)).quote(input_mint,output_mint,amount))
    def append(kind,**record):
        record['payload'].update(metadata or {})
        return store.append(kind,provenance=provenance,**record)
    assert _record_quote(append,value,side,'synthetic-'+side)
    return store.events()[-1]


def capture(tmp_path,*,actual=True,clocks=True,sell_amount='1000',sell_actual=True,
            sell_refused=False,phase='initial',requested=1100,source_slot=None,
            source_time=None,include_sell=True,checkpoint_time=1030,inventory_damage=None,
            provenance='synthetic'):
    wall=[1021]
    with CaptureStore(tmp_path/'research.sqlite',clock_ms=lambda:wall[0]) as store:
        buy=quote_event(store,'buy',requested=1000,amount='100000000',output='1000',
            actual=actual,clocks=clocks,provenance=provenance)
        inventory=projected_research_inventory(buy,decision_at_ms=1030)
        wall[0]=checkpoint_time
        retained=deepcopy(inventory)
        if inventory_damage:inventory_damage(retained)
        store.append('checkpoint',provenance=provenance,mint=USDC,received_at_ms=checkpoint_time,
            outcome='research_inventory_fixed',payload={'inventory':retained})
        if include_sell:
            wall[0]=requested+21
            quote_event(store,'sell',requested=requested,amount=sell_amount,output='101000000',
                actual=sell_actual,clocks=clocks,source_slot=source_slot,source_time=source_time,
                refused=sell_refused,metadata=dict(probe_phase=phase,inventory_buy_observation_id=buy['id']),
                provenance=provenance)
        events=store.events();tail=store.verify_integrity()
    return events,tail,inventory,buy


def evaluate(tmp_path,**kwargs):
    events,tail,_,_=capture(tmp_path,**kwargs)
    return evaluate_research_cycles(events,expected_tail=tail)


def test_missing_actual_input_and_source_clocks_preserve_research_Q_but_not_strict_permission(tmp_path):
    events,tail,inventory,buy=capture(tmp_path,actual=False,clocks=False,sell_actual=False)
    assert inventory['accepted'] is True and inventory['acquired_atomic']=='1000'
    assert inventory['budget_lamports']=='100000000'
    assert inventory['actual_input_known'] is inventory['source_timing_qualified'] is False
    assert 'buy_actual_input_unknown' in inventory['limitations']
    assert 'buy_source_time_unknown' in inventory['limitations']
    strict=inventory_from_buy(buy,token_decimals=6,entry_decision_at_ms=1030,max_source_age_ms=5000)
    assert strict['accepted'] is False and 'buy_actual_input_unknown' in strict['reasons']
    result=evaluate_research_cycles(events,expected_tail=tail)
    assert result['complete_receipt_linked_indicative_pairs']==1
    assert result['complete_receipt_linked_live_market_pairs']==0
    assert result['complete_receipt_linked_synthetic_pairs']==1
    assert result['prospective_economic_cycles_usable']==result['strict_market_cycles']==0
    assert result['net_market_pnl_sol'] is None


def test_exact_conditional_delta_and_cost_scenarios_do_not_double_count_route_fee(tmp_path):
    result=evaluate(tmp_path)
    pair=result['research_cycles'][0]
    assert pair['conditional_quoted_delta_lamports']=='1000000'
    # Provider's route fee is already included in101000000 quoted proceeds.
    assert pair['curve_or_route_fees_already_in_quote_counted_again'] is False
    assert [x['conditional_net_lamports'] for x in pair['hypothetical_cost_scenarios']]==[
        '1000000','995000','900000','0']
    assert all(x['provenance']=='explicit_hypothesis_not_observed_cost' for x in pair['hypothetical_cost_scenarios'])
    assert pair['unknown_additional_cost_break_even_lamports']=='1000000'
    assert pair['retained_projected_quantity_atomic']=='1000'
    assert pair['modeled_remainder_atomic_if_full_quote_filled']=='0'
    assert pair['observed_position_or_remainder_atomic'] is None
    assert result['ledger_mutated'] is result['execution_verified'] is result['trade_allowed'] is False


@pytest.mark.parametrize('sell_amount,sell_actual,reason',[
    ('250',True,'sell_quote_not_for_full_projected_quantity'),
    ('1000','999','sell_actual_input_not_full_projected_quantity'),
])
def test_partial_or_adjusted_quotes_never_close_the_projected_lot(tmp_path,sell_amount,sell_actual,reason):
    result=evaluate(tmp_path,sell_amount=sell_amount,sell_actual=sell_actual)
    pair=result['research_cycles'][0]
    assert result['complete_receipt_linked_indicative_pairs']==0
    assert pair['reasons']==[reason]
    assert pair['retained_projected_quantity_atomic']=='1000'
    assert pair['conditional_quoted_delta_lamports'] is None


@pytest.mark.parametrize('actual',[ '99999999','1'])
def test_explicit_adjusted_buy_budget_is_not_assumed_to_equal_requested_spend(tmp_path,actual):
    _,_,inventory,_=capture(tmp_path,actual=actual,include_sell=False)
    assert inventory['accepted'] is False
    assert inventory['reasons']==['buy_actual_input_adjusted_budget_ambiguous']


def test_sell_refusal_is_retained_and_projected_remainder_not_sold(tmp_path):
    result=evaluate(tmp_path,sell_refused=True)
    pair=result['research_cycles'][0]
    assert pair['provider_refusal']=='provider_rejected'
    assert pair['reasons']==['sell_quote_unavailable']
    assert pair['retained_projected_quantity_atomic']=='1000'
    assert pair['conditional_quoted_delta_lamports'] is None


def test_absent_exit_is_unknown_with_all_expected_quantity_retained(tmp_path):
    result=evaluate(tmp_path,include_sell=False)
    assert result['research_cycles'][0]['status']=='UNKNOWN_EXIT'
    assert result['research_cycles'][0]['retained_projected_quantity_atomic']=='1000'


@pytest.mark.parametrize('kwargs,reason',[
    ({'requested':1025},'sell_requested_before_projected_inventory_committed'),
    ({'source_slot':99},'sell_source_slot_before_buy'),
    ({'source_time':989},'sell_source_clock_before_buy'),
    ({'requested':7000,'source_time':1000},'sell_source_quote_stale'),
    ({'source_time':99999999},'sell_local_or_source_chronology_inconsistent'),
    ({'phase':'followup'},'followup_before_preregistered_15000ms_horizon'),
])
def test_bad_chronology_and_premature_followup_never_produce_a_complete_pair(tmp_path,kwargs,reason):
    result=evaluate(tmp_path,**kwargs)
    assert result['complete_receipt_linked_indicative_pairs']==0
    assert result['research_cycles'][0]['reasons']==[reason]


def test_followup_after_15seconds_keeps_the_known_full_quantity_and_scope(tmp_path):
    result=evaluate(tmp_path,phase='followup',requested=16030)
    assert result['complete_receipt_linked_indicative_pairs']==1
    assert result['research_cycles'][0]['elapsed_after_inventory_decision_ms']==15000
    assert result['strict_market_cycles']==0


def test_forged_checkpoint_quantity_cannot_override_the_retained_buy_response(tmp_path):
    result=evaluate(tmp_path,inventory_damage=lambda value:value.update(acquired_atomic='9999999'))
    assert result['complete_receipt_linked_indicative_pairs']==0
    assert result['inventory_failures'][0]['reason']=='inventory_checkpoint_does_not_reproduce'
    assert result['buy_attempts'][0]['inventory_projected'] is False


def test_capture_integrity_is_verified_before_economic_arithmetic(tmp_path):
    events,tail,_,_=capture(tmp_path)
    events[-1]['payload']['output_amount_atomic']='999999999'
    with pytest.raises(ValueError):evaluate_research_cycles(events,expected_tail=tail)


def test_live_receipts_can_be_described_without_claiming_fresh_independent_economic_proof(tmp_path):
    result=evaluate(tmp_path,actual=False,clocks=False,sell_actual=False,provenance='live')
    assert result['complete_receipt_linked_live_market_pairs']==1
    assert result['complete_receipt_linked_synthetic_pairs']==0
    assert result['prospective_economic_cycles_usable']==0
    assert result['source_authenticity_or_independence_certified'] is False


def test_historical_replay_never_becomes_new_live_or_synthetic_market_data(tmp_path):
    result=evaluate(tmp_path,provenance='historical_replay')
    assert result['complete_receipt_linked_live_market_pairs']==0
    assert result['complete_receipt_linked_synthetic_pairs']==0
    assert result['complete_receipt_linked_historical_pairs']==1
