"""Staged migration liquidation protects original held LaunchLab inventory.

Synthetically fill a LaunchLab buy into the real durable journal, then link a
different CPMM pool and simulate its full unsigned SELL in LIVE_PREPARED.
No external wallet or market network. No signature or transaction may be sent.
"""
import asyncio
import base64
from copy import deepcopy
import json
import struct

import pytest

from bot.p3.certification import _decode
from bot.live.cpmm_exit import build_cpmm_exit
from bot.live.cpmm_stage import stage_cpmm_exit
from bot.live.route import associated_token_address,ephemeral_wsol_address
from bot.live.safety import Mode
from test_p3_research_integration import research_snapshot
from test_live_engine import configured,finalized_payload
from test_live_wire_route import route_request
from test_live_cpmm_exit import fixture_bank,mutate_raw,MINT,WALLET,POOL
from test_live_migration_evidence import migration,SIG
from test_live_unsigned_preflight import SimulationRpc,GENESIS,ENDPOINT


class StageRpc(SimulationRpc):
    def __init__(self):
        super().__init__()
        self.slot=1600

    async def simulate_transaction(self, raw, *, sig_verify, min_context_slot):
        assert sig_verify is False
        assert min_context_slot==1500
        assert type(raw) is bytes and raw[1:65]==bytes(64)
        self.calls.append('simulateTransaction')
        self.simulated_raw=raw
        return dict(context_slot=self.slot,err=self.error,unitsConsumed=self.units)


def _run(coro):
    return asyncio.run(coro)


def _holding(tmp_path):
    # Original real LaunchLab decoder fixture index 24 has mint bytes([55]).
    raw,addresses,_,_=research_snapshot(index=24,platform_verified=True,
                                         return_accounts=True)
    assert addresses['mint_a']==MINT
    base=route_request()
    wallet=base['wallet']
    assert wallet==WALLET
    base.update(accounts=raw,pool_address=addresses['pool'],mint=MINT)
    ata=associated_token_address(wallet,MINT)
    wsol,_=ephemeral_wsol_address(wallet,base['decision_id'])
    raw[wallet]=dict(base['accounts'].get(wallet,
        dict(owner='11111111111111111111111111111111',executable=False,
             data=['','base64'],lamports=10000000000)))
    raw[ata]=None
    raw[wsol]=None
    engine,original,rpc,_,now=configured(tmp_path,request=base)
    decision=base['decision_id']
    send=_run(engine.execute(decision,original))
    rpc.status=dict(confirmationStatus='finalized',err=None,slot=1300)
    rpc.tx=finalized_payload(original,send['signature'])
    _run(engine.recover(decision))
    pos=engine.journal.con.execute(
        'SELECT * FROM positions WHERE mint=? AND pool=?',(MINT,original.pool)).fetchone()
    assert pos['quantity_atomic']==original.expected_output
    assert engine.journal.verify_audit()
    engine.mode=Mode.LIVE_PREPARED
    engine.rpc=StageRpc()
    return engine,original,int(pos['quantity_atomic'])


def _staged(tmp_path):
    engine,old,amount=_holding(tmp_path)
    args=fixture_bank()
    args.update(amount_in=amount,context_slot=1500,
                available_at_ms=1400,decision_at_ms=1500)
    raw=args['accounts']
    ata=associated_token_address(WALLET,MINT)
    mutate_raw(raw[ata],64,struct.pack('<Q',amount))
    # Scale reserves above any retained synthetic inventory so sizing stays
    # unrelated to first-cohort quotes and within bounded price impact.
    poolraw=base64.b64decode(raw[POOL]['data'][0])
    m0=poolraw[8+32*5:8+32*6]
    for i in (0,1):
        vault_key=next(k for k in raw
                if k!=POOL and k!=ata and type(raw[k]) is dict
                and raw[k]['owner'].startswith('Token') and
                base64.b64decode(raw[k]['data'][0])[:32] ==
                    poolraw[8+32*(5+i):8+32*(6+i)]
                and len(base64.b64decode(raw[k]['data'][0]))==165)
        value=max(1000000000000,amount*1000)
        mutate_raw(raw[vault_key],64,struct.pack('<Q',value))
        if poolraw[8+32*(5+i):8+32*(6+i)]==_decode('So11111111111111111111111111111111111111112'):
            raw[vault_key]['lamports']=value+2039280
    cpmm=build_cpmm_exit(**args)
    tx=migration()
    ix=tx['transaction']['message']['instructions'][0]
    old_index=ix['accounts'][17]
    tx['transaction']['message']['accountKeys'][old_index]['pubkey']=old.pool
    tx['slot']=1301
    return engine,old,cpmm,tx,amount


def _stage(engine,old,cpmm,tx,**kwargs):
    params=dict(decision_id=json.loads(cpmm.rebuild_request_json)['decision_id'],
        original_pool=old.pool,order=cpmm,migration_transaction=tx,
        migration_signature=SIG,expected_genesis_hash=GENESIS,
        expected_endpoint_sha256=ENDPOINT,now_ms=1500)
    params.update(kwargs)
    return _run(stage_cpmm_exit(engine,**params))


def test_cpmm_stage_simulates_full_exit_of_original_owned_inventory_without_moving_it(tmp_path):
    engine,old,cpmm,tx,amount=_staged(tmp_path)
    try:
        before=[dict(row) for row in engine.journal.con.execute(
            'SELECT * FROM positions')]
        response=_stage(engine,old,cpmm,tx)
        assert response['stage_status']=='SIMULATED_UNSIGNED_ONLY'
        assert response['held_inventory_atomic']==amount
        assert response['migrated_exit_input_atomic']==amount
        assert response['original_pool']==old.pool
        assert response['migrated_cpmm_pool']==POOL
        assert response['simulation']['result']=='SIMULATION_SUCCEEDED_UNSENT'
        assert response['source_transport_authenticated'] is False
        assert response['live_execution_allowed'] is False
        assert response['financial_reservation_created'] is False
        assert response['position_transferred_to_cpmm'] is False
        assert [dict(row) for row in engine.journal.con.execute(
            'SELECT * FROM positions')]==before
        assert engine.journal.get(json.loads(cpmm.rebuild_request_json)['decision_id'])['state']=='SIMULATED'
        assert engine.rpc.calls==['getGenesisHash','getBlockHeight','simulateTransaction']
        assert engine.journal.verify_audit()
        duplicate=_stage(engine,old,cpmm,tx)
        assert duplicate['stage_status']=='SIMULATED_UNSIGNED_ONLY'
    finally:
        engine.journal.close()


@pytest.mark.parametrize('mutation',[
    'wrong_migration_pool','too_early_migration',
    'source_slot_precedes_migration','unowned_quantity',
    'enabled_mode','fake_transport',
])
def test_cpmm_stage_rejects_unverified_owned_exit_or_armed_environment(tmp_path,mutation):
    engine,old,cpmm,tx,amount=_staged(tmp_path)
    try:
        kwargs={}
        if mutation=='wrong_migration_pool':
            kwargs['original_pool']=POOL
        if mutation=='too_early_migration':
            tx['slot']=1300
        if mutation=='source_slot_precedes_migration':
            tx['slot']=1501
        if mutation=='unowned_quantity':
            from dataclasses import replace
            cpmm=replace(cpmm,base_balance_before=amount+1)
        if mutation=='enabled_mode':
            engine.mode=Mode.LIVE_ENABLED
        if mutation=='fake_transport':
            kwargs['expected_endpoint_sha256']='f'*64
            result=_stage(engine,old,cpmm,tx,**kwargs)
            assert result['stage_status']=='REFUSED'
            assert not result['live_execution_allowed']
            assert engine.journal.con.execute(
                "SELECT COUNT(*) FROM orders WHERE state='SIMULATED'").fetchone()[0]==0
            return
        with pytest.raises(ValueError):
            _stage(engine,old,cpmm,tx,**kwargs)
        assert engine.journal.con.execute(
            "SELECT COUNT(*) FROM orders WHERE state='SIMULATED'").fetchone()[0]==0
    finally:
        engine.journal.close()
