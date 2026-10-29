"""Verify a historical Raydium LaunchLab platform creation transaction offline.

The pinned Raydium IDL defines CreatePlatformConfig account 0 as the signing
platform_admin, account 3 as platform_config, and the Anchor instruction
discriminator below. Certify the canonical PDA only after verifying that a
retained successful on-chain transaction contains this exact instruction.

The transaction itself MUST have independently retained RPC provenance, slot and
signature. This module performs no RPC call and does not change STRICT checks;
it returns a corroborated historical public admin seed for later integration.
"""

from bot.p3.certification import PROGRAM, _decode, find_program_address

# Raydium IDL commit e7e0c96fe77bcf6a020b84a44c47a722aac8e359
_CREATE_PLATFORM_CONFIG_DISC = bytes([176,90,196,175,253,113,220,20])
_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def _b58_bytes(value):
    if type(value) is not str or not value or len(value)>4096:
        raise ValueError('invalid_instruction_data')
    number=0
    for char in value:
        number=number*58+_BASE58.index(char)
    prefix=len(value)-len(value.lstrip('1'))
    return bytes(prefix)+number.to_bytes((number.bit_length()+7)//8,'big')


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
              instruction_idl_pin='e7e0c96fe77bcf6a020b84a44c47a722aac8e359')

    def reject(why):
        return {**base,'reason':why}

    if (type(tx) is not dict or type(signature) is not str or not signature
            or type(snapshot_context_slot) is not int or snapshot_context_slot<=0):
        return reject('retained_tx_signature_and_snapshot_slot_required')
    try:
        _decode(platform_config)
        slot=tx.get('slot')
        meta=tx['meta']
        txbody=tx['transaction']
        message=txbody['message']
        keys=message['accountKeys']
        instructions=message['instructions']
        signatures=txbody['signatures']
        if (type(slot) is not int or not 0 < slot <= snapshot_context_slot
                or type(meta) is not dict or 'err' not in meta or meta['err'] is not None
                or type(keys) is not list or type(instructions) is not list
                or type(signatures) is not list or not signatures or signatures[0]!=signature):
            return reject('transaction_source_or_success_not_verified')
        keyed={}
        for i,item in enumerate(keys):
            if type(item) is not dict or type(item.get('pubkey')) is not str:
                return reject('json_parsed_account_key_signer_flags_required')
            keyed[i]=item
        if len({k['pubkey'] for k in keyed.values()}) != len(keys):
            return reject('duplicate_transaction_account_keys')
        for item in instructions:
            if type(item) is not dict:
                continue
            program=item.get('programId')
            if program is None:
                index=item.get('programIdIndex')
                if type(index) is not int or index not in keyed:
                    continue
                program=keyed[index]['pubkey']
            if program!=PROGRAM:
                continue
            raw=item.get('data')
            if type(raw) is list and len(raw)==2 and raw[1]=='base58':
                raw=raw[0]
            if type(raw) is not str:
                continue
            try:
                data=_b58_bytes(raw)
            except (ValueError,OverflowError):
                continue
            if not data.startswith(_CREATE_PLATFORM_CONFIG_DISC):
                continue
            accounts=item.get('accounts')
            if type(accounts) is not list or len(accounts)<4:
                continue
            def pub(ref):
                if type(ref) is int and ref in keyed:
                    return keyed[ref]['pubkey']
                if type(ref) is str and ref in {x['pubkey'] for x in keyed.values()}:
                    return ref
                raise ValueError('missing_account_reference')
            try:
                admin,pda=pub(accounts[0]),pub(accounts[3])
                if (pda!=platform_config
                        or not any(k['pubkey']==admin and k.get('signer') is True
                                   for k in keyed.values())):
                    continue
                derived,bump=find_program_address((b'platform_config',_decode(admin)))
            except (ValueError,KeyError):
                continue
            if derived == platform_config:
                return {**base,'status':'PASS','reason':None,
                        'historical_platform_admin':admin,
                        'creation_slot':slot,'historical_seed_certified':True,
                        'pda_bump':bump,'transaction_signature':signature,
                        'instruction_discriminator_hex':_CREATE_PLATFORM_CONFIG_DISC.hex(),
                        'signature_matches_retained_tx':True,
                        'platform_admin_was_transaction_signer':True,
                        'not_a_current_admin_authorization':True}
        return reject('no_matching_signed_platform_create_instruction_with_canonical_PDA')
    except (ValueError,KeyError,TypeError,OverflowError):
        return reject('malformed_historical_transaction')
