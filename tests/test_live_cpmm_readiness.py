"""Read-only CPMM readiness service orchestration tests.

The service dependencies are fake only in this suite; the individual loader,
migration, bank, and RPC message decoders have separate real-wire fixture
tests. Passing cannot certify a mainnet execution or independently sign.
"""
import asyncio

import pytest

from bot.live import cpmm_readiness as runbook
from bot.p3.certification import PROGRAM
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.cpmm_exit import build_cpmm_exit
from test_live_cpmm_exit import fixture_bank,MINT,WALLET,POOL
from test_live_unsigned_preflight import ENDPOINT,GENESIS


SOURCE=_p=fixture_bank()
ORIGINAL=SOURCE['wallet']


class NoFinancialRpc:
    async def send_transaction(self,*_args,**_kwargs):
        raise AssertionError('unsigned_runbook_may_not_send')

    async def sign_message(self,*_args,**_kwargs):
        raise AssertionError('unsigned_runbook_may_not_sign')


def run(monkeypatch,*,attack=None,overrides=None):
    log=[]
    order=build_cpmm_exit(**fixture_bank())
    async def pin(_rpc,**kw):
        log.append(('pin',kw['program_id']))
        if attack=='pin' and kw['program_id']==CPMM_PROGRAM:
            return dict(result='REFUSED')
        return dict(result='PIN_MATCHED_READ_ONLY',programdata_sha256='a'*64,
            elf_sha256='b'*64,deployment_slot=90,joint_bank_slot=110)
    async def migration(_rpc,**kw):
        log.append(('migration',kw['cpmm_pool']))
        if attack=='migration':
            return dict(status='REFUSED',reason='source_unqualified')
        return dict(status='FINALIZED_RPC_STRUCTURAL_MATCH',
                    migration_slot=111,raw_RPC_response_returned_to_caller=True)
    async def bank(_rpc,**kw):
        log.append(('bank',kw['min_context_slot']))
        if attack=='bank_wrong_pool':
            from dataclasses import replace
            result=replace(order,pool=kw['wallet'])
        else:result=order
        return dict(order=result,source_bank_slot=1235,
                    decision_at_ms=1080,
                    migration_provenance_verified_by_this_module=False)
    async def simulation(_rpc,prepared,**kw):
        log.append(('simulation',prepared.side))
        if attack=='simulation':
            return dict(result='REFUSED',reason='simulation_error')
        return dict(result='SIMULATION_SUCCEEDED_UNSENT',
                    message_sha256='a'*64,source_slot=prepared.source_slot,
                    route_executed=False)
    monkeypatch.setattr(runbook,'attest_program_pin',pin)
    monkeypatch.setattr(runbook,'read_finalized_migration',migration)
    monkeypatch.setattr(runbook,'prepare_cpmm_sell_from_rpc',bank)
    monkeypatch.setattr(runbook,'check_unsigned_order',simulation)
    params=dict(program_pins={PROGRAM:{},CPMM_PROGRAM:{}},
        original_launchlab_pool=GENESIS,migrated_cpmm_pool=POOL,
        migration_signature=GENESIS,mint=MINT,wallet=WALLET,
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
    ('pin',2),('migration',3),('simulation',5),
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
