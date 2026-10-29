"""Native-SOL decisions use finalized fake-RPC inventory, never PAPER quotes."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from bot.live.engine import ExecutionEngine
from bot.live.journal import ExecutionJournal
from bot.live.positions import FrozenEntryPlan, persist_entry_plan, evaluate_live_position
from bot.live.route import build_launchlab_order
from bot.p3.launchlab import _pool
from test_live_engine import configured, finalized_payload, sell_request, FakeRpc
from test_p3_research_integration import mutate_account


def plan_for(order, **changes):
    data=dict(entry_decision_id=json.loads(order.rebuild_request_json)['decision_id'],
        entry_at_ms=1100,tp_pct='1000',sl_pct='100',trailing_stop_pct='0',
        hold_seconds=1800,net_take_profit_lamports=0,max_observation_age_ms=5000,
        max_price_impact_bps=2000)
    data.update(changes)
    return FrozenEntryPlan(**data)


def filled(tmp_path, **changes):
    engine,order,rpc,signer,clock=configured(tmp_path)
    plan=plan_for(order,**changes)
    persist_entry_plan(engine.journal,order.mint,order.pool,plan,at_ms=1100)
    result=asyncio.run(engine.execute(plan.entry_decision_id,order))
    rpc.status=dict(confirmationStatus='finalized',err=None,slot=1300)
    rpc.tx=finalized_payload(order,result['signature'])
    asyncio.run(engine.recover(plan.entry_decision_id))
    return engine,order,plan,rpc,clock


def frame_for(order, held, *, at=1200, ident='frame-1', partial=None, quote_add=0):
    request=sell_request(held,held,'exit-'+ident)
    request.update(context_slot=1301+(at-1200),available_at_ms=at,decision_at_ms=at)
    if quote_add:
        # Synthetic, coherent external buy movement; never a market observation.
        from test_p3_asof_real_decoder_integration import _advance_accounts
        from bot.p3.launchlab import addresses_from_pool
        addresses=addresses_from_pool(request['accounts'][order.pool],pool_address=order.pool)
        request['accounts']=_advance_accounts(request['accounts'],addresses,
            token_atomic=1000000,sol_lamports=quote_add)
    full=build_launchlab_order(**request)
    partials=[]
    if partial:
        request['amount_in']=partial
        partials.append(build_launchlab_order(**request))
    return dict(id=ident,mint=order.mint,pool=order.pool,available_at_ms=at,
        source_slot=request['context_slot'],prepared_full_exit=full,
        prepared_partial_exits=tuple(partials))


def health(at=1200,**changes):
    return dict(allow_position_management=True,observed_at_ms=at,**changes)


def evaluate(engine,order,frame,**kwargs):
    at=kwargs.pop('at',frame['available_at_ms'])
    return evaluate_live_position(engine.journal,order.mint,order.pool,frame,
        health=kwargs.pop('health',health(at)),at=at,**kwargs)


def test_unknown_frozen_plan_and_retrospective_registration_refuse(tmp_path):
    engine,order,rpc,_,_=configured(tmp_path)
    result=asyncio.run(engine.execute(json.loads(order.rebuild_request_json)['decision_id'],order))
    rpc.status=dict(confirmationStatus='finalized',err=None,slot=1300)
    rpc.tx=finalized_payload(order,result['signature'])
    asyncio.run(engine.recover(json.loads(order.rebuild_request_json)['decision_id']))
    frame=frame_for(order,order.expected_output)
    assert evaluate(engine,order,frame)['reasons']==['pre_entry_frozen_plan_missing']
    with pytest.raises(ValueError,match='before_order'):
        persist_entry_plan(engine.journal,order.mint,order.pool,plan_for(order),at_ms=1100)


def test_native_sol_hold_uses_exact_inventory_without_usd_or_fake_quote(tmp_path):
    engine,order,plan,_,_=filled(tmp_path)
    frame=frame_for(order,order.expected_output)
    result=evaluate(engine,order,frame)
    assert result['action']=='HOLD' and result['remaining_atomic']==str(order.expected_output)
    assert result['conditional_full_net_lamports'] is not None
    assert result['liquidation_basis']=='CONDITIONAL_PINNED_CURVE_AT_OBSERVED_BANK'
    assert result['execution_verified'] is False
    assert 'price_usd' not in frame


def test_frozen_stop_loss_uses_net_sell_value_after_actual_entry_fee(tmp_path):
    engine,order,plan,_,_=filled(tmp_path,sl_pct='0.1')
    frame=frame_for(order,order.expected_output)
    result=evaluate(engine,order,frame)
    full=frame['prepared_full_exit']
    assert result['action']=='EXIT' and result['reasons']==['frozen_stop_loss_reached']
    assert result['input_quantity_atomic']==str(order.expected_output)
    assert int(result['conditional_full_net_lamports'])==full.expected_output-full.network_fee_upper_lamports-(order.input_amount+5002)
    assert result['execution_blocked'] is False


def test_time_stop_and_emergency_are_blocked_without_qualified_full_exit(tmp_path):
    engine,order,plan,_,_=filled(tmp_path,hold_seconds=1)
    frame=frame_for(order,order.expected_output,at=2200)
    frame['prepared_full_exit']=None
    result=evaluate(engine,order,frame)
    assert result['action']=='EXIT' and result['execution_blocked']
    assert 'full_exact_exit_model_unavailable' in result['reasons']
    engine.journal.kill('fixture emergency',2300)
    frame['id']='emergency';frame['available_at_ms']=2300
    result=evaluate(engine,order,frame)
    assert result['action']=='EMERGENCY_EXIT' and result['execution_blocked']
    assert result['input_quantity_atomic']==str(order.expected_output)


@pytest.mark.parametrize('change', ['future','stale','wrong_quantity','fees_unknown','old_slot'])
def test_exit_causality_exact_quantity_and_costs_fail_closed(tmp_path,change):
    engine,order,plan,_,_=filled(tmp_path,sl_pct='0.1')
    frame=frame_for(order,order.expected_output)
    if change=='future':frame['available_at_ms']=1300
    if change=='stale':frame['available_at_ms']=1
    if change=='wrong_quantity':frame['prepared_full_exit']=replace(frame['prepared_full_exit'],input_amount=1)
    if change=='fees_unknown':frame['prepared_full_exit']=replace(frame['prepared_full_exit'],network_fee_upper_lamports=None)
    if change=='old_slot':frame['source_slot']=1299
    result=evaluate(engine,order,frame,at=1200)
    assert result['action']=='WAIT_FOR_DATA' and result['execution_blocked']
    assert result['conditional_full_net_lamports'] is None


def test_plan_thresholds_are_immutable_and_no_replacement_from_frame(tmp_path):
    engine,order,plan,_,_=filled(tmp_path)
    changed=replace(plan,sl_pct='0.1')
    with pytest.raises(ValueError,match='immutable'):
        persist_entry_plan(engine.journal,order.mint,order.pool,changed,at_ms=1200)
    result=evaluate(engine,order,frame_for(order,order.expected_output),entry_plan=changed)
    assert result['reasons']==['supplied_entry_plan_differs_from_frozen_plan']


def test_decisions_and_peak_survive_restart_replay_and_detect_mutation(tmp_path):
    engine,order,plan,_,_=filled(tmp_path)
    frame=frame_for(order,order.expected_output)
    original=evaluate(engine,order,frame)
    count=engine.journal.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
    engine.journal.close()
    journal=ExecutionJournal(tmp_path/'private-live.sqlite')
    restored=ExecutionEngine(journal=journal,rpc=FakeRpc())
    assert evaluate(restored,order,frame)==original
    assert journal.con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==count
    changed=deepcopy(frame);changed['features']={'observed_at':1,'momentum_60s':1}
    with pytest.raises(ValueError,match='reused_with_changed'):
        evaluate(restored,order,changed)
    journal.con.execute("UPDATE live_position_peaks SET numerator='999999'")
    with pytest.raises(ValueError,match='bound_to_durable_audit'):
        evaluate(restored,order,frame)


def test_partial_reduction_then_final_close_preserves_exact_remaining_cost(tmp_path):
    engine,order,plan,rpc,clock=filled(tmp_path)
    held=order.expected_output;half=held//2
    frame=frame_for(order,held,partial=half)
    frame.update(features=dict(mint=order.mint,observed_at=1,momentum_60s=-1,
        tx_buys_5m=1,tx_sells_5m=2),features_available_at_ms=1200)
    result=evaluate(engine,order,frame)
    assert result['action']=='REDUCE' and result['input_quantity_atomic']==str(half)
    sell=frame['prepared_partial_exits'][0];clock[0]=1200
    decision=json.loads(sell.rebuild_request_json)['decision_id']
    submitted=asyncio.run(engine.execute(decision,sell))
    rpc.tx=finalized_payload(sell,submitted['signature']);rpc.tx['slot']=1302
    rpc.status=dict(confirmationStatus='finalized',err=None,slot=1302)
    asyncio.run(engine.recover(decision))
    position=engine.journal.con.execute('SELECT * FROM positions').fetchone()
    assert position['quantity_atomic']==held-half
    basis=position['entry_cost_lamports']
    next_frame=frame_for(order,held-half,at=1400,ident='after-partial')
    next_result=evaluate(engine,order,next_frame)
    full=next_frame['prepared_full_exit']
    assert int(next_result['remaining_basis_lamports'])==basis
    assert int(next_result['conditional_full_net_lamports'])==full.expected_output-full.network_fee_upper_lamports-basis
    with pytest.raises(ValueError,match='reused_with_changed'):
        evaluate(engine,order,frame)
