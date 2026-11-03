"""Synthetic loader-v3 ProgramData attestation; no wallet or network.

This verifies byte-level agreement between the pinned value and one final
Program+ProgramData RPC bank; it does not authenticate the public RPC.
"""
import asyncio
import base64
from copy import deepcopy
import hashlib
import struct

import pytest

from bot.p3.certification import _decode,_encode,find_program_address
from bot.live.program_pin import LOADER,attest_program_pin


PROGRAM=_encode(bytes([42])*32)
GENESIS=_encode(bytes([12])*32)
AUTHORITY=_encode(bytes([71])*32)
ENDPOINT='a'*64
PROGRAMDATA,_=find_program_address((_decode(PROGRAM),),program_id=LOADER)


def account(raw,*,executable):
    return dict(owner=LOADER,executable=executable,lamports=10_000_000,
                space=len(raw),
                data=[base64.b64encode(raw).decode(),'base64'])


def bank(*,authority=AUTHORITY):
    program=account(struct.pack('<I',2)+_decode(PROGRAMDATA),executable=True)
    header=struct.pack('<IQB',3,90,1 if authority else 0)
    header+=_decode(authority) if authority else bytes(32)
    pd=account(header+b'\x7fELF'+bytes([3,5,7,11])*60,executable=False)
    raw=base64.b64decode(pd['data'][0])
    pins=dict(program_id=PROGRAM,expected_endpoint_sha256=ENDPOINT,
        expected_genesis_hash=GENESIS,min_context_slot=299,
        expected_deployment_slot=90,
        expected_programdata_sha256=hashlib.sha256(raw).hexdigest(),
        expected_elf_sha256=hashlib.sha256(raw[45:]).hexdigest(),
        expected_upgrade_authority=authority)
    return program,pd,pins


class FakeRpc:
    endpoint_sha256=ENDPOINT

    def __init__(self,first,second,*,s1=300,s2=301):
        self.first,self.second=deepcopy(first),deepcopy(second)
        self.s1,self.s2=s1,s2
        self.genesis=GENESIS
        self.calls=[]

    async def genesis_hash(self):
        self.calls.append('getGenesisHash')
        return self.genesis

    async def get_multiple_accounts(self,addresses,*,min_context_slot):
        self.calls.append(('getMultipleAccounts',tuple(addresses),min_context_slot))
        if len(addresses)==1:
            assert tuple(addresses)==(PROGRAM,)
            return dict(context=dict(slot=self.s1),value=[deepcopy(self.first)])
        assert tuple(addresses)==(PROGRAM,PROGRAMDATA)
        return dict(context=dict(slot=self.s2),value=deepcopy(self.second))

    async def send_transaction(self,*_args,**_kwargs):
        raise AssertionError('program_pin_may_never_send')


def run(rpc,pins):
    return asyncio.run(attest_program_pin(rpc,**pins))


@pytest.mark.parametrize('authority',[AUTHORITY,None])
def test_exact_program_and_programdata_sha_and_immutable_authority_pin(authority):
    program,pd,pins=bank(authority=authority)
    rpc=FakeRpc(program,[program,pd])
    result=run(rpc,pins)
    assert result['result']=='PIN_MATCHED_READ_ONLY'
    assert result['program_id']==PROGRAM
    assert result['programdata_address']==PROGRAMDATA
    assert result['first_bank_slot']==300 and result['joint_bank_slot']==301
    assert result['deployment_slot']==90
    assert result['upgrade_authority']==authority
    assert result['programdata_sha256']==pins['expected_programdata_sha256']
    assert result['elf_sha256']==pins['expected_elf_sha256']
    assert not result['live_execution_authorized']
    assert not result['source_build_verified']
    assert not result['independent_RPC_consensus_verified']
    assert rpc.calls==[
        'getGenesisHash',
        ('getMultipleAccounts',(PROGRAM,),299),
        ('getMultipleAccounts',(PROGRAM,PROGRAMDATA),300)]


@pytest.mark.parametrize('attack',[
    'wrong_endpoint','wrong_genesis','first_program_owner','first_executable',
    'first_wrong_PDA','first_wrong_state','second_pointer_change',
    'second_owner','second_executable','programdata_discriminator',
    'changed_ELF','bad_ELF_magic','changed_upgrade_authority',
    'bad_upgrade_tag','wrong_last_upgrade_slot','reported_space_mismatch',
    'stale_first_bank','stale_second_bank','activation_not_effective',
])
def test_any_mismatch_refuses_exact_program_identity(attack):
    program,pd,pins=bank()
    rpc=FakeRpc(program,[program,pd])
    if attack=='wrong_endpoint':pins['expected_endpoint_sha256']='b'*64
    if attack=='wrong_genesis':rpc.genesis=PROGRAM
    if attack=='first_program_owner':rpc.first['owner']=PROGRAM
    if attack=='first_executable':rpc.first['executable']=False
    if attack=='first_wrong_PDA':
        rpc.first['data']=[base64.b64encode(
            struct.pack('<I',2)+_decode(PROGRAM)).decode(),'base64']
    if attack=='first_wrong_state':
        rpc.first['data']=[base64.b64encode(
            struct.pack('<I',1)+_decode(PROGRAMDATA)).decode(),'base64']
    if attack=='second_pointer_change':
        p=struct.pack('<I',2)+_decode(PROGRAM)
        rpc.second[0]=account(p,executable=True)
    if attack=='second_owner':rpc.second[1]['owner']=PROGRAM
    if attack=='second_executable':rpc.second[1]['executable']=True
    if attack=='programdata_discriminator':
        mutate(rpc.second[1],0,struct.pack('<I',2))
    if attack=='changed_ELF':mutate(rpc.second[1],55,b'X')
    if attack=='bad_ELF_magic':mutate(rpc.second[1],45,b'NONE')
    if attack=='changed_upgrade_authority':
        mutate(rpc.second[1],13,_decode(PROGRAM))
    if attack=='bad_upgrade_tag':mutate(rpc.second[1],12,b'\x02')
    if attack=='wrong_last_upgrade_slot':
        mutate(rpc.second[1],4,struct.pack('<Q',91))
    if attack=='reported_space_mismatch':rpc.second[1]['space']=1
    if attack=='stale_first_bank':rpc.s1=298
    if attack=='stale_second_bank':rpc.s2=299
    if attack=='activation_not_effective':
        mutate(rpc.second[1],4,struct.pack('<Q',301))
    with pytest.raises(ValueError):
        run(rpc,pins)
    assert all(x!='sendTransaction' for x in rpc.calls)


def mutate(account,offset,new_bytes):
    raw=bytearray(base64.b64decode(account['data'][0]))
    raw[offset:offset+len(new_bytes)]=new_bytes
    account['data'][0]=base64.b64encode(raw).decode()


def test_expected_code_or_slot_can_not_be_omitted_or_supplied_as_booleans():
    program,pd,pins=bank()
    for field,bad in (('expected_programdata_sha256',''),
                      ('expected_elf_sha256','A'*64),
                      ('expected_deployment_slot',True),
                      ('min_context_slot',True)):
        altered=dict(pins,**{field:bad})
        with pytest.raises(ValueError):
            run(FakeRpc(program,[program,pd]),altered)


def test_address_owner_and_elf_unpinned_cannot_be_promotion_to_live():
    program,pd,pins=bank()
    r=run(FakeRpc(program,[program,pd]),pins)
    assert r['live_ready_to_arm'] is False
    assert r['live_execution_authorized'] is False
