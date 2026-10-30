"""Synthetic Ed25519 fixtures for Solana v1 GET receipt read-only verification."""
import base64
import struct

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from bot.live import solana_v1_readonly as mod
from bot.p3.certification import PROGRAM, _decode, _encode
from bot.scanner.transaction_parser import _CREATE_DISCRIMINATORS


def signed_receipt(*, tamper=False, unknown_mask=False, extra_byte=False,
                   no_create=False):
    key = Ed25519PrivateKey.from_private_bytes(bytes([42]) * 32)
    payer = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    keys = [payer, _decode(PROGRAM)] + [bytes([n]) * 32 for n in range(20, 26)]
    discriminator = sorted(_CREATE_DISCRIMINATORS)[0]
    instruction_data = (b"\x22" * 8 if no_create else discriminator) + bytes([1, 2])
    mask = 1 << 7 if unknown_mask else (1 << 2) | (1 << 3)
    message = bytearray(b"\x81")
    message += bytes([1, 0, 0])  # 1 signer: fee payer
    message += struct.pack("<I", mask)
    message += bytes([10]) * 32
    message += bytes([1, len(keys)])  # 1 ix, 8 embedded public keys
    for pub in keys:
        message += pub
    if not unknown_mask:
        message += struct.pack("<I", 100000)
        message += struct.pack("<I", 65536)
    # program index 1; accounts at ids 0,2,3,4,5,6,7
    message += bytes([1, 7]) + struct.pack("<H", len(instruction_data))
    message += bytes([0, 2, 3, 4, 5, 6, 7]) + instruction_data
    signature = key.sign(bytes(message))
    wire = bytes(message) + signature + (b"\x00" if extra_byte else b"")
    if tamper:
        changed = bytearray(wire)
        changed[-65] ^= 1  # mutate signed instruction payload
        wire = bytes(changed)
    return dict(version=1, slot=10101, meta=dict(err=None),
                transaction=[base64.b64encode(wire).decode(), "base64"]), _encode(signature)


def test_strict_v1_cryptographic_creation_and_config():
    tx, sig = signed_receipt()
    result = mod.verify_v1_base64_receipt(tx, expected_signature=sig,
                                           expected_slot=10101)
    assert result["status"] == "V1_ED25519_MESSAGE_VALID"
    assert result["config"]["compute_unit_limit"] == 100000
    assert result["config"]["loaded_accounts_data_size_limit"] == 65536
    assert result["compiled_outer_instructions"] == 1
    assert len(result["launched_candidates"]) == 1
    assert result["launched_candidates"][0]["payer"] == result["signer_public_keys"][0]
    assert result["launched_candidates"][0]["creator"] == result["account_keys"][2]
    assert result["launched_candidates"][0]["pool"] == result["account_keys"][6]
    assert result["launched_candidates"][0]["mint"] == result["account_keys"][7]
    assert result["financial_order_submitted"] is False
    assert result["economic_edge_validated"] is False


def test_legitimate_v1_noncreation_remains_noncreation():
    tx, sig = signed_receipt(no_create=True)
    assert mod.verify_v1_base64_receipt(tx, expected_signature=sig,
               expected_slot=10101)["launched_candidates"] == []


@pytest.mark.parametrize("opts,reason", [
    (dict(tamper=True), "v1_exact_ed25519_message_invalid"),
    (dict(extra_byte=True), "v1_signature_tail_length_invalid"),
    (dict(unknown_mask=True), "v1_unknown_config_mask_bits"),
])
def test_mutated_v1_wire_rejected(opts, reason):
    tx, sig = signed_receipt(**opts)
    with pytest.raises(ValueError, match=reason):
        mod.verify_v1_base64_receipt(tx, expected_signature=sig,
                                      expected_slot=10101)


def test_signature_slot_version_and_finality_guard():
    tx, sig = signed_receipt()
    with pytest.raises(ValueError, match="v1_expected_first_signature_mismatch"):
        mod.verify_v1_base64_receipt(tx, expected_signature=_encode(bytes([1])*64),
                                      expected_slot=10101)
    with pytest.raises(ValueError, match="slot_or_status_invalid"):
        mod.verify_v1_base64_receipt(tx, expected_signature=sig,
                                      expected_slot=10102)
    bad = dict(tx, meta=dict(err={"InstructionError": [0]}))
    with pytest.raises(ValueError, match="slot_or_status_invalid"):
        mod.verify_v1_base64_receipt(bad, expected_signature=sig,
                                      expected_slot=10101)
    bad = dict(tx, version=0)
    with pytest.raises(ValueError, match="slot_or_status_invalid"):
        mod.verify_v1_base64_receipt(bad, expected_signature=sig,
                                      expected_slot=10101)
