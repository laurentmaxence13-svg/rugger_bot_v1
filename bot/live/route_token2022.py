"""Token-2022 variant of the pinned LaunchLab exact-input route (OFFLINE ONLY).

Separate code from ``route.build_launchlab_order``, which is unchanged and
keeps refusing Token-2022 mints. This module accepts ONLY the allowlist of
POLITIQUE_TOKEN2022_v1:

* the base mint is owned by Token-2022 and the frozen reader
  ``bot.p3.token2022.decode_mint`` accepts it (mint extensions MetadataPointer
  18 and TokenMetadata 19 only), with no mint and no freeze authority, and the
  frozen ``launchlab.analyze_snapshot`` (published_metadata_v1) + frozen
  ``snapshot_safety_reason`` qualify the whole pool;
* our associated token account, when it exists, is exactly the 170-byte
  layout the associated-token-account program creates for Token-2022: the
  165-byte base, AccountType=Account (2) and ONE ImmutableOwner TLV (type 7,
  length 0). Anything else refuses, unknown included.

It is NOT reachable from the engine: ``route_dispatch.validate_execution_order``
and ``route_kind`` only accept ``PreparedLaunchLabOrder`` (exact type), and
``PreparedLaunchLabOrderToken2022`` is a distinct type. Wiring it into the
engine needs its own audit and GO. No HTTP, signer, wallet loading or funds.
"""
from dataclasses import dataclass
import base64
import hashlib
import json
import struct

from bot.live.route import (
    ATA_PROGRAM, BUY_EXACT_IN, COMPUTE_BUDGET_PROGRAM, SELL_EXACT_IN, SWAP_WRITABLE,
    SYSTEM_PROGRAM, TOKEN_PROGRAM, _u64, associated_token_address, ephemeral_wsol_address)
from bot.live.wire import AccountMeta as AM, Instruction, PreparedTransaction, compile_legacy
from bot.p3 import launchlab
from bot.p3.certification import PROGRAM, SOURCE_PINS, _decode, find_program_address
from bot.p3.observed_activity import snapshot_safety_reason
from bot.p3.quotes import SOL_MINT
from bot.p3.token2022 import TOKEN_2022_PROGRAM, TokenEvidenceError, decode_mint, decode_vault

ROUTE_KIND = 'LAUNCHLAB_TOKEN2022'
ALLOWED_MINT_EXTENSIONS = frozenset(('18', '19'))  # MetadataPointer, TokenMetadata
TOKEN2022_ACCOUNT_BASE_LEN = 165
ACCOUNT_TYPE_ACCOUNT = 2
IMMUTABLE_OWNER = 7
TOKEN2022_ATA_LEN = 170  # 165 + AccountType(1) + ImmutableOwner TLV header(4) + 0
# Rent-exempt minimum: (data_len + 128) * 3480 lamports/byte-year * 2 years.
TOKEN2022_ATA_RENT_LAMPORTS = (TOKEN2022_ATA_LEN + 128) * 3480 * 2  # 2_074_080
_ATA_SUFFIX = bytes((ACCOUNT_TYPE_ACCOUNT,)) + struct.pack('<HH', IMMUTABLE_OWNER, 0)


def token2022_associated_token_address(wallet, mint):
    """ATA PDA with the Token-2022 program id as the token-program seed."""
    return associated_token_address(wallet, mint, TOKEN_2022_PROGRAM)


def decode_token2022_ata(account):
    """Decode OUR Token-2022 associated token account, strict allowlist.

    Exactly 170 bytes: the 165-byte base (read by the frozen ``decode_vault``
    on that prefix, so option tags, state and native backing keep its exact
    checks), AccountType=Account and one ImmutableOwner TLV of length 0.
    Any other length, account type, extension or trailing byte refuses.
    """
    if (type(account) is not dict or account.get('owner') != TOKEN_2022_PROGRAM
            or account.get('executable') is not False):
        raise ValueError('token2022_ATA_owner_or_executable_invalid')
    data = account.get('data')
    if (type(data) not in (list, tuple) or len(data) != 2 or data[1] != 'base64'
            or type(data[0]) is not str or len(data[0]) > 1000):
        raise ValueError('token2022_ATA_encoding_invalid')
    try:
        raw = base64.b64decode(data[0], validate=True)
    except (ValueError, TypeError):
        raise ValueError('token2022_ATA_encoding_invalid') from None
    if len(raw) != TOKEN2022_ATA_LEN:
        raise ValueError('token2022_ATA_length_not_170')
    if raw[TOKEN2022_ACCOUNT_BASE_LEN] != ACCOUNT_TYPE_ACCOUNT:
        raise ValueError('token2022_ATA_account_type_invalid')
    if raw[TOKEN2022_ACCOUNT_BASE_LEN:] != _ATA_SUFFIX:
        raise ValueError('token2022_ATA_extension_not_allowed')
    base = dict(account, data=[base64.b64encode(raw[:TOKEN2022_ACCOUNT_BASE_LEN]).decode(), 'base64'])
    try:
        facts, _ = decode_vault(base)
    except TokenEvidenceError as error:
        raise ValueError('token2022_ATA_' + str(error)) from None
    facts = dict(facts, extension_types=[IMMUTABLE_OWNER])
    return facts, raw


def token2022_mint_refusal(mint_account, mint):
    """None if the mint is in the allowlist, else the explicit refusal reason."""
    if type(mint_account) is not dict:
        return 'token2022_mint_account_missing'
    if mint_account.get('owner') != TOKEN_2022_PROGRAM:
        return 'token2022_route_requires_token2022_mint'
    try:
        facts, _ = decode_mint(mint_account, mint)
    except TokenEvidenceError as error:
        return 'token2022_mint_refused:' + str(error)
    if not {str(kind) for kind in facts['extension_types']} <= ALLOWED_MINT_EXTENSIONS:
        return 'token2022_mint_refused:mint_extension_not_supported'
    if facts['mint_authority_present']:
        return 'token2022_mint_authority_present'
    if facts['freeze_authority_present']:
        return 'token2022_freeze_authority_present'
    return None


@dataclass(frozen=True)
class PreparedLaunchLabOrderToken2022:
    """Distinct type on purpose: the engine's exact-type dispatch refuses it."""
    transaction: PreparedTransaction
    side: str
    input_amount: int
    minimum_out: int
    expected_output: int
    slippage_bps: int
    price_impact_bps: int
    max_price_impact_bps: int
    mint: str
    pool: str
    user: str
    input_is_native: bool
    source_slot: int
    source_available_at_ms: int
    decision_at_ms: int
    semantic_digest: str
    base_token_account: str
    quote_token_account: str
    base_token_program: str
    network_fee_upper_lamports: int
    rent_deposit_lamports: int
    base_balance_before: int
    wallet_lamports_before: int
    source_account_digest: str
    source_pins: tuple
    rebuild_request_json: str


def build_launchlab_order_token2022(*, accounts, pool_address, mint, wallet, context_slot,
                                    available_at_ms, decision_at_ms, side, amount_in,
                                    slippage_bps, max_slippage_bps, max_price_impact_bps,
                                    recent_blockhash, last_valid_block_height,
                                    rent_exempt_lamports, base_ata_rent_lamports, decision_id,
                                    compute_unit_limit=200000,
                                    priority_fee_micro_lamports=0,
                                    max_priority_fee_lamports=0):
    """Unsigned Token-2022 LaunchLab exact-input order; mirrors route.py.

    Same request shape as ``build_launchlab_order``. Differences only: the
    base mint must be an allowlisted Token-2022 mint, our ATA is derived and
    created with the Token-2022 program and must be the exact 170-byte
    ImmutableOwner layout, the swap's base_token_program is Token-2022 (the
    quote/WSOL side stays classic SPL Token), and the ATA rent deposit is
    exactly 2,074,080 lamports.
    """
    request_json = json.dumps(dict(locals()), sort_keys=True, separators=(',', ':'),
                              allow_nan=False)
    _decode(wallet); _decode(mint); _decode(pool_address)
    _u64(amount_in, positive=True)
    if side not in ('BUY', 'SELL') or type(side) is not str:
        raise ValueError('explicit_BUY_or_SELL_required')
    if (type(slippage_bps) is not int or type(max_slippage_bps) is not int
            or not 0 <= slippage_bps <= max_slippage_bps < 10000):
        raise ValueError('slippage_limit_invalid')
    if (type(max_price_impact_bps) is not int or not 0 <= max_price_impact_bps < 10000):
        raise ValueError('explicit_price_impact_limit_required')
    if (type(available_at_ms) is not int or type(decision_at_ms) is not int
            or not 0 <= decision_at_ms - available_at_ms <= 5000):
        raise ValueError('fresh_asof_raw_bank_required')
    if type(context_slot) is not int or context_slot <= 0:
        raise ValueError('observed_context_slot_required')
    if (type(compute_unit_limit) is not int or not 0 < compute_unit_limit <= 1400000):
        raise ValueError('compute_unit_limit_invalid')
    _u64(priority_fee_micro_lamports); _u64(max_priority_fee_lamports)
    priority = (compute_unit_limit * priority_fee_micro_lamports + 999999) // 1000000
    if priority > max_priority_fee_lamports:
        raise ValueError('priority_fee_limit_exceeded')
    _u64(rent_exempt_lamports, positive=True)
    _u64(base_ata_rent_lamports, positive=True)
    if base_ata_rent_lamports != TOKEN2022_ATA_RENT_LAMPORTS:
        raise ValueError('token2022_ATA_rent_must_be_2074080')
    if type(accounts) is not dict:
        raise ValueError('same_bank_raw_account_mapping_required')
    # Allowlist first, with an explicit reason, before the full pool analysis.
    refusal = token2022_mint_refusal(accounts.get(mint), mint)
    if refusal:
        raise ValueError(refusal)
    analysis = launchlab.analyze_snapshot(accounts, context_slot=context_slot,
        expected_mint=mint, pool_address=pool_address,
        input_lamports=amount_in if side == 'BUY' else 1,
        evidence_profile='published_metadata_v1', compute_projection=side == 'BUY')
    safety = snapshot_safety_reason(analysis)
    if safety:
        raise ValueError('route_bank_unqualified:' + safety)
    facts = analysis['facts']
    identity = facts['identity_certification']
    if identity['program_derived_addresses_verified'] is not True:
        raise ValueError('route_platform_or_PDA_identity_unknown')
    addresses = facts['addresses']
    # Defence in depth on the frozen analysis' own decoded facts.
    base_mint, base_vault = facts['base_mint'], facts['base_vault']
    if (accounts[mint].get('owner') != TOKEN_2022_PROGRAM
            or base_mint.get('token_program') != TOKEN_2022_PROGRAM
            or not set(base_mint.get('extension_types', ())) <= ALLOWED_MINT_EXTENSIONS
            or base_mint['mint_authority_present'] or base_mint['freeze_authority_present']
            or base_vault.get('token_program') != TOKEN_2022_PROGRAM
            or base_vault.get('extension_types') != []
            or facts['pool']['mint_program_flag'] != '1'):
        raise ValueError('token2022_pool_facts_inconsistent')
    if side == 'BUY' and analysis['conditional_projection'] is None:
        raise ValueError('route_curve_projection_refused')
    base_ata = token2022_associated_token_address(wallet, mint)
    quote_account, seed = ephemeral_wsol_address(wallet, decision_id)
    if wallet in set(addresses.values()) or base_ata in set(addresses.values()) or quote_account in set(addresses.values()):
        raise ValueError('route_user_pool_account_alias')
    if any(address not in accounts for address in (wallet, base_ata, quote_account)):
        raise ValueError('explicit_user_account_observations_required')
    if accounts[quote_account] is not None:
        raise ValueError('dedicated_WSOL_account_already_exists')
    wallet_account = accounts[wallet]
    if (type(wallet_account) is not dict or wallet_account.get('owner') != SYSTEM_PROGRAM
            or wallet_account.get('executable') is not False
            or wallet_account.get('data') not in (['', 'base64'], ('', 'base64'))):
        raise ValueError('plain_system_wallet_account_required')
    wallet_balance = _u64(wallet_account.get('lamports'))
    before = accounts[base_ata]
    base_balance = 0
    if before is not None:
        decoded, _ = decode_token2022_ata(before)
        if (decoded['mint'] != mint or decoded['authority'] != wallet
                or decoded['state'] != 1 or decoded['delegate_present']
                or decoded['close_authority_present'] or decoded['is_native']):
            raise ValueError('unsafe_or_foreign_user_base_ATA')
        base_balance = decoded['amount_atomic']
    if side == 'SELL' and (before is None or base_balance < amount_in):
        raise ValueError('insufficient_owned_token_inventory')
    if side == 'BUY':
        expected_output = int(analysis['conditional_projection']['buy_output_atomic'])
        impact = analysis['conditional_projection']['buy_output_shortfall_vs_spot_without_fees']
        impact_numerator, impact_denominator = int(impact['numerator']), int(impact['denominator'])
    else:
        numeric_pool = dict(facts['pool'])
        for name in ('status', 'virtual_a', 'virtual_b', 'real_a', 'real_b',
                     'protocol_fee_accrued', 'platform_fee_accrued'):
            numeric_pool[name] = int(numeric_pool[name])
        sale = launchlab.observed_sell_projection(numeric_pool,
            input_token_atomic=amount_in,
            fee_rates_ppm=(int(facts['config']['trade_fee_rate_ppm']),
                int(facts['platform']['platform_fee_rate_ppm']),
                int(facts['platform']['creator_fee_rate_ppm'])),
            quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
            curve_type=int(facts['config']['curve_type']), share_fee_rate_ppm=0)
        expected_output = int(sale['output_lamports'])
        x = numeric_pool['virtual_a'] - numeric_pool['real_a']
        y = numeric_pool['virtual_b'] + numeric_pool['real_b']
        impact_numerator = amount_in*y - int(sale['gross_output_lamports'])*x
        impact_denominator = amount_in*y
    price_impact_bps = (impact_numerator*10000 + impact_denominator-1)//impact_denominator
    if price_impact_bps > max_price_impact_bps:
        raise ValueError('curve_price_impact_limit_exceeded')
    minimum_out = expected_output * (10000 - slippage_bps) // 10000
    _u64(minimum_out, positive=True)
    rent = rent_exempt_lamports + (base_ata_rent_lamports if before is None else 0)
    network_fee = 5000 + priority  # Exactly one required signer, no precompiles.
    required_lamports = rent + network_fee + (amount_in if side == 'BUY' else 0)
    _u64(required_lamports)
    if required_lamports > wallet_balance:
        raise ValueError('wallet_insufficient_for_input_rent_and_fees')
    instructions = [
        Instruction(COMPUTE_BUDGET_PROGRAM, (), b'\x02' + struct.pack('<I', compute_unit_limit)),
        Instruction(COMPUTE_BUDGET_PROGRAM, (), b'\x03' + struct.pack('<Q', priority_fee_micro_lamports))]
    if before is None:
        # CreateIdempotent with the Token-2022 program account: the ATA program
        # sizes it (ImmutableOwner) and initializes it through Token-2022.
        instructions.append(Instruction(ATA_PROGRAM,
            (AM(wallet, True, True), AM(base_ata, False, True), AM(wallet), AM(mint),
             AM(SYSTEM_PROGRAM), AM(TOKEN_2022_PROGRAM)), b'\x01'))
    # Temporary WSOL account: unchanged, classic SPL Token program.
    funding = rent_exempt_lamports + (amount_in if side == 'BUY' else 0)
    creation_data = (struct.pack('<I', 3) + _decode(wallet)
        + struct.pack('<Q', len(seed)) + seed.encode()
        + struct.pack('<QQ', funding, 165) + _decode(TOKEN_PROGRAM))
    instructions.extend((
        Instruction(SYSTEM_PROGRAM,
            (AM(wallet, True, True), AM(quote_account, False, True), AM(wallet, True)), creation_data),
        Instruction(TOKEN_PROGRAM, (AM(quote_account, False, True), AM(SOL_MINT)),
                    b'\x12' + _decode(wallet)),  # InitializeAccount3
        Instruction(TOKEN_PROGRAM, (AM(quote_account, False, True),), b'\x11')))  # SyncNative
    authority = find_program_address((b'vault_auth_seed',))[0]
    event_authority = find_program_address((b'__event_authority',))[0]
    # IDL order (launchlab_swap_abi.json): base_token_program then
    # quote_token_program; the latter is pinned to classic SPL Token.
    swap_keys = (wallet, authority, addresses['config'], addresses['platform'],
        pool_address, base_ata, quote_account, addresses['vault_a'], addresses['vault_b'],
        mint, SOL_MINT, TOKEN_2022_PROGRAM, TOKEN_PROGRAM, event_authority, PROGRAM)
    instructions.append(Instruction(PROGRAM,
        tuple(AM(key, i == 0, i in SWAP_WRITABLE) for i, key in enumerate(swap_keys)),
        (BUY_EXACT_IN if side == 'BUY' else SELL_EXACT_IN)
        + struct.pack('<QQQ', amount_in, minimum_out, 0)))
    instructions.append(Instruction(TOKEN_PROGRAM,
        (AM(quote_account, False, True), AM(wallet, False, True), AM(wallet, True)), b'\x09'))
    prepared = compile_legacy(tuple(instructions), fee_payer=wallet,
        recent_blockhash=recent_blockhash, last_valid_block_height=last_valid_block_height)
    if prepared.required_signers != (wallet,):
        raise ValueError('unexpected_external_signer_required')
    account_digest = hashlib.sha256(json.dumps(accounts, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    semantic = dict(route=ROUTE_KIND, base_token_program=TOKEN_2022_PROGRAM,
        side=side, input_amount=amount_in, minimum_out=minimum_out,
        mint=mint, pool=pool_address, wallet=wallet, context_slot=context_slot,
        source_account_digest=account_digest, decision_id=decision_id,
        slippage_bps=slippage_bps, max_slippage_bps=max_slippage_bps,
        max_price_impact_bps=max_price_impact_bps,
        available_at_ms=available_at_ms, decision_at_ms=decision_at_ms,
        max_priority_fee_lamports=max_priority_fee_lamports,
        message_sha256=hashlib.sha256(prepared.message).hexdigest())
    semantic_digest = hashlib.sha256(json.dumps(semantic, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return PreparedLaunchLabOrderToken2022(prepared, side, amount_in, minimum_out,
        expected_output, slippage_bps, price_impact_bps, max_price_impact_bps,
        mint, pool_address, wallet, side == 'BUY', context_slot,
        available_at_ms, decision_at_ms, semantic_digest, base_ata, quote_account,
        TOKEN_2022_PROGRAM, network_fee, rent, base_balance, wallet_balance, account_digest,
        tuple(sorted(SOURCE_PINS.items())), request_json)


def validate_prepared_order_token2022(order):
    """Full rebuild from the retained raw request; any changed byte/field fails."""
    if type(order) is not PreparedLaunchLabOrderToken2022:
        raise ValueError('token2022_router_generated_order_required')
    try:
        rebuilt = build_launchlab_order_token2022(**json.loads(order.rebuild_request_json))
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('prepared_route_rebuild_failed') from None
    if rebuilt != order:
        raise ValueError('prepared_route_or_wire_modified')
    return rebuilt
