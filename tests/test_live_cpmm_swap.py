"""Protocol ABI test for standalone post-migration CPMM SELL instruction.

All accounts are synthetic *public* addresses; neither user funds nor RPC calls
are involved. Passing tests proves IDL encoding and PDA consistency only.
"""
import struct

import pytest

from bot.p3.certification import _decode, _encode, find_program_address
from bot.p3.quotes import SOL_MINT
from bot.live.route import TOKEN_PROGRAM, associated_token_address, ephemeral_wsol_address
from bot.live.cpmm_swap import (
    CPMM_PROGRAM, CPMM_SWAP_BASE_INPUT, CPMM_SWAP_ROLES,
    SOURCE_PIN, build_cpmm_sell_instruction,
)
from bot.live.wire import Instruction


WALLET=_encode(bytes([22])*32)
MINT=_encode(bytes([55])*32)
POOL=_encode(bytes([88])*32)
DECISION='cpmm-post-migration-synthetic-001'


def params():
    sorted_mints=sorted([MINT, SOL_MINT],key=_decode)
    return dict(wallet=WALLET,mint=MINT,pool=POOL,amm_config_index=0,
        token_0_mint=sorted_mints[0],token_1_mint=sorted_mints[1],
        input_vault=find_program_address((b'pool_vault',_decode(POOL),_decode(MINT)),
                                          program_id=CPMM_PROGRAM)[0],
        output_vault=find_program_address((b'pool_vault',_decode(POOL),_decode(SOL_MINT)),
                                           program_id=CPMM_PROGRAM)[0],
        observation_state=find_program_address((b'observation',_decode(POOL)),
                                                program_id=CPMM_PROGRAM)[0],
        amount_in_atomic=100000,expected_output_lamports=10000000,
        slippage_bps=100,decision_id=DECISION)


def test_cpmm_sell_is_real_pinned_exact_input_instruction_not_executable_authority():
    p=params()
    result=build_cpmm_sell_instruction(**p)
    instruction=result.instruction
    assert type(instruction) is Instruction
    assert instruction.program_id==CPMM_PROGRAM
    assert SOURCE_PIN['commit']=='e7e0c96fe77bcf6a020b84a44c47a722aac8e359'
    assert CPMM_SWAP_BASE_INPUT==bytes((143,190,90,218,196,30,51,222))
    assert len(instruction.accounts)==13
    assert len(instruction.data)==24
    assert instruction.data[:8]==CPMM_SWAP_BASE_INPUT
    assert struct.unpack('<QQ',instruction.data[8:])==(100000,9900000)
    assert result.minimum_out_lamports==9900000
    keys=[a.pubkey for a in instruction.accounts]
    assert keys[0]==WALLET
    assert keys[4]==associated_token_address(WALLET,MINT)
    assert keys[5]==ephemeral_wsol_address(WALLET,DECISION)[0]
    assert keys[6]==p['input_vault'] and keys[7]==p['output_vault']
    assert keys[8:12]==[TOKEN_PROGRAM,TOKEN_PROGRAM,MINT,SOL_MINT]
    assert keys[12]==p['observation_state']
    assert keys[1]==find_program_address(
        (b'vault_and_lp_mint_auth_seed',),program_id=CPMM_PROGRAM)[0]
    assert keys[2]==find_program_address(
        (b'amm_config',b'\x00\x00'),program_id=CPMM_PROGRAM)[0]
    assert [a.is_signer for a in instruction.accounts]==[True]+[False]*12
    assert [i for i,a in enumerate(instruction.accounts) if a.is_writable]==[3,4,5,6,7,12]
    assert not result.migration_source_verified
    assert not result.provider_quote_verified
    assert not result.transaction_complete
    assert not result.trading_allowed


def test_mint_order_is_canonical_and_supports_either_token_index():
    p=params()
    result=build_cpmm_sell_instruction(**p)
    assert result.pool==POOL
    p['token_0_mint'],p['token_1_mint']=p['token_1_mint'],p['token_0_mint']
    with pytest.raises(ValueError,match='sorted'):
        build_cpmm_sell_instruction(**p)


@pytest.mark.parametrize('field,value',[
    ('input_vault',MINT),('output_vault',WALLET),
    ('observation_state',POOL),
])
def test_wrong_vault_or_observation_PDA_refused(field,value):
    p=params();p[field]=value
    with pytest.raises(ValueError,match='PDA_mismatch'):
        build_cpmm_sell_instruction(**p)


@pytest.mark.parametrize('field,value',[
    ('amount_in_atomic',0),('amount_in_atomic',True),
    ('amount_in_atomic',2**64),
    ('expected_output_lamports',0),
    ('expected_output_lamports',2**64),
    ('slippage_bps',True),('slippage_bps',10000),
    ('amm_config_index',65536),('amm_config_index',-1),
])
def test_invalid_amount_fee_or_config_refused(field,value):
    p=params();p[field]=value
    with pytest.raises(ValueError):
        build_cpmm_sell_instruction(**p)


def test_slippage_rounding_must_not_allow_zero_minimum():
    p=params();p.update(expected_output_lamports=1,slippage_bps=9999)
    with pytest.raises(ValueError):
        build_cpmm_sell_instruction(**p)


def test_pool_cannot_alias_wallet_even_if_pd_as_derive_correctly():
    p=params();p['pool']=WALLET
    p['input_vault']=find_program_address(
        (b'pool_vault',_decode(WALLET),_decode(MINT)),program_id=CPMM_PROGRAM)[0]
    p['output_vault']=find_program_address(
        (b'pool_vault',_decode(WALLET),_decode(SOL_MINT)),program_id=CPMM_PROGRAM)[0]
    p['observation_state']=find_program_address(
        (b'observation',_decode(WALLET)),program_id=CPMM_PROGRAM)[0]
    with pytest.raises(ValueError,match='must_not_alias'):
        build_cpmm_sell_instruction(**p)


def test_foreign_mint_or_incorrect_quote_pair_refused():
    p=params();p['token_1_mint']=_encode(bytes([75])*32)
    with pytest.raises(ValueError,match='pair'):
        build_cpmm_sell_instruction(**p)
