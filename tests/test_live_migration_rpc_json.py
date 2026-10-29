"""Real RPC getTransaction JSON uses compact account-key strings and header bits.

These cases are synthetic, but they exercise the exact API JSON encoding for
legacy and version 0/ALT address lookups without mocking the decoder itself.
Never infer RPC authenticity or an Ed25519 signature from successful parsing.
"""
from copy import deepcopy

import pytest

from bot.p3.certification import _encode
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.migration_evidence import validate_migrate_to_cpswap_transaction
from test_live_migration_evidence import migration,SIG,MINT,OLD,NEW


def _compiled(tx, *, loaded_role=None):
    clone=deepcopy(tx)
    body=clone['transaction']['message']
    source=body['accountKeys']
    ix=body['instructions'][0]
    names=[x['pubkey'] for x in source]
    roles=[names[i] for i in ix['accounts']]
    program=names[ix['programIdIndex']]
    loaded=None
    if loaded_role is not None:
        loaded=roles[loaded_role]
        assert source[names.index(loaded)]['writable']
    reordered=sorted([x for x in source if x['pubkey']!=loaded],
        key=lambda k: (not k['signer'],not k['writable']))
    readable=[k for k in reordered if k['signer'] and not k['writable']]
    unsigned_ro=[k for k in reordered if not k['signer'] and not k['writable']]
    body['header']={
        'numRequiredSignatures':sum(k['signer'] for k in reordered),
        'numReadonlySignedAccounts':len(readable),
        'numReadonlyUnsignedAccounts':len(unsigned_ro),
    }
    static=[k['pubkey'] for k in reordered]
    keys=static + ([loaded] if loaded else [])
    ix['accounts']=[keys.index(key) for key in roles]
    ix['programIdIndex']=keys.index(program)
    body['accountKeys']=static
    if loaded:
        clone['version']=0
        body['addressTableLookups']=[dict(
            accountKey=_encode(bytes([98])*32),
            writableIndexes=[0],readonlyIndexes=[])]
        clone['meta']['loadedAddresses']=dict(writable=[loaded],readonly=[])
    else:
        clone['version']='legacy'
    return clone


def _validate(tx):
    return validate_migrate_to_cpswap_transaction(tx,signature=SIG,
        mint=MINT,launchlab_pool=OLD,cpmm_pool=NEW,observed_at_slot=101)


def test_rpc_raw_legacy_keys_recover_writable_signer_and_exact_migration_roles():
    tx=_compiled(migration())
    original=deepcopy(tx)
    result=_validate(tx)
    assert result['status']=='STRUCTURAL_MIGRATION_RECEIPT',result
    assert tx==original
    normalized=normalized_compiled_transaction(tx)
    ix=normalized['transaction']['message']['instructions'][0]
    keys=normalized['transaction']['message']['accountKeys']
    assert keys[0]['signer'] and keys[0]['writable']
    assert keys[ix['accounts'][5]]['writable']
    assert keys[ix['accounts'][17]]['writable']
    assert all(isinstance(k,dict) for k in keys)
    assert result['source_transport_authenticated'] is False
    assert result['live_execution_authorized'] is False


def test_rpc_v0_migrated_pool_in_loaded_writable_alt_is_supported_by_header_rules():
    tx=_compiled(migration(),loaded_role=8)
    normalized=normalized_compiled_transaction(tx)
    keys=normalized['transaction']['message']['accountKeys']
    ix=normalized['transaction']['message']['instructions'][0]
    migrated_vault=keys[ix['accounts'][8]]
    assert migrated_vault['source']=='lookupTable'
    assert migrated_vault['writable'] and not migrated_vault['signer']
    assert _validate(tx)['status']=='STRUCTURAL_MIGRATION_RECEIPT'


@pytest.mark.parametrize('change',[
    'unknown_version','readonly_header_for_required_pool','missing_header',
    'malformed_signature_count','mixed_key_encodings','duplicate_static_key',
    'lookup_missing_meta','lookup_wrong_count','lookup_duplicate_key',
    'lookup_loaded_readonly_instead_of_writable',
    'legacy_with_v0_lookup',
])
def test_forged_compiled_RPC_header_or_lookup_permissions_fail_closed(change):
    tx=_compiled(migration(),loaded_role=8)
    message=tx['transaction']['message']
    meta=tx['meta']
    if change=='unknown_version':tx['version']=1
    if change=='readonly_header_for_required_pool':
        message['header']['numReadonlyUnsignedAccounts']+=1
    if change=='missing_header':del message['header']
    if change=='malformed_signature_count':
        message['header']['numRequiredSignatures']=2
    if change=='mixed_key_encodings':
        message['accountKeys'][2]=dict(pubkey=message['accountKeys'][2])
    if change=='duplicate_static_key':
        message['accountKeys'][2]=message['accountKeys'][3]
    if change=='lookup_missing_meta':del meta['loadedAddresses']
    if change=='lookup_wrong_count':message['addressTableLookups'][0]['writableIndexes']=[]
    if change=='lookup_duplicate_key':
        meta['loadedAddresses']['writable'][0]=message['accountKeys'][3]
    if change=='lookup_loaded_readonly_instead_of_writable':
        meta['loadedAddresses']['writable']=[]
        meta['loadedAddresses']['readonly']=list(
            [_compiled(migration(),loaded_role=8)['meta']['loadedAddresses']['writable'][0]])
        message['addressTableLookups'][0]['writableIndexes']=[]
        message['addressTableLookups'][0]['readonlyIndexes']=[0]
    if change=='legacy_with_v0_lookup':tx['version']='legacy'
    assert _validate(tx)['status']=='UNKNOWN',change


def test_original_jsonParsed_fixture_unchanged():
    tx=migration()
    before=deepcopy(tx)
    assert _validate(tx)['status']=='STRUCTURAL_MIGRATION_RECEIPT'
    assert tx==before
