"""Offline wire and real-ABI construction; fixtures are not chain executions."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from bot.live.wire import AccountMeta as AM, Instruction, compile_legacy, shortvec
from bot.live.route import (
    SYSTEM_PROGRAM, TOKEN_PROGRAM, ATA_PROGRAM, COMPUTE_BUDGET_PROGRAM,
    BUY_EXACT_IN, SELL_EXACT_IN, associated_token_address, ephemeral_wsol_address,
    build_launchlab_order, validate_prepared_order,
)
from bot.p3.certification import PROGRAM, _decode, _encode
from test_p3_research_integration import research_snapshot


def _take_compact(raw, position):
    result = 0
    shift = 0
    while True:
        limb = raw[position]
        position += 1
        result |= (limb & 127) << shift
        if limb < 128:
            return result, position
        shift += 7
        assert shift <= 14


def _instructions(message):
    """Independent minimal reader of compiled legacy messages."""
    header = tuple(message[:3])
    count, p = _take_compact(message, 3)
    keys = tuple(_encode(message[p + 32*i:p + 32*(i+1)]) for i in range(count))
    p += 32 * count
    blockhash = _encode(message[p:p+32])
    p += 32
    count, p = _take_compact(message, p)
    instructions = []
    for _ in range(count):
        program = keys[message[p]]
        p += 1
        count, p = _take_compact(message, p)
        accounts = tuple(keys[i] for i in message[p:p+count])
        p += count
        length, p = _take_compact(message, p)
        data = message[p:p+length]
        p += length
        instructions.append((program, accounts, data))
    assert p == len(message)
    return header, keys, blockhash, instructions


def route_request(side='BUY', *, has_ata=False, platform_verified=True):
    accounts, addresses, _, _ = research_snapshot(
        platform_verified=platform_verified, return_accounts=True)
    wallet = _encode(bytes([22])*32)
    decision = 'synthetic-isolated-decision-001'
    ata = associated_token_address(wallet, addresses['mint_a'])
    wsol, _ = ephemeral_wsol_address(wallet, decision)
    accounts[wallet] = dict(owner=SYSTEM_PROGRAM, executable=False,
                            data=['', 'base64'], lamports=10_000_000_000)
    accounts[ata] = None
    if has_ata or side == 'SELL':
        import base64
        raw = bytearray(165)
        raw[:32] = _decode(addresses['mint_a'])
        raw[32:64] = _decode(wallet)
        struct.pack_into('<Q', raw, 64, 1_000_000_000)
        raw[108] = 1
        accounts[ata] = dict(owner=TOKEN_PROGRAM, executable=False, lamports=2_039_280,
                            data=[base64.b64encode(raw).decode(), 'base64'])
    accounts[wsol] = None
    return dict(accounts=accounts, pool_address=addresses['pool'], mint=addresses['mint_a'],
        wallet=wallet, context_slot=1234, available_at_ms=1000, decision_at_ms=1100,
        side=side, amount_in=100_000_000, slippage_bps=100, max_slippage_bps=200,
        max_price_impact_bps=500,
        recent_blockhash=_encode(bytes([33])*32), last_valid_block_height=5000,
        rent_exempt_lamports=2_039_280, base_ata_rent_lamports=2_039_280,
        decision_id=decision, compute_unit_limit=200000,
        priority_fee_micro_lamports=10, max_priority_fee_lamports=2)


def test_shortvec_canonical_edges_and_type_refusals():
    assert [shortvec(i) for i in (0, 127, 128, 255, 65535)] == [
        b'\x00', b'\x7f', b'\x80\x01', b'\xff\x01', b'\xff\xff\x03']
    for value in (True, -1, 65536, 1.0, '1'):
        with pytest.raises(ValueError):
            shortvec(value)


def test_legacy_system_transfer_matches_independent_wire_vector():
    payer = _encode(bytes([1])*32)
    target = _encode(bytes([2])*32)
    blockhash = _encode(bytes([3])*32)
    data = struct.pack('<IQ', 2, 19)
    tx = compile_legacy((Instruction(SYSTEM_PROGRAM,
        (AM(payer, True, True), AM(target, False, True)), data),),
        fee_payer=payer, recent_blockhash=blockhash, last_valid_block_height=100)
    expected = (bytes((1, 0, 1, 3)) + bytes([1])*32 + bytes([2])*32 + bytes(32)
                + bytes([3])*32 + bytes((1, 2, 2, 0, 1, 12)) + data)
    assert tx.message == expected
    assert tx.unsigned_transaction() == b'\x01' + bytes(64) + expected
    assert tx.required_signers == (payer,)


def test_shared_account_privileges_are_unioned_but_program_cannot_be_writable():
    payer = _encode(bytes([1])*32)
    target = _encode(bytes([2])*32)
    instructions = (Instruction(SYSTEM_PROGRAM, (AM(target),), b'1'),
                    Instruction(SYSTEM_PROGRAM, (AM(target, False, True),), b'2'))
    tx = compile_legacy(instructions, fee_payer=payer, recent_blockhash=target,
                        last_valid_block_height=100)
    assert tx.account_keys == (payer, target, SYSTEM_PROGRAM)
    assert tx.message[:3] == bytes((1, 0, 1))
    with pytest.raises(ValueError, match='program_account_privilege_escalation'):
        compile_legacy((Instruction(SYSTEM_PROGRAM, (AM(SYSTEM_PROGRAM, False, True),), b''),),
            fee_payer=payer, recent_blockhash=target, last_valid_block_height=100)


def test_packet_size_and_exact_signature_vector_are_enforced():
    request = route_request()
    tx = build_launchlab_order(**request).transaction
    assert len(tx.unsigned_transaction()) <= 1232
    for signatures in ((), (bytes(63),), [bytes(64)], (bytes(64), bytes(64))):
        with pytest.raises(ValueError, match='signature_vector'):
            tx.transaction(signatures)
    with pytest.raises(ValueError, match='packet_limit'):
        compile_legacy((Instruction(SYSTEM_PROGRAM, (), b'A'*1200),),
            fee_payer=request['wallet'], recent_blockhash=request['recent_blockhash'],
            last_valid_block_height=100)


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_launchlab_exact_in_abi_account_order_quantities_and_fee_bounds(side):
    request = route_request(side)
    order = build_launchlab_order(**request)
    assert validate_prepared_order(order) == order
    assert order.network_fee_upper_lamports == 5002
    assert order.rent_deposit_lamports == (4_078_560 if side == 'BUY' else 2_039_280)
    header, keys, blockhash, instructions = _instructions(order.transaction.message)
    assert header[0] == 1 and keys[0] == request['wallet']
    assert blockhash == request['recent_blockhash']
    swaps = [i for i in instructions if i[0] == PROGRAM]
    assert len(swaps) == 1
    _, accounts, data = swaps[0]
    assert len(accounts) == 15
    assert accounts[0] == request['wallet']
    assert accounts[4:7] == (request['pool_address'], order.base_token_account, order.quote_token_account)
    assert accounts[9:13] == (request['mint'], 'So11111111111111111111111111111111111111112',
                               TOKEN_PROGRAM, TOKEN_PROGRAM)
    assert accounts[-1] == PROGRAM
    assert data[:8] == (BUY_EXACT_IN if side == 'BUY' else SELL_EXACT_IN)
    assert struct.unpack('<QQQ', data[8:]) == (100_000_000, order.minimum_out, 0)
    assert order.minimum_out == order.expected_output * 9900 // 10000
    assert instructions[-1] == (TOKEN_PROGRAM,
        (order.quote_token_account, request['wallet'], request['wallet']), b'\x09')
    assert sum(i[0] == ATA_PROGRAM for i in instructions) == (side == 'BUY')
    # These bytes prepare a transaction. No fake signature, RPC response, fill,
    # program deployment attestation or economic gain is asserted by the route.


def test_ephemeral_wsol_system_create_with_seed_matches_official_bincode_layout():
    request = route_request()
    order = build_launchlab_order(**request)
    ix = next(i for i in _instructions(order.transaction.message)[3] if i[0] == SYSTEM_PROGRAM)
    _, seed = ephemeral_wsol_address(request['wallet'], request['decision_id'])
    assert ix[1] == (request['wallet'], order.quote_token_account, request['wallet'])
    expected = (struct.pack('<I', 3) + _decode(request['wallet']) + struct.pack('<Q', 32)
        + seed.encode() + struct.pack('<QQ', 102_039_280, 165) + _decode(TOKEN_PROGRAM))
    assert ix[2] == expected
    assert _decode(order.quote_token_account) == hashlib.sha256(
        _decode(request['wallet']) + seed.encode() + _decode(TOKEN_PROGRAM)).digest()


@pytest.mark.parametrize('field,value,reason', [
    ('slippage_bps', 201, 'slippage'), ('max_slippage_bps', 10000, 'slippage'),
    ('amount_in', True, 'atomic'), ('amount_in', 2**64, 'atomic'),
    ('available_at_ms', 1200, 'asof'), ('decision_at_ms', 6001, 'asof'),
    ('compute_unit_limit', 1400001, 'compute'), ('max_priority_fee_lamports', 1, 'priority'),
    ('side', 'buy', 'BUY_or_SELL'), ('context_slot', 0, 'context_slot'),
])
def test_invalid_order_bounds_refuse_before_signing(field, value, reason):
    request = route_request()
    request[field] = value
    with pytest.raises(ValueError, match=reason):
        build_launchlab_order(**request)


def test_unknown_platform_identity_never_becomes_live_permission():
    with pytest.raises(ValueError, match='identity_unknown'):
        build_launchlab_order(**route_request(platform_verified=False))


def test_modified_pool_raw_bytes_and_authorities_fail_closed():
    request = route_request()
    request['accounts'][request['mint']]['executable'] = True
    with pytest.raises(ValueError, match='route_bank_unqualified'):
        build_launchlab_order(**request)


def test_no_drain_of_existing_wsol_and_no_invention_of_missing_account_observation():
    request = route_request()
    wsol, _ = ephemeral_wsol_address(request['wallet'], request['decision_id'])
    request['accounts'][wsol] = dict(lamports=100)
    with pytest.raises(ValueError, match='already_exists'):
        build_launchlab_order(**request)
    del request['accounts'][wsol]
    with pytest.raises(ValueError, match='explicit_user_account'):
        build_launchlab_order(**request)


def test_insufficient_fee_rent_balance_and_sell_inventory_refused():
    request = route_request()
    request['accounts'][request['wallet']]['lamports'] = 100_000_000
    with pytest.raises(ValueError, match='wallet_insufficient'):
        build_launchlab_order(**request)
    request = route_request('SELL')
    request['amount_in'] = 1_000_000_001
    with pytest.raises(ValueError, match='insufficient_owned'):
        build_launchlab_order(**request)


def test_prepared_intent_and_message_tampering_are_detected_by_full_rebuild():
    order = build_launchlab_order(**route_request())
    for corrupt in (
        replace(order, minimum_out=1),
        replace(order, transaction=replace(order.transaction, message=order.transaction.message[:-1] + b'X')),
        replace(order, semantic_digest='0'*64),
        replace(order, source_slot=order.source_slot+1),
    ):
        with pytest.raises(ValueError, match='modified'):
            validate_prepared_order(corrupt)


def test_rebuild_request_is_immutable_serialization_of_original_accounts():
    request = route_request()
    order = build_launchlab_order(**request)
    request['accounts'][request['wallet']]['lamports'] = 0
    assert validate_prepared_order(order) == order
    assert json.loads(order.rebuild_request_json)['accounts'][request['wallet']]['lamports'] == 10_000_000_000


def test_existing_safe_base_ata_is_reused_not_closed_or_recreated():
    order = build_launchlab_order(**route_request(has_ata=True))
    instructions = _instructions(order.transaction.message)[3]
    assert all(i[0] != ATA_PROGRAM for i in instructions)
    assert order.rent_deposit_lamports == 2_039_280
    assert instructions[-1][1][0] != order.base_token_account


def test_sell_does_not_require_new_buy_to_fit_near_fundraising_boundary():
    from bot.p3 import launchlab
    from test_p3_launchlab import mutate_account
    request = route_request('SELL')
    pool = launchlab._pool(request['accounts'][request['pool_address']])[0]
    mutate_account(request['accounts'], request['pool_address'], 69,
                   pool['real_b']+1, '<Q')
    # An additional buy is unavailable, but safe owned inventory can be sold.
    order = build_launchlab_order(**request)
    assert order.side == 'SELL' and order.minimum_out > 0
    bad_buy = deepcopy(request)
    bad_buy['side'] = 'BUY'
    with pytest.raises(ValueError, match='route_bank_unqualified'):
        build_launchlab_order(**bad_buy)
    request['accounts'][request['mint']]['executable'] = True
    with pytest.raises(ValueError, match='route_bank_unqualified'):
        build_launchlab_order(**request)


def test_token2022_route_refuses_explicitly_until_extension_route_is_certified():
    from bot.p3.launchlab import TOKEN_2022_PROGRAM
    request = route_request()
    request['accounts'][request['mint']]['owner'] = TOKEN_2022_PROGRAM
    with pytest.raises(ValueError, match='Token2022_live_route_not_certified'):
        build_launchlab_order(**request)


def test_curve_impact_bound_is_distinct_from_slippage_and_network_fee():
    request = route_request()
    order = build_launchlab_order(**request)
    assert 0 < order.price_impact_bps < request['max_price_impact_bps']
    request['max_price_impact_bps'] = 0
    with pytest.raises(ValueError, match='price_impact_limit'):
        build_launchlab_order(**request)


@pytest.mark.parametrize('side,idl_name', [('BUY', 'buy_exact_in'), ('SELL', 'sell_exact_in')])
def test_compiled_swap_uses_independently_retained_official_idl_discriminator_and_privileges(side, idl_name):
    abi = json.loads((Path(__file__).parents[1] / 'bot/live/launchlab_swap_abi.json').read_text())
    assert abi['source_git_blob'] == '70186e3f02c2bead7e5a9a92453104df853683ed'
    official = next(i for i in abi['instructions'] if i['name'] == idl_name)
    assert [a['type'] for a in official['args']] == ['u64', 'u64', 'u64']
    order = build_launchlab_order(**route_request(side))
    header, keys, _, instructions = _instructions(order.transaction.message)
    _, swap_accounts, data = next(i for i in instructions if i[0] == abi['address'])
    assert data[:8] == bytes(official['discriminator'])
    n_signers, readonly_signers, readonly_unsigned = header
    for address, entry in zip(swap_accounts, official['accounts'], strict=True):
        index = keys.index(address)
        signer = index < n_signers
        writable = (index < n_signers-readonly_signers if signer
                    else index < len(keys)-readonly_unsigned)
        assert signer == entry.get('signer', False)
        assert writable == entry.get('writable', False)


def test_total_sale_closes_the_base_token_account_and_a_partial_sale_never_does():
    wsol_close = lambda order, request: (TOKEN_PROGRAM,
        (order.quote_token_account, request['wallet'], request['wallet']), b'\x09')
    partial_request = route_request('SELL')
    partial = build_launchlab_order(**partial_request)
    instructions = _instructions(partial.transaction.message)[3]
    assert partial.input_amount < partial.base_balance_before
    assert instructions[-1] == wsol_close(partial, partial_request)
    assert all(i[1][0] != partial.base_token_account for i in instructions if i[2] == b'\x09')

    total_request = dict(route_request('SELL'), amount_in=1_000_000_000, max_price_impact_bps=5000)
    total = build_launchlab_order(**total_request)
    instructions = _instructions(total.transaction.message)[3]
    assert total.input_amount == total.base_balance_before == 1_000_000_000
    # the WSOL account is closed first, then the emptied base account: rent goes back to the wallet
    assert instructions[-2] == wsol_close(total, total_request)
    assert instructions[-1] == (TOKEN_PROGRAM,
        (total.base_token_account, total_request['wallet'], total_request['wallet']), b'\x09')
    assert sum(i[2] == b'\x09' for i in instructions) == 2
    assert total.transaction.required_signers == (total_request['wallet'],)
    assert validate_prepared_order(total) == total

    buy = build_launchlab_order(**route_request('BUY', has_ata=True))
    assert sum(i[2] == b'\x09' for i in _instructions(buy.transaction.message)[3]) == 1
