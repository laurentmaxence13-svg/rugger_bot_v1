"""Frozen Master exits continue over one inventory through CPMM graduation.

All accounts, migration receipts, signer responses and finality responses are
isolated fixtures. These tests execute the actual runtime, router, native
accountant and restart path; they never contact a market or claim real profit.
"""
import asyncio
from copy import deepcopy
import json
import struct

import pytest

from bot.live.cpmm_exit import build_cpmm_exit,_pool
from bot.live.engine import ExecutionEngine
from bot.live.journal import ExecutionJournal
from bot.live.positions import FrozenEntryPlan,persist_entry_plan,evaluate_live_position
from bot.live.route import build_launchlab_order,ephemeral_wsol_address
from bot.live.runtime import LiveRuntime
from bot.p3.certification import _decode
from bot.p3.quotes import SOL_MINT
from test_live_cpmm_engine import configured_cpmm,resized,settle
from test_live_cpmm_exit import mutate_raw


def run(value):return asyncio.run(value)


def configured_runtime(tmp_path,monkeypatch,*,sl_pct='100',hold_seconds=1800):
    original_execute=ExecutionEngine.execute
    async def freeze_before_actual_buy(engine,decision_id,order):
        if order.side=='BUY':
            plan=FrozenEntryPlan(entry_decision_id=decision_id,entry_at_ms=1100,
                tp_pct='1000',sl_pct=sl_pct,trailing_stop_pct='0',
                hold_seconds=hold_seconds,net_take_profit_lamports=0,
                max_observation_age_ms=5000,max_price_impact_bps=2000)
            persist_entry_plan(engine.journal,order.mint,order.pool,plan,at_ms=1100)
        return await original_execute(engine,decision_id,order)
    # The shared fixture normally calls the engine directly. Freeze the exact
    # entry plan at that same pre-entry boundary, as the real runtime does.
    with monkeypatch.context() as m:
        m.setattr(ExecutionEngine,'execute',freeze_before_actual_buy)
        engine,old,order,rpc,clock,binding=configured_cpmm(tmp_path)
    async def context():
        return dict(health=dict(allow_new_entries=True,observed_at_ms=clock[0]),capital=None)
    async def no_buy(*_):raise AssertionError('CPMM position management must not request a new BUY')
    runtime=LiveRuntime(engine=engine,decision_context_provider=context,
        route_request_provider=no_buy,clock_ms=lambda:clock[0])
    runtime.approved_policy_sha256=runtime.core.policy_sha256
    return runtime,engine,old,order,rpc,clock,binding


def priced(order,*,basis,held,amount=None,ident='runtime-cpmm',at=1500,slot=1500):
    amount=held if amount is None else amount
    value=resized(order,amount=amount,held=held,ident=ident,at=at,slot=slot)
    data=json.loads(value.rebuild_request_json)
    import base64
    pool=_pool(base64.b64decode(data['accounts'][order.pool]['data'][0]))
    token_index=0 if pool['token_0_mint']==order.mint else 1
    input_key=pool[f'token_{token_index}_vault']
    quote_key=pool[f'token_{1-token_index}_vault']
    raw=base64.b64decode(data['accounts'][input_key]['data'][0])
    reserve=struct.unpack_from('<Q',raw,64)[0]
    # A synthetic contemporaneous bank with liquidation near the actual entry
    # basis. Its real integer curve fees make it slightly below break-even.
    quote=basis*(reserve+held)//held
    mutate_raw(data['accounts'][quote_key],64,struct.pack('<Q',quote))
    data['accounts'][quote_key]['lamports']=quote+2039280
    return build_cpmm_exit(**data)


def frame(old,order,*,ident='CPMM-frame',partials=()):
    return dict(id=ident,kind='position',mint=old.mint,pool=old.pool,
        available_at_ms=order.decision_at_ms,source_slot=order.source_slot,
        prepared_full_exit=order,prepared_partial_exits=partials)


def test_runtime_frozen_stop_loss_executes_cpmm_and_settles_original_position(tmp_path,monkeypatch):
    runtime,engine,old,cpmm,rpc,clock,binding=configured_runtime(tmp_path,monkeypatch,sl_pct='0.1')
    before=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    order=priced(cpmm,basis=before['entry_cost_lamports'],held=before['quantity_atomic'])
    try:
        value=run(runtime.observe_position(frame(old,order)))
        assert value['proposal']['action']=='EXIT'
        assert value['proposal']['reasons']==['frozen_stop_loss_reached']
        assert value['proposal']['migration_binding_sha256']==binding['binding_sha256']
        assert value['inventory_pool']==old.pool and value['execution_pool']==cpmm.pool
        assert value['proposal']['liquidation_basis']=='CONDITIONAL_CPMM_AT_OBSERVED_BANK'
        assert value['execution']['state']=='SUBMITTED'
        again=run(runtime.observe_position(frame(old,order)))
        assert again['execution']['state']=='SUBMITTED' and len(rpc.send_calls)==1
        assert settle(engine,rpc,order,value['execution'],1600)['state']=='RECONCILED'
        position=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
        assert position['pool']==old.pool and position['quantity_atomic']==0
        assert position['entry_cost_lamports']==0
        assert position['locked_rent_lamports']==before['locked_rent_lamports']
        assert engine.journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
        assert engine.journal.verify_audit()
    finally:engine.journal.close()


def test_partial_reduction_restart_and_timeout_keep_one_frozen_plan_and_cost_basis(tmp_path,monkeypatch):
    runtime,engine,old,cpmm,rpc,clock,_=configured_runtime(tmp_path,monkeypatch,hold_seconds=1)
    before=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    held,basis=before['quantity_atomic'],before['entry_cost_lamports'];half=held//2
    full=priced(cpmm,basis=basis,held=held,ident='cpmm-full-initial')
    partial=priced(cpmm,basis=basis,held=held,amount=half,ident='cpmm-partial-initial')
    tape=frame(old,full,partials=(partial,))
    tape.update(features=dict(mint=old.mint,observed_at=1,momentum_60s=-1,
        tx_buys_5m=1,tx_sells_5m=2),features_available_at_ms=1500)
    frozen=engine.journal.con.execute('SELECT plan_json FROM live_position_plans').fetchone()[0]
    first=run(runtime.observe_position(tape))
    assert first['proposal']['action']=='REDUCE'
    assert first['proposal']['input_quantity_atomic']==str(half)
    settle(engine,rpc,partial,first['execution'],1600)
    middle=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    assert middle['quantity_atomic']==held-half and middle['pool']==old.pool
    engine.journal.close()
    journal=ExecutionJournal(tmp_path/'private-live.sqlite');engine.journal=journal
    restored=ExecutionEngine(journal=journal,rpc=rpc,signer=engine.signer,
        verifier=engine.verifier,mode=engine.mode,envelope=engine.envelope,
        arming=engine.arming,evidence_provider=engine.evidence_provider,clock_ms=lambda:clock[0])
    runtime.engine=restored;clock[0]=2300;rpc.simulation['context_slot']=1800
    final=priced(cpmm,basis=middle['entry_cost_lamports'],held=held-half,
        ident='cpmm-final-remainder',at=2300,slot=1800)
    try:
        value=run(runtime.observe_position(frame(old,final,ident='CPMM-remainder')))
        assert value['proposal']['action']=='EXIT'
        assert value['proposal']['reasons']==['frozen_maximum_hold_reached']
        assert int(value['proposal']['remaining_basis_lamports'])==middle['entry_cost_lamports']
        assert int(value['proposal']['conditional_position_net_lamports'])==partial.expected_output+final.expected_output-10004-basis
        settle(restored,rpc,final,value['execution'],1801)
        assert journal.con.execute('SELECT quantity_atomic,entry_cost_lamports FROM positions').fetchone()[:]==(0,0)
        assert journal.con.execute('SELECT plan_json FROM live_position_plans').fetchone()[0]==frozen
        assert len(rpc.send_calls)==2 and journal.verify_audit()
    finally:journal.close()


@pytest.mark.parametrize('damage',['missing_binding','before_receipt','wrong_original_pool','future_features'])
def test_migration_position_unknown_or_noncausal_source_never_executes(tmp_path,monkeypatch,damage):
    runtime,engine,old,cpmm,rpc,clock,_=configured_runtime(tmp_path,monkeypatch,sl_pct='0.1')
    before=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    order=priced(cpmm,basis=before['entry_cost_lamports'],held=before['quantity_atomic'])
    tape=frame(old,order)
    if damage=='missing_binding':engine.journal.con.execute('DELETE FROM cpmm_migrations')
    if damage=='wrong_original_pool':tape['pool']=cpmm.pool
    if damage=='future_features':tape['features_available_at_ms']=1501
    if damage=='before_receipt':
        args=json.loads(order.rebuild_request_json);args['available_at_ms']=1399
        tape['prepared_full_exit']=build_cpmm_exit(**args)
    try:
        if damage in ('missing_binding','future_features'):
            with pytest.raises(ValueError):run(runtime.observe_position(tape))
        else:
            response=run(runtime.observe_position(tape))
            assert response['execution'] is None and response['proposal']['execution_blocked']
        assert not rpc.send_calls
        assert dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())==before
    finally:engine.journal.close()
