"""Raydium CPMM account layouts (same offsets as R01's bot/live/cpmm_exit.py _pool/_config) and the exact
getProgramAccounts filters of the owner text B(b) (R02 v1.2). PDAs and base58 come from the frozen tree
(bot.p3.certification), the program id from cpmmx.events (frozen)."""
import base64
import struct

from bot.p3 import certification as CERT
from cpmmx.events import CPMM_PROGRAM

WSOL = 'So11111111111111111111111111111111111111112'
POOL_DISCRIMINATOR = bytes((247, 237, 227, 245, 215, 195, 222, 70))
CONFIG_DISCRIMINATOR = bytes((218, 244, 33, 104, 203, 203, 43, 111))
POOL_ACCOUNT_SIZE = 637
CONFIG_ACCOUNT_SIZE = 236
TRADE_FEE_RATE_U1 = 2_500
POOL_SLICE = (0, 413)                       # dataSlice of text B(b): up to creator_fees_token_1 included
POOL_KEYS = ('amm_config', 'pool_creator', 'token_0_vault', 'token_1_vault', 'lp_mint', 'token_0_mint',
             'token_1_mint', 'token_0_program', 'token_1_program', 'observation_key')
MINT_OFFSETS = (168, 200)                   # token_0_mint, token_1_mint
TOKEN_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'

b58encode = CERT._encode
b58decode = CERT._decode                    # 32-byte public addresses only
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58decode_any(text):
    """Any base58 string (memcmp bytes of any length); leading '1' = leading zero bytes."""
    number = 0
    for c in text:
        number = number * 58 + _B58.index(c)
    body = number.to_bytes((number.bit_length() + 7) // 8, 'big') if number else b''
    return b'\0' * (len(text) - len(text.lstrip('1'))) + body


class LayoutError(ValueError):
    pass


def config_filters():
    return [{'dataSize': CONFIG_ACCOUNT_SIZE},
            {'memcmp': {'offset': 0, 'bytes': b58encode(CONFIG_DISCRIMINATOR)}},
            {'memcmp': {'offset': 12, 'bytes': b58encode(struct.pack('<Q', TRADE_FEE_RATE_U1))}}]


def pool_filters(config, mint_offset):
    if mint_offset not in MINT_OFFSETS:
        raise LayoutError('mint_offset_must_be_168_or_200')
    return [{'dataSize': POOL_ACCOUNT_SIZE},
            {'memcmp': {'offset': 0, 'bytes': b58encode(POOL_DISCRIMINATOR)}},
            {'memcmp': {'offset': 8, 'bytes': config}},
            {'memcmp': {'offset': mint_offset, 'bytes': WSOL}}]


def raw(account_data):
    """Base64 data of an RPC account (``[data, 'base64']``)."""
    if not (isinstance(account_data, list) and len(account_data) == 2 and account_data[1] == 'base64'):
        raise LayoutError('account_data_not_base64')
    return base64.b64decode(account_data[0], validate=True)


def decode_config(data):
    if len(data) != CONFIG_ACCOUNT_SIZE or data[:8] != CONFIG_DISCRIMINATOR:
        raise LayoutError('not_an_amm_config')
    d = dict(bump=data[8], disabled=data[9], index=struct.unpack_from('<H', data, 10)[0])
    for offset, key in ((12, 'trade_fee_rate'), (20, 'protocol_fee_rate'), (28, 'fund_fee_rate'),
                        (108, 'creator_fee_rate'), (116, 'creator_fee_share_rate')):
        d[key] = struct.unpack_from('<Q', data, offset)[0]
    return d


def decode_pool(data):
    """Decodes the dataSlice 0..413 of text B(b) (or the full 637-byte account)."""
    if len(data) not in (POOL_SLICE[1], POOL_ACCOUNT_SIZE) or data[:8] != POOL_DISCRIMINATOR:
        raise LayoutError('not_a_pool_state')
    d = {key: b58encode(data[8 + i * 32:40 + i * 32]) for i, key in enumerate(POOL_KEYS)}
    for offset, key in ((328, 'auth_bump'), (329, 'status'), (330, 'lp_mint_decimals'), (331, 'mint_0_decimals'),
                        (332, 'mint_1_decimals'), (389, 'creator_fee_on'), (390, 'enable_creator_fee')):
        d[key] = data[offset]
    for offset, key in ((333, 'lp_supply'), (373, 'open_time')):
        d[key] = struct.unpack_from('<Q', data, offset)[0]
    return d


def config_pda(index):
    return CERT.find_program_address((b'amm_config', index.to_bytes(2, 'big')), CPMM_PROGRAM)[0]


def vault_pda(pool, mint):
    return CERT.find_program_address((b'pool_vault', b58decode(pool), b58decode(mint)), CPMM_PROGRAM)[0]


def spl_amount(data):
    """Amount (u64 at offset 64) and mint of an SPL token account (165 bytes or more, Token-2022 extensions allowed)."""
    if len(data) < 165:
        raise LayoutError('not_a_token_account')
    return b58encode(data[:32]), struct.unpack_from('<Q', data, 64)[0]
