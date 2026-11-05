"""Original-pool inventory identity survives CPMM settlement and restarts.

All fills and migration RPC responses are isolated synthetic fixtures. No key,
network, user database or actual financial operation is involved.
"""
import asyncio
from copy import deepcopy
import hashlib
import json

import pytest

from bot.live.engine import order_record
from bot.live.journal import ExecutionJournal,canonical
from bot.live.migration_rpc_receipt import read_finalized_migration
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.cpmm_exit import build_cpmm_exit
from bot.live.route import ephemeral_wsol_address
from bot.p3.certification import _encode
from test_live_cpmm_stage import _staged
from test_live_migration_evidence import SIG
from test_live_signed_migration_reference import signed_rpc_migration
from test_live_unsigned_preflight import GENESIS,ENDPOINT


def registered(tmp_path):
    engine,old,cpmm,tx,amount=_staged(tmp_path)
    signed,real_sig=signed_rpc_migration(tx)
    class Rpc:
        endpoint_sha256=ENDPOINT
        async def genesis_hash(self):return GENESIS
        async def get_transaction(self,signature):
            assert signature==real_sig
            return deepcopy(signed)
    receipt=asyncio.run(read_finalized_migration(Rpc(),signature=real_sig,mint=cpmm.mint,
        launchlab_pool=old.pool,cpmm_pool=cpmm.pool,expected_endpoint_sha256=ENDPOINT,
        expected_genesis_hash=GENESIS,observed_at_slot=cpmm.source_slot))
    assert receipt['status']=='FINALIZED_RPC_STRUCTURAL_MATCH',receipt
    binding=engine.journal.register_cpmm_migration(receipt,wallet=cpmm.user,
        received_at_ms=1400,expected_endpoint_sha256=ENDPOINT,expected_genesis_hash=GENESIS)
    assert binding['cryptographic_signature_verified'] is True
    assert binding['consensus_independently_verified'] is False
    return engine,old,cpmm,signed,amount,binding


def record(cpmm,binding,**overrides):
    value=order_record(cpmm)
    value.update(route_kind='CPMM',program_id=CPMM_PROGRAM,
        inventory_pool=binding['inventory_pool'],migration_binding_sha256=binding['binding_sha256'])
    value.update(overrides)
    return value


def reserve(journal,decision):
    return journal.reserve(decision,1500,wallet_balance_lamports=10_000_000_000,
        max_capital_lamports=1_000_000_000,max_open_positions=4,
        max_in_flight_orders=3,max_daily_spend_lamports=2_000_000_000,
        max_daily_loss_lamports=100_000_000)


def prepared(journal,value,decision='journal-cpmm-exit'):
    journal.create(decision,value,1500)
    journal.transition(decision,('PREPARED',),'SIMULATED',1500)
    return decision


def partial_order(order,quantity,decision):
    args=json.loads(order.rebuild_request_json)
    args['accounts'].pop(ephemeral_wsol_address(order.user,args['decision_id'])[0])
    args.update(amount_in=quantity,decision_id=decision)
    args['accounts'][ephemeral_wsol_address(order.user,decision)[0]]=None
    return build_cpmm_exit(**args)


def fill(order,*,slot=1600,failed=False):
    fee=5000
    return dict(slot=slot,fee_lamports=fee,
        chain_error={'InstructionError':[1,'Custom']} if failed else None,
        token_delta_atomic=0 if failed else -order.input_amount,
        wallet_delta_lamports=-fee if failed else order.expected_output-fee,
        gross_output_lamports=0 if failed else order.expected_output,
        rent_locked_lamports=0,realized_market_execution=True,economic_edge_proven=False)


def test_registration_keeps_one_original_position_and_source_receipt_across_restart(tmp_path):
    engine,old,cpmm,_,amount,binding=registered(tmp_path)
    journal=engine.journal
    before=[dict(r) for r in journal.con.execute('SELECT * FROM positions')]
    assert len(before)==1 and before[0]['pool']==old.pool and before[0]['quantity_atomic']==amount
    again=journal.register_cpmm_migration(binding['receipt'],wallet=cpmm.user,
        received_at_ms=1400,expected_endpoint_sha256=ENDPOINT,expected_genesis_hash=GENESIS)
    assert again==binding
    assert journal.register_cpmm_migration(binding['receipt'],wallet=cpmm.user,
        received_at_ms=1500,expected_endpoint_sha256=ENDPOINT,expected_genesis_hash=GENESIS)==binding
    assert [dict(r) for r in journal.con.execute('SELECT * FROM positions')]==before
    journal.close()
    restored=ExecutionJournal(tmp_path/'private-live.sqlite')
    try:
        assert restored.migration_binding(cpmm.mint,cpmm.pool,at_ms=1500,source_slot=1500,
            wallet=cpmm.user,endpoint_sha256=ENDPOINT,genesis_hash=GENESIS)==binding
        assert restored.verify_audit()
        assert restored.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
    finally:restored.close()


@pytest.mark.parametrize('change',['structural_only','raw_hash','wrong_wallet','wrong_endpoint','wrong_genesis','too_early'])
def test_migration_cannot_be_promoted_by_missing_or_inconsistent_rpc_evidence(tmp_path,change):
    engine,old,cpmm,tx,amount,binding=registered(tmp_path)
    receipt=deepcopy(binding['receipt']);wallet=cpmm.user;endpoint=ENDPOINT;genesis=GENESIS
    if change=='structural_only':receipt=receipt['structural_validation']
    elif change=='raw_hash':receipt['raw_RPC_response']['slot']+=1
    elif change=='wrong_wallet':wallet=old.mint
    elif change=='wrong_endpoint':endpoint='b'*64
    elif change=='wrong_genesis':genesis=old.pool
    elif change=='too_early':
        receipt['raw_RPC_response']['slot']=1300
        receipt['raw_response_sha256']=hashlib.sha256(canonical(receipt['raw_RPC_response']).encode()).hexdigest()
    try:
        with pytest.raises(ValueError):
            engine.journal.register_cpmm_migration(receipt,wallet=wallet,
                received_at_ms=1400,expected_endpoint_sha256=endpoint,expected_genesis_hash=genesis)
        assert engine.journal.verify_audit()
    finally:engine.journal.close()


@pytest.mark.parametrize('change',['wallet','endpoint','genesis','future_receipt','older_bank'])
def test_binding_does_not_retime_or_change_owner_or_rpc_scope(tmp_path,change):
    engine,old,cpmm,_,_,binding=registered(tmp_path)
    args=dict(at_ms=1500,source_slot=1500,wallet=cpmm.user,
        endpoint_sha256=ENDPOINT,genesis_hash=GENESIS)
    if change=='wallet':args['wallet']=old.mint
    elif change=='endpoint':args['endpoint_sha256']='b'*64
    elif change=='genesis':args['genesis_hash']=old.pool
    elif change=='future_receipt':args['at_ms']=1399
    elif change=='older_bank':args['source_slot']=1499
    try:
        with pytest.raises(ValueError):engine.journal.migration_binding(cpmm.mint,cpmm.pool,**args)
    finally:engine.journal.close()


def test_cpmm_reservation_uses_original_inventory_and_blocks_a_second_route(tmp_path):
    engine,old,cpmm,_,amount,binding=registered(tmp_path);journal=engine.journal
    try:
        decision=prepared(journal,record(cpmm,binding));reserve(journal,decision)
        risk=journal.risk_snapshot(at=1500,wallet_balance_lamports=10_000_000_000)
        assert len(risk.positions)==1 and risk.positions[0].pool==old.pool
        assert risk.positions[0].reserved_atomic==amount
        second=prepared(journal,record(cpmm,binding),'different-cpmm-attempt')
        with pytest.raises(ValueError,match='already_reserved'):reserve(journal,second)
        assert journal.get(second)['reserved_atomic']==0
        assert journal.get(decision)['reserved_atomic']==amount
        assert journal.verify_audit()
    finally:journal.close()


def test_legacy_route_cannot_reclaim_inventory_after_graduation_is_known(tmp_path):
    engine,old,cpmm,_,_,binding=registered(tmp_path)
    try:
        legacy=order_record(old)
        legacy.update(side='SELL',input_amount=cpmm.input_amount)
        decision=prepared(engine.journal,legacy,'forged-old-LaunchLab-route')
        assert engine.journal.inventory_migration(cpmm.mint,old.pool)==binding
        with pytest.raises(ValueError,match='finalized_CPmm_migration'):
            reserve(engine.journal,decision)
        assert engine.journal.get(decision)['reserved_atomic']==0
    finally:engine.journal.close()


def test_full_cpmm_settlement_releases_once_and_keeps_original_basis_and_locked_asset(tmp_path):
    engine,old,cpmm,_,amount,binding=registered(tmp_path);journal=engine.journal
    try:
        before=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        decision=prepared(journal,record(cpmm,binding));reserve(journal,decision)
        fill=dict(slot=1600,fee_lamports=5000,chain_error=None,
            token_delta_atomic=-amount,wallet_delta_lamports=cpmm.expected_output-5000,
            gross_output_lamports=cpmm.expected_output,rent_locked_lamports=0,
            realized_market_execution=True,economic_edge_proven=False)
        journal.finalize(decision,fill,1600)
        after=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        assert after['pool']==old.pool and after['quantity_atomic']==after['entry_cost_lamports']==0
        assert after['locked_rent_lamports']==before['locked_rent_lamports']
        day=dict(journal.con.execute('SELECT * FROM daily').fetchone())
        assert day['realized_pnl']==cpmm.expected_output-5000-before['entry_cost_lamports']
        assert journal.get(decision)['reserved_atomic']==journal.get(decision)['reserved_lamports']==0
        journal.finalize(decision,fill,1601)
        assert dict(journal.con.execute('SELECT * FROM daily').fetchone())==day
        assert journal.verify_audit()
    finally:journal.close()


def test_nonfinancial_stage_can_never_reserve_live_inventory(tmp_path):
    engine,old,cpmm,_,_,binding=registered(tmp_path)
    try:
        stage=order_record(cpmm);stage['original_launchlab_pool']=old.pool
        decision=prepared(engine.journal,stage)
        with pytest.raises(ValueError,match='nonfinancial'):reserve(engine.journal,decision)
        assert engine.journal.get(decision)['reserved_atomic']==0
    finally:engine.journal.close()


def test_tampered_binding_is_detected_on_restart_lookup(tmp_path):
    engine,_,cpmm,_,_,binding=registered(tmp_path)
    try:
        engine.journal.con.execute("UPDATE cpmm_migrations SET binding_json='{}'")
        with pytest.raises(ValueError,match='durable_audit'):
            engine.journal.migration_binding(cpmm.mint,cpmm.pool,at_ms=1500,source_slot=1500,
                wallet=cpmm.user,endpoint_sha256=ENDPOINT,genesis_hash=GENESIS)
    finally:engine.journal.close()


def test_concurrent_partial_reservations_never_exceed_one_original_inventory(tmp_path):
    engine,old,cpmm,_,amount,binding=registered(tmp_path);journal=engine.journal
    try:
        a=partial_order(cpmm,amount//2,'partial-reservation-1')
        b=partial_order(cpmm,amount-amount//2,'partial-reservation-2')
        left=prepared(journal,record(a,binding),'partial-reservation-1');reserve(journal,left)
        right=prepared(journal,record(b,binding),'partial-reservation-2');reserve(journal,right)
        assert sum(r[0] for r in journal.con.execute('SELECT reserved_atomic FROM orders'))==amount
        # One atomic token is entirely consumed by integer-rounded LP /
        # creator fees and cannot form a valid CPMM order. Use a small
        # economically executable order to challenge the inventory gate,
        # not the independent minimum-fee safety check.
        excess_amount=10_000
        extra=prepared(journal,record(partial_order(cpmm,excess_amount,'excess-1'),binding),'excess-1')
        with pytest.raises(ValueError,match='already_reserved'):reserve(journal,extra)
        first_position=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        first_basis=first_position['entry_cost_lamports']
        journal.finalize(left,fill(a),1600)
        remaining=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        assert remaining['quantity_atomic']==b.input_amount
        assert remaining['entry_cost_lamports']==first_basis-first_basis*a.input_amount//amount
        journal.finalize(right,fill(b,slot=1601),1601)
        closed=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        assert closed['quantity_atomic']==closed['entry_cost_lamports']==0
        daily=dict(journal.con.execute('SELECT * FROM daily').fetchone())
        assert daily['realized_pnl']==a.expected_output+b.expected_output-10000-first_basis
        assert journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
        assert closed['locked_rent_lamports']==first_position['locked_rent_lamports']
        assert journal.verify_audit()
    finally:journal.close()


def test_failed_cpmm_sale_charges_real_fee_without_consuming_inventory(tmp_path):
    engine,old,cpmm,_,amount,binding=registered(tmp_path);journal=engine.journal
    try:
        before=dict(journal.con.execute('SELECT * FROM positions').fetchone())
        before_day=dict(journal.con.execute('SELECT * FROM daily').fetchone())
        decision=prepared(journal,record(cpmm,binding));reserve(journal,decision)
        journal.finalize(decision,fill(cpmm,failed=True),1600)
        assert dict(journal.con.execute('SELECT * FROM positions').fetchone())==before
        day=dict(journal.con.execute('SELECT * FROM daily').fetchone())
        assert day['spent']==before_day['spent']+5000
        assert day['realized_loss']==before_day['realized_loss']+5000
        assert day['realized_pnl']==before_day['realized_pnl']-5000
        assert journal.get(decision)['reserved_atomic']==0
        assert journal.verify_audit()
    finally:journal.close()


def test_ambiguous_migrated_sale_preserves_reservations_and_binding_after_restart(tmp_path):
    engine,old,cpmm,_,amount,binding=registered(tmp_path);journal=engine.journal
    decision=prepared(journal,record(cpmm,binding));reserve(journal,decision)
    raw=cpmm.transaction.transaction((bytes([8])*64,))
    journal.transition(decision,('RESERVED',),'SIGNED',1500,signature=_encode(bytes([8])*64),signed_raw=raw)
    journal.transition(decision,('SIGNED',),'SUBMITTING',1500,final_admission=lambda:None)
    journal.transition(decision,('SUBMITTING',),'UNCERTAIN',1501)
    journal.kill('isolated-ambiguous-outcome',1501)
    journal.close()
    restored=ExecutionJournal(tmp_path/'private-live.sqlite')
    try:
        risk=restored.risk_snapshot(at=1600,wallet_balance_lamports=10_000_000_000)
        assert risk.unresolved_orders==1 and risk.kill_switch
        assert risk.positions[0].pool==old.pool and risk.positions[0].reserved_atomic==amount
        assert restored.get(decision)['signed_raw']==raw
        assert restored.bound_migration(cpmm.mint,cpmm.pool,at_ms=1600,
            source_slot=1600,wallet=cpmm.user)==binding
        with pytest.raises(ValueError,match='cannot_release'):
            restored.release_unsent(decision,1600,'blind-retry-forbidden')
        assert restored.verify_audit()
    finally:restored.close()


@pytest.mark.parametrize('damage',[
    'first_signature','second_signature','recent_blockhash','payer_pubkey',
])
def test_financial_migration_refuses_structurally_valid_but_unsigned_history(
        tmp_path,damage):
    engine,old,cpmm,parsed,amount=_staged(tmp_path)
    raw,signature=signed_rpc_migration(parsed)
    if damage=='first_signature':
        signature=_encode(bytes([17])*64)
        raw['transaction']['signatures'][0]=signature
    elif damage=='second_signature':
        raw['transaction']['signatures'][1]=_encode(bytes([18])*64)
    elif damage=='recent_blockhash':
        raw['transaction']['message']['recentBlockhash']=_encode(bytes([19])*32)
    else:
        raw['transaction']['message']['accountKeys'][0]=_encode(bytes([20])*32)
    class Rpc:
        endpoint_sha256=ENDPOINT
        async def genesis_hash(self):return GENESIS
        async def get_transaction(self,asked):
            assert asked==signature
            return deepcopy(raw)
    try:
        receipt=asyncio.run(read_finalized_migration(Rpc(),signature=signature,
            mint=cpmm.mint,launchlab_pool=old.pool,cpmm_pool=cpmm.pool,
            expected_endpoint_sha256=ENDPOINT,expected_genesis_hash=GENESIS,
            observed_at_slot=cpmm.source_slot))
        assert receipt['status']=='FINALIZED_RPC_STRUCTURAL_MATCH'
        assert receipt['cryptographic_signature_bytes_verified'] is False
        before=[dict(x) for x in engine.journal.con.execute('SELECT * FROM positions')]
        with pytest.raises(ValueError,match='cryptographic_signatures'):
            engine.journal.register_cpmm_migration(receipt,wallet=cpmm.user,
                received_at_ms=1400,expected_endpoint_sha256=ENDPOINT,
                expected_genesis_hash=GENESIS)
        assert engine.journal.con.execute(
            'SELECT COUNT(*) FROM cpmm_migrations').fetchone()[0]==0
        assert [dict(x) for x in engine.journal.con.execute(
            'SELECT * FROM positions')]==before
        assert engine.journal.verify_audit()
    finally:engine.journal.close()


@pytest.mark.parametrize('downgrade',['legacy_structural_only','changed_proof_digest'])
def test_older_or_forged_durable_migration_binding_cannot_enable_financial_sell(
        tmp_path,downgrade):
    engine,old,cpmm,_,_,binding=registered(tmp_path)
    journal=engine.journal
    try:
        # Model a pre-upgrade journal with a perfectly consistent hash chain,
        # not just a corrupted row rejected by the normal audit code.
        row=journal.con.execute('SELECT * FROM cpmm_migrations').fetchone()
        past=json.loads(row['binding_json'])
        past.pop('binding_sha256')
        if downgrade=='legacy_structural_only':
            past['cryptographic_signature_verified']=False
            past.pop('cryptographic_proof_sha256')
            past.pop('exact_signed_message_sha256')
            past['source_scope']='retained_pinned_finalized_RPC_claim'
        else:
            past['cryptographic_proof_sha256']='f'*64
        past['binding_sha256']=hashlib.sha256(canonical(past).encode()).hexdigest()
        encoded=canonical(past)
        journal.con.execute('UPDATE cpmm_migrations SET binding_json=?',(encoded,))
        last=journal.con.execute('SELECT * FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()
        event=json.loads(last['event_json'])
        assert event['kind']=='cpmm_migration'
        event['binding_json']=encoded
        event_json=canonical(event)
        event_sha=hashlib.sha256((last['previous_hash']+event_json).encode()).hexdigest()
        journal.con.execute('UPDATE audit SET event_json=?,event_hash=? WHERE sequence=?',
                            (event_json,event_sha,last['sequence']))
        assert journal.verify_audit()
        with pytest.raises(ValueError,match=(
            'legacy_structural_only' if downgrade=='legacy_structural_only'
            else 'retained_migration_Ed25519')):
            journal.bound_migration(cpmm.mint,cpmm.pool,
                at_ms=1500,source_slot=cpmm.source_slot,wallet=cpmm.user)
        assert journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==1
        assert journal.verify_audit()
    finally:journal.close()
