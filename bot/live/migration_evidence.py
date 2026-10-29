"""Check the pinned LaunchLab migrate_to_cpswap on-chain transaction anatomy.

Historical getTransaction JSON is untrusted until acquired and archived through
an independently authenticated RPC context. This validator proves structural
linkage among the original LaunchLab pool, mint, and the actual CPMM pool,
including canonical downstream vaults/LP/authority. A CPMM pool_state may be a
random signer address, not a canonical pool PDA; never guess its address.

No RPC, wallet, signature, send or LIVE arm is performed by this module.
"""
import hashlib
import json

from bot.p3.certification import PROGRAM, _decode, find_program_address
from bot.p3.platform_admin_history import _b58_bytes, _signature
from bot.p3.quotes import SOL_MINT
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.migration_rpc_json import normalized_compiled_transaction


MIGRATE_TO_CPSWAP_DISC=bytes((136,92,200,103,28,218,144,140))
REQUIRED_ACCOUNT_COUNT=28
PINNED_IDL_REVISION='e7e0c96fe77bcf6a020b84a44c47a722aac8e359'
ROLES=(
    'payer','base_mint','quote_mint','platform_config','cpswap_program',
    'cpswap_pool','cpswap_authority','cpswap_lp_mint',
    'cpswap_base_vault','cpswap_quote_vault','cpswap_config',
    'cpswap_create_pool_fee','cpswap_observation','lock_program',
    'lock_authority','lock_lp_vault','authority','pool_state',
    'global_config','base_vault','quote_vault','pool_lp_token',
    'base_token_program','quote_token_program','associated_token_program',
    'system_program','rent_program','metadata_program',
)


def validate_migrate_to_cpswap_transaction(tx, *, signature, mint, launchlab_pool,
                                           cpmm_pool, observed_at_slot):
    """Return structural claim with evidence hash, never live permission."""
    base=dict(schema='rugger-cpmm-migration-structural-v1',
        status='UNKNOWN',reason=None,source_idl_commit=PINNED_IDL_REVISION,
        launchlab_pool=launchlab_pool,cpmm_pool=cpmm_pool,mint=mint,
        migration_signature=None,migration_slot=None,
        migration_instruction_matches=False,
        source_transport_authenticated=False,
        cryptographic_signatures_verified=False,
        cpmm_pool_state_account_decoded=False,
        live_execution_authorized=False)

    def no(reason):
        return dict(base,reason=reason)

    try:
        for addr in (mint,launchlab_pool,cpmm_pool):
            _decode(addr)
        _signature(signature)
        if (type(observed_at_slot) is not int or observed_at_slot<=0
                or type(tx) is not dict):
            return no('transaction_and_observation_slot_required')
        raw_transaction_sha256=hashlib.sha256(json.dumps(
            tx,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        ).hexdigest()
        tx=normalized_compiled_transaction(tx)
        slot=tx['slot']
        payload=tx['transaction']
        meta=tx['meta']
        keys=payload['message']['accountKeys']
        instructions=payload['message']['instructions']
        signatures=payload['signatures']
        if (type(slot) is not int or not 0<slot<=observed_at_slot
                or type(meta) is not dict or meta.get('err') is not None
                or 'err' not in meta
                or type(keys) is not list or type(instructions) is not list
                or type(signatures) is not list or len(signatures)<1
                or signatures[0]!=signature):
            return no('successful_historical_signature_and_slot_required')
        if any(_signature(s)!=s for s in signatures):
            return no('invalid_transaction_signature_encodings')
        keys_by_index={}
        for i,k in enumerate(keys):
            if type(k) is not dict or type(k.get('pubkey')) is not str:
                return no('json_parsed_account_keys_required')
            _decode(k['pubkey'])
            if type(k.get('signer')) is not bool or type(k.get('writable')) is not bool:
                return no('account_signer_and_writable_flags_required')
            keys_by_index[i]=k
        if len({k['pubkey'] for k in keys_by_index.values()})!=len(keys):
            return no('duplicate_transaction_keys')
        n=sum(k['signer'] for k in keys)
        header=payload['message'].get('header')
        if (n!=len(signatures) or n<=0 or keys[0]['signer'] is not True
                or any(k['signer']!=(i<n) for i,k in enumerate(keys))
                or (header is not None and header.get('numRequiredSignatures')!=n)):
            return no('transaction_signer_vector_invalid')
        for ix in instructions:
            if type(ix) is not dict:
                continue
            idx=ix.get('programIdIndex')
            if type(idx) is not int or idx not in keys_by_index:
                continue
            if keys_by_index[idx]['pubkey']!=PROGRAM:
                continue
            data=ix.get('data')
            if type(data) is not str:
                continue
            try:
                raw=_b58_bytes(data)
            except (ValueError,OverflowError):
                continue
            if raw!=MIGRATE_TO_CPSWAP_DISC:
                continue
            references=ix.get('accounts')
            if type(references) is not list or len(references)!=REQUIRED_ACCOUNT_COUNT:
                continue
            if any(type(i) is not int or i not in keys_by_index for i in references):
                continue
            resolved=[keys_by_index[i]['pubkey'] for i in references]
            if (resolved[0]!=keys[0]['pubkey']
                    or resolved[1]!=mint
                    or resolved[2]!=SOL_MINT
                    or resolved[4]!=CPMM_PROGRAM
                    or resolved[5]!=cpmm_pool
                    or resolved[17]!=launchlab_pool):
                continue
            if keys_by_index[references[0]]['signer'] is not True:
                continue
            if any(keys_by_index[references[i]]['writable'] is not True
                   for i in (5,7,8,9,12,17)):
                continue
            expected=dict(
                cpswap_authority=find_program_address(
                    (b'vault_and_lp_mint_auth_seed',),
                    program_id=CPMM_PROGRAM)[0],
                cpswap_lp_mint=find_program_address(
                    (b'pool_lp_mint',_decode(cpmm_pool)),
                    program_id=CPMM_PROGRAM)[0],
                cpswap_base_vault=find_program_address(
                    (b'pool_vault',_decode(cpmm_pool),_decode(mint)),
                    program_id=CPMM_PROGRAM)[0],
                cpswap_quote_vault=find_program_address(
                    (b'pool_vault',_decode(cpmm_pool),_decode(SOL_MINT)),
                    program_id=CPMM_PROGRAM)[0],
                cpswap_observation=find_program_address(
                    (b'observation',_decode(cpmm_pool)),
                    program_id=CPMM_PROGRAM)[0],
            )
            named=dict(zip(ROLES,resolved,strict=True))
            if any(named[k]!=v for k,v in expected.items()):
                continue
            return dict(base,status='STRUCTURAL_MIGRATION_RECEIPT',
                reason=None,migration_signature=signature,migration_slot=slot,
                migration_instruction_matches=True,
                normalized_role_sha256=hashlib.sha256(
                    json.dumps(named,sort_keys=True,separators=(',',':')).encode()
                ).hexdigest(),
                retained_transaction_sha256=raw_transaction_sha256,
                cpswap_config=named['cpswap_config'],
                source_transport_authenticated=False,
                cryptographic_signatures_verified=False,
                cpmm_pool_state_account_decoded=False,
                live_execution_authorized=False)
        return no('no_exact_pinned_migrate_to_cpswap_instruction_and_PDA_graph')
    except (KeyError,TypeError,ValueError,OverflowError):
        return no('malformed_historical_migration_transaction')
