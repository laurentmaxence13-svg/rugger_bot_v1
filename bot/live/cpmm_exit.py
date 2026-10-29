"""Full unsigned CPMM post-migration SELL, from a single retained RPC bank.

Strict classic-SPL token -> WSOL only. Uses pinned public CPMM PoolState,
AmmConfig and curve source. Includes compute-budget, temporary WSOL account,
exact-input swap, and atomic close-to-SOL. External signer and live engine
integration remain separate. NO network, signing, wallet loading or submission.

The supplied candidate pool must be independently linked to LaunchLab
graduation by verified chain provenance before enabling live execution.
This module validates *pool state*, not the migration transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import struct

from bot.p3 import launchlab
from bot.p3.certification import _decode, _encode, find_program_address
from bot.p3.quotes import SOL_MINT
from bot.live.cpmm_swap import (
    CPMM_PROGRAM, SOURCE_PIN, build_cpmm_sell_instruction,
)
from bot.live.route import (
    SYSTEM_PROGRAM, TOKEN_PROGRAM, COMPUTE_BUDGET_PROGRAM,
    associated_token_address, ephemeral_wsol_address,
)
from bot.live.wire import (
    AccountMeta as AM, Instruction, PreparedTransaction, compile_legacy,
)


POOL_DISCRIMINATOR=bytes((247,237,227,245,215,195,222,70))
CONFIG_DISCRIMINATOR=bytes((218,244,33,104,203,203,43,111))
OBSERVATION_DISCRIMINATOR=bytes((122,174,197,53,129,9,165,132))
POOL_ACCOUNT_SIZE=637
CONFIG_ACCOUNT_SIZE=236
OBSERVATION_ACCOUNT_SIZE=4075
FEE_DENOMINATOR=1_000_000
CPMM_SOURCE_REVISION='b3187ae53a1b95a201f855a59024a12ca8f5b51a'


def _uint(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        raise ValueError('cpmm_exact_u64_required')
    return value


def _account(raw, *, name, size, discriminator):
    try:
        data=launchlab._account(raw,CPMM_PROGRAM,size,name)
    except (launchlab.SnapshotEvidenceError, ValueError, TypeError):
        raise ValueError('cpmm_'+name+'_owner_length_or_encoding_invalid') from None
    if data[:8]!=discriminator:
        raise ValueError('cpmm_'+name+'_discriminator_mismatch')
    return data


def _key(raw,offset):
    return _encode(raw[offset:offset+32])


def _pool(raw):
    keys=tuple(_key(raw,8+i*32) for i in range(10))
    fields=('amm_config','pool_creator','token_0_vault','token_1_vault',
            'lp_mint','token_0_mint','token_1_mint','token_0_program',
            'token_1_program','observation_key')
    d=dict(zip(fields,keys,strict=True))
    for offset,key in ((328,'auth_bump'),(329,'status'),(330,'lp_mint_decimals'),
                       (331,'mint_0_decimals'),(332,'mint_1_decimals'),
                       (389,'creator_fee_on'),(390,'enable_creator_fee')):
        d[key]=raw[offset]
    for offset,key in ((333,'lp_supply'),(341,'protocol_fees_token_0'),
        (349,'protocol_fees_token_1'),(357,'fund_fees_token_0'),
        (365,'fund_fees_token_1'),(373,'open_time'),(381,'recent_epoch'),
        (397,'creator_fees_token_0'),(405,'creator_fees_token_1')):
        d[key]=struct.unpack_from('<Q',raw,offset)[0]
    if d['enable_creator_fee'] not in (0,1) or d['creator_fee_on'] not in (0,1,2):
        raise ValueError('cpmm_creator_fee_mode_invalid')
    return d


def _config(raw):
    d=dict(bump=raw[8],disabled=raw[9],
           index=struct.unpack_from('<H',raw,10)[0])
    for offset,key in ((12,'trade_fee_rate'),(20,'protocol_fee_rate'),
                       (28,'fund_fee_rate'),(108,'creator_fee_rate'),
                       (116,'creator_fee_share_rate')):
        d[key]=struct.unpack_from('<Q',raw,offset)[0]
    return d


def _ceil_ratio(a,n,d=FEE_DENOMINATOR):
    return (a*n+d-1)//d


def _quote_exact_input(*, amount, input_reserve, output_reserve,
                       config, creator_enabled, creator_fee_on_input):
    trade=config['trade_fee_rate']
    creator=config['creator_fee_rate'] if creator_enabled else 0
    if (trade+creator >= FEE_DENOMINATOR or
            config['protocol_fee_rate']+config['fund_fee_rate']>FEE_DENOMINATOR
            or config['creator_fee_share_rate']>FEE_DENOMINATOR):
        raise ValueError('cpmm_unsupported_fee_rates')
    if creator_fee_on_input:
        fee=_ceil_ratio(amount,trade+creator)
        traded=amount-fee
        creator_paid=fee*creator//(trade+creator) if trade+creator else 0
        trade_paid=fee-creator_paid
    else:
        trade_paid=_ceil_ratio(amount,trade)
        traded=amount-trade_paid
        creator_paid=0
    if traded<=0:
        raise ValueError('cpmm_input_fully_consumed_by_fees')
    # Raydium cp-swap ConstantProductCurve::swap_base_input_without_fees
    gross=traded*output_reserve//(input_reserve+traded)
    if gross<=0 or gross>=output_reserve:
        raise ValueError('cpmm_curve_output_zero_or_vault_exhausted')
    if not creator_fee_on_input:
        creator_paid=_ceil_ratio(gross,creator)
    output=gross-(creator_paid if not creator_fee_on_input else 0)
    if output<=0:
        raise ValueError('cpmm_output_zero_after_creator_fee')
    if output>=2**64:
        raise ValueError('cpmm_output_u64_overflow')
    return dict(output=output,gross=gross,
                trade_fee=trade_paid,creator_fee=creator_paid,
                traded=traded)


@dataclass(frozen=True)
class PreparedCpmmExit:
    transaction: PreparedTransaction
    side: str
    input_amount: int
    minimum_out: int
    expected_output: int
    price_impact_bps: int
    max_price_impact_bps: int
    mint: str
    pool: str
    user: str
    source_slot: int
    source_available_at_ms: int
    decision_at_ms: int
    semantic_digest: str
    base_token_account: str
    quote_token_account: str
    network_fee_upper_lamports: int
    rent_deposit_lamports: int
    base_balance_before: int
    wallet_lamports_before: int
    source_account_digest: str
    fee_detail_json: str
    source_pins: tuple
    rebuild_request_json: str
    migration_provenance_verified: bool = False
    live_execution_enabled: bool = False


def build_cpmm_exit(*, accounts, pool_address, mint, wallet, context_slot,
                    available_at_ms, decision_at_ms, observed_block_time_seconds,
                    amount_in, slippage_bps, max_slippage_bps,
                    max_price_impact_bps, recent_blockhash, last_valid_block_height,
                    rent_exempt_lamports, decision_id, compute_unit_limit=200000,
                    priority_fee_micro_lamports=0, max_priority_fee_lamports=0):
    """Build an entire CPMM classic-SPL SELL transaction, UNSIGNED and disabled.

    All 10 required raw accounts MUST come from the same RPC context.slot.
    A successful build does not certify provenance of LaunchLab graduation.
    """
    request_json=json.dumps(dict(locals()),sort_keys=True,separators=(',',':'),allow_nan=False)
    for key in (pool_address,mint,wallet,recent_blockhash):
        _decode(key)
    amount_in=_uint(amount_in,positive=True)
    _uint(context_slot,positive=True);_uint(available_at_ms)
    _uint(decision_at_ms,positive=True);_uint(observed_block_time_seconds,positive=True)
    _uint(last_valid_block_height,positive=True)
    _uint(rent_exempt_lamports,positive=True)
    _uint(priority_fee_micro_lamports)
    _uint(max_priority_fee_lamports)
    if (type(slippage_bps) is not int or type(max_slippage_bps) is not int
            or not 0<=slippage_bps<=max_slippage_bps<10000
            or type(max_price_impact_bps) is not int
            or not 0<=max_price_impact_bps<10000
            or type(compute_unit_limit) is not int
            or not 0<compute_unit_limit<=1400000
            or not 0<=decision_at_ms-available_at_ms<=5000
            or observed_block_time_seconds>decision_at_ms//1000+120):
        raise ValueError('cpmm_explicit_temporal_slippage_and_compute_limits_required')
    if type(accounts) is not dict or mint==SOL_MINT:
        raise ValueError('cpmm_explicit_classic_SPL_bank_required')
    raw_pool=_account(accounts.get(pool_address),name='pool',size=POOL_ACCOUNT_SIZE,
                      discriminator=POOL_DISCRIMINATOR)
    pool=_pool(raw_pool)
    if ({pool['token_0_mint'],pool['token_1_mint']} != {mint,SOL_MINT}
            or not _decode(pool['token_0_mint'])<_decode(pool['token_1_mint'])
            or pool['token_0_program'] != TOKEN_PROGRAM
            or pool['token_1_program'] != TOKEN_PROGRAM
            or pool['status'] & 4 or pool['status'] & ~7
            or pool['open_time']>observed_block_time_seconds
            or pool['lp_supply']==0):
        raise ValueError('cpmm_pool_mint_status_time_or_program_unqualified')
    authority,bump=find_program_address(
        (b'vault_and_lp_mint_auth_seed',),program_id=CPMM_PROGRAM)
    if pool['auth_bump']!=bump:
        raise ValueError('cpmm_pool_authority_bump_mismatch')
    config_address=pool['amm_config']
    config=_config(_account(accounts.get(config_address),name='config',
                    size=CONFIG_ACCOUNT_SIZE,discriminator=CONFIG_DISCRIMINATOR))
    canonical_config,config_bump=find_program_address(
        (b'amm_config',config['index'].to_bytes(2,'big')),program_id=CPMM_PROGRAM)
    if config['bump']!=config_bump or canonical_config!=config_address or config['disabled'] not in (0,1):
        raise ValueError('cpmm_noncanonical_fee_config')
    expected_vaults=tuple(find_program_address(
        (b'pool_vault',_decode(pool_address),_decode(pool['token_'+str(i)+'_mint'])),
        program_id=CPMM_PROGRAM)[0] for i in (0,1))
    if expected_vaults != (pool['token_0_vault'],pool['token_1_vault']):
        raise ValueError('cpmm_vaults_not_derived_from_actual_pool')
    observation=find_program_address(
        (b'observation',_decode(pool_address)),program_id=CPMM_PROGRAM)[0]
    if observation!=pool['observation_key']:
        raise ValueError('cpmm_observation_PDA_mismatch')
    canonical_lp=find_program_address(
        (b'pool_lp_mint',_decode(pool_address)),program_id=CPMM_PROGRAM)[0]
    if pool['lp_mint']!=canonical_lp:
        raise ValueError('cpmm_lp_mint_PDA_mismatch')
    raw_observation=_account(accounts.get(observation),name='observation',
             size=OBSERVATION_ACCOUNT_SIZE,discriminator=OBSERVATION_DISCRIMINATOR)
    # A newly initialized CPMM has pool_id set and initialized=false until its
    # first swap updates the oracle. Neither value means reserves are absent.
    if (raw_observation[8] not in (0,1) or struct.unpack_from('<H',raw_observation,9)[0]>=100
            or _key(raw_observation,11)!=pool_address):
        raise ValueError('cpmm_observation_content_identity_invalid')
    token_index=0 if pool['token_0_mint']==mint else 1
    input_vault=pool['token_'+str(token_index)+'_vault']
    output_vault=pool['token_'+str(1-token_index)+'_vault']
    base_ata=associated_token_address(wallet,mint)
    temp_wsol,seed=ephemeral_wsol_address(wallet,decision_id)
    required=(pool_address,config_address,observation,input_vault,output_vault,
              mint,SOL_MINT,wallet,base_ata,temp_wsol)
    if len(set(required))!=len(required) or set(accounts)!=set(required):
        raise ValueError('cpmm_same_bank_complete_nonaliased_accounts_required')
    if accounts[temp_wsol] is not None:
        raise ValueError('cpmm_ephemeral_WSOL_already_exists')
    wallet_account=accounts[wallet]
    if (type(wallet_account) is not dict or wallet_account.get('owner')!=SYSTEM_PROGRAM
            or wallet_account.get('executable') is not False
            or wallet_account.get('data') not in (['','base64'],('','base64'))):
        raise ValueError('cpmm_plain_system_wallet_required')
    wallet_balance=_uint(wallet_account.get('lamports'))
    base_mint,_=launchlab._mint_state(accounts[mint],'base_mint')
    sol_mint,_=launchlab._mint_state(accounts[SOL_MINT],'sol_mint')
    if (base_mint['decimals'] != pool['mint_'+str(token_index)+'_decimals']
            or sol_mint['decimals']!=9
            or pool['mint_'+str(1-token_index)+'_decimals']!=9
            or base_mint['mint_authority_present'] or base_mint['freeze_authority_present']
            or sol_mint['freeze_authority_present']):
        raise ValueError('cpmm_mint_decimals_or_authorities_unqualified')
    token_vaults=[]
    for idx in (0,1):
        key=pool['token_'+str(idx)+'_vault']
        state,_=launchlab._vault(accounts[key],'cpmm_vault_'+str(idx))
        if (state['mint'] != pool['token_'+str(idx)+'_mint']
                or state['authority']!=authority or state['state']!=1
                or state['delegate_present'] or state['close_authority_present']
                or state['is_native']!=(pool['token_'+str(idx)+'_mint']==SOL_MINT)):
            raise ValueError('cpmm_vault_identity_or_authority_invalid')
        token_vaults.append(state)
    user_state,_=launchlab._vault(accounts[base_ata],'user_base_ATA')
    if (user_state['mint']!=mint or user_state['authority']!=wallet
            or user_state['state']!=1 or user_state['is_native']
            or user_state['delegate_present'] or user_state['close_authority_present']
            or user_state['amount_atomic']<amount_in):
        raise ValueError('cpmm_user_inventory_unqualified')
    reserve=[]
    for i in (0,1):
        fees=(pool['protocol_fees_token_'+str(i)]
              +pool['fund_fees_token_'+str(i)]
              +pool['creator_fees_token_'+str(i)])
        if fees>=token_vaults[i]['amount_atomic']:
            raise ValueError('cpmm_effective_vault_insufficient_after_accrued_fees')
        reserve.append(token_vaults[i]['amount_atomic']-fees)
    creator_enabled=bool(pool['enable_creator_fee'])
    creator_input=creator_enabled and (pool['creator_fee_on']==0 or
                  pool['creator_fee_on']==(1 if token_index==0 else 2))
    quote=_quote_exact_input(amount=amount_in,input_reserve=reserve[token_index],
        output_reserve=reserve[1-token_index],config=config,
        creator_enabled=creator_enabled,creator_fee_on_input=creator_input)
    expected_output=quote['output']
    # Gross relative loss against the fee-free *pre-trade* spot; this binds
    # curve impact plus explicit LP/creator fee, conservatively.
    spot_numerator=amount_in*reserve[1-token_index]
    price_impact_numerator=spot_numerator-expected_output*reserve[token_index]
    if price_impact_numerator<0:
        raise ValueError('cpmm_curve_output_exceeds_fee_free_spot')
    price_impact_bps=(price_impact_numerator*10000+spot_numerator-1)//spot_numerator
    if price_impact_bps>max_price_impact_bps:
        raise ValueError('cpmm_price_impact_limit_exceeded')
    swap=build_cpmm_sell_instruction(
        wallet=wallet,mint=mint,pool=pool_address,amm_config_index=config['index'],
        token_0_mint=pool['token_0_mint'],token_1_mint=pool['token_1_mint'],
        input_vault=input_vault,output_vault=output_vault,
        observation_state=observation,amount_in_atomic=amount_in,
        expected_output_lamports=expected_output,
        slippage_bps=slippage_bps,decision_id=decision_id)
    priority=(compute_unit_limit*priority_fee_micro_lamports+999999)//1000000
    if priority>max_priority_fee_lamports:
        raise ValueError('cpmm_priority_fee_cap_exceeded')
    fee_upper=5000+priority
    if rent_exempt_lamports+fee_upper>wallet_balance:
        raise ValueError('cpmm_wallet_cannot_fund_rent_and_fee')
    funding=(struct.pack('<I',3)+_decode(wallet)+struct.pack('<Q',len(seed))
             +seed.encode()+struct.pack('<QQ',rent_exempt_lamports,165)
             +_decode(TOKEN_PROGRAM))
    instructions=(
        Instruction(COMPUTE_BUDGET_PROGRAM,(),b'\x02'+struct.pack('<I',compute_unit_limit)),
        Instruction(COMPUTE_BUDGET_PROGRAM,(),b'\x03'+struct.pack('<Q',priority_fee_micro_lamports)),
        Instruction(SYSTEM_PROGRAM,(
            AM(wallet,True,True),AM(temp_wsol,False,True),AM(wallet,True)),funding),
        Instruction(TOKEN_PROGRAM,(AM(temp_wsol,False,True),AM(SOL_MINT)),
                    b'\x12'+_decode(wallet)),
        swap.instruction,
        Instruction(TOKEN_PROGRAM,(AM(temp_wsol,False,True),
                        AM(wallet,False,True),AM(wallet,True)),b'\x09'),
    )
    prepared=compile_legacy(instructions,fee_payer=wallet,
         recent_blockhash=recent_blockhash,last_valid_block_height=last_valid_block_height)
    if prepared.required_signers!=(wallet,):
        raise ValueError('cpmm_unexpected_additional_signer')
    digest=hashlib.sha256(json.dumps(accounts,sort_keys=True,
         separators=(',',':'),allow_nan=False).encode()).hexdigest()
    fees=dict(quote,trade_fee_rate=config['trade_fee_rate'],
        creator_fee_rate=config['creator_fee_rate'] if creator_enabled else 0,
        creator_fee_on_input=creator_input,
        input_reserve=reserve[token_index],output_reserve=reserve[1-token_index],
        accrued_fees_deducted=True)
    fee_json=json.dumps(fees,sort_keys=True,separators=(',',':'))
    intent_hash=hashlib.sha256(json.dumps(dict(
        message_sha256=hashlib.sha256(prepared.message).hexdigest(),
        source_slot=context_slot,source_account_digest=digest,
        user=wallet,mint=mint,pool=pool_address,
        decision_id=decision_id,amount_in=amount_in,
        expected_output=expected_output,minimum_out=swap.minimum_out_lamports),
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return PreparedCpmmExit(
        prepared,'SELL',amount_in,swap.minimum_out_lamports,
        expected_output,price_impact_bps,max_price_impact_bps,
        mint,pool_address,wallet,context_slot,available_at_ms,
        decision_at_ms,intent_hash,base_ata,temp_wsol,
        fee_upper,rent_exempt_lamports,user_state['amount_atomic'],
        wallet_balance,digest,fee_json,
        tuple(sorted(SOURCE_PIN.items()))+(
            ('cpmm_source_revision',CPMM_SOURCE_REVISION),),request_json)


def validate_cpmm_exit(order):
    if type(order) is not PreparedCpmmExit:
        raise ValueError('CPMM_builder_order_required')
    try:
        rebuilt=build_cpmm_exit(**json.loads(order.rebuild_request_json))
    except (TypeError,ValueError,KeyError,OverflowError,
            launchlab.SnapshotEvidenceError):
        raise ValueError('CPMM_exit_route_rebuild_failed') from None
    if order != rebuilt or order.live_execution_enabled or order.migration_provenance_verified:
        raise ValueError('CPMM_order_identity_or_authorization_modified')
    return rebuilt
