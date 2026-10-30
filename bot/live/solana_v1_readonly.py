"""Read-only Solana transaction-v1 cryptographic forensic verifier.

Pinned wire layout: https://solana.com/docs/core/transactions/versioned-transactions
Version 1: 0x81|header(3)|mask(u32)|blockhash(32)|n_ix(u8)|n_keys(u8)
|keys(32*n)|config_values(bitmask)|ix_headers(4*n_ix)|ix_payloads
|trailing_ed25519_signatures(64*n_signers).

No wallet, signing, transaction construction, sending or LIVE authorization.
All evidence is for the specific GET getTransaction(base64) RPC response.
Never reinterpret a jsonParsed v1 response as a signed-message proof.
"""
import base64
import hashlib
import struct

from bot.p3.certification import PROGRAM, _decode, _encode
from bot.p3.platform_admin_history import _signature
from bot.scanner.transaction_parser import find_raydium_launches

MAX_WIRE_BYTES = 4096
MAX_IX = 64
MAX_KEYS = 96


def verify_v1_base64_receipt(tx, *, expected_signature, expected_slot):
    _signature(expected_signature)
    if type(expected_slot) is not int or expected_slot <= 0:
        raise ValueError("v1_exact_source_slot_required")
    if (type(tx) is not dict or type(tx.get("version")) is not int
            or tx["version"] != 1 or tx.get("slot") != expected_slot or
            type(tx.get("meta")) is not dict or
            tx["meta"].get("err") is not None or
            type(tx.get("transaction")) is not list or
            len(tx["transaction"]) != 2 or
            tx["transaction"][1] != "base64" or
            type(tx["transaction"][0]) is not str):
        raise ValueError("v1_rpc_receipt_version_slot_or_status_invalid")
    try:
        wire = base64.b64decode(tx["transaction"][0], validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("v1_transaction_base64_invalid") from None
    if (not 80 <= len(wire) <= MAX_WIRE_BYTES or wire[0] != 0x81):
        raise ValueError("v1_wire_prefix_or_length_invalid")
    offset = 1

    def read(n):
        nonlocal offset
        if n < 0 or offset + n > len(wire):
            raise ValueError("v1_wire_truncated")
        part = wire[offset:offset+n]
        offset += n
        return part

    required, readonly_signers, readonly_unsigned = read(3)
    if not 1 <= required <= MAX_KEYS or readonly_signers >= required:
        raise ValueError("v1_signer_header_invalid")
    mask = int.from_bytes(read(4), "little")
    if mask & ~31 or (mask & 3) not in (0, 3):
        raise ValueError("v1_unknown_config_mask_bits")
    blockhash = read(32)
    number_ix, number_keys = read(1)[0], read(1)[0]
    if (number_ix > MAX_IX or not required <= number_keys <= MAX_KEYS or
            readonly_unsigned > number_keys - required):
        raise ValueError("v1_instruction_or_address_count_invalid")
    keys = [_encode(read(32)) for _ in range(number_keys)]
    if len(set(keys)) != len(keys):
        raise ValueError("v1_duplicate_static_addresses")
    config = {}
    if mask & 3:
        config["priority_fee_lamports"] = int.from_bytes(read(8), "little")
    for bit, name in ((2, "compute_unit_limit"),
                      (3, "loaded_accounts_data_size_limit"),
                      (4, "requested_heap_size")):
        if mask & (1 << bit):
            config[name] = int.from_bytes(read(4), "little")
    headers = []
    for _ in range(number_ix):
        program_id, n_accounts = read(2)
        data_size = int.from_bytes(read(2), "little")
        if program_id >= number_keys or n_accounts > number_keys:
            raise ValueError("v1_instruction_index_or_accounts_invalid")
        headers.append((program_id, n_accounts, data_size))
    instructions = []
    for program_id, n_accounts, data_size in headers:
        indices = list(read(n_accounts))
        if any(i >= number_keys for i in indices):
            raise ValueError("v1_instruction_account_reference_invalid")
        data = read(data_size)
        instructions.append(dict(
            programId=keys[program_id],
            accounts=[keys[i] for i in indices],
            data=_encode(data)))
    message_end = offset
    if len(wire) - message_end != required * 64:
        raise ValueError("v1_signature_tail_length_invalid")
    signatures = [read(64) for _ in range(required)]
    if _encode(signatures[0]) != expected_signature:
        raise ValueError("v1_expected_first_signature_mismatch")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        raise RuntimeError("v1_crypto_dependency_unavailable") from None
    for key, signature in zip(keys[:required], signatures, strict=True):
        try:
            Ed25519PublicKey.from_public_bytes(_decode(key)).verify(
                signature, wire[:message_end])
        except Exception:
            raise ValueError("v1_exact_ed25519_message_invalid") from None
    launches = find_raydium_launches(dict(
        transaction=dict(message=dict(instructions=instructions)),
        meta=dict(err=None, innerInstructions=[])))
    # Outer instructions are included in the verified v1 message. Inner
    # instructions returned in meta are RPC claims and not promoted here.
    return dict(schema="rugger-solana-v1-signed-outer-launchlab-v1",
        status="V1_ED25519_MESSAGE_VALID",
        source_program=PROGRAM,
        slot=expected_slot, signature=expected_signature,
        exact_message_sha256=hashlib.sha256(wire[:message_end]).hexdigest(),
        raw_wire_sha256=hashlib.sha256(wire).hexdigest(),
        account_keys=keys,
        signer_public_keys=keys[:required],
        compiled_outer_instructions=len(instructions),
        config_mask=mask,
        config=config,
        launched_candidates=[dict(payer=v["payer"], creator=v["creator"],
                                  mint=v["mint"], pool=v["pool_state"])
                             for v in launches],
        signed_instruction_evidence=True,
        provider_finality_independently_verified=False,
        actual_buy_sell_trades=0, live_ready_to_arm=False,
        financial_order_submitted=False, economic_edge_validated=False)
