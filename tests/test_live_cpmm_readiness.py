"""Read-only CPMM readiness service orchestration tests.

The service dependencies are fake only in this suite; the individual loader,
migration, bank, and RPC message decoders have separate real-wire fixture
tests. Passing cannot certify a mainnet execution or independently sign.
"""
import asyncio
import hashlib

import pytest

from bot.live import cpmm_readiness as runbook
from bot.p3.certification import PROGRAM
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.cpmm_exit import build_cpmm_exit
from test_live_cpmm_exit import fixture_bank,MINT,WALLET,POOL
from test_live_unsigned_preflight import ENDPOINT,GENESIS
from test_live_solana_signatures import signed_fixture


class NoFinancialRpc:
    async def send_transaction(self,*_args,**_kwargs):
        raise AssertionError('unsigned_runbook_may_not_send')

    async def sign_message(self,*_args,**_kwargs):
        raise AssertionError('unsigned_runbook_may_not_sign')


def run(monkeypatch,*,attack=None,overrides=None):
    log=[]
    order=build_cpmm_exit(**fixture_bank())
    signed_migration,_=signed_fixture()
    signed_migration["slot"]=111
    signed_signature=signed_migration["transaction"]["signatures"][0]
    async def pin(_rpc,**kw):
        log.append(('pin',kw['program_id']))
        if attack=='pin' and kw['program_id']==CPMM_PROGRAM:
            return dict(result='REFUSED')
        return dict(result='PIN_MATCHED_READ_ONLY',program_id=kw['program_id'],
            programdata_sha256='a'*64,elf_sha256='b'*64,
            deployment_slot=90,joint_bank_slot=1234)
    async def migration(_rpc,**kw):
        log.append(('migration',kw['cpmm_pool']))
        if attack=='migration':
            return dict(status='REFUSED',reason='source_unqualified')
        if attack=='forged_signature':
            signed_migration["transaction"]["message"]["recentBlockhash"]=PROGRAM
        return dict(status='FINALIZED_RPC_STRUCTURAL_MATCH',
                    migration_slot=111,raw_RPC_response_returned_to_caller=True,
                    raw_RPC_response=signed_migration,
                    source_launchlab_pool=kw['launchlab_pool'],
                    migrated_cpmm_pool=kw['cpmm_pool'],
                    mint=kw['mint'],signature=kw['signature'])
    async def bank(_rpc,**kw):
        log.append(('bank',kw['min_context_slot']))
        if attack=='bank_wrong_pool':
            from dataclasses import replace
            result=replace(order,pool=kw['wallet'])
        else:result=order
        return dict(order=result,source_bank_slot=order.source_slot,
                    decision_at_ms=order.decision_at_ms,
                    bank_received_at_ms=order.source_available_at_ms,
                    migration_provenance_verified_by_this_module=False)
    async def simulation(_rpc,prepared,**kw):
        log.append(('simulation',prepared.side))
        if attack=='simulation':
            return dict(result='REFUSED',reason='simulation_error')
        data=dict(result='SIMULATION_SUCCEEDED_UNSENT',side='SELL',
                    message_sha256=hashlib.sha256(prepared.transaction.message).hexdigest(),
                    unsigned_transaction_sha256=hashlib.sha256(
                        prepared.transaction.unsigned_transaction()).hexdigest(),
                    source_slot=prepared.source_slot,
                    simulation_slot=prepared.source_slot,
                    route_executed=False,sig_verify=False,
                    live_ready_to_arm=False)
        if attack=='forged_simulation':
            data['message_sha256']='0'*64
        return data
    monkeypatch.setattr(runbook,'attest_program_pin',pin)
    monkeypatch.setattr(runbook,'read_finalized_migration',migration)
    monkeypatch.setattr(runbook,'prepare_cpmm_sell_from_rpc',bank)
    monkeypatch.setattr(runbook,'check_unsigned_order',simulation)
    params=dict(program_pins={PROGRAM:{},CPMM_PROGRAM:{}},
        original_launchlab_pool=GENESIS,migrated_cpmm_pool=POOL,
        migration_signature=signed_signature,mint=MINT,wallet=WALLET,
        decision_id='synthetic-cpmm-end-to-end-001',
        expected_endpoint_sha256=ENDPOINT,
        expected_genesis_hash=GENESIS,
        min_context_slot=1234,clock_ms=lambda:1100,
        amount_in=order.input_amount,
        slippage_bps=100,max_slippage_bps=200,
        max_price_impact_bps=500)
    params.update(overrides or {})
    return asyncio.run(runbook.preflight_migrated_sell(NoFinancialRpc(),**params)),log


def test_read_only_runbook_checks_both_programs_before_migration_bank_and_unsigned_wire(monkeypatch):
    result,calls=run(monkeypatch)
    assert result['status']=='UNSIGNED_CPMM_ROUTE_SIMULATED'
    assert calls==[
        ('pin',PROGRAM),('pin',CPMM_PROGRAM),('migration',POOL),
        ('bank',1234),('simulation','SELL')]
    assert result['program_pins_matched']
    assert result['historical_signature_cryptographically_verified'] is True
    assert result['historical_migration_signatures']['exact_message_sha256']
    assert len(result['program_pin_read_only_evidence'])==2
    assert result['exact_prepared_order'].transaction.required_signers==(WALLET,)
    assert result['exact_prepared_order'].pool==POOL
    assert result['unsigned_message_sha256']
    assert not result['operator_pin_approval_independently_established']
    assert not result['live_execution_authorized']
    assert not result['live_ready_to_arm']
    assert not result['financial_order_submitted']
    assert not result['actual_mainnet_execution_confirmed']
    assert not result['economic_edge_validated']


@pytest.mark.parametrize('attack,expected_calls',[
    ('pin',2),('migration',3),('forged_signature',3),('simulation',5),
])
def test_fail_closed_short_circuits_preflight(monkeypatch,attack,expected_calls):
    result,calls=run(monkeypatch,attack=attack)
    assert result['status']=='REFUSED'
    assert len(calls)==expected_calls
    assert result['financial_order_submitted'] is False


def test_different_pool_from_migration_cannot_be_promoted(monkeypatch):
    with pytest.raises(ValueError,match='differs'):
        run(monkeypatch,attack='bank_wrong_pool')


@pytest.mark.parametrize('attack',[
    {PROGRAM:{},CPMM_PROGRAM:{},'extra':{}},
    {PROGRAM:{}},
    {},
    None,
])
def test_program_pins_must_be_exact_explicit_pair(monkeypatch,attack):
    with pytest.raises(ValueError,match='two_explicit'):
        run(monkeypatch,overrides={'program_pins':attack})


def test_simulation_clock_must_follow_bank_decision(monkeypatch):
    with pytest.raises(ValueError,match='simulation_clock_invalid'):
        run(monkeypatch,overrides={'clock_ms':lambda:1000})


def test_forged_successful_simulation_message_never_qualifies(monkeypatch):
    with pytest.raises(ValueError,match='receipt_identity'):
        run(monkeypatch,attack='forged_simulation')
