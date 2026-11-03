"""Verify a historical Raydium LaunchLab platform creation transaction offline.

The pinned Raydium IDL defines CreatePlatformConfig account 0 as the signing
platform_admin, account 3 as platform_config, and the Anchor instruction
discriminator below. Certify the canonical PDA only after verifying that a
retained successful on-chain transaction contains this exact instruction.

The transaction itself MUST have independently retained RPC provenance, slot and
signature. This module performs no RPC call and does not change STRICT checks;
it returns a corroborated historical public admin seed for later integration.
"""

import hashlib
import json
import struct
from copy import deepcopy

from bot.p3.certification import PROGRAM, SOURCE_PINS, _decode, find_program_address

# Raydium IDL commit e7e0c96fe77bcf6a020b84a44c47a722aac8e359
_CREATE_PLATFORM_CONFIG_DISC = bytes([176,90,196,175,253,113,220,20])
_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_SYSTEM_PROGRAM = '11111111111111111111111111111111'


def _signature(value):
    """Validate a transaction identifier's encoding, never assert its signature."""
    if type(value) is not str or not 64 <= len(value) <= 88:
        raise ValueError('invalid_transaction_signature_encoding')
    decoded=_b58_bytes(value)
    if len(decoded)!=64 or not any(decoded):
        raise ValueError('invalid_transaction_signature_encoding')
    return value


def _b58_bytes(value):
    if type(value) is not str or not value or len(value)>4096:
        raise ValueError('invalid_instruction_data')
    number=0
    for char in value:
        number=number*58+_BASE58.index(char)
    prefix=len(value)-len(value.lstrip('1'))
    return bytes(prefix)+number.to_bytes((number.bit_length()+7)//8,'big')


def _create_params(data):
    """Decode the pinned PlatformParams Borsh structure without echoing strings.

    MigrateNftInfo:3*u64, fee_rate:u64, 3UTF8strings, creator_fee_rate:u64,
    platform_vesting_scale:u64. A discriminator plus arbitrary bytes is not a
    create instruction. The minimum is68bytes including its8-byte discriminator.
    """
    if not data.startswith(_CREATE_PLATFORM_CONFIG_DISC) or len(data)<68:
        raise ValueError('pinned_platform_params_missing_or_truncated')
    offset=40
    for limit in (64,256,256):
        if offset+4>len(data):
            raise ValueError('pinned_platform_params_missing_or_truncated')
        size=struct.unpack_from('<I',data,offset)[0]
        offset+=4
        if size>limit or offset+size>len(data):
            raise ValueError('pinned_platform_params_missing_or_truncated')
        data[offset:offset+size].decode('utf-8')
        offset+=size
    if offset+16!=len(data):
        raise ValueError('pinned_platform_params_length_mismatch')
    return hashlib.sha256(data).hexdigest()


def verify_historical_platform_creation(tx, *, platform_config, signature,
                                        snapshot_context_slot):
    """Verify original admin signer and canonical PDA; do not promote on error.

    `tx` is the direct getTransaction response; the caller must verify the
    retained network receipt, event hash chain and claimed signature/slot.
    An IDL-confirmed instruction is stronger than guessing from fee wallets.
    """
    base=dict(schema='p3-historical-platform-creation-evidence-v1',
              status='UNKNOWN',reason=None,platform_config=platform_config,
              historical_platform_admin=None,creation_slot=None,
              historical_seed_certified=False,strict_snapshot_identity_promoted=False,
              current_execution_or_trading_permission=False,
              source_tx_provenance_certified_by_this_function=False,
              cryptographic_signature_verified=False,
              signature_verification_scope='identifier_and_RPC_signer_flags_only; serialized_message_not_provided',
              instruction_idl_pin='e7e0c96fe77bcf6a020b84a44c47a722aac8e359')

    def reject(why):
        return {**base,'reason':why}

    if (type(tx) is not dict or type(signature) is not str or not signature
            or type(snapshot_context_slot) is not int or snapshot_context_slot<=0):
        return reject('retained_tx_signature_and_snapshot_slot_required')
    try:
        _decode(platform_config)
        _signature(signature)
        slot=tx.get('slot')
        meta=tx['meta']
        txbody=tx['transaction']
        message=txbody['message']
        keys=message['accountKeys']
        instructions=message['instructions']
        signatures=txbody['signatures']
        block_time=tx.get('blockTime')
        if (type(slot) is not int or not 0 < slot <= snapshot_context_slot
                or type(meta) is not dict or 'err' not in meta or meta['err'] is not None
                or type(keys) is not list or type(instructions) is not list
                or type(signatures) is not list or not signatures or signatures[0]!=signature
                or (block_time is not None and (type(block_time) is not int or block_time<0))):
            return reject('transaction_source_or_success_not_verified')
        if any(_signature(value)!=value for value in signatures):
            return reject('transaction_signature_encoding_invalid')
        keyed={}
        for i,item in enumerate(keys):
            if (type(item) is not dict or type(item.get('pubkey')) is not str
                    or type(item.get('signer')) is not bool):
                return reject('json_parsed_account_key_signer_flags_required')
            _decode(item['pubkey'])
            if item['signer'] and item.get('source')=='lookupTable':
                return reject('lookup_table_account_cannot_be_transaction_signer')
            keyed[i]=item
        if len({k['pubkey'] for k in keyed.values()}) != len(keys):
            return reject('duplicate_transaction_account_keys')
        signer_count=sum(item['signer'] for item in keys)
        if (not keys or keys[0]['signer'] is not True or keys[0].get('writable') is not True
                or signer_count!=len(signatures)
                or any(item['signer']!=(i<signer_count) for i,item in enumerate(keys))):
            return reject('transaction_signature_or_signer_count_inconsistent')
        header=message.get('header')
        if header is not None and (type(header) is not dict
                or type(header.get('numRequiredSignatures')) is not int
                or header['numRequiredSignatures']!=signer_count):
            return reject('message_header_signature_count_inconsistent')
        pubkeys={item['pubkey']:item for item in keys}
        for item in instructions:
            if type(item) is not dict:
                continue
            program=item.get('programId')
            if 'programIdIndex' in item:
                index=item.get('programIdIndex')
                if type(index) is not int or index not in keyed:
                    return reject('invalid_program_account_reference')
                indexed=keyed[index]['pubkey']
                if program is not None and program!=indexed:
                    return reject('conflicting_program_account_references')
                program=indexed
            if program!=PROGRAM:
                continue
            if program not in pubkeys:
                return reject('program_account_missing_from_message')
            raw=item.get('data')
            if type(raw) is list and len(raw)==2 and raw[1]=='base58':
                raw=raw[0]
            if type(raw) is not str:
                continue
            try:
                data=_b58_bytes(raw)
                instruction_sha256=_create_params(data)
            except (ValueError,OverflowError,UnicodeError):
                continue
            accounts=item.get('accounts')
            if type(accounts) is not list or len(accounts)<8:
                continue
            def pub(ref):
                if type(ref) is int and ref in keyed:
                    return keyed[ref]['pubkey']
                if type(ref) is str and ref in pubkeys:
                    return ref
                raise ValueError('missing_account_reference')
            try:
                resolved=[pub(ref) for ref in accounts]
                admin,pda=resolved[0],resolved[3]
                if (pda!=platform_config
                        or resolved[5]!=_SYSTEM_PROGRAM
                        or pubkeys[admin]['signer'] is not True
                        or pubkeys[admin].get('writable') is not True
                        or pubkeys[pda].get('writable') is not True):
                    continue
                derived,bump=find_program_address((b'platform_config',_decode(admin)))
            except (ValueError,KeyError):
                continue
            if derived == platform_config:
                return {**base,'status':'PASS','reason':None,
                        'historical_platform_admin':admin,
                        'creation_slot':slot,'historical_seed_certified':True,
                        'creation_time_ms':None if block_time is None else block_time*1000,
                        'pda_bump':bump,'transaction_signature':signature,
                        'instruction_discriminator_hex':_CREATE_PLATFORM_CONFIG_DISC.hex(),
                        'instruction_data_sha256':instruction_sha256,
                        'pinned_instruction_layout_verified':True,
                        'pinned_required_account_roles_verified':True,
                        'signature_matches_retained_tx':True,
                        'platform_admin_was_transaction_signer':True,
                        'not_a_current_admin_authorization':True}
        return reject('no_matching_signed_platform_create_instruction_with_canonical_PDA')
    except (ValueError,KeyError,TypeError,OverflowError):
        return reject('malformed_historical_transaction')


def refine_snapshot_with_platform_history(analysis, tx, *, signature,
                                          proof_available_at_ms, decision_at_ms):
    """Refine one missing public PDA seed only with a before-decision proof.

    The caller must independently retain and verify the RPC request/transaction
    envelope and hash chain. This function proves mathematical seed equality,
    signer/instruction binding and as-of availability, not transport authenticity
    or an Ed25519 signature over unavailable serialized transaction bytes.

    Other unknowns/failures, source account hashes, fees, quantities, safety and
    economic flags remain unchanged. A late/invalid proof returns an unchanged
    deep copy, never a retrospective upgrade of an earlier decision.
    """
    result=deepcopy(analysis)
    try:
        if (type(analysis) is not dict or analysis.get('evidence_profile')!='published_metadata_v1'
                or any(type(v) is not int or v<0 for v in (proof_available_at_ms,decision_at_ms))
                or proof_available_at_ms>decision_at_ms or analysis.get('risk_flags')!=[]):
            return result
        facts=analysis['facts'];identity=facts['identity_certification']
        if (facts.get('account_context_basis')!='caller_supplied_single_getMultipleAccounts_response'
                or facts.get('supply_consistency',{}).get('matches') is not True
                or identity.get('source_pins')!=SOURCE_PINS
                or identity.get('program_derived_addresses_verified') is not False
                or identity.get('account_discriminators_verified') is not True):
            return result
        checks=identity['checks']
        if type(checks) is not list or any(type(c) is not dict for c in checks):
            return result
        by_name={c.get('name'):c for c in checks}
        required={'pool_pda','vault_a_pda','vault_b_pda','config_pda','authority_pda','platform_pda',
            'pool_discriminator','config_discriminator','platform_discriminator',
            'input_graph','pool_layout_owner','config_layout_owner','platform_layout_owner',
            'pool_link_config','pool_link_platform','pool_link_mint_a','pool_link_mint_b',
            'pool_link_vault_a','pool_link_vault_b','mint_a_program_owner','mint_b_program_owner',
            'vault_a_layout_owner','vault_b_layout_owner','vault_a_mint_link','vault_b_mint_link',
            'config_quote_link','platform_empty_curve_params'}
        if len(by_name)!=len(checks) or not required<=by_name.keys():
            return result
        platform=by_name['platform_pda']
        reason='original_platform_admin_seed_not_retained'
        if (platform.get('status')!='UNKNOWN' or platform.get('reason')!=reason
                or identity.get('blocking_reasons')!=[reason]
                or any(c.get('status')!='PASS' for c in checks if c.get('name')!='platform_pda')):
            return result
        address=facts['addresses']['platform']
        if facts['pool']['platform']!=address:
            return result
        proof=verify_historical_platform_creation(tx,platform_config=address,
            signature=signature,snapshot_context_slot=analysis['context_slot'])
        if (proof['status']!='PASS' or not proof['historical_seed_certified']
                or (proof.get('creation_time_ms') is not None
                    and proof['creation_time_ms']>proof_available_at_ms)):
            return result
        refined=result['facts']['identity_certification']
        target=next(c for c in refined['checks'] if c['name']=='platform_pda')
        previous=deepcopy(target)
        target.clear()
        target.update(name='platform_pda',status='PASS',reason=None,derived_address=address,bump=proof['pda_bump'],
            verified_historical_admin=proof['historical_platform_admin'],
            verification_basis='canonical_PDA_from_pinned_create_instruction_transaction_signer',
            historical_signature=signature,creation_slot=proof['creation_slot'],
            proof_available_at_ms=proof_available_at_ms,previous_candidate_check=previous)
        refined['blocking_reasons']=[]
        refined['program_derived_addresses_verified']=True
        refined['program_derived_addresses_partially_verified']=True
        result['facts']['program_derived_addresses_verified']=True
        result['blocking_reasons']=[item for item in result.get('blocking_reasons',[]) if item!=reason]
        result['facts']['historical_platform_refinement']=dict(
            schema='p3-asof-platform-history-refinement-v1',proof_available_at_ms=proof_available_at_ms,
            decision_at_ms=decision_at_ms,creation_slot=proof['creation_slot'],
            transaction_signature=signature,platform_config=address,
            historical_platform_admin=proof['historical_platform_admin'],
            transaction_sha256=hashlib.sha256(json.dumps(tx,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            cryptographic_signature_verified=False,source_provenance_certified_by_helper=False,
            public_seed_PDA_mathematical_match=True,execution_verified=False,trade_allowed=False)
        return result
    except (ValueError,KeyError,TypeError,OverflowError):
        return deepcopy(analysis)
