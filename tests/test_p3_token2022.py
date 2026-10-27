"""Synthetic Token-2022 permission/metadata evidence, without network or wallets."""
import base64
import hashlib
import json
import struct

import pytest

from bot.p3 import token2022 as t22
from test_p3_launchlab import encode


MINT_BYTES = bytes([31]) * 32
MINT = encode(MINT_BYTES)


def account(raw):
    return {'owner': t22.TOKEN_2022_PROGRAM, 'executable': False,
            'data': [base64.b64encode(raw).decode(), 'base64'], 'lamports': 10**10}


def base_mint():
    raw = bytearray(82)
    struct.pack_into('<Q', raw, 36, 10**15)
    raw[44:46] = bytes([6, 1])
    return raw


def string(value):
    return struct.pack('<I', len(value)) + value


def metadata(*, mint=MINT_BYTES, pairs=()):
    return (bytes([12])*32 + mint + string(b'synthetic') + string(b'SYN')
            + string(b'https://example.invalid/metadata?api_key=never-emitted')
            + struct.pack('<I', len(pairs))
            + b''.join(string(key) + string(value) for key, value in pairs))


def extended(*entries):
    return bytes(base_mint()) + bytes(83) + b'\1' + b''.join(
        struct.pack('<HH', kind, len(value)) + value for kind, value in entries)


def base_vault():
    raw = bytearray(165)
    raw[:32] = MINT_BYTES
    raw[32:64] = bytes([22]) * 32
    struct.pack_into('<Q', raw, 64, 8_000_000)
    raw[108] = 1
    return raw


def test_base_mint_82_bytes_preserves_exact_supply_and_base_permissions():
    raw = base_mint()
    facts, retained = t22.decode_mint(account(raw), MINT)
    assert retained == bytes(raw)
    assert facts['supply_atomic'] == 10**15 and facts['decimals'] == 6
    assert facts['mint_authority'] is facts['freeze_authority'] is None
    assert facts['mint_authority_present'] is facts['freeze_authority_present'] is False
    assert facts['extension_types'] == [] and facts['extensions_transfer_neutral'] is True


def test_metadata_only_is_bound_to_mint_and_never_exposes_metadata_text():
    value = metadata(pairs=((b'public-tag', b'value'),))
    raw = extended((18, bytes([12])*32 + MINT_BYTES), (19, value))
    facts, retained = t22.decode_mint(account(raw), MINT)
    assert retained == raw and facts['extension_types'] == [18, 19]
    assert facts['metadata']['mint_matches_expected'] is True
    assert facts['metadata']['update_authority_present'] is True
    assert facts['metadata']['additional_pairs_count'] == 1
    assert facts['metadata_pointer']['address_matches_mint'] is True
    assert facts['mint_authority_present'] is facts['freeze_authority_present'] is False
    assert facts['extension_data_sha256']['19'] == hashlib.sha256(value).hexdigest()
    text = json.dumps(facts)
    assert 'never-emitted' not in text and 'https://' not in text and 'synthetic' not in text


def test_spoofed_metadata_or_invalid_expected_address_cannot_qualify():
    with pytest.raises(t22.TokenEvidenceError, match='metadata_mint'):
        t22.decode_mint(account(extended((19, metadata(mint=bytes([32])*32)))), MINT)
    for expected in (True, None, 1, '', 'x'*32, '1'*33):
        with pytest.raises(t22.TokenEvidenceError, match='expected_mint_address'):
            t22.decode_mint(account(base_mint()), expected)


def test_transfer_fees_hooks_nontransferable_and_unknown_extensions_are_blocked():
    for kind in (1, 6, 9, 12, 14, 26, 65535):
        with pytest.raises(t22.TokenEvidenceError, match='extension_not_supported'):
            t22.decode_mint(account(extended((18, bytes(64)), (kind, bytes(8)))), MINT)


def test_malformed_duplicate_or_hidden_tlv_and_padding_are_blocked():
    valid = extended((18, bytes(64)))
    bad_padding = bytearray(valid); bad_padding[100] = 1
    bad_type = bytearray(valid); bad_type[165] = 2
    malformed = (bytes(bad_padding), bytes(bad_type), valid[:-1], valid + b'\x12',
                 extended((18, bytes(64)), (18, bytes(64))), extended((18, bytes(63))),
                 valid + bytes(4) + struct.pack('<HH', 14, 0), bytes(base_mint()) + bytes(83))
    for raw in malformed:
        with pytest.raises(t22.TokenEvidenceError):
            t22.decode_mint(account(raw), MINT)
    facts, _ = t22.decode_mint(account(valid + bytes(12)), MINT)
    assert facts['extension_types'] == [18]


def test_metadata_borsh_truncation_invalid_utf8_duplicates_and_tail_are_blocked():
    invalid_utf8 = bytes(32) + MINT_BYTES + string(b'\xff') + string(b'') + string(b'') + bytes(4)
    malformed = (metadata()[:-1], invalid_utf8, metadata() + b'\0',
                 metadata(pairs=((b'a', b'1'), (b'a', b'2'))),
                 bytes(32) + MINT_BYTES + struct.pack('<I', 0xffffffff))
    for value in malformed:
        with pytest.raises(t22.TokenEvidenceError):
            t22.decode_mint(account(extended((19, value))), MINT)


def test_mint_authorities_are_facts_not_silently_cleared_and_tags_are_strict():
    raw = base_mint()
    struct.pack_into('<I', raw, 0, 1); raw[4:36] = bytes([10])*32
    struct.pack_into('<I', raw, 46, 1); raw[50:82] = bytes([11])*32
    facts, _ = t22.decode_mint(account(raw), MINT)
    assert facts['mint_authority_present'] is facts['freeze_authority_present'] is True
    assert facts['mint_authority'] == encode(bytes([10])*32)
    assert facts['freeze_authority'] == encode(bytes([11])*32)
    for offset, fmt, value in ((0, '<I', 2), (46, '<I', 255), (45, '<B', 0), (45, '<B', 2)):
        bad = bytearray(raw); struct.pack_into(fmt, bad, offset, value)
        with pytest.raises(t22.TokenEvidenceError):
            t22.decode_mint(account(bad), MINT)


def test_vault_165_bytes_preserves_amount_links_and_permission_states():
    raw = base_vault()
    facts, retained = t22.decode_vault(account(raw))
    assert retained == bytes(raw) and facts['amount_atomic'] == 8_000_000
    assert facts['mint'] == MINT and facts['authority'] == encode(bytes([22])*32)
    assert facts['state'] == 1 and facts['delegate_present'] is facts['close_authority_present'] is False
    frozen = bytearray(raw); frozen[108] = 2
    assert t22.decode_vault(account(frozen))[0]['state'] == 2
    delegated = bytearray(raw); struct.pack_into('<I', delegated, 72, 1)
    assert t22.decode_vault(account(delegated))[0]['delegate_present'] is True


def test_vault_extension_states_option_tags_and_native_backing_fail_closed():
    for offset, value in ((72, 2), (109, 2), (129, 2)):
        raw = base_vault(); struct.pack_into('<I', raw, offset, value)
        with pytest.raises(t22.TokenEvidenceError):
            t22.decode_vault(account(raw))
    raw = base_vault(); raw[108] = 3
    with pytest.raises(t22.TokenEvidenceError, match='state_invalid'):
        t22.decode_vault(account(raw))
    for suffix in (b'\2', b'\2' + struct.pack('<HH', 2, 8) + bytes(8)):
        with pytest.raises(t22.TokenEvidenceError, match='extensions_not_supported'):
            t22.decode_vault(account(base_vault() + suffix))
    raw = base_vault(); struct.pack_into('<I', raw, 109, 1)
    struct.pack_into('<Q', raw, 113, 10**10)
    with pytest.raises(t22.TokenEvidenceError, match='native_backing_insufficient'):
        t22.decode_vault(account(raw))


def test_account_owner_encoding_and_lamport_types_never_accept_unsafe_evidence():
    for change in ({'owner': 'other'}, {'executable': 0}, {'executable': True},
                   {'data': ['not base64!', 'base64']}, {'data': [True, 'base64']}):
        candidate = account(base_mint()); candidate.update(change)
        with pytest.raises(t22.TokenEvidenceError):
            t22.decode_mint(candidate, MINT)
    for lamports in (True, -1, 1.0, '100', None, 2**64):
        candidate = account(base_vault()); candidate['lamports'] = lamports
        with pytest.raises(t22.TokenEvidenceError, match='lamports_invalid'):
            t22.decode_vault(candidate)
