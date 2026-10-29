"""Cryptographic verification of the exact Solana compiled transaction message.

getTransaction(encoding="json") provides all legacy and v0 message fields.
Rebuild precisely the serialized bytes and verify EACH required Ed25519
signature against the original static signer keys. This checks signatures,
NOT inclusion/finality in the chain, ownership of a wallet, or trade consent.

No private keys, signer, network, send or wallet-account calls.
"""
import hashlib

from bot.p3.certification import _decode, _encode
from bot.p3.platform_admin_history import _b58_bytes, _signature
from .migration_rpc_json import normalized_compiled_transaction
from .wire import shortvec


def compiled_message_bytes(tx):
    """Serialize canonical getTransaction encoding=json legacy or v0 message."""
    normalized = normalized_compiled_transaction(tx)
    message = tx["transaction"]["message"]
    header = message["header"]
    counts = tuple(header[k] for k in (
        "numRequiredSignatures","numReadonlySignedAccounts",
        "numReadonlyUnsignedAccounts"))
    keys = message["accountKeys"]
    version = tx.get("version","legacy")
    if (type(version) is bool or version not in ("legacy",0) or
            any(type(n) is not int or not 0<=n<=255 for n in counts)):
        raise ValueError("unsupported_transaction_message_or_header")
    n_loaded = len(normalized["transaction"]["message"]["accountKeys"])
    if not 0<counts[0]<=len(keys):
        raise ValueError("compiled_signer_count_invalid")
    raw = bytearray(b"\x80" if version==0 else b"")
    raw.extend(bytes(counts))
    raw.extend(shortvec(len(keys)))
    for key in keys:
        raw.extend(_decode(key))
    raw.extend(_decode(message["recentBlockhash"]))
    ixs = message["instructions"]
    if type(ixs) is not list or len(ixs)>65535:
        raise ValueError("compiled_instructions_invalid")
    raw.extend(shortvec(len(ixs)))
    for ix in ixs:
        if type(ix) is not dict:
            raise ValueError("compiled_instruction_invalid")
        program_index=ix.get("programIdIndex")
        indices=ix.get("accounts")
        encoded=ix.get("data")
        if (type(program_index) is not int or not 0<=program_index<n_loaded or
                type(indices) is not list or len(indices)>255 or
                any(type(i) is not int or not 0<=i<n_loaded for i in indices)
                or type(encoded) is not str):
            raise ValueError("compiled_instruction_index_invalid")
        # Message bytes store actual compiled indices, not looked-up public
        # keys. This applies to v0 lookup-table indexes as well.
        data=_b58_bytes(encoded)
        if _encode(data)!=encoded or len(data)>1232:
            raise ValueError("compiled_instruction_data_noncanonical")
        raw.extend(bytes([program_index]))
        raw.extend(shortvec(len(indices)))
        raw.extend(bytes(indices))
        raw.extend(shortvec(len(data)))
        raw.extend(data)
    if version==0:
        lookups=message.get("addressTableLookups",[])
        if type(lookups) is not list or len(lookups)>255:
            raise ValueError("invalid_v0_lookup_vector")
        raw.extend(shortvec(len(lookups)))
        for lookup in lookups:
            if type(lookup) is not dict:
                raise ValueError("v0_lookup_not_object")
            writable=lookup.get("writableIndexes")
            readonly=lookup.get("readonlyIndexes")
            if (type(writable) is not list or type(readonly) is not list
                    or len(writable)>255 or len(readonly)>255
                    or any(type(i) is not int or not 0<=i<256
                           for i in writable+readonly)):
                raise ValueError("invalid_v0_lookup_table_indices")
            raw.extend(_decode(lookup["accountKey"]))
            raw.extend(shortvec(len(writable)))
            raw.extend(bytes(writable))
            raw.extend(shortvec(len(readonly)))
            raw.extend(bytes(readonly))
    if len(raw)>1232:
        raise ValueError("serialized_Solana_message_packet_limit")
    return bytes(raw)


def verify_compiled_rpc_signatures(tx):
    """Check exact Ed25519 signatures, without claiming RPC consensus."""
    wire=compiled_message_bytes(tx)
    keys=tx["transaction"]["message"]["accountKeys"]
    signatures=tx["transaction"]["signatures"]
    required=tx["transaction"]["message"]["header"]["numRequiredSignatures"]
    if (type(signatures) is not list or len(signatures)!=required
            or type(required) is not int or required<1):
        raise ValueError("exact_compiled_signer_vector_required")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        raise RuntimeError("cryptographic_Ed25519_dependency_required") from None
    for i in range(required):
        _signature(signatures[i])
        signed_bytes=_b58_bytes(signatures[i])
        if _encode(signed_bytes)!=signatures[i] or len(signed_bytes)!=64:
            raise ValueError("noncanonical_Ed25519_signature_encoding")
        try:
            Ed25519PublicKey.from_public_bytes(_decode(keys[i])).verify(
                signed_bytes,wire)
        except Exception:
            raise ValueError("historical_transaction_Ed25519_signature_invalid") from None
    return dict(schema="rugger-solana-exact-message-signatures-v1",
        result="ED25519_MESSAGE_SIGNATURES_VALID",
        transaction_version=tx.get("version","legacy"),
        required_signatures=required,
        exact_message_sha256=hashlib.sha256(wire).hexdigest(),
        signatures_sha256=hashlib.sha256(
            b"".join(_b58_bytes(sig) for sig in signatures)).hexdigest(),
        cryptographic_signatures_verified=True,
        independent_chain_inclusion_verified=False,
        independent_RPC_consensus_verified=False,
        real_financial_execution_verified=False,
        live_execution_authorized=False,
        live_ready_to_arm=False)
