"""Offline Token-2022 LaunchLab route and cleanup, on synthetic fixtures only.

The Token-2022 fixtures are derived from the existing SPL route fixture: the
base mint gets the MetadataPointer (18) + TokenMetadata (19) extensions and
the Token-2022 owner, the pool's mint-program flag is set, the base vault is
owned by Token-2022 (165 bytes, as the frozen reader requires), and our ATA
is the 170-byte ImmutableOwner layout. Payloads are models, not executions.
"""
import base64
from copy import deepcopy
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from bot.live import route_dispatch
from bot.live.cleanup import (SUGGESTED_MAX_DUST_BURN_ATOMIC, build_base_account_cleanup,
                              reconcile_cleanup, validate_prepared_cleanup)
from bot.live.cleanup_token2022 import (
    PreparedBaseAccountCleanupToken2022, build_base_account_cleanup_token2022,
    reconcile_cleanup_token2022, validate_prepared_cleanup_token2022)
from bot.live.route import (
    ATA_PROGRAM, BUY_EXACT_IN, COMPUTE_BUDGET_PROGRAM, SELL_EXACT_IN, SYSTEM_PROGRAM,
    TOKEN_PROGRAM, PreparedLaunchLabOrder, associated_token_address, build_launchlab_order,
    ephemeral_wsol_address, validate_prepared_order)
from bot.live.route_token2022 import (
    TOKEN2022_ATA_LEN, TOKEN2022_ATA_RENT_LAMPORTS, PreparedLaunchLabOrderToken2022,
    build_launchlab_order_token2022, decode_token2022_ata, token2022_associated_token_address,
    validate_prepared_order_token2022)
from bot.p3 import launchlab
from bot.p3.certification import PROGRAM, _decode, _encode, find_program_address
from bot.p3.quotes import SOL_MINT
from bot.p3.token2022 import TOKEN_2022_PROGRAM
from test_live_cleanup_base_account import (FROZEN_CHAIN, cleanup_payload, cleanup_request,
                                            totally_sold)
from test_live_engine import configured, run, sell_request
from test_live_wire_route import _instructions, route_request
from test_p3_token2022 import metadata

T22 = TOKEN_2022_PROGRAM
SPL_RENT = 2_039_280
HELD = 1_000_000_000  # base inventory in the SPL fixture's existing ATA
# SPL cleanup messages computed at HEAD 96748264 with bot/live/cleanup.py untouched.
SPL_CLEANUP_PINS = {
    0: ('702e6bf32b8b0ef2e94fbe1fd7a589b2f09a0e61b6dabd499d0551914c4f3670',
        'db62f80fe0f9d8c5d53ede1aaef6ab445ac3a025e5053943562d351f62b89ff8'),
    7: ('288993ad0522369ffba6065b50ed8bf7f9e3dde3b4da433855d3bec4a24c7962',
        'f4f6c05076d498dfd75a204783dd55b615612149e6b00de92e0cd0ec65c309d0'),
}


# ---------------------------------------------------------------- fixtures

def _b64(raw):
    return base64.b64encode(bytes(raw)).decode()


def _raw(account):
    return bytearray(base64.b64decode(account['data'][0]))


def _convert_mint(account, mint, extra=()):
    """SPL fixture mint bytes + AccountType::Mint + 18/19 (+ extra TLVs)."""
    raw = bytes(_raw(account))
    ext = metadata(mint=_decode(mint))
    raw += (bytes(83) + b'\1' + struct.pack('<HH', 18, 64) + bytes(32) + _decode(mint)
            + struct.pack('<HH', 19, len(ext)) + ext)
    for kind, value in extra:
        raw += struct.pack('<HH', kind, len(value)) + value
    account['data'][0] = _b64(raw)
    account['owner'] = T22


def t22_ata_account(mint, wallet, amount, *, suffix=b'\2' + struct.pack('<HH', 7, 0),
                    lamports=TOKEN2022_ATA_RENT_LAMPORTS):
    raw = bytearray(165)
    raw[:32] = _decode(mint)
    raw[32:64] = _decode(wallet)
    struct.pack_into('<Q', raw, 64, amount)
    raw[108] = 1
    return dict(owner=T22, executable=False, lamports=lamports,
                data=[_b64(bytes(raw) + suffix), 'base64'])


def to_token2022(request, *, extra_mint_extensions=()):
    """Turn an SPL route request into its Token-2022 counterpart."""
    request = deepcopy(request)
    accounts, mint, wallet = request['accounts'], request['mint'], request['wallet']
    _convert_mint(accounts[mint], mint, extra_mint_extensions)
    pool = accounts[request['pool_address']]
    raw = _raw(pool); raw[365] = 1; pool['data'][0] = _b64(raw)
    accounts[launchlab._pool(pool)[0]['vault_a']]['owner'] = T22
    old = accounts.pop(associated_token_address(wallet, mint))
    ata = token2022_associated_token_address(wallet, mint)
    accounts[ata] = None if old is None else t22_ata_account(
        mint, wallet, struct.unpack_from('<Q', _raw(old), 64)[0])
    request['base_ata_rent_lamports'] = TOKEN2022_ATA_RENT_LAMPORTS
    return request


def t22_request(side='BUY', **kwargs):
    return to_token2022(route_request(side, **kwargs))


def t22_sell(quantity, held, decision):
    return to_token2022(sell_request(quantity, held, decision))


def ata_of(request):
    return token2022_associated_token_address(request['wallet'], request['mint'])


def set_ata(request, account):
    request['accounts'][ata_of(request)] = account


def mutate_ata(request, offset, value, fmt='<I'):
    account = request['accounts'][ata_of(request)]
    raw = _raw(account)
    if isinstance(value, bytes):
        raw[offset:offset + len(value)] = value
    else:
        struct.pack_into(fmt, raw, offset, value)
    account['data'][0] = _b64(raw)


def mutate_mint(request, offset, value):
    account = request['accounts'][request['mint']]
    raw = _raw(account); raw[offset:offset + len(value)] = value
    account['data'][0] = _b64(raw)


def swap_of(order):
    header, keys, _, instructions = _instructions(order.transaction.message)
    return header, keys, instructions, next(i for i in instructions if i[0] == PROGRAM)


def privileges(header, keys, address):
    n_signers, readonly_signers, readonly_unsigned = header
    index = keys.index(address)
    signer = index < n_signers
    writable = (index < n_signers - readonly_signers if signer
                else index < len(keys) - readonly_unsigned)
    return signer, writable


# ------------------------------------------- SPL chain unchanged (pinned)

def test_spl_route_messages_still_match_the_frozen_chain_pins():
    buy = build_launchlab_order(**route_request())
    quantity = buy.expected_output
    built = dict(BUY=buy,
        PARTIAL=build_launchlab_order(**sell_request(quantity // 2, quantity, 'golden-partial')),
        TOTAL=build_launchlab_order(**sell_request(quantity, quantity, 'golden-total')))
    for name, order in built.items():
        assert type(order) is PreparedLaunchLabOrder
        assert (hashlib.sha256(order.transaction.message).hexdigest(),
                order.semantic_digest) == FROZEN_CHAIN[name], name


@pytest.mark.parametrize('leftover', sorted(SPL_CLEANUP_PINS))
def test_spl_cleanup_messages_are_pinned_and_unchanged(leftover):
    cleanup = build_base_account_cleanup(**cleanup_request(leftover))
    assert (hashlib.sha256(cleanup.transaction.message).hexdigest(),
            cleanup.semantic_digest) == SPL_CLEANUP_PINS[leftover]


def test_spl_route_still_refuses_a_full_token2022_request():
    request = t22_request()
    request['base_ata_rent_lamports'] = SPL_RENT
    with pytest.raises(ValueError, match='^Token2022_live_route_not_certified$'):
        build_launchlab_order(**request)


def test_spl_cleanup_still_refuses_a_token2022_mint():
    request = t22_cleanup_request()
    # The SPL builder derives the classic ATA; give it an explicit observation.
    request['accounts'][associated_token_address(request['wallet'], request['mint'])] = None
    with pytest.raises(ValueError, match='^Token2022_cleanup_not_certified$'):
        build_base_account_cleanup(**request)


# ------------------------------------------------------------ BUY / SELL

def test_token2022_ata_is_derived_with_the_token2022_program_seed():
    request = t22_request()
    wallet, mint = request['wallet'], request['mint']
    expected = find_program_address((_decode(wallet), _decode(T22), _decode(mint)),
                                    program_id=ATA_PROGRAM)[0]
    assert ata_of(request) == expected != associated_token_address(wallet, mint)
    assert TOKEN2022_ATA_LEN == 170
    assert TOKEN2022_ATA_RENT_LAMPORTS == 2_074_080 == (170 + 128) * 3480 * 2


def test_buy_without_ata_creates_it_with_token2022_and_matches_the_idl():
    request = t22_request()
    order = build_launchlab_order_token2022(**request)
    assert type(order) is PreparedLaunchLabOrderToken2022
    header, keys, instructions, swap = swap_of(order)
    wallet, mint, ata = request['wallet'], request['mint'], ata_of(request)
    wsol, _ = ephemeral_wsol_address(wallet, request['decision_id'])
    assert order.transaction.required_signers == (wallet,) and header[0] == 1
    assert [i[0] for i in instructions] == [
        COMPUTE_BUDGET_PROGRAM, COMPUTE_BUDGET_PROGRAM, ATA_PROGRAM, SYSTEM_PROGRAM,
        TOKEN_PROGRAM, TOKEN_PROGRAM, PROGRAM, TOKEN_PROGRAM]
    create = instructions[2]
    assert create[1] == (wallet, ata, wallet, mint, SYSTEM_PROGRAM, T22) and create[2] == b'\x01'
    # Temporary WSOL stays on the classic token program, 165 bytes.
    system = instructions[3]
    assert system[1] == (wallet, wsol, wallet)
    assert system[2][-40:] == struct.pack('<Q', 165) + _decode(TOKEN_PROGRAM)
    funding = struct.unpack_from('<Q', system[2], len(system[2]) - 48)[0]
    assert funding == request['rent_exempt_lamports'] + request['amount_in']
    assert instructions[4][1] == (wsol, SOL_MINT) and instructions[4][2][:1] == b'\x12'
    assert instructions[5] == (TOKEN_PROGRAM, (wsol,), b'\x11')
    assert instructions[7] == (TOKEN_PROGRAM, (wsol, wallet, wallet), b'\x09')
    # Swap: IDL account order and privileges, Token-2022 base program.
    abi = json.loads((Path(__file__).parents[1] / 'bot/live/launchlab_swap_abi.json').read_text())
    official = next(i for i in abi['instructions'] if i['name'] == 'buy_exact_in')
    assert len(swap[1]) == len(official['accounts']) == 15
    for address, entry in zip(swap[1], official['accounts'], strict=True):
        assert privileges(header, keys, address) == (entry.get('signer', False),
                                                     entry.get('writable', False)), entry['name']
        if 'address' in entry:
            assert address == entry['address']
    roles = dict(zip((a['name'] for a in official['accounts']), swap[1]))
    assert roles['user_base_token'] == ata and roles['user_quote_token'] == wsol
    assert roles['base_token_mint'] == mint and roles['quote_token_mint'] == SOL_MINT
    assert roles['base_token_program'] == T22 and roles['quote_token_program'] == TOKEN_PROGRAM
    assert roles['program'] == PROGRAM == abi['address']
    assert swap[2] == BUY_EXACT_IN + struct.pack('<QQQ', request['amount_in'],
                                                 order.minimum_out, 0)
    assert bytes(official['discriminator']) == BUY_EXACT_IN
    # Amounts, slippage and costs.
    assert order.minimum_out == order.expected_output * (10000 - request['slippage_bps']) // 10000
    assert order.minimum_out > 0 and order.input_is_native and order.base_balance_before == 0
    assert order.rent_deposit_lamports == SPL_RENT + 2_074_080
    assert order.network_fee_upper_lamports == 5000 + 2
    assert order.base_token_account == ata and order.base_token_program == T22
    # Same curve arithmetic as the SPL route on the same reserves.
    spl = build_launchlab_order(**route_request())
    assert (order.expected_output, order.minimum_out, order.price_impact_bps) == (
        spl.expected_output, spl.minimum_out, spl.price_impact_bps)
    assert validate_prepared_order_token2022(order) == order


def test_buy_with_existing_170_byte_ata_does_not_recreate_or_redeposit():
    request = t22_request(has_ata=True)
    order = build_launchlab_order_token2022(**request)
    _, _, instructions, swap = swap_of(order)
    assert ATA_PROGRAM not in [i[0] for i in instructions]
    assert swap[1][5] == ata_of(request) and swap[1][11] == T22
    assert order.base_balance_before == HELD
    assert order.rent_deposit_lamports == SPL_RENT
    facts, raw = decode_token2022_ata(request['accounts'][ata_of(request)])
    assert len(raw) == 170 and facts['extension_types'] == [7] and facts['amount_atomic'] == HELD


@pytest.mark.parametrize('kind', ['PARTIAL', 'TOTAL'])
def test_partial_and_total_sell_route_and_never_touch_the_base_account(kind):
    buy = build_launchlab_order_token2022(**t22_request())
    quantity = buy.expected_output
    amount = quantity // 2 if kind == 'PARTIAL' else quantity
    request = t22_sell(amount, quantity, 't22-' + kind.lower())
    order = build_launchlab_order_token2022(**request)
    header, keys, instructions, swap = swap_of(order)
    wsol, _ = ephemeral_wsol_address(request['wallet'], request['decision_id'])
    assert order.side == 'SELL' and not order.input_is_native
    assert [i[0] for i in instructions] == [
        COMPUTE_BUDGET_PROGRAM, COMPUTE_BUDGET_PROGRAM, SYSTEM_PROGRAM,
        TOKEN_PROGRAM, TOKEN_PROGRAM, PROGRAM, TOKEN_PROGRAM]
    funding = struct.unpack_from('<Q', instructions[2][2], len(instructions[2][2]) - 48)[0]
    assert funding == request['rent_exempt_lamports']
    assert swap[2] == SELL_EXACT_IN + struct.pack('<QQQ', amount, order.minimum_out, 0)
    assert swap[1][11] == T22 and swap[1][12] == TOKEN_PROGRAM
    abi = json.loads((Path(__file__).parents[1] / 'bot/live/launchlab_swap_abi.json').read_text())
    official = next(i for i in abi['instructions'] if i['name'] == 'sell_exact_in')
    for address, entry in zip(swap[1], official['accounts'], strict=True):
        assert privileges(header, keys, address) == (entry.get('signer', False),
                                                     entry.get('writable', False))
    # Only the temporary WSOL account is closed; no Burn, no base close.
    assert [i for i in instructions if i[2][:1] in (b'\x08', b'\x09')] == [
        (TOKEN_PROGRAM, (wsol, request['wallet'], request['wallet']), b'\x09')]
    assert T22 not in [i[0] for i in instructions]
    assert order.rent_deposit_lamports == SPL_RENT
    assert order.base_balance_before == quantity
    assert order.minimum_out == order.expected_output * 9900 // 10000 > 0
    spl = build_launchlab_order(**sell_request(amount, quantity, 't22-' + kind.lower()))
    assert (order.expected_output, order.minimum_out) == (spl.expected_output, spl.minimum_out)
    assert validate_prepared_order_token2022(order) == order


# ---------------------------------------------------- full-rebuild checks

def test_full_rebuild_detects_every_modified_message_byte_and_every_field():
    order = build_launchlab_order_token2022(**t22_request())
    message = order.transaction.message
    for index in range(len(message)):
        changed = bytearray(message); changed[index] ^= 1
        forged = replace(order, transaction=replace(order.transaction, message=bytes(changed)))
        with pytest.raises(ValueError, match='prepared_route_or_wire_modified'):
            validate_prepared_order_token2022(forged)
    for field in fields(order):
        if field.name in ('transaction', 'rebuild_request_json', 'source_pins'):
            continue
        value = getattr(order, field.name)
        other = (not value if type(value) is bool else value + 1 if type(value) is int
                 else ('BUY' if value == 'SELL' else 'SELL') if field.name == 'side'
                 else TOKEN_PROGRAM if field.name == 'base_token_program' else value + 'x')
        with pytest.raises(ValueError, match='prepared_route_or_wire_modified'):
            validate_prepared_order_token2022(replace(order, **{field.name: other}))
    with pytest.raises(ValueError, match='prepared_route_or_wire_modified'):
        validate_prepared_order_token2022(replace(order, source_pins=()))
    request = json.loads(order.rebuild_request_json)
    request['amount_in'] += 1
    with pytest.raises(ValueError, match='prepared_route_or_wire_modified'):
        validate_prepared_order_token2022(replace(order, rebuild_request_json=json.dumps(request)))
    request['base_ata_rent_lamports'] = SPL_RENT
    with pytest.raises(ValueError, match='prepared_route_rebuild_failed'):
        validate_prepared_order_token2022(replace(order, rebuild_request_json=json.dumps(request)))


def test_validators_do_not_cross_routes():
    t22 = build_launchlab_order_token2022(**t22_request())
    spl = build_launchlab_order(**route_request())
    with pytest.raises(ValueError, match='^router_generated_order_required$'):
        validate_prepared_order(t22)
    with pytest.raises(ValueError, match='^token2022_router_generated_order_required$'):
        validate_prepared_order_token2022(spl)
    # Re-labelling the Token-2022 order as an SPL order fails its SPL rebuild.
    disguised = PreparedLaunchLabOrder(**{f.name: getattr(t22, f.name)
                                          for f in fields(PreparedLaunchLabOrder)})
    with pytest.raises(ValueError, match='^prepared_route_rebuild_failed$'):
        validate_prepared_order(disguised)


# -------------------------------------------------------------- refusals

FORBIDDEN_MINT_EXTENSIONS = {
    'TransferFeeConfig': (1, bytes(108)),
    'MintCloseAuthority': (3, bytes(32)),
    'DefaultAccountState': (6, b'\x02'),
    'NonTransferable': (9, b''),
    'InterestBearingConfig': (10, bytes(52)),
    'PermanentDelegate': (12, bytes([5]) * 32),
    'TransferHook': (14, bytes(64)),
    'GroupPointer': (20, bytes(64)),
    'ScaledUiAmount': (25, bytes(56)),
    'Pausable': (26, bytes(33)),
    'PermissionedBurn': (28, bytes(32)),
    'unknown_29': (29, b''),
    'unknown_65535': (65535, bytes(4)),
}


@pytest.mark.parametrize('name', sorted(FORBIDDEN_MINT_EXTENSIONS))
@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_each_forbidden_mint_extension_refuses_with_explicit_reason(name, side):
    request = to_token2022(route_request(side),
                           extra_mint_extensions=(FORBIDDEN_MINT_EXTENSIONS[name],))
    with pytest.raises(ValueError, match='^token2022_mint_refused:mint_extension_not_supported$'):
        build_launchlab_order_token2022(**request)


def test_duplicate_or_malformed_mint_extensions_refuse():
    request = to_token2022(route_request(), extra_mint_extensions=((18, bytes(64)),))
    with pytest.raises(ValueError, match='^token2022_mint_refused:mint_duplicate_extension$'):
        build_launchlab_order_token2022(**request)
    request = t22_request()
    mutate_mint(request, 165, b'\x02')  # AccountType::Account on a mint
    with pytest.raises(ValueError, match='^token2022_mint_refused:mint_padding_or_account_type_invalid$'):
        build_launchlab_order_token2022(**request)


@pytest.mark.parametrize('offset,reason', [
    (0, 'token2022_mint_authority_present'),
    (46, 'token2022_freeze_authority_present')])
def test_mint_or_freeze_authority_refuses(offset, reason):
    request = t22_request()
    mutate_mint(request, offset, struct.pack('<I', 1) + bytes([9]) * 32)
    with pytest.raises(ValueError, match='^' + reason + '$'):
        build_launchlab_order_token2022(**request)


def test_spl_mint_passed_to_the_token2022_route_refuses():
    request = route_request()
    request['base_ata_rent_lamports'] = TOKEN2022_ATA_RENT_LAMPORTS
    with pytest.raises(ValueError, match='^token2022_route_requires_token2022_mint$'):
        build_launchlab_order_token2022(**request)


def test_wrong_ata_rent_or_unflagged_pool_or_spl_vault_refuse():
    request = t22_request()
    request['base_ata_rent_lamports'] = SPL_RENT
    with pytest.raises(ValueError, match='^token2022_ATA_rent_must_be_2074080$'):
        build_launchlab_order_token2022(**request)
    request = t22_request()
    pool = request['accounts'][request['pool_address']]
    raw = _raw(pool); raw[365] = 0; pool['data'][0] = _b64(raw)
    with pytest.raises(ValueError, match='^route_bank_unqualified:'):
        build_launchlab_order_token2022(**request)
    request = t22_request()
    vault = launchlab._pool(request['accounts'][request['pool_address']])[0]['vault_a']
    request['accounts'][vault]['owner'] = TOKEN_PROGRAM
    with pytest.raises(ValueError, match='^route_bank_unqualified:'):
        build_launchlab_order_token2022(**request)


def test_a_170_byte_immutable_owner_base_vault_is_refused_by_the_frozen_reader():
    """Documents the frozen limit: decode_vault reads 165-byte vaults only."""
    request = t22_request()
    vault = launchlab._pool(request['accounts'][request['pool_address']])[0]['vault_a']
    account = request['accounts'][vault]
    account['data'][0] = _b64(bytes(_raw(account)) + b'\2' + struct.pack('<HH', 7, 0))
    analysis = launchlab.analyze_snapshot(request['accounts'], context_slot=1234,
        expected_mint=request['mint'], pool_address=request['pool_address'],
        input_lamports=request['amount_in'], evidence_profile='published_metadata_v1')
    assert 'base_vault_vault_extensions_not_supported' in analysis['risk_flags']
    with pytest.raises(ValueError, match='^route_bank_unqualified:'):
        build_launchlab_order_token2022(**request)


@pytest.mark.parametrize('suffix,reason', [
    (b'', 'token2022_ATA_length_not_170'),
    (b'\2' + struct.pack('<HH', 7, 0) + struct.pack('<HH', 8, 1) + b'\1',
     'token2022_ATA_length_not_170'),  # + MemoTransfer
    (b'\2' + struct.pack('<HH', 7, 0) + bytes(4), 'token2022_ATA_length_not_170'),
    (b'\2' + struct.pack('<HH', 11, 0), 'token2022_ATA_extension_not_allowed'),  # CpiGuard
    (b'\2' + struct.pack('<HH', 2, 0), 'token2022_ATA_extension_not_allowed'),
    (b'\2' + struct.pack('<HH', 7, 1), 'token2022_ATA_extension_not_allowed'),
    (b'\1' + struct.pack('<HH', 7, 0), 'token2022_ATA_account_type_invalid'),
    (b'\0' + struct.pack('<HH', 7, 0), 'token2022_ATA_account_type_invalid')])
def test_ata_with_extra_or_wrong_extension_or_length_refuses(suffix, reason):
    request = t22_request('SELL')
    set_ata(request, t22_ata_account(request['mint'], request['wallet'], HELD, suffix=suffix))
    with pytest.raises(ValueError, match='^' + reason + '$'):
        build_launchlab_order_token2022(**request)


def test_ata_owned_by_the_classic_program_refuses():
    request = t22_request('SELL')
    request['accounts'][ata_of(request)]['owner'] = TOKEN_PROGRAM
    with pytest.raises(ValueError, match='^token2022_ATA_owner_or_executable_invalid$'):
        build_launchlab_order_token2022(**request)


@pytest.mark.parametrize('offset,value,fmt', [
    (72, 1, '<I'),            # delegate present
    (129, 1, '<I'),           # close authority present
    (108, 2, '<B'),           # frozen
    (32, bytes([44]) * 32, None),   # foreign owner
    (0, bytes([45]) * 32, None)])   # foreign mint
def test_ata_with_delegate_close_authority_frozen_or_foreign_refuses(offset, value, fmt):
    request = t22_request('SELL')
    mutate_ata(request, offset, value, fmt)
    with pytest.raises(ValueError, match='^unsafe_or_foreign_user_base_ATA$'):
        build_launchlab_order_token2022(**request)


def test_insufficient_inventory_refuses():
    request = t22_sell(HELD + 1, HELD, 't22-over-sell')
    with pytest.raises(ValueError, match='^insufficient_owned_token_inventory$'):
        build_launchlab_order_token2022(**request)
    request = t22_request('SELL')
    request['accounts'][ata_of(request)] = None
    with pytest.raises(ValueError, match='^insufficient_owned_token_inventory$'):
        build_launchlab_order_token2022(**request)


def test_wallet_must_cover_input_both_rents_and_fee_exactly():
    request = t22_request()
    need = request['amount_in'] + SPL_RENT + TOKEN2022_ATA_RENT_LAMPORTS + 5002
    request['accounts'][request['wallet']]['lamports'] = need
    assert build_launchlab_order_token2022(**request).wallet_lamports_before == need
    request['accounts'][request['wallet']]['lamports'] = need - 1
    with pytest.raises(ValueError, match='^wallet_insufficient_for_input_rent_and_fees$'):
        build_launchlab_order_token2022(**request)


def test_sale_on_a_pool_state_that_cannot_pay_is_refused_by_the_curve():
    request = t22_request('SELL')
    pool = request['accounts'][request['pool_address']]
    raw = _raw(pool); struct.pack_into('<Q', raw, 61, 1); pool['data'][0] = _b64(raw)  # real_b
    with pytest.raises(ValueError, match='observed_exit_liquidity_insufficient'):
        build_launchlab_order_token2022(**request)
    request = t22_sell(10**14 + 1, 10**14 + 1, 't22-beyond-curve')  # > real_a
    with pytest.raises(ValueError, match='sell_exceeds_observed_outstanding_curve_tokens'):
        build_launchlab_order_token2022(**request)


# -------------------------------- engine: refused unless Token-2022 is authorized
# (Before the engine wiring these tests pinned "not reachable". Wired now, they pin the refusal by default:
#  an envelope that does not list the Token-2022 program admits nothing, and nothing is signed or sent.)

def test_engine_refuses_a_token2022_order_without_journal_signature_or_send(tmp_path):
    for side in ('BUY', 'SELL'):
        # BUY and SELL fixtures share one decision id: one fresh journal per side.
        (tmp_path / side).mkdir(mode=0o700)
        engine, _, rpc, signer, _ = configured(tmp_path / side)
        order = build_launchlab_order_token2022(**t22_request(side))
        decision = json.loads(order.rebuild_request_json)['decision_id']
        with pytest.raises(ValueError, match='program_not_authorized'):
            run(engine.execute(decision, order))
        disguised = PreparedLaunchLabOrder(**{f.name: getattr(order, f.name)
                                              for f in fields(PreparedLaunchLabOrder)})
        with pytest.raises(ValueError, match='^prepared_route_rebuild_failed$'):
            run(engine.execute(decision + '-disguised', disguised))
        assert engine.journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 0
        assert not rpc.send_calls and signer.calls == 0
    assert route_dispatch.route_kind(order) == 'LAUNCHLAB_TOKEN2022'


def test_engine_cleanup_route_refuses_the_token2022_cleanup(tmp_path):
    """The default SPL cleanup kind still refuses a Token-2022 cleanup object: kinds never cross."""
    engine, buy, sell, _, rpc, signer = totally_sold(tmp_path)
    sends, signs = len(rpc.send_calls), signer.calls
    orders = engine.journal.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    cleanup = build_base_account_cleanup_token2022(**t22_cleanup_request(decision='t22-cleanup-e'))
    with pytest.raises(ValueError, match='^builder_generated_cleanup_required$'):
        run(engine.cleanup('t22-cleanup-e', mint=buy.mint, wallet=buy.user,
                           build=lambda bound: cleanup))
    for check in (route_dispatch.validate_execution_order, validate_prepared_cleanup):
        with pytest.raises(ValueError):
            check(cleanup)
    assert engine.journal.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == orders
    assert len(rpc.send_calls) == sends and signer.calls == signs
    assert engine.journal.cleanup('t22-cleanup-e')['outcome'] == 'NOT_SENT'
    assert engine.journal.get('t22-cleanup-e') is None


# --------------------------------------------------------------- cleanup

def t22_cleanup_request(leftover=0, *, decision='t22-fixture-cleanup-0', **changes):
    source = t22_request('SELL')
    wallet, mint = source['wallet'], source['mint']
    ata = ata_of(source)
    request = dict(accounts={wallet: source['accounts'][wallet], mint: source['accounts'][mint],
                             ata: t22_ata_account(mint, wallet, leftover)},
        mint=mint, wallet=wallet, context_slot=1300, available_at_ms=1000,
        decision_at_ms=1100, recent_blockhash=_encode(bytes([34]) * 32),
        last_valid_block_height=5000, decision_id=decision,
        max_dust_burn_atomic=SUGGESTED_MAX_DUST_BURN_ATOMIC,
        compute_unit_limit=20_000, priority_fee_micro_lamports=10, max_priority_fee_lamports=2)
    request.update(changes)
    return request


def t22_cleanup_payload(cleanup, signature, **kwargs):
    payload = cleanup_payload(cleanup, signature, rent=TOKEN2022_ATA_RENT_LAMPORTS, **kwargs)
    for label in ('preTokenBalances', 'postTokenBalances'):
        for entry in payload['meta'][label]:
            entry['programId'] = T22
    return payload


def test_total_sale_then_close_only_on_token2022():
    quantity = build_launchlab_order_token2022(**t22_request()).expected_output
    total = build_launchlab_order_token2022(**t22_sell(quantity, quantity, 't22-total'))
    assert total.input_amount == total.base_balance_before == quantity
    cleanup = build_base_account_cleanup_token2022(**t22_cleanup_request(0))
    assert type(cleanup) is PreparedBaseAccountCleanupToken2022
    header, keys, _, instructions = _instructions(cleanup.transaction.message)
    wallet = cleanup.user
    assert cleanup.base_token_account == total.base_token_account
    assert cleanup.token_program == T22 and cleanup.transaction.required_signers == (wallet,)
    assert [i[0] for i in instructions] == [COMPUTE_BUDGET_PROGRAM, COMPUTE_BUDGET_PROGRAM, T22]
    assert instructions[2] == (T22, (cleanup.base_token_account, wallet, wallet), b'\x09')
    assert TOKEN_PROGRAM not in keys and cleanup.burn_amount == 0
    assert cleanup.account_lamports_observed == TOKEN2022_ATA_RENT_LAMPORTS
    assert privileges(header, keys, cleanup.base_token_account) == (False, True)
    assert validate_prepared_cleanup_token2022(cleanup) == cleanup


def test_dust_is_burned_then_closed_on_token2022_and_bound_is_enforced():
    cleanup = build_base_account_cleanup_token2022(**t22_cleanup_request(7))
    header, keys, _, instructions = _instructions(cleanup.transaction.message)
    wallet, ata, mint = cleanup.user, cleanup.base_token_account, cleanup.mint
    assert instructions[2:] == [
        (T22, (ata, mint, wallet), b'\x08' + struct.pack('<Q', 7)),
        (T22, (ata, wallet, wallet), b'\x09')]
    assert privileges(header, keys, mint) == (False, True)
    assert cleanup.burn_amount == 7
    with pytest.raises(ValueError, match='^leftover_exceeds_retained_dust_bound_account_left_open$'):
        build_base_account_cleanup_token2022(**t22_cleanup_request(SUGGESTED_MAX_DUST_BURN_ATOMIC + 1))


def test_token2022_cleanup_refusals():
    request = t22_cleanup_request()
    spl = cleanup_request()  # classic mint and classic ATA
    with pytest.raises(ValueError, match='^cleanup_token2022_route_requires_token2022_mint$'):
        build_base_account_cleanup_token2022(**dict(request, accounts={
            **request['accounts'], request['mint']: spl['accounts'][spl['mint']]}))
    for name in ('PermanentDelegate', 'TransferHook', 'unknown_29'):
        bad = t22_cleanup_request()
        account = bad['accounts'][bad['mint']]
        kind, value = FORBIDDEN_MINT_EXTENSIONS[name]
        account['data'][0] = _b64(bytes(_raw(account)) + struct.pack('<HH', kind, len(value)) + value)
        with pytest.raises(ValueError, match='^cleanup_token2022_mint_refused:mint_extension_not_supported$'):
            build_base_account_cleanup_token2022(**bad)
    for suffix in (b'', b'\2' + struct.pack('<HH', 11, 0)):
        bad = t22_cleanup_request()
        ata = token2022_associated_token_address(bad['wallet'], bad['mint'])
        bad['accounts'][ata] = t22_ata_account(bad['mint'], bad['wallet'], 0, suffix=suffix)
        with pytest.raises(ValueError, match='^unsafe_or_foreign_user_base_ATA$'):
            build_base_account_cleanup_token2022(**bad)
    bad = t22_cleanup_request()
    bad['accounts'][token2022_associated_token_address(bad['wallet'], bad['mint'])] = None
    with pytest.raises(ValueError, match='^base_token_account_absent_nothing_to_close$'):
        build_base_account_cleanup_token2022(**bad)
    cleanup = build_base_account_cleanup_token2022(**request)
    for field in ('burn_amount', 'account_lamports_observed', 'network_fee_upper_lamports'):
        with pytest.raises(ValueError, match='prepared_cleanup_or_wire_modified'):
            validate_prepared_cleanup_token2022(replace(cleanup, **{field: getattr(cleanup, field) + 1}))
    with pytest.raises(ValueError, match='prepared_cleanup_or_wire_modified'):
        validate_prepared_cleanup_token2022(replace(cleanup, token_program=TOKEN_PROGRAM))
    message = bytearray(cleanup.transaction.message); message[-1] ^= 1
    with pytest.raises(ValueError, match='prepared_cleanup_or_wire_modified'):
        validate_prepared_cleanup_token2022(replace(cleanup, transaction=replace(
            cleanup.transaction, message=bytes(message))))


def test_standalone_reconciliation_returns_the_deposit_never_as_sale_proceeds():
    for leftover in (0, 7):
        cleanup = build_base_account_cleanup_token2022(**t22_cleanup_request(leftover))
        signature = _encode(bytes([77]) * 64)
        result = reconcile_cleanup_token2022(cleanup, signature,
                                             t22_cleanup_payload(cleanup, signature))
        assert result['account_closed'] is True and result['chain_error'] is None
        assert result['deposit_returned_lamports'] == TOKEN2022_ATA_RENT_LAMPORTS
        assert result['wallet_delta_lamports'] == TOKEN2022_ATA_RENT_LAMPORTS - 5001
        assert result['cost_lamports'] == result['fee_lamports'] == 5001
        assert result['burned_atomic'] == leftover
        assert (result['sale_proceeds_lamports'], result['gross_output_lamports'],
                result['market_pnl_lamports']) == (0, 0, 0)
        assert result['token_program'] == T22
    failed = reconcile_cleanup_token2022(cleanup, signature,
        t22_cleanup_payload(cleanup, signature, error={'InstructionError': [3, 'Custom']}))
    assert failed['account_closed'] is False and failed['deposit_returned_lamports'] == 0
    assert failed['wallet_delta_lamports'] == -5001
    with pytest.raises(ValueError, match='base_token_account_not_closed_at_finality'):
        reconcile_cleanup_token2022(cleanup, signature,
                                    t22_cleanup_payload(cleanup, signature, closed=False))
    payload = t22_cleanup_payload(cleanup, signature)
    payload['meta']['preTokenBalances'][0]['programId'] = TOKEN_PROGRAM
    with pytest.raises(ValueError, match='cleanup_token_balance_entry_invalid'):
        reconcile_cleanup_token2022(cleanup, signature, payload)
    payload = t22_cleanup_payload(cleanup, signature)
    payload['meta']['postBalances'][payload['transaction']['message']['accountKeys'].index(
        cleanup.user)] += 1  # one extra lamport cannot be explained
    with pytest.raises(ValueError, match='cleanup_native_cash_flow_unexplained'):
        reconcile_cleanup_token2022(cleanup, signature, payload)
    with pytest.raises(ValueError, match='builder_generated_cleanup_required'):
        reconcile_cleanup(cleanup, signature, t22_cleanup_payload(cleanup, signature))
