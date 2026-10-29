"""CPMM read-only bank acquisition with real builder and synthetic RPC only."""
import asyncio
from copy import deepcopy
import base64
import struct

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
        self.block_time=1
        self.message_fee=5002

    async def genesis_hash(self):
        self.calls.append('genesis')
        return self.genesis

    async def get_multiple_accounts(self,keys,*,min_context_slot):
        self.calls.append(('bank',tuple(keys),min_context_slot))
        if len(keys)==1:
            return dict(context=dict(slot=self.first_slot),
                value=[deepcopy(self.accounts[keys[0]])])
        values=[deepcopy(self.accounts[k]) for k in keys]
        if self.change_pool:
            raw=bytearray(base64.b64decode(values[0]['data'][0]))
            # Replace canonical LP mint, a stable pool identity field.
            raw[8+4*32:8+5*32]=bytes([93])*32
            values[0]['data'][0]=base64.b64encode(raw).decode()
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

    async def get_block_time(self,slot):
        assert slot==self.second_slot
        self.calls.append(('getBlockTime',slot))
        return self.block_time

    async def get_fee_for_message(self,message):
        assert type(message) is bytes and len(message)>0
        self.calls.append('getFeeForMessage')
        return self.message_fee

    async def send_transaction(self,*args,**kwargs):
        raise AssertionError('read_only_bank_probe_may_not_send')


def prepare(rpc,*,ticks=(1050,1070,1100,1120),**overrides):
    args=rpc.kwargs
    clock=iter(ticks)
    params=dict(pool_address=args['pool_address'],mint=args['mint'],
        wallet=args['wallet'],decision_id=args['decision_id'],
        min_context_slot=1234,
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
    assert result['read_only_RPC_calls']==7
    assert result['message_fee_lamports']==5002
    assert result['fee_verified_at_ms']==1120
    assert result['source_block_time_seconds']==1
    assert result['source_block_time_slot']==1235
    assert result['source_block_time_provided_by_pinned_RPC'] is True
    assert result['observed_block_time_independently_verified'] is False
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
        'genesis','bank','bank','blockhash','rent','getBlockTime','getFeeForMessage']
    assert rpc.calls[2][2]==1234 and len(rpc.calls[2][1])==10


def test_legitimate_inflight_reserve_or_counter_updates_use_only_joint_bank():
    rpc=FakeRpc(fixture_bank())
    first_raw=rpc.accounts[rpc.kwargs['pool_address']]['data'][0]
    original=rpc.get_multiple_accounts
    async def changed_bank(keys,*,min_context_slot):
        outcome=await original(keys,min_context_slot=min_context_slot)
        if len(keys)==10:
            raw=bytearray(base64.b64decode(outcome['value'][0]['data'][0]))
            # Real pools update LP supply, fees and counters; this is a
            # mutable field, not a change in the linked account graph.
            struct.pack_into('<Q',raw,333,struct.unpack_from('<Q',raw,333)[0]+12)
            outcome['value'][0]['data'][0]=base64.b64encode(raw).decode()
        return outcome
    rpc.get_multiple_accounts=changed_bank
    result=prepare(rpc)
    assert result['order'].source_slot==1235
    assert result['order'].transaction.required_signers==(rpc.kwargs['wallet'],)
    assert rpc.accounts[rpc.kwargs['pool_address']]['data'][0]==first_raw
    assert result['live_execution_authorized'] is False


@pytest.mark.parametrize('attack',[
    'endpoint','genesis','first_bank','second_bank','changed_pool',
    'incomplete_bank','blockhash_bank','missing_token_account',
    'stale_acquisition','stale_decision','wrong_mint',
    'missing_source_block_time','future_source_block_time',
    'missing_message_fee','excess_message_fee','stale_message_fee',
])
def test_any_stale_bank_or_unknown_account_fails_closed(attack):
    rpc=FakeRpc(fixture_bank())
    overrides={}
    ticks=(1050,1070,1100,1120)
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
    if attack=='stale_acquisition':ticks=(1050,7000,7100,7200)
    if attack=='stale_decision':ticks=(1050,1070,7000,7100)
    if attack=='wrong_mint':
        overrides['mint']=rpc.kwargs['wallet']
    if attack=='missing_source_block_time':rpc.block_time=None
    if attack=='future_source_block_time':rpc.block_time=99999
    if attack=='missing_message_fee':rpc.message_fee=None
    if attack=='excess_message_fee':rpc.message_fee=6000
    if attack=='stale_message_fee':ticks=(1050,1070,1100,7000)
    with pytest.raises((ValueError,TypeError)):
        prepare(rpc,ticks=ticks,**overrides)
    assert 'sendTransaction' not in rpc.calls


@pytest.mark.parametrize('key,bad',[
    ('min_context_slot',True),('min_context_slot',0),
    ('max_bank_age_ms',False),('max_bank_age_ms',5001),
])
def test_source_limits_are_required_and_bounded(key,bad):
    rpc=FakeRpc(fixture_bank())
    with pytest.raises(ValueError):
        prepare(rpc,**{key:bad})
    assert rpc.calls==[]
