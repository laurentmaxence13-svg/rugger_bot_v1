"""Offline end-to-end CPMM post-migration SELL construction on raw packed banks.

All bank values/addresses are synthetic; no real migration, market receipt,
wallet material, RPC, or funds. This is executable-ABI validation only.
"""
import base64
from dataclasses import replace
import hashlib
import json
import struct

import pytest

from bot.p3.certification import _decode,_encode,find_program_address
from bot.p3.quotes import SOL_MINT
from bot.live.route import (
    TOKEN_PROGRAM,SYSTEM_PROGRAM,COMPUTE_BUDGET_PROGRAM,
    associated_token_address,ephemeral_wsol_address,
)
from bot.live.cpmm_swap import CPMM_PROGRAM,CPMM_SWAP_BASE_INPUT
from bot.live.cpmm_exit import (
    build_cpmm_exit,validate_cpmm_exit,
    POOL_DISCRIMINATOR,CONFIG_DISCRIMINATOR,OBSERVATION_DISCRIMINATOR,
    POOL_ACCOUNT_SIZE,CONFIG_ACCOUNT_SIZE,OBSERVATION_ACCOUNT_SIZE,
)
from test_live_wire_route import _instructions


WALLET=_encode(bytes([22])*32)
MINT=_encode(bytes([55])*32)
POOL=_encode(bytes([88])*32)
BLOCKHASH=_encode(bytes([33])*32)
DECISION='synthetic-cpmm-end-to-end-001'
RENT=2039280


def _raw(data,owner,lamports=100000000):
    return dict(owner=owner,executable=False,lamports=lamports,
                data=[base64.b64encode(bytes(data)).decode(),'base64'])


def _mint_state(*,decimals,supply):
    v=bytearray(82)
    struct.pack_into('<Q',v,36,supply)
    v[44],v[45]=decimals,1
    return _raw(v,TOKEN_PROGRAM)


def _token_state(mint,authority,amount,*,native=False):
    v=bytearray(165)
    v[0:32]=_decode(mint)
    v[32:64]=_decode(authority)
    struct.pack_into('<Q',v,64,amount)
    v[108]=1
    if native:
        struct.pack_into('<I',v,109,1)
        struct.pack_into('<Q',v,113,RENT)
    return _raw(v,TOKEN_PROGRAM,lamports=(amount+RENT if native else RENT))


def fixture_bank(*,creator_enabled=True,creator_on=0):
    config,bump=find_program_address((b'amm_config',bytes([0,0])),program_id=CPMM_PROGRAM)
    authority,auth_bump=find_program_address(
        (b'vault_and_lp_mint_auth_seed',),program_id=CPMM_PROGRAM)
    lp=find_program_address((b'pool_lp_mint',_decode(POOL)),program_id=CPMM_PROGRAM)[0]
    observation=find_program_address(
        (b'observation',_decode(POOL)),program_id=CPMM_PROGRAM)[0]
    tokens=sorted([MINT,SOL_MINT],key=_decode)
    vaults=[find_program_address(
        (b'pool_vault',_decode(POOL),_decode(token)),program_id=CPMM_PROGRAM)[0]
        for token in tokens]
    names=(config,_encode(bytes([77])*32),vaults[0],vaults[1],
           lp,tokens[0],tokens[1],TOKEN_PROGRAM,TOKEN_PROGRAM,observation)
    pool=bytearray(POOL_ACCOUNT_SIZE)
    pool[:8]=POOL_DISCRIMINATOR
    for i,k in enumerate(names):
        pool[8+i*32:8+(i+1)*32]=_decode(k)
    pool[328],pool[329]=auth_bump,0
    pool[330]=6
    pool[331]=6 if tokens[0]==MINT else 9
    pool[332]=6 if tokens[1]==MINT else 9
    pool[389]=creator_on
    pool[390]=int(creator_enabled)
    struct.pack_into('<Q',pool,333,100000000000)
    struct.pack_into('<Q',pool,373,1)
    cfg=bytearray(CONFIG_ACCOUNT_SIZE)
    cfg[:8]=CONFIG_DISCRIMINATOR
    cfg[8]=bump
    struct.pack_into('<Q',cfg,12,2500)
    struct.pack_into('<Q',cfg,20,100000)
    struct.pack_into('<Q',cfg,28,10000)
    struct.pack_into('<Q',cfg,108,1000)
    ob=bytearray(OBSERVATION_ACCOUNT_SIZE)
    ob[:8]=OBSERVATION_DISCRIMINATOR
    ob[8]=1
    ob[11:43]=_decode(POOL)
    ata=associated_token_address(WALLET,MINT)
    wsol,_=ephemeral_wsol_address(WALLET,DECISION)
    amounts={MINT:1_000_000_000,SOL_MINT:5_000_000_000}
    accounts={
        POOL:_raw(pool,CPMM_PROGRAM),
        config:_raw(cfg,CPMM_PROGRAM),
        observation:_raw(ob,CPMM_PROGRAM),
        MINT:_mint_state(decimals=6,supply=1000000000000),
        SOL_MINT:_mint_state(decimals=9,supply=1000000000000000),
        WALLET:dict(owner=SYSTEM_PROGRAM,executable=False,
                    lamports=10000000000,data=['','base64']),
        ata:_token_state(MINT,WALLET,10000000),
        wsol:None,
    }
    for token,key in zip(tokens,vaults,strict=True):
        accounts[key]=_token_state(token,authority,amounts[token],
                                   native=(token==SOL_MINT))
    args=dict(accounts=accounts,pool_address=POOL,mint=MINT,wallet=WALLET,
        context_slot=1234,available_at_ms=1000,decision_at_ms=1100,
        observed_block_time_seconds=1,amount_in=1000000,
        slippage_bps=100,max_slippage_bps=200,max_price_impact_bps=500,
        recent_blockhash=BLOCKHASH,last_valid_block_height=5000,
        rent_exempt_lamports=RENT,decision_id=DECISION,
        compute_unit_limit=200000,priority_fee_micro_lamports=10,
        max_priority_fee_lamports=2)
    return args


def mutate_raw(account,offset,data):
    raw=bytearray(base64.b64decode(account['data'][0]))
    raw[offset:offset+len(data)]=data
    account['data'][0]=base64.b64encode(raw).decode()


def test_entire_fee_aware_sell_is_atomic_legacy_wire_for_classic_spl():
    args=fixture_bank()
    order=build_cpmm_exit(**args)
    assert order.side=='SELL'
    assert order.user==WALLET and order.pool==POOL and order.mint==MINT
    assert order.transaction.required_signers==(WALLET,)
    assert order.minimum_out==order.expected_output*99//100
    assert order.price_impact_bps<=500
    assert order.network_fee_upper_lamports==5002
    assert order.rent_deposit_lamports==RENT
    assert len(order.transaction.unsigned_transaction())<=1232
    _,keys,bhash,ixs=_instructions(order.transaction.message)
    assert bhash==BLOCKHASH
    assert len(ixs)==6
    assert [t[0] for t in ixs]==[
        COMPUTE_BUDGET_PROGRAM,COMPUTE_BUDGET_PROGRAM,SYSTEM_PROGRAM,
        TOKEN_PROGRAM,CPMM_PROGRAM,TOKEN_PROGRAM]
    assert ixs[4][2][:8]==CPMM_SWAP_BASE_INPUT
    assert struct.unpack('<QQ',ixs[4][2][8:])==(order.input_amount,order.minimum_out)
    assert ixs[5][2]==b'\x09'
    assert order.quote_token_account==ephemeral_wsol_address(WALLET,DECISION)[0]
    assert not order.live_execution_enabled
    assert not order.migration_provenance_verified
    assert validate_cpmm_exit(order)==order
    fees=json.loads(order.fee_detail_json)
    assert fees['creator_fee_on_input'] is True
    assert fees['creator_fee']>0 and fees['trade_fee']>0
    assert fees['output']==order.expected_output


def test_creator_fee_on_output_is_included_in_user_receipt():
    p=fixture_bank(creator_enabled=True,creator_on=2)
    token_index=0 if p['mint']<p['accounts'][POOL]['owner'] else 0
    # Choose the mode that is NOT the actual input token's index.
    raw=base64.b64decode(p['accounts'][POOL]['data'][0])
    keys=[_encode(raw[8+32*i:8+32*(i+1)]) for i in range(10)]
    input_idx=0 if keys[5]==MINT else 1
    mutate_raw(p['accounts'][POOL],389,bytes((2 if input_idx==0 else 1,)))
    order=build_cpmm_exit(**p)
    fees=json.loads(order.fee_detail_json)
    assert not fees['creator_fee_on_input']
    assert fees['creator_fee']>0
    assert fees['gross']-fees['creator_fee']==fees['output']


def test_disabled_creator_fee_is_zero_even_when_config_rate_positive():
    p=fixture_bank(creator_enabled=False)
    result=build_cpmm_exit(**p)
    fees=json.loads(result.fee_detail_json)
    assert fees['creator_fee']==0 and fees['creator_fee_rate']==0


@pytest.mark.parametrize('change,why',[
    ('status','status_time_or_program'),
    ('bad_pool_owner','owner_length_or_encoding'),
    ('bad_pool_disc','discriminator'),
    ('bad_config_fee','unsupported_fee_rates'),
    ('bad_observation','observation_content_identity'),
    ('freeze','mint_decimals_or_authorities'),
    ('insufficient_user','user_inventory'),
    ('bad_wallet','cannot_fund_rent_and_fee'),
    ('quote_not_native','vault_identity_or_authority'),
])
def test_adversarial_raw_bank_is_refused(change,why):
    p=fixture_bank()
    account=p['accounts']
    pool=account[POOL]
    poolraw=base64.b64decode(pool['data'][0])
    config=_encode(poolraw[8:40])
    quote_vault=_encode(poolraw[8+32*2:8+32*3]) if _encode(poolraw[8+32*5:8+32*6])==SOL_MINT else _encode(poolraw[8+32*3:8+32*4])
    if change=='status':
        mutate_raw(pool,329,b'\x04')
    if change=='bad_pool_owner':
        pool['owner']=SYSTEM_PROGRAM
    if change=='bad_pool_disc':
        mutate_raw(pool,0,b'ABCDEFGH')
    if change=='bad_config_fee':
        mutate_raw(account[config],12,struct.pack('<Q',1000000))
    if change=='bad_observation':
        ob=_encode(poolraw[8+32*9:8+32*10])
        mutate_raw(account[ob],11,_decode(WALLET))
    if change=='freeze':
        mutate_raw(account[MINT],46,struct.pack('<I',1))
    if change=='insufficient_user':
        ata=associated_token_address(WALLET,MINT)
        mutate_raw(account[ata],64,struct.pack('<Q',999))
    if change=='bad_wallet':
        account[WALLET]['lamports']=100
    if change=='quote_not_native':
        mutate_raw(account[quote_vault],109,struct.pack('<I',0))
    with pytest.raises(ValueError,match=why):
        build_cpmm_exit(**p)


def test_strict_same_bank_and_ephemeral_WSOL_absence():
    p=fixture_bank()
    del p['accounts'][SOL_MINT]
    with pytest.raises(ValueError,match='same_bank_complete'):
        build_cpmm_exit(**p)
    p=fixture_bank()
    wsol=ephemeral_wsol_address(WALLET,DECISION)[0]
    p['accounts'][wsol]=dict()
    with pytest.raises(ValueError,match='already_exists'):
        build_cpmm_exit(**p)


@pytest.mark.parametrize('field,value',[
    ('amount_in',0),('amount_in',True),('amount_in',2**64),
    ('slippage_bps',10000),('max_price_impact_bps',True),
    ('compute_unit_limit',1400001),('available_at_ms',20000),
    ('context_slot',0),('observed_block_time_seconds',100000),
])
def test_explicit_limits_refuse_unbounded_or_stale_routes(field,value):
    p=fixture_bank();p[field]=value
    with pytest.raises(ValueError):
        build_cpmm_exit(**p)


def test_prepared_transaction_or_permission_tampering_does_not_pass_rebuild():
    o=build_cpmm_exit(**fixture_bank())
    with pytest.raises(ValueError,match='modified'):
        validate_cpmm_exit(replace(o,minimum_out=o.minimum_out-1))
    with pytest.raises(ValueError,match='modified'):
        validate_cpmm_exit(replace(o,live_execution_enabled=True))
    with pytest.raises(ValueError,match='modified'):
        validate_cpmm_exit(replace(o,migration_provenance_verified=True))


def test_unknown_pool_state_must_be_rejected_without_migration_proof():
    p=fixture_bank()
    p['pool_address']=WALLET
    with pytest.raises(ValueError):
        build_cpmm_exit(**p)
