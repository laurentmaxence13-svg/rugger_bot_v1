"""Offline decoder of Pyth push-oracle updates on Solana (W1 protocol R7, option B').

Source (official docs archived 2026-11-08, sponsored-feeds.mdx sha256 f413c248...): the Pyth
Data Association pushes SOL/USD (feed ef0d8b6f...b56d) to the price feed account
7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE (Pyth Core, shard 0) on a 60 s heartbeat or a
0.5 % deviation. Each push is a transaction that verifies a Wormhole VAA and then calls the
push-oracle program ``UpdatePriceFeed`` once per feed (layout read by RUGGER 03 on two real
P0 transactions and re-derived here):

  data = discriminator 1c095d965699bc73 | u32 LE message length (85) | message |
         u32 LE proof node count | nodes x 20 bytes | treasury_id u8 | shard_id u16 LE |
         feed_id[32]
  message (big-endian) = type u8 (0 = price feed) | feed_id[32] | price i64 | conf u64 |
         exponent i32 | publish_time i64 | prev_publish_time i64 | ema_price i64 | ema_conf u64

Accounts of the instruction: [payer, receiver program, encoded VAA, config, treasury,
PRICE FEED ACCOUNT, system]. Only a SUCCESSFUL transaction counts: the chain verified the VAA
and the Merkle proof inside it, but nothing here re-verifies them, so every point stays
``NOT_VERIFIED_IN_REPLAY`` (bot.p4.sol_usd_series). Evidence: sha256 of the canonical JSON of
the RPC entry (getTransactionsForAddress full), the raw wire bytes not being returned.
No network access.
"""
import hashlib
import json
import struct

from bot.market.launchlab_events import b58decode

PUSH_ORACLE_PROGRAM = 'pythWSnswVUd12oZpeFP8e9CVaEqJg25g1Vtc2biRsT'
RECEIVER_PROGRAM = 'rec5EKMGg6MxZYaMdyBfgwp4d5rB9T1VQH5pJv5LtFJ'
UPDATE_PRICE_FEED = bytes.fromhex('1c095d965699bc73')
SOL_USD_FEED_ID = 'ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d'
SOL_USD_ACCOUNT = '7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE'
PRICE_ACCOUNT_INDEX = 5
MESSAGE_LENGTH = 85
POINT_SCHEMA = 'rugger-sol-usd-point-v1'


class PythPushError(ValueError):
    pass


def account_keys(entry):
    """Static keys then lookup-table keys (writable, readonly): the compiled index order."""
    message = entry['transaction']['message']
    keys = list(message['accountKeys'])
    if any(type(key) is not str for key in keys):
        raise PythPushError('compiled_account_keys_required')
    loaded = (entry.get('meta') or {}).get('loadedAddresses') or {}
    return keys + list(loaded.get('writable') or []) + list(loaded.get('readonly') or [])


def decode_update(data):
    """Decode one UpdatePriceFeed instruction's data; refuse anything that does not parse exactly."""
    if data[:8] != UPDATE_PRICE_FEED:
        raise PythPushError('not_update_price_feed')
    offset = 8
    (length,) = struct.unpack_from('<I', data, offset)
    offset += 4
    if length != MESSAGE_LENGTH or len(data) < offset + length + 4:
        raise PythPushError('unexpected_message_length')
    message = data[offset:offset + length]
    offset += length
    (nodes,) = struct.unpack_from('<I', data, offset)
    offset += 4 + 20 * nodes
    if len(data) != offset + 1 + 2 + 32:
        raise PythPushError('unexpected_instruction_length')
    treasury_id, shard_id = struct.unpack_from('<BH', data, offset)
    tail_feed = data[offset + 3:].hex()
    if message[0] != 0:
        raise PythPushError('not_a_price_feed_message')
    feed_id = message[1:33].hex()
    price, conf, exponent, publish_time, prev_publish_time, ema_price, ema_conf = struct.unpack(
        '>qQiqqqQ', message[33:])
    if tail_feed != feed_id:
        raise PythPushError('feed_id_mismatch_between_message_and_instruction')
    return dict(feed_id=feed_id, price=price, conf=conf, exponent=exponent, publish_time=publish_time,
                prev_publish_time=prev_publish_time, ema_price=ema_price, ema_conf=ema_conf,
                proof_nodes=nodes, treasury_id=treasury_id, shard_id=shard_id)


def _instructions(entry):
    message = entry['transaction']['message']
    yield from message.get('instructions') or []
    for group in (entry.get('meta') or {}).get('innerInstructions') or []:
        yield from group.get('instructions') or []


def updates(entry, *, feed_id=SOL_USD_FEED_ID, price_account=SOL_USD_ACCOUNT):
    """Decoded updates of ``feed_id`` written to ``price_account`` by a successful transaction."""
    if (entry.get('meta') or {}).get('err') is not None:
        return []
    keys = account_keys(entry)
    found = []
    for ix in _instructions(entry):
        if keys[ix['programIdIndex']] != PUSH_ORACLE_PROGRAM:
            continue
        data = b58decode(ix['data'])
        if data[:8] != UPDATE_PRICE_FEED:
            continue
        accounts = [keys[i] for i in ix['accounts']]
        update = decode_update(data)
        if update['feed_id'] != feed_id:
            continue
        if len(accounts) <= PRICE_ACCOUNT_INDEX or accounts[PRICE_ACCOUNT_INDEX] != price_account:
            raise PythPushError('feed_written_to_another_account')
        if update['shard_id'] != 0:
            raise PythPushError('unexpected_shard')
        found.append(update)
    if len(found) > 1:
        raise PythPushError('several_updates_of_one_feed_in_one_transaction')
    return found


def evidence_sha256(entry):
    return hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sol_usd_points(entries, *, feed_id=SOL_USD_FEED_ID, price_account=SOL_USD_ACCOUNT):
    """``rugger-sol-usd-point-v1`` points (kind ``pyth_onchain_account``) sorted by chain position."""
    points = []
    for entry in entries:
        if type(entry.get('transactionIndex')) is not int or type(entry.get('slot')) is not int:
            raise PythPushError('chain_position_required')
        for update in updates(entry, feed_id=feed_id, price_account=price_account):
            if update['price'] <= 0:
                raise PythPushError('non_positive_price')
            points.append(dict(schema=POINT_SCHEMA, slot=entry['slot'], transaction_index=entry['transactionIndex'],
                               block_time=entry.get('blockTime'), received_at_ms=None,
                               publish_time=update['publish_time'], price=update['price'],
                               exponent=update['exponent'], confidence=update['conf'],
                               source_kind='pyth_onchain_account', source_ref=price_account,
                               evidence_sha256=evidence_sha256(entry), signature=None))
    points.sort(key=lambda p: (p['slot'], p['transaction_index']))
    for earlier, later in zip(points, points[1:]):
        if (later['slot'], later['transaction_index']) == (earlier['slot'], earlier['transaction_index']):
            raise PythPushError('duplicate_chain_position')
        if later['publish_time'] < earlier['publish_time']:
            raise PythPushError('publish_time_moved_backwards')     # the account only moves forward
    return points
