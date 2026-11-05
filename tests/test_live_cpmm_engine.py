"""One native journal/engine across a finalized LaunchLab buy and CPMM sells.

Every migration, bank, signature and finality response below is an explicit
isolated fixture. No market acquisition, secret, wallet or submission occurs.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from bot.live.cpmm_exit import build_cpmm_exit
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.engine import ExecutionEngine, reconcile_transaction
from bot.live.journal import ExecutionJournal
from bot.live.route import ephemeral_wsol_address
from bot.live.safety import AdmissionRequest,HealthEvidence,Mode,arm,enable
from bot.p3.certification import PROGRAM
from test_live_engine import FakeRpc,finalized_payload


def run(value):return asyncio.run(value)


class CpmmRpc(FakeRpc):
    def __init__(self):
        super().__init__();self.minimum_simulation_slots=[]

    async def simulate_transaction(self,raw,*,sig_verify,min_context_slot=None):
        self.minimum_simulation_slots.append(min_context_slot)
        return await super().simulate_transaction(raw,sig_verify=sig_verify)


def configured_cpmm(tmp_path):
    from test_live_cpmm_journal import registered
    engine,old,order,_tx,_amount,binding=registered(tmp_path)
    clock=[1500]
    engine.clock_ms=lambda:clock[0]
    engine.envelope=replace(engine.envelope,allowed_programs=(PROGRAM,CPMM_PROGRAM))
    engine.arming=enable(engine.envelope,arm(engine.envelope,now_ms=1400,
        arm_receipt='ISOLATED-cpmm-arm'),now_ms=1450,enable_receipt='ISOLATED-cpmm-enable')
    engine.mode=Mode.LIVE_ENABLED
    rpc=CpmmRpc();rpc.simulation['context_slot']=1600
    engine.rpc=rpc

    async def evidence(decision,prepared):
        parameters=json.loads(prepared.rebuild_request_json)
        program=CPMM_PROGRAM if type(prepared) is type(order) else PROGRAM
        current=engine.journal.migration_binding(prepared.mint,prepared.pool,
            at_ms=clock[0],source_slot=prepared.source_slot,wallet=prepared.user,
            endpoint_sha256=rpc.endpoint_sha256,genesis_hash=engine.envelope.genesis_hash) if program==CPMM_PROGRAM else None
        req=AdmissionRequest(decision_id=decision,side=prepared.side.lower(),wallet=prepared.user,
            cluster=engine.envelope.cluster,genesis_hash=engine.envelope.genesis_hash,
            rpc_endpoint_sha256=rpc.endpoint_sha256,program_id=program,
            mint=prepared.mint,pool=prepared.pool,quote_source_id='ISOLATED-CPMM-bank',
            quote_payload_sha256=prepared.source_account_digest,
            route_message_sha256=hashlib.sha256(prepared.transaction.message).hexdigest(),
            quote_received_at_ms=prepared.source_available_at_ms,risk_checked_at_ms=clock[0],
            quote_context_slot=prepared.source_slot,observed_bank_slot=prepared.source_slot,
            amount_in_atomic=prepared.input_amount,quote_input_atomic=prepared.input_amount,
            quote_output_atomic=prepared.expected_output,minimum_out_atomic=prepared.minimum_out,
            network_fee_upper_lamports=prepared.network_fee_upper_lamports,
            priority_fee_lamports=(parameters['compute_unit_limit']*parameters['priority_fee_micro_lamports']+999999)//1000000,
            compute_units=parameters['compute_unit_limit'],slippage_bps=parameters['slippage_bps'],
            price_impact_bps=prepared.price_impact_bps,rent_deposit_upper_lamports=prepared.rent_deposit_lamports,
            exit_capacity_atomic=prepared.input_amount,identity_verified=True,route_verified=True,
            costs_known=True,anti_rug_reasons=(),position_pool=current['inventory_pool'] if current else None)
        h=HealthEvidence(observed_at_ms=clock[0],scanner_heartbeat_at_ms=clock[0],
            rpc_success_at_ms=clock[0],websocket_heartbeat_at_ms=clock[0],
            scanner_connected=True,rpc_connected=True,websocket_connected=True,
            rpc_genesis_hash=engine.envelope.genesis_hash,rpc_endpoint_sha256=rpc.endpoint_sha256,
            clock_offset_ms=0)
        return req,h
    engine.evidence_provider=evidence
    return engine,old,order,rpc,clock,binding


def decision(order):return json.loads(order.rebuild_request_json)['decision_id']


def settle(engine,rpc,order,result,slot,*,error=None,proceeds=None):
    rpc.tx=finalized_payload(order,result['signature'],error=error,proceeds=proceeds)
    rpc.tx['slot']=slot
    rpc.status=dict(confirmationStatus='finalized',err=error,slot=slot)
    return run(engine.recover(decision(order)))


def resized(order,*,amount,held,ident,slot=1700,at=1700):
    import struct
    from test_live_cpmm_exit import mutate_raw
    args=json.loads(order.rebuild_request_json)
    previous=args['decision_id'];args['accounts']=deepcopy(args['accounts'])
    old_wsol,_=ephemeral_wsol_address(order.user,previous)
    args['accounts'].pop(old_wsol)
    new_wsol,_=ephemeral_wsol_address(order.user,ident);args['accounts'][new_wsol]=None
    args.update(amount_in=amount,decision_id=ident,context_slot=slot,
        available_at_ms=at,decision_at_ms=at)
    mutate_raw(args['accounts'][order.base_token_account],64,struct.pack('<Q',held))
    return build_cpmm_exit(**args)


def test_same_engine_buy_migrate_sell_reconciles_original_position_exactly_once(tmp_path):
    engine,old,order,rpc,clock,binding=configured_cpmm(tmp_path)
    before=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    try:
        result=run(engine.execute(decision(order),order))
        assert result['state']=='SUBMITTED'
        assert rpc.minimum_simulation_slots==[order.source_slot]
        row=engine.journal.get(decision(order));saved=json.loads(row['order_json'])
        assert saved['program_id']==CPMM_PROGRAM and saved['pool']==order.pool
        assert saved['inventory_pool']==old.pool and old.pool!=order.pool
        assert saved['migration_binding_sha256']==binding['binding_sha256']
        assert row['reserved_atomic']==before['quantity_atomic']
        assert settle(engine,rpc,order,result,1600)['state']=='RECONCILED'
        position=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
        assert position['pool']==old.pool and position['quantity_atomic']==0
        assert position['entry_cost_lamports']==0
        assert position['locked_rent_lamports']==before['locked_rent_lamports']
        assert engine.journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
        daily=engine.journal.con.execute('SELECT * FROM daily').fetchone()
        assert daily['realized_pnl']==order.expected_output-5002-before['entry_cost_lamports']
        run(engine.recover(decision(order)));run(engine.execute(decision(order),order))
        assert len(rpc.send_calls)==1
        assert engine.journal.verify_audit()
    finally:engine.journal.close()


def test_cpmm_partial_exit_then_restart_and_full_remainder_preserve_total_cost(tmp_path):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    initial=engine.journal.con.execute('SELECT * FROM positions').fetchone()
    basis,held=initial['entry_cost_lamports'],initial['quantity_atomic']
    half=held//2
    first=resized(order,amount=half,held=held,ident='ISOLATED-cpmm-half',slot=1700,at=1700)
    clock[0]=1700;rpc.simulation['context_slot']=1700
    result=run(engine.execute(decision(first),first));settle(engine,rpc,first,result,1701)
    intermediate=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    assert intermediate['quantity_atomic']==held-half and intermediate['pool']==old.pool
    engine.journal.close()
    journal=ExecutionJournal(tmp_path/'private-live.sqlite');engine.journal=journal
    # The constructor re-verifies persisted orders, migration mapping and book.
    restored=ExecutionEngine(journal=journal,rpc=rpc,clock_ms=lambda:clock[0])
    run(restored.recover(decision(first)))
    last=resized(order,amount=held-half,held=held-half,ident='ISOLATED-cpmm-last',slot=1800,at=1800)
    clock[0]=1800;rpc.simulation['context_slot']=1800
    try:
        done=run(engine.execute(decision(last),last));settle(engine,rpc,last,done,1801)
        final=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        assert final['quantity_atomic']==final['entry_cost_lamports']==0
        assert final['pool']==old.pool
        daily=journal.con.execute('SELECT * FROM daily').fetchone()
        assert daily['realized_pnl']==first.expected_output+last.expected_output-10004-basis
        assert len(rpc.send_calls)==2 and journal.verify_audit()
    finally:journal.close()


def test_ambiguous_cpmm_send_keeps_original_inventory_reserved_across_restart(tmp_path):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    rpc.send_error=TimeoutError('ISOLATED-not-network')
    result=run(engine.execute(decision(order),order))
    assert result['state']=='UNCERTAIN' and engine.journal.killed
    reserved=engine.journal.get(decision(order))['reserved_atomic']
    assert reserved==order.input_amount
    engine.journal.close()
    journal=ExecutionJournal(tmp_path/'private-live.sqlite')
    restored=ExecutionEngine(journal=journal,rpc=rpc,clock_ms=lambda:clock[0])
    try:
        rpc.height=5001
        assert run(restored.recover(decision(order)))['state']=='EXPIRED_UNKNOWN'
        assert journal.get(decision(order))['reserved_atomic']==reserved
        assert journal.con.execute('SELECT pool FROM positions').fetchone()[0]==old.pool
        assert len(rpc.send_calls)==1 and journal.verify_audit()
    finally:journal.close()


def test_failed_cpmm_sell_charges_fee_without_changing_original_quantity_or_basis(tmp_path):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    before=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
    error={'InstructionError':[4,{'Custom':6000}]}
    try:
        result=run(engine.execute(decision(order),order));settle(engine,rpc,order,result,1600,error=error)
        after=dict(engine.journal.con.execute('SELECT * FROM positions').fetchone())
        assert before==after
        daily=engine.journal.con.execute('SELECT * FROM daily').fetchone()
        assert daily['realized_loss']==5002 and daily['realized_pnl']==-5002
        assert engine.journal.get(decision(order))['reserved_atomic']==0
        assert engine.journal.verify_audit()
    finally:engine.journal.close()


@pytest.mark.parametrize('damage',['program','position','quantity','missing_binding'])
def test_cpmm_admission_rejects_mismatched_route_or_unbound_position(tmp_path,damage):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    provider=engine.evidence_provider
    if damage=='missing_binding':
        engine.journal.con.execute('DELETE FROM cpmm_migrations')
    else:
        async def altered(*args):
            req,h=await provider(*args)
            field={'program':'program_id','position':'position_pool','quantity':'amount_in_atomic'}[damage]
            value={'program':PROGRAM,'position':order.pool,'quantity':order.input_amount-1}[damage]
            return replace(req,**{field:value}),h
        engine.evidence_provider=altered
    try:
        with pytest.raises((ValueError,RuntimeError)):
            run(engine.execute(decision(order),order))
        assert not rpc.send_calls
    finally:engine.journal.close()


def test_cpmm_finalized_receipt_rejects_changed_message_and_stale_slot(tmp_path):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    try:
        result=run(engine.execute(decision(order),order))
        row=engine.journal.get(decision(order));payload=finalized_payload(order,result['signature'])
        payload['slot']=order.source_slot-1
        with pytest.raises(ValueError,match='precedes'):reconcile_transaction(row,payload)
        payload['slot']=1600;payload['transaction']['message']['instructions'][-1]['data']='1'
        with pytest.raises(ValueError,match='message'):reconcile_transaction(row,payload)
        assert engine.journal.get(decision(order))['reserved_atomic']==order.input_amount
    finally:engine.journal.close()


def test_known_migration_retires_forged_active_LaunchLab_route_before_simulation(tmp_path):
    from bot.live.route import build_launchlab_order
    engine,old,cpmm,rpc,clock,_=configured_cpmm(tmp_path)
    args=json.loads(old.rebuild_request_json)
    args['accounts'][old.base_token_account]=deepcopy(json.loads(cpmm.rebuild_request_json)['accounts'][cpmm.base_token_account])
    prior=args['decision_id'];old_temp,_=ephemeral_wsol_address(old.user,prior)
    args['accounts'].pop(old_temp)
    new_id='ISOLATED-false-active-LaunchLab'
    new_temp,_=ephemeral_wsol_address(old.user,new_id);args['accounts'][new_temp]=None
    args.update(side='SELL',amount_in=cpmm.input_amount,decision_id=new_id,
        context_slot=1700,available_at_ms=1500,decision_at_ms=1500)
    forged=build_launchlab_order(**args)
    try:
        with pytest.raises(ValueError,match='retired'):
            run(engine.execute(new_id,forged))
        assert not rpc.simulation_calls and not rpc.send_calls
        assert engine.journal.risk_snapshot(at=1500,wallet_balance_lamports=10_000_000_000).reserved_lamports==0
    finally:engine.journal.close()


@pytest.mark.parametrize('source',['endpoint','genesis'])
def test_restart_reconciliation_rejects_different_rpc_source_before_status_lookup(tmp_path,source):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    result=run(engine.execute(decision(order),order))
    row=engine.journal.get(decision(order));reservation=row['reserved_atomic']
    if source=='endpoint':rpc.endpoint_sha256='b'*64
    else:
        async def wrong_genesis():return old.pool
        rpc.genesis_hash=wrong_genesis
    async def no_status(*_):raise AssertionError('No wrong-source status lookup')
    rpc.signature_status=no_status
    try:
        with pytest.raises(ValueError):run(engine.recover(decision(order)))
        assert engine.journal.get(decision(order))['reserved_atomic']==reservation
        assert len(rpc.send_calls)==1
    finally:engine.journal.close()


@pytest.mark.parametrize('damage',[
    'temp_rent_not_closed','preexisting_temp_balance',
    'temp_post_token_zero','temp_post_token_positive',
    'post_token_balances_missing','post_token_index_boolean',
])
def test_finalized_cpmm_sell_cannot_settle_with_unclosed_ephemeral_wsol(
        tmp_path,damage):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    result=run(engine.execute(decision(order),order))
    assert result['state']=='SUBMITTED'
    saved=engine.journal.get(decision(order))
    payload=finalized_payload(order,result['signature'])
    payload['slot']=1600
    keys=payload['transaction']['message']['accountKeys']
    index=keys.index(order.quote_token_account)
    assert index!=keys.index(order.base_token_account)
    if damage=='temp_rent_not_closed':
        payload['meta']['postBalances'][index]=order.rent_deposit_lamports
    elif damage=='preexisting_temp_balance':
        payload['meta']['preBalances'][index]=1
    elif damage=='post_token_balances_missing':
        payload['meta'].pop('postTokenBalances')
    elif damage=='post_token_index_boolean':
        payload['meta']['postTokenBalances'].append(
            dict(accountIndex=True,mint=order.mint,owner=order.user,
                 uiTokenAmount=dict(amount='0')))
    else:
        payload['meta']['postTokenBalances'].append(
            dict(accountIndex=index,mint='So11111111111111111111111111111111111111112',
                 owner=order.user,
                 uiTokenAmount=dict(amount='0' if damage=='temp_post_token_zero' else '1')))
    before=[dict(x) for x in engine.journal.con.execute('SELECT * FROM positions')]
    try:
        with pytest.raises(ValueError,match='CPMM_'):
            reconcile_transaction(saved,payload)
        assert [dict(x) for x in engine.journal.con.execute(
            'SELECT * FROM positions')]==before
        assert engine.journal.get(decision(order))['reserved_atomic']==order.input_amount
        assert len(rpc.send_calls)==1
        assert engine.journal.verify_audit()
    finally:engine.journal.close()


def test_finalized_cpmm_sell_proves_ephemeral_wsol_close_with_real_receipt_shape(tmp_path):
    engine,old,order,rpc,clock,_=configured_cpmm(tmp_path)
    try:
        result=run(engine.execute(decision(order),order))
        assert result['state']=='SUBMITTED'
        payload=finalized_payload(order,result['signature'])
        payload['slot']=1600
        keys=payload['transaction']['message']['accountKeys']
        index=keys.index(order.quote_token_account)
        assert payload['meta']['preBalances'][index]==0
        assert payload['meta']['postBalances'][index]==0
        reconciliation=reconcile_transaction(engine.journal.get(decision(order)),payload)
        assert reconciliation['chain_error'] is None
        assert reconciliation['inventory_pool']==old.pool
        assert reconciliation['gross_output_lamports']==order.expected_output
        assert reconciliation['rent_locked_lamports']==0
    finally:engine.journal.close()
