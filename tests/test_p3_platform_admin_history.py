"""Synthetic signed-instruction binding tests, not real RPC proof.

The canonical PDA algorithm is stubbed here. Integration tests MUST use the
repo's actual certification module and historical on-chain bytes before merge.
"""
import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROGRAM='LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
DISCRIMINATOR=bytes([176,90,196,175,253,113,220,20])
ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def encode(raw):
    n=int.from_bytes(raw,'big');s=''
    while n:
        n,i=divmod(n,58);s=ALPHABET[i]+s
    return s


@pytest.fixture
def functions(monkeypatch):
    m=ModuleType('bot.p3.certification')
    m.PROGRAM=PROGRAM
    m._decode=lambda addr: addr.encode('ascii')
    m.find_program_address=lambda seeds:('PDA_'+seeds[1].decode('ascii'),255)
    monkeypatch.setitem(sys.modules,'bot.p3.certification',m)
    spec=importlib.util.spec_from_file_location('test_platform_history',
        Path(__file__).resolve().parents[1]/'bot/p3/platform_admin_history.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.verify_historical_platform_creation


def transaction():
    return {'slot':100,'meta':{'err':None},'transaction':{
        'signatures':['SIG_test'],'message':{
            'accountKeys':[{'pubkey':'AdminA','signer':True},
                           {'pubkey':'FeeWallet','signer':False},
                           {'pubkey':'NFTWallet','signer':False},
                           {'pubkey':'PDA_AdminA','signer':False},
                           {'pubkey':PROGRAM,'signer':False}],
            'instructions':[{'programId':PROGRAM,'data':encode(DISCRIMINATOR+b'xx'),
                             'accounts':[0,1,2,3]}]}}}


def check(fn,tx):
    return fn(tx,platform_config='PDA_AdminA',signature='SIG_test',snapshot_context_slot=101)


def test_signed_creation_with_exact_discriminator_and_PDA(functions):
    raw=transaction();before=copy.deepcopy(raw)
    result=check(functions,raw)
    assert result['status']=='PASS'
    assert result['historical_seed_certified'] is True
    assert result['historical_platform_admin']=='AdminA'
    assert result['pda_bump']==255
    assert result['creation_slot']==100
    assert result['strict_snapshot_identity_promoted'] is False
    assert result['source_tx_provenance_certified_by_this_function'] is False
    assert result['current_execution_or_trading_permission'] is False
    assert raw==before


@pytest.mark.parametrize('modify',[
    lambda x: x['meta'].__setitem__('err',{'InstructionError':[0,'Custom']}),
    lambda x: x.__setitem__('slot',102),
    lambda x: x['transaction']['message']['accountKeys'][0].__setitem__('signer',False),
    lambda x: x['transaction']['message']['instructions'][0].__setitem__('programId','WrongProgram'),
    lambda x: x['transaction']['message']['instructions'][0].__setitem__('data','1'),
    lambda x: x['transaction']['message']['instructions'][0].__setitem__('accounts',[1,0,2,3]),
    lambda x: x['transaction']['message']['instructions'][0].__setitem__('accounts',[0,1,2,1]),
    lambda x: x['transaction']['signatures'].__setitem__(0,'OTHER_SIG'),
    lambda x: x['transaction']['message']['accountKeys'][3].__setitem__('pubkey','OTHER_PDA'),
])
def test_wrong_or_unsigned_source_never_certified(functions,modify):
    x=transaction();modify(x)
    result=check(functions,x)
    assert result['status']=='UNKNOWN'
    assert not result['historical_seed_certified']
    assert not result['strict_snapshot_identity_promoted']


def test_compiled_program_id_account_indices_supported(functions):
    x=transaction();ix=x['transaction']['message']['instructions'][0]
    del ix['programId'];ix['programIdIndex']=4
    assert check(functions,x)['status']=='PASS'
