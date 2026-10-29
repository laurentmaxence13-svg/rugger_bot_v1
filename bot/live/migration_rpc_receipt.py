"""Bounded, read-only finalized migration receipt from the configured Solana RPC.

Use the real SolanaRpc.get_transaction() transport, whose request uses
getTransaction encoding=json, commitment=finalized and maxSupportedVersion=0.
The validator handles legacy and v0 message key layouts and compares the
exact LaunchLab migrate_to_cpswap account graph. This service performs no
transaction construction, signature, wallet access or send.

A single trusted-TLS RPC endpoint plus matching genesis and configured endpoint
is evidence of what that RPC *returned*, not independently proven block
consensus, cryptographic signature bytes, or permission to trade.
"""
import hashlib
import json
import re

from bot.p3.certification import _decode
from bot.p3.platform_admin_history import _signature
from .migration_evidence import validate_migrate_to_cpswap_transaction


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:
        raise ValueError('exact_pinned_endpoint_sha256_required')
    return value


async def read_finalized_migration(rpc, *, signature, mint, launchlab_pool,
                                   cpmm_pool, expected_endpoint_sha256,
                                   expected_genesis_hash, observed_at_slot):
    """Query the one exact signature, once; retain both result and refused status.

    The caller is responsible for enforcing the RPC transport budget, deadline,
    permitted proxy, and retaining raw JSON receipts in a separate artifact.
    """
    for key in (mint,launchlab_pool,cpmm_pool,expected_genesis_hash):
        _decode(key)
    _signature(signature)
    _sha(expected_endpoint_sha256)
    if type(observed_at_slot) is not int or observed_at_slot<=0:
        raise ValueError('exact_fresh_source_bank_slot_required')
    base=dict(schema='rugger-finalized-cpmm-migration-rpc-v1',
        status='UNKNOWN',signature=signature,mint=mint,
        source_launchlab_pool=launchlab_pool,migrated_cpmm_pool=cpmm_pool,
        expected_endpoint_sha256=expected_endpoint_sha256,
        expected_genesis_hash=expected_genesis_hash,
        observed_at_slot=observed_at_slot,
        raw_RPC_response_returned_to_caller=False,
        durable_receipt_archived_by_this_function=False,
        transport_beyond_pinned_endpoint_independently_verified=False,
        cryptographic_signature_bytes_verified=False,
        network_consensus_independently_verified=False,
        live_execution_allowed=False)
    if getattr(rpc,'endpoint_sha256',None)!=expected_endpoint_sha256:
        return dict(base,reason='RPC_endpoint_not_expected',rpc_calls=0)
    observed_genesis=await rpc.genesis_hash()
    if observed_genesis!=expected_genesis_hash:
        return dict(base,reason='RPC_genesis_not_expected',rpc_calls=1)
    raw=await rpc.get_transaction(signature)
    if raw is None:
        return dict(base,reason='finalized_migration_receipt_unavailable',
                    rpc_calls=2)
    if type(raw) is not dict:
        return dict(base,reason='malformed_finalized_RPC_response',rpc_calls=2)
    normalized_bytes=json.dumps(raw,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()
    structural=validate_migrate_to_cpswap_transaction(
        raw,signature=signature,mint=mint,launchlab_pool=launchlab_pool,
        cpmm_pool=cpmm_pool,observed_at_slot=observed_at_slot)
    if structural['status']!='STRUCTURAL_MIGRATION_RECEIPT':
        return dict(base,status='REFUSED',reason=structural['reason'],
            rpc_calls=2,raw_RPC_response_returned_to_caller=True,
            raw_RPC_response=raw,
            raw_response_sha256=hashlib.sha256(normalized_bytes).hexdigest(),
            structural_validation=structural)
    return dict(base,status='FINALIZED_RPC_STRUCTURAL_MATCH',
        reason=None,rpc_calls=2,
        raw_response_sha256=hashlib.sha256(normalized_bytes).hexdigest(),
        migration_slot=structural['migration_slot'],
        normalized_role_sha256=structural['normalized_role_sha256'],
        source_RPC_endpoint_pin_matched=True,
        source_RPC_genesis_pin_matched=True,
        raw_RPC_response_returned_to_caller=True,
        raw_RPC_response=raw,
        source_signature_appeared_in_finalized_RPC_transaction=True,
        structural_validation=structural,
        transport_beyond_pinned_endpoint_independently_verified=False,
        cryptographic_signature_bytes_verified=False,
        network_consensus_independently_verified=False,
        live_execution_allowed=False)
