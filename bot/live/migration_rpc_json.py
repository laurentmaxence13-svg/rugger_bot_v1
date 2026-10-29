"""Normalize exact Solana getTransaction(encoding="json") account-key vectors.

Legacy transaction.message.accountKeys are base58 strings, not jsonParsed
entries with signer/writable flags. Derive access bits from the actual
message.header and, for v0, meta.loadedAddresses. Validate the lookup counts
before any migration instruction can use an address. The original response is
NEVER mutated. Does not authenticate the RPC or verify signature bytes.

Do not use this parser to authorize a financial transaction by itself.
"""
from copy import deepcopy

from bot.p3.certification import _decode


def _key(value):
    if type(value) is not str:
        raise ValueError('compiled_account_key_not_base58_string')
    _decode(value)
    return value


def normalized_compiled_transaction(tx):
    """Return structural jsonParsed-like key flags from canonical compiled JSON."""
    if type(tx) is not dict:
        raise ValueError('raw_compiled_transaction_required')
    try:
        body=tx['transaction']
        message=body['message']
        keys=message['accountKeys']
        header=message['header']
        meta=tx['meta']
        signatures=body['signatures']
    except (KeyError,TypeError):
        raise ValueError('raw_compiled_message_header_required') from None
    if (type(keys) is not list or not keys or len(keys)>256
            or type(meta) is not dict or type(signatures) is not list
            or type(header) is not dict):
        raise ValueError('raw_compiled_message_structure_invalid')
    # Already-jsonParsed account dictionaries must be handled by the
    # main migration validator; no coercion or source-flag reinterpretation.
    if all(type(k) is dict for k in keys):
        return deepcopy(tx)
    if any(type(k) is not str for k in keys):
        raise ValueError('mixed_jsonParsed_and_compiled_account_keys_forbidden')
    counts=tuple(header.get(k) for k in (
        'numRequiredSignatures','numReadonlySignedAccounts',
        'numReadonlyUnsignedAccounts'))
    if any(type(n) is not int or n<0 or n>255 for n in counts):
        raise ValueError('raw_legacy_header_counts_invalid')
    required,readonly_signed,readonly_unsigned=counts
    n=len(keys)
    if (not 1<=required<=n or readonly_signed>=required
            or readonly_unsigned>n-required or len(signatures)!=required):
        raise ValueError('compiled_signer_or_readonly_header_inconsistent')
    static=[_key(k) for k in keys]
    if len(set(static))!=len(static):
        raise ValueError('duplicate_static_message_keys')
    v0=tx.get('version', 'legacy')
    if v0 not in ('legacy',0):
        raise ValueError('unsupported_transaction_message_version')
    lookups=message.get('addressTableLookups',[])
    if type(lookups) is not list:
        raise ValueError('malformed_address_lookup_table_refs')
    if v0=='legacy' and lookups:
        raise ValueError('legacy_message_cannot_have_lookups')
    if v0==0 and lookups:
        if type(meta.get('loadedAddresses')) is not dict:
            raise ValueError('lookup_keys_must_be_attested_by_RPC_meta')
        loaded=meta['loadedAddresses']
        writable=loaded.get('writable')
        readonly=loaded.get('readonly')
        if type(writable) is not list or type(readonly) is not list:
            raise ValueError('lookup_key_permission_vector_required')
        wanted_w=wanted_r=0
        for info in lookups:
            if type(info) is not dict:
                raise ValueError('malformed_lookup_reference')
            table=_key(info.get('accountKey'))
            wi,ri=info.get('writableIndexes'),info.get('readonlyIndexes')
            if (type(wi) is not list or type(ri) is not list
                    or any(type(i) is not int or not 0<=i<256 for i in wi+ri)
                    or len(set(wi+ri))!=len(wi+ri)):
                raise ValueError('lookup_indices_invalid_or_duplicated')
            wanted_w+=len(wi)
            wanted_r+=len(ri)
        if wanted_w!=len(writable) or wanted_r!=len(readonly):
            raise ValueError('RPC_loaded_address_count_disagrees_with_message')
    else:
        loaded=meta.get('loadedAddresses',{'writable':[],'readonly':[]})
        if (type(loaded) is not dict or loaded.get('writable')!=[]
                or loaded.get('readonly')!=[]):
            raise ValueError('unexpected_loaded_accounts_without_address_lookups')
        writable,readonly=[],[]
    loaded_w=[_key(v) for v in writable]
    loaded_r=[_key(v) for v in readonly]
    if len(set(static+loaded_w+loaded_r))!=len(static)+len(loaded_w)+len(loaded_r):
        raise ValueError('duplicate_static_or_loaded_message_keys')
    if n+len(loaded_w)+len(loaded_r)>256:
        raise ValueError('compiled_message_account_index_overflow')
    result=[]
    for i,key in enumerate(static):
        signer=i<required
        writable_flag=(i<required-readonly_signed if signer
                       else i<n-readonly_unsigned)
        result.append(dict(pubkey=key,signer=signer,writable=writable_flag,
                           source='transaction'))
    result.extend(dict(pubkey=key,signer=False,writable=True,
                       source='lookupTable') for key in loaded_w)
    result.extend(dict(pubkey=key,signer=False,writable=False,
                       source='lookupTable') for key in loaded_r)
    out=deepcopy(tx)
    out['transaction']['message']['accountKeys']=result
    return out
