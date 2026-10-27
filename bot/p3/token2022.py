"""Pure Token-2022 header reader for base accounts and metadata-only mints.

Only MetadataPointer (18) and TokenMetadata (19) mint extensions are supported.
Transfer fees, hooks, non-transferability and every other extension fail closed.
This does not certify pool identity, PDA ownership, execution or future selling.
Metadata text is validated structurally and hashed, never returned or followed.
"""
import base64
import hashlib
import struct


TOKEN_2022_PROGRAM = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_U64_MAX = (1 << 64) - 1
SOURCE_SHA256 = {
    'token2022_interface_extension_mod.rs': 'd273a87617b06f4a813a2c3c3bbab8180a0a4c657d836a95475259eca9e40f5a',
    'token2022_metadata_pointer_mod.rs': 'db4f962e95f2a652b8faf06c8821cb2c7e6ecd31e90cc27d46df0ca143768633',
    'token_metadata_state.rs': '865edf6b1d21d913403308e4bd6347d7210e02489c46c243ecd5210995f791de',
}
SOURCE_URLS = {
    'token2022_interface_extension_mod.rs': 'https://raw.githubusercontent.com/solana-program/token-2022/main/interface/src/extension/mod.rs',
    'token2022_metadata_pointer_mod.rs': 'https://raw.githubusercontent.com/solana-program/token-2022/main/interface/src/extension/metadata_pointer/mod.rs',
    'token_metadata_state.rs': 'https://raw.githubusercontent.com/solana-program/token-metadata/main/interface/src/state.rs',
}


class TokenEvidenceError(ValueError):
    """Categorical unsupported or malformed account evidence; no raw text."""


def _b58(raw):
    number, result = int.from_bytes(raw, 'big'), ''
    while number:
        number, digit = divmod(number, 58)
        result = _B58[digit] + result
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + result


def _address_bytes(value):
    if type(value) is not str or not 32 <= len(value) <= 44:
        raise TokenEvidenceError('invalid_expected_mint_address')
    number = 0
    for character in value:
        if character not in _B58:
            raise TokenEvidenceError('invalid_expected_mint_address')
        number = number * 58 + _B58.index(character)
    raw = b'\0' * (len(value) - len(value.lstrip('1')))
    raw += number.to_bytes((number.bit_length() + 7) // 8, 'big')
    if len(raw) != 32:
        raise TokenEvidenceError('invalid_expected_mint_address')
    return raw


def _raw_account(account):
    if (type(account) is not dict or account.get('owner') != TOKEN_2022_PROGRAM
            or account.get('executable') is not False):
        raise TokenEvidenceError('token2022_owner_or_executable_invalid')
    data = account.get('data')
    if (type(data) not in (list, tuple) or len(data) != 2 or data[1] != 'base64'
            or type(data[0]) is not str or len(data[0]) > 100_000):
        raise TokenEvidenceError('token2022_encoding_invalid')
    try:
        raw = base64.b64decode(data[0], validate=True)
    except (ValueError, TypeError):
        raise TokenEvidenceError('token2022_encoding_invalid') from None
    if len(raw) > 70_000 or len(raw) == 355:  # SPL excludes the multisig size.
        raise TokenEvidenceError('token2022_layout_length_unsupported')
    return raw


def _option(raw, offset, name):
    value = struct.unpack_from('<I', raw, offset)[0]
    if value not in (0, 1):
        raise TokenEvidenceError(name + '_option_invalid')
    return bool(value)


def _metadata(value, expected_mint):
    # TokenMetadata's SPL discriminator is NOT part of its Token-2022 TLV value.
    if len(value) < 80 or value[32:64] != expected_mint:
        raise TokenEvidenceError('metadata_mint_or_layout_invalid')
    offset = 64

    def integer():
        nonlocal offset
        if offset + 4 > len(value):
            raise TokenEvidenceError('metadata_borsh_truncated')
        result = struct.unpack_from('<I', value, offset)[0]
        offset += 4
        return result

    def text_digest():
        nonlocal offset
        length = integer()
        if offset + length > len(value):
            raise TokenEvidenceError('metadata_borsh_truncated')
        raw_text = value[offset:offset + length]
        try:
            raw_text.decode('utf-8')
        except UnicodeDecodeError:
            raise TokenEvidenceError('metadata_text_encoding_invalid') from None
        offset += length
        return hashlib.sha256(raw_text).digest()

    for _ in range(3):  # name, symbol, URI; none is returned or followed.
        text_digest()
    count = integer()
    if count > (len(value) - offset) // 8:
        raise TokenEvidenceError('metadata_borsh_truncated')
    keys = set()
    for _ in range(count):
        key = text_digest()
        if key in keys:
            raise TokenEvidenceError('metadata_duplicate_key')
        keys.add(key)
        text_digest()
    if offset != len(value):
        # A deliberately narrower subset than unchecked Borsh with realloc tail.
        raise TokenEvidenceError('metadata_trailing_bytes_unsupported')
    return {'update_authority_present': any(value[:32]),
            'mint_matches_expected': True, 'additional_pairs_count': count}


def _extensions(raw):
    if len(raw) == 82:
        return {}
    if len(raw) < 166 or any(raw[82:165]) or raw[165] != 1:
        raise TokenEvidenceError('mint_padding_or_account_type_invalid')
    offset, result = 166, {}
    while offset < len(raw):
        # Zero realloc capacity contains no initialized extension. Nonzero tails
        # cannot hide a later transfer extension after an uninitialized marker.
        if not any(raw[offset:]):
            break
        if offset + 4 > len(raw):
            raise TokenEvidenceError('mint_tlv_truncated')
        kind, size = struct.unpack_from('<HH', raw, offset)
        offset += 4
        if kind not in (18, 19):
            raise TokenEvidenceError('mint_extension_not_supported')
        if kind in result:
            raise TokenEvidenceError('mint_duplicate_extension')
        if offset + size > len(raw):
            raise TokenEvidenceError('mint_tlv_truncated')
        result[kind] = raw[offset:offset + size]
        offset += size
    return result


def decode_mint(account, expected_address):
    """Return (header facts, raw bytes) for the supported Token-2022 subset.

    Known metadata authorities affect metadata, not mint/freeze permissions.
    Callers still must reject unsafe base permissions and certify pool links.
    """
    expected = _address_bytes(expected_address)
    raw = _raw_account(account)
    extensions = _extensions(raw)
    if len(raw) < 82 or raw[45] != 1:
        raise TokenEvidenceError('mint_not_initialized')
    mint_option = _option(raw, 0, 'mint_authority')
    freeze_option = _option(raw, 46, 'freeze_authority')
    facts = {
        'supply_atomic': struct.unpack_from('<Q', raw, 36)[0],
        'decimals': raw[44], 'initialized': True,
        'mint_authority_present': mint_option,
        'mint_authority': _b58(raw[4:36]) if mint_option else None,
        'freeze_authority_present': freeze_option,
        'freeze_authority': _b58(raw[50:82]) if freeze_option else None,
        'token_program': TOKEN_2022_PROGRAM,
        'extension_types': list(extensions),
        'extension_data_sha256': {str(kind): hashlib.sha256(data).hexdigest()
                                  for kind, data in extensions.items()},
        'extensions_transfer_neutral': True,
        'source_sha256': dict(SOURCE_SHA256),
    }
    if 18 in extensions:
        pointer = extensions[18]
        if len(pointer) != 64:
            raise TokenEvidenceError('metadata_pointer_length_invalid')
        facts['metadata_pointer'] = {'authority_present': any(pointer[:32]),
            'address_present': any(pointer[32:]),
            'address_matches_mint': pointer[32:] == expected}
    if 19 in extensions:
        facts['metadata'] = _metadata(extensions[19], expected)
    return facts, raw


def decode_vault(account):
    """Return (header facts, raw bytes); only the 165-byte base is supported."""
    raw = _raw_account(account)
    if len(raw) != 165:
        raise TokenEvidenceError('vault_extensions_not_supported')
    delegate = _option(raw, 72, 'vault_delegate')
    native = _option(raw, 109, 'vault_native')
    close = _option(raw, 129, 'vault_close_authority')
    if raw[108] not in (0, 1, 2):
        raise TokenEvidenceError('vault_state_invalid')
    lamports = account.get('lamports')
    if type(lamports) is not int or not 0 <= lamports <= _U64_MAX:
        raise TokenEvidenceError('vault_lamports_invalid')
    amount = struct.unpack_from('<Q', raw, 64)[0]
    reserve = struct.unpack_from('<Q', raw, 113)[0] if native else None
    if native and (reserve > lamports or amount > lamports - reserve):
        raise TokenEvidenceError('vault_native_backing_insufficient')
    return {
        'mint': _b58(raw[:32]), 'authority': _b58(raw[32:64]),
        'amount_atomic': amount, 'account_lamports': lamports,
        'native_rent_reserve_lamports': reserve, 'state': raw[108],
        'delegate_present': delegate, 'close_authority_present': close,
        'is_native': native, 'token_program': TOKEN_2022_PROGRAM,
        'extension_types': [], 'extensions_transfer_neutral': True,
        'source_sha256': dict(SOURCE_SHA256),
    }, raw
