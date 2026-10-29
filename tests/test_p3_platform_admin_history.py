"""Pinned IDL account/data/signature binding; all envelopes are synthetic."""
import copy
import struct

import pytest

from bot.p3.certification import find_program_address
from bot.p3.platform_admin_history import verify_historical_platform_creation

PROGRAM='LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
DISCRIMINATOR=bytes([176,90,196,175,253,113,220,20])
ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def encode(raw):
    n=int.from_bytes(raw,'big');s=''
    while n:
        n,i=divmod(n,58);s=ALPHABET[i]+s
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+s


SIGNATURE=encode(bytes([5])*64)
ADMIN=encode(bytes([61])*32)
PLATFORM=find_program_address((b'platform_config',bytes([61])*32))[0]


def create_params():
    # Actual pinned Borsh schema: three migration scales, fee, three strings,
    # creator fee and vesting scale. No source text is market evidence.
    strings=(b'synthetic',b'',b'')
    return (DISCRIMINATOR+struct.pack('<QQQQ',1000000,0,0,10000)
        +b''.join(struct.pack('<I',len(item))+item for item in strings)
        +struct.pack('<QQ',5000,0))


@pytest.fixture
def functions():
    return verify_historical_platform_creation


def transaction():
    return {'slot':100,'meta':{'err':None},'transaction':{
        'signatures':[SIGNATURE],'message':{
            'accountKeys':[{'pubkey':ADMIN,'signer':True,'writable':True},
                           {'pubkey':encode(bytes([62])*32),'signer':False},
                           {'pubkey':encode(bytes([63])*32),'signer':False},
                           {'pubkey':PLATFORM,'signer':False,'writable':True},
                           {'pubkey':encode(bytes([64])*32),'signer':False},
                           {'pubkey':'11111111111111111111111111111111','signer':False},
                           {'pubkey':encode(bytes([65])*32),'signer':False},
                           {'pubkey':encode(bytes([66])*32),'signer':False},
                           {'pubkey':PROGRAM,'signer':False}],
            'instructions':[{'programId':PROGRAM,'data':encode(create_params()),
                             'accounts':[0,1,2,3,4,5,6,7]}]}}}


def check(fn,tx):
    return fn(tx,platform_config=PLATFORM,signature=SIGNATURE,snapshot_context_slot=101)


def test_signed_creation_with_exact_discriminator_and_PDA(functions):
    raw=transaction();before=copy.deepcopy(raw)
    result=check(functions,raw)
    assert result['status']=='PASS'
    assert result['historical_seed_certified'] is True
    assert result['historical_platform_admin']==ADMIN
    assert result['pda_bump']==find_program_address((b'platform_config',bytes([61])*32))[1]
    assert result['creation_slot']==100
    assert result['strict_snapshot_identity_promoted'] is False
    assert result['source_tx_provenance_certified_by_this_function'] is False
    assert result['current_execution_or_trading_permission'] is False
    assert result['cryptographic_signature_verified'] is False
    assert result['pinned_instruction_layout_verified'] is True
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
    del ix['programId'];ix['programIdIndex']=8
    assert check(functions,x)['status']=='PASS'


@pytest.mark.parametrize('lengths', [(65,0,0),(0,257,0),(0,0,257)])
def test_pinned_platform_string_capacity_is_enforced(functions,lengths):
    value=transaction()
    data=(DISCRIMINATOR+struct.pack('<QQQQ',0,0,0,0)
        +b''.join(struct.pack('<I',n)+b'x'*n for n in lengths)
        +struct.pack('<QQ',0,0))
    value['transaction']['message']['instructions'][0]['data']=encode(data)
    assert check(functions,value)['status']=='UNKNOWN'


@pytest.mark.parametrize('modify',[
    lambda tx:tx['transaction']['signatures'].__setitem__(0,'not_a_transaction_signature'),
    lambda tx:tx['transaction']['signatures'].append(SIGNATURE),
    lambda tx:tx['transaction']['message'].__setitem__('header',{'numRequiredSignatures':2}),
    lambda tx:tx['transaction']['message']['accountKeys'][0].__setitem__('writable',False),
    lambda tx:tx['transaction']['message']['accountKeys'][0].__setitem__('source','lookupTable'),
    lambda tx:tx['transaction']['message']['accountKeys'][3].__setitem__('writable',False),
    lambda tx:tx['transaction']['message']['accountKeys'][1].__setitem__('signer',1),
    lambda tx:tx['transaction']['message']['accountKeys'][1].__setitem__('pubkey',ADMIN),
    lambda tx:tx['transaction']['message']['instructions'][0].__setitem__('programIdIndex',5),
    lambda tx:tx['transaction']['message']['instructions'][0].__setitem__('programIdIndex',True),
    lambda tx:tx['transaction']['message']['instructions'][0].__setitem__('accounts',[0,1,2,3]),
    lambda tx:tx['transaction']['message']['instructions'][0]['accounts'].__setitem__(5,6),
    lambda tx:tx['transaction']['message']['instructions'][0].__setitem__('data',encode(DISCRIMINATOR+b'xx')),
    lambda tx:tx['transaction']['message']['instructions'][0].__setitem__('data',encode(create_params()[:-1])),
    lambda tx:tx['transaction']['message']['instructions'][0].__setitem__('data',encode(create_params()+b'junk')),
])
def test_abbreviated_or_inconsistent_historical_proof_never_certifies(functions,modify):
    tx=transaction();modify(tx)
    result=check(functions,tx)
    assert result['status']=='UNKNOWN'
    assert not result['historical_seed_certified']
    assert not result['cryptographic_signature_verified']


def test_actual_public_key_instruction_accounts_can_replace_indices(functions):
    tx=transaction();message=tx['transaction']['message'];ix=message['instructions'][0]
    ix['accounts']=[message['accountKeys'][i]['pubkey'] for i in ix['accounts']]
    assert check(functions,tx)['status']=='PASS'
