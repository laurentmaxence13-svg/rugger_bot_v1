"""CPMM read-only bank acquisition with real builder and synthetic RPC only."""
import asyncio
from copy import deepcopy

import pytest

from bot.live.cpmm_bank import prepare_cpmm_sell_from_rpc
from bot.live.cpmm_exit import validate_cpmm_exit
from test_live_cpmm_exit import fixture_bank
from test_live_unsigned_preflight import ENDPOINT,GENESIS


class FakeRpc:
    endpoint_sha256=ENDPOINT

    def __init__(self,kwargs):
        self.kwargs=deepcopy(kwargs)
        self.accounts=deepcopy(kwargs['accounts'])
        self.calls=[]
        self.genesis=GENESIS
        self.first_slot=1234
        self.second_slot=1235
        self.blockhash_slot=1236
        self.change_pool=False
        self.drop_account=False

    async def genesis_hash(self):
        self.calls.append('genesis')
        return self.genesis

    async def get_multiple_accounts(self,keys,*,min_context_slot):
        self.calls.append(('bank',tuple(keys),min_context_slot))
        if len(keys)==1:
            return dict(context=dict(slot=self.first_slot),
                value=[deepcopy(self.accounts[keys[0]])])
        values=[deepcopy(self.accounts[k]) for k in keys]
        if self.change_pool:values[0]['lamports']+=1
        if self.drop_account:values.pop()
        return dict(context=dict(slot=self.second_slot),value=values)

    async def get_latest_blockhash(self):
        self.calls.append('blockhash')
        return dict(blockhash=self.kwargs['recent_blockhash'],
            last_valid_block_height=5000,context_slot=self.blockhash_slot)

    async def rent_exemption(self,account_size):
        assert account_size==165
        self.calls.append('rent')
        return 2039280

    async def send_transaction(self,*args,**kwargs):
        raise AssertionError('read_only_bank_probe_may_not_send')


def prepare(rpc,*,ticks=(1050,1070,1100),**overrides):
    args=rpc.kwargs
    clock=iter(ticks)
    params=dict(pool_address=args['pool_address'],mint=args['mint'],
        wallet=args['wallet'],decision_id=args['decision_id'],
        min_context_slot=1234,observed_block_time_seconds=1,
        expected_genesis_hash=GENESIS,expected_endpoint_sha256=ENDPOINT,
        amount_in=args['amount_in'],slippage_bps=args['slippage_bps'],
        max_slippage_bps=args['max_slippage_bps'],
        max_price_impact_bps=args['max_price_impact_bps'],
        compute_unit_limit=args['compute_unit_limit'],
        priority_fee_micro_lamports=args['priority_fee_micro_lamports'],
        max_priority_fee_lamports=args['max_priority_fee_lamports'])
    params.update(overrides)
    return asyncio.run(prepare_cpmm_sell_from_rpc(
        rpc,clock_ms=lambda:next(clock),**params))


def test_pool_discovery_reads_all_ten_accounts_in_one_bank_and_builds_real_unsigned_sell():
    rpc=FakeRpc(fixture_bank())
    result=prepare(rpc)
    order=result['order']
    assert validate_cpmm_exit(order)==order
    assert order.transaction.required_signers==(order.user,)
    assert result['read_only_RPC_calls']==5
    assert result['source_bank_slot']==1235
    assert result['initial_pool_bank_slot']==1234
    assert result['blockhash_bank_slot']==1236
    assert order.source_available_at_ms==1070
    assert order.decision_at_ms==1100
    assert result['transaction_sent'] is False
    assert result['live_execution_authorized'] is False
    assert result['onchain_program_pin_verified_by_this_module'] is False
    assert result['migration_provenance_verified_by_this_module'] is False
    assert [c[0] if isinstance(c,tuple) else c for c in rpc.calls]==[
        'genesis','bank','bank','blockhash','rent']
    assert rpc.calls[2][2]==1234 and len(rpc.calls[2][1])==10


@pytest.mark.parametrize('attack',[
    'endpoint','genesis','first_bank','second_bank','changed_pool',
    'incomplete_bank','blockhash_bank','missing_token_account',
    'stale_acquisition','stale_decision','wrong_mint',
])
def test_any_stale_bank_or_unknown_account_fails_closed(attack):
    rpc=FakeRpc(fixture_bank())
    overrides={}
    ticks=(1050,1070,1100)
    if attack=='endpoint':overrides['expected_endpoint_sha256']='f'*64
    if attack=='genesis':rpc.genesis=rpc.kwargs['pool_address']
    if attack=='first_bank':rpc.first_slot=1233
    if attack=='second_bank':rpc.second_slot=1233
    if attack=='changed_pool':rpc.change_pool=True
    if attack=='incomplete_bank':rpc.drop_account=True
    if attack=='blockhash_bank':rpc.blockhash_slot=1234
    if attack=='missing_token_account':
        from bot.live.route import associated_token_address
        address=associated_token_address(rpc.kwargs['wallet'],rpc.kwargs['mint'])
        rpc.accounts[address]=None
    if attack=='stale_acquisition':ticks=(1050,7000,7100)
    if attack=='stale_decision':ticks=(1050,1070,7000)
    if attack=='wrong_mint':
        overrides['mint']=rpc.kwargs['wallet']
    with pytest.raises((ValueError,TypeError)):
        prepare(rpc,ticks=ticks,**overrides)
    assert 'sendTransaction' not in rpc.calls


@pytest.mark.parametrize('key,bad',[
    ('min_context_slot',True),('min_context_slot',0),
    ('max_bank_age_ms',False),('max_bank_age_ms',5001),
    ('observed_block_time_seconds',0),
    ('observed_block_time_seconds',True),
])
def test_source_limits_are_required_and_bounded(key,bad):
    rpc=FakeRpc(fixture_bank())
    with pytest.raises(ValueError):
        prepare(rpc,**{key:bad})
    assert rpc.calls==[]
