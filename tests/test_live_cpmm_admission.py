"""Actual admission wiring over an owned, audit-bound synthetic migration.

All RPC responses, migration and executable bytes are explicit offline fixtures.
No external wallet, chain signature, transaction or code approval is performed.
"""
import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest

from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.evidence import (AntiRugEvidence,ClockOffsetEvidence,DeploymentPin,
    FreshAdmissionEvidence,UPGRADEABLE_LOADER,verify_deployment)
from bot.live.migration_rpc_receipt import read_finalized_migration
from bot.live.safety import evaluate_admission
from bot.p3.certification import PROGRAM,_decode,_encode,find_program_address
from bot.scanner.supervision import ScannerHealth
from test_live_cpmm_stage import _staged
from test_live_evidence import FixtureRpc,GENESIS,ENDPOINT,_raw_account,deployment_fixture
from test_live_migration_evidence import SIG
from test_live_migration_rpc_json import _compiled
from test_live_migration_rpc_receipt import Rpc as MigrationRpc


def cpmm_deployment():
    programdata=find_program_address((_decode(CPMM_PROGRAM),),UPGRADEABLE_LOADER)[0]
    authority=_encode(bytes([81])*32)
    elf=b'\x7fELF'+bytes(60)
    pin=DeploymentPin(CPMM_PROGRAM,programdata,hashlib.sha256(elf).hexdigest(),
        100,authority,900,'ISOLATED-config-reviewer','ISOLATED-official-ABI-and-deployment-fingerprint','b'*64)
    program=_raw_account(struct.pack('<I',2)+_decode(programdata),executable=True)
    data=_raw_account(struct.pack('<IQB',3,100,1)+_decode(authority)+elf,executable=False)
    return pin,program,data


def exercise(tmp_path,assertion,*,register=True,registered_at_ms=1400):
    engine,entry,order,migration,amount=_staged(tmp_path)
    async def scenario():
        receipt=await read_finalized_migration(MigrationRpc(_compiled(migration)),
            signature=SIG,mint=order.mint,launchlab_pool=entry.pool,cpmm_pool=order.pool,
            expected_endpoint_sha256=ENDPOINT,expected_genesis_hash=GENESIS,
            observed_at_slot=order.source_slot)
        if register:
            engine.journal.register_cpmm_migration(receipt,wallet=order.user,
                received_at_ms=registered_at_ms,expected_endpoint_sha256=ENDPOINT,
                expected_genesis_hash=GENESIS)
        pin,program,data=cpmm_deployment()
        bank=deepcopy(json.loads(order.rebuild_request_json)['accounts'])
        bank[CPMM_PROGRAM],bank[pin.programdata_address]=program,data
        rpc=FixtureRpc(bank);rpc.slot=1600
        now=[1500]
        scanner=ScannerHealth(require_observations=True,
            clock_ms=lambda:now[0],monotonic_ms=lambda:now[0])
        task=scanner.start_task(asyncio.Event().wait(),'ISOLATED-migration-scanner')
        scanner.observe_rpc(True);scanner.observe_websocket('subscribed')
        envelope=replace(engine.envelope,allowed_programs=(PROGRAM,CPMM_PROGRAM))
        anti=AntiRugEvidence(json.loads(order.rebuild_request_json)['decision_id'],
            order.mint,order.pool,order.source_account_digest,1500,(),'c'*64)
        clock=ClockOffsetEvidence(0,1500,'ISOLATED-measured-clock','d'*64)
        provider=FreshAdmissionEvidence(rpc=rpc,envelope=envelope,scanner_health=scanner,
            deployment_pin=None,deployment_pins={PROGRAM:deployment_fixture()[0],CPMM_PROGRAM:pin},
            journal=engine.journal,anti_rug_provider=lambda *_:value.anti,
            clock_offset_provider=lambda:value.clock,clock_ms=lambda:now[0])
        value=SimpleNamespace(engine=engine,entry=entry,order=order,amount=amount,
            pin=pin,bank=bank,rpc=rpc,now=now,scanner=scanner,anti=anti,clock=clock,
            provider=provider,envelope=envelope,decision=json.loads(order.rebuild_request_json)['decision_id'])
        try:return await assertion(value)
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
    try:return asyncio.run(scenario())
    finally:engine.journal.close()


def test_current_CPmm_bank_and_original_owned_position_share_one_risk_identity(tmp_path):
    async def check(v):
        before=[dict(r) for r in v.engine.journal.con.execute('SELECT * FROM positions')]
        request,health=await v.provider(v.decision,v.order)
        assert request.program_id==CPMM_PROGRAM and request.pool==v.order.pool
        assert request.position_pool==v.entry.pool!=request.pool
        assert request.exit_capacity_atomic==v.amount
        assert request.quote_received_at_ms==1400 and request.quote_context_slot==1500
        assert request.observed_bank_slot==1600 and health.scanner_heartbeat_at_ms==1500
        risk=v.engine.journal.risk_snapshot(at=1500,wallet_balance_lamports=10_000_000_000)
        verdict=evaluate_admission(request,envelope=v.envelope,arming=None,
            health=health,risk=risk,now_ms=1500,require_enabled=False)
        assert verdict.allowed,verdict.reasons
        assert [dict(r) for r in v.engine.journal.con.execute('SELECT * FROM positions')]==before
        assert [c[0] for c in v.rpc.calls]==['getMultipleAccounts','getGenesisHash','getMinimumBalanceForRentExemption']
        assert v.provider.last_assessment['migration_binding_sha256']
        assert v.provider.last_assessment['realized_market_execution'] is False
        assert not v.provider.last_assessment['deployment']['source_code_audit_performed']
    exercise(tmp_path,check)


@pytest.mark.parametrize('failure',['missing_binding','missing_journal','wrong_pin','unallowed_program','wrong_endpoint'])
def test_CPmm_admission_never_uses_structural_or_unbound_inventory(tmp_path,failure):
    async def check(v):
        if failure=='missing_journal':v.provider.journal=None
        elif failure=='wrong_pin':v.provider.deployment_pins[CPMM_PROGRAM]=deployment_fixture()[0]
        elif failure=='unallowed_program':v.provider.envelope=replace(v.envelope,allowed_programs=(PROGRAM,))
        elif failure=='wrong_endpoint':v.rpc.endpoint_sha256='f'*64
        with pytest.raises(ValueError):await v.provider(v.decision,v.order)
        assert not v.rpc.calls
    exercise(tmp_path,check,register=failure!='missing_binding')


def test_future_migration_receipt_cannot_authorize_an_earlier_sell_decision(tmp_path):
    async def check(v):
        with pytest.raises(ValueError,match='causal_clock'):
            await v.provider(v.decision,v.order)
        assert not v.rpc.calls
    exercise(tmp_path,check,registered_at_ms=1501)


@pytest.mark.parametrize('role',['pool','wallet','ATA','WSOL','mint'])
def test_current_CPmm_raw_accounts_are_rechecked_without_retiming_quote(tmp_path,role):
    async def check(v):
        address={'pool':v.order.pool,'wallet':v.order.user,'ATA':v.order.base_token_account,
                 'WSOL':v.order.quote_token_account,'mint':v.order.mint}[role]
        if v.bank[address] is None:v.bank[address]=dict(lamports=1)
        else:v.bank[address]['lamports']+=1
        with pytest.raises(ValueError,match='raw_account_changed'):
            await v.provider(v.decision,v.order)
        assert len(v.rpc.calls)==1 and v.provider.last_assessment is None
    exercise(tmp_path,check)


@pytest.mark.parametrize('field',['ELF','upgrade_authority','deployment_slot'])
def test_current_CPmm_program_change_is_not_automatically_approved(tmp_path,field):
    async def check(v):
        data=v.bank[v.pin.programdata_address]
        raw=bytearray(base64.b64decode(data['data'][0]))
        raw[{'ELF':60,'upgrade_authority':13,'deployment_slot':4}[field]]^=1
        data['data'][0]=base64.b64encode(raw).decode()
        with pytest.raises(ValueError):await v.provider(v.decision,v.order)
        assert len(v.rpc.calls)==1 and v.provider.last_assessment is None
    exercise(tmp_path,check)


@pytest.mark.parametrize('failure',['pin','scanner','binding'])
def test_synchronous_CPmm_final_gate_rechecks_real_services_and_durable_binding(tmp_path,failure):
    async def check(v):
        await v.provider(v.decision,v.order);calls=len(v.rpc.calls)
        if failure=='pin':v.provider.deployment_pins[CPMM_PROGRAM]=None
        elif failure=='scanner':v.scanner.observe_websocket('disconnected')
        else:
            row=v.engine.journal.con.execute('SELECT binding_json FROM cpmm_migrations').fetchone()
            value=json.loads(row[0]);value['inventory_pool']=v.order.pool
            v.engine.journal.con.execute('UPDATE cpmm_migrations SET binding_json=?',(json.dumps(value),))
        with pytest.raises(ValueError):v.provider.assert_operational_now()
        assert len(v.rpc.calls)==calls
    exercise(tmp_path,check)


def test_migrated_risk_identity_cannot_be_relabelled_or_used_by_LaunchLab(tmp_path):
    async def check(v):
        request,health=await v.provider(v.decision,v.order)
        with pytest.raises(ValueError,match='CPMM_sell'):
            replace(request,program_id=PROGRAM)
        with pytest.raises(ValueError,match='CPMM_sell'):
            replace(request,position_pool=request.pool)
        risk=v.engine.journal.risk_snapshot(at=1500,wallet_balance_lamports=10_000_000_000)
        verdict=evaluate_admission(replace(request,position_pool=None),envelope=v.envelope,
            arming=None,health=health,risk=risk,now_ms=1500,require_enabled=False)
        assert not verdict.allowed and 'sell_exceeds_unreserved_inventory' in verdict.reasons
    exercise(tmp_path,check)


def test_deployment_pin_distinguishes_current_bytes_from_unpublished_LaunchLab_source():
    pin,program,data=deployment_fixture()
    report=verify_deployment(program,data,pin,observed_slot=1300,now_ms=1100)
    assert report['source_build_match']=='UNAVAILABLE_UNPUBLISHED'
    assert not report['source_code_audit_performed']
    pin,program,data=cpmm_deployment()
    assert verify_deployment(program,data,pin,observed_slot=1600,now_ms=1500)['program_id']==CPMM_PROGRAM
