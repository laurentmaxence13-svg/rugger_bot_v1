"""Pinned LaunchLab exact-input instructions, from retained raw bank accounts.

Only active native-SOL, classic SPL-token curves are routed in this version.
Token-2022 and migration refuse explicitly. Preparation is not authorization,
program binary attestation, a provider quote, simulation success, or a fill.
"""
from dataclasses import dataclass
import hashlib
import json
import struct

from bot.live.wire import AccountMeta as AM, Instruction, PreparedTransaction, compile_legacy
from bot.p3 import launchlab
from bot.p3.certification import PROGRAM, SOURCE_PINS, _decode, _encode, find_program_address
from bot.p3.observed_activity import snapshot_safety_reason
from bot.p3.quotes import SOL_MINT

SYSTEM_PROGRAM = '11111111111111111111111111111111'
TOKEN_PROGRAM = launchlab.TOKEN_PROGRAM
ATA_PROGRAM = 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'
COMPUTE_BUDGET_PROGRAM = 'ComputeBudget111111111111111111111111111111'
BUY_EXACT_IN = bytes((250, 234, 13, 123, 213, 156, 19, 236))
SELL_EXACT_IN = bytes((149, 39, 222, 155, 211, 124, 152, 26))
# These exact discriminators, argument types and all fifteen account flags were
# compared to the complete IDL blob SOURCE_PINS['git_blob'], not market bytes.
SWAP_ACCOUNT_ORDER = (
    'payer', 'authority', 'global_config', 'platform_config', 'pool_state',
    'user_base_token', 'user_quote_token', 'base_vault', 'quote_vault',
    'base_token_mint', 'quote_token_mint', 'base_token_program',
    'quote_token_program', 'event_authority', 'program')
SWAP_WRITABLE = frozenset((0, 4, 5, 6, 7, 8))
SYSTEM_CREATE_WITH_SEED_PIN = dict(repository='solana-labs/solana', ref='v1.18.26',
    path='sdk/program/src/system_instruction.rs')


def _u64(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        raise ValueError('exact_atomic_u64_required')
    return value


def associated_token_address(wallet, mint, token_program=TOKEN_PROGRAM):
    return find_program_address((_decode(wallet), _decode(token_program), _decode(mint)),
                                program_id=ATA_PROGRAM)[0]


def ephemeral_wsol_address(wallet, decision_id):
    if type(decision_id) is not str or not 1 <= len(decision_id) <= 256:
        raise ValueError('bounded_stable_decision_id_required')
    seed = hashlib.sha256(('rugger-wsol-v1:' + decision_id).encode()).hexdigest()[:32]
    address = _encode(hashlib.sha256(_decode(wallet) + seed.encode() + _decode(TOKEN_PROGRAM)).digest())
    return address, seed


@dataclass(frozen=True)
class PreparedLaunchLabOrder:
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
    network_fee_upper_lamports: int
    rent_deposit_lamports: int
    base_balance_before: int
    wallet_lamports_before: int
    source_account_digest: str
    source_pins: tuple
    rebuild_request_json: str


def build_launchlab_order(*, accounts, pool_address, mint, wallet, context_slot,
                         available_at_ms, decision_at_ms, side, amount_in,
                         slippage_bps, max_slippage_bps, max_price_impact_bps, recent_blockhash,
                         last_valid_block_height, rent_exempt_lamports,
                         base_ata_rent_lamports, decision_id,
                         compute_unit_limit=200000,
                         priority_fee_micro_lamports=0,
                         max_priority_fee_lamports=0):
    """Build real unsigned instructions; caller must revalidate before signing.

    accounts MUST include explicit observed entries for the wallet, derived
    base ATA, and dedicated WSOL address, in addition to the seven pool roles.
    Absence is an explicit RPC null, not an omitted key. WSOL is fresh and is
    closed in the same atomic transaction; an existing WSOL account is never
    drained. No HTTP, signer, wallet loading or financial operation occurs.
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
    if type(accounts) is not dict:
        raise ValueError('same_bank_raw_account_mapping_required')
    if type(accounts.get(mint)) is dict and accounts[mint].get('owner') == launchlab.TOKEN_2022_PROGRAM:
        raise ValueError('Token2022_live_route_not_certified')
    # Re-decode raw bytes independently: caller-supplied success booleans or
    # modified analysis summaries cannot bypass account identity/permissions.
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
    if accounts[mint].get('owner') != TOKEN_PROGRAM:
        raise ValueError('Token2022_live_route_not_certified')
    if side == 'BUY' and analysis['conditional_projection'] is None:
        raise ValueError('route_curve_projection_refused')
    base_ata = associated_token_address(wallet, mint)
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
        decoded, _ = launchlab._vault(before, 'user_base_token')
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
        # Compare gross curve output against fee-free infinitesimal spot.
        # Curve fees and network costs remain separate, never double counted.
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
        instructions.append(Instruction(ATA_PROGRAM,
            (AM(wallet, True, True), AM(base_ata, False, True), AM(wallet), AM(mint),
             AM(SYSTEM_PROGRAM), AM(TOKEN_PROGRAM)), b'\x01'))
    # SystemInstruction::CreateAccountWithSeed (bincode enum=3). The duplicate
    # wallet/base account positions are required by the canonical System ABI.
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
    swap_keys = (wallet, authority, addresses['config'], addresses['platform'],
        pool_address, base_ata, quote_account, addresses['vault_a'], addresses['vault_b'],
        mint, SOL_MINT, TOKEN_PROGRAM, TOKEN_PROGRAM, event_authority, PROGRAM)
    instructions.append(Instruction(PROGRAM,
        tuple(AM(key, i == 0, i in SWAP_WRITABLE) for i, key in enumerate(swap_keys)),
        (BUY_EXACT_IN if side == 'BUY' else SELL_EXACT_IN)
        + struct.pack('<QQQ', amount_in, minimum_out, 0)))
    instructions.append(Instruction(TOKEN_PROGRAM,
        (AM(quote_account, False, True), AM(wallet, False, True), AM(wallet, True)), b'\x09'))
    if side == 'SELL' and amount_in == base_balance:
        # Total exit: the base token account is empty after the exact-input
        # sale, so close it in the same atomic transaction and recover its
        # rent deposit. The token program refuses the close (and so the whole
        # transaction) if any token is left. A partial sale never closes it.
        instructions.append(Instruction(TOKEN_PROGRAM,
            (AM(base_ata, False, True), AM(wallet, False, True), AM(wallet, True)), b'\x09'))
    prepared = compile_legacy(tuple(instructions), fee_payer=wallet,
        recent_blockhash=recent_blockhash, last_valid_block_height=last_valid_block_height)
    if prepared.required_signers != (wallet,):
        raise ValueError('unexpected_external_signer_required')
    account_digest = hashlib.sha256(json.dumps(accounts, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    semantic = dict(side=side, input_amount=amount_in, minimum_out=minimum_out,
        mint=mint, pool=pool_address, wallet=wallet, context_slot=context_slot,
        source_account_digest=account_digest, decision_id=decision_id,
        slippage_bps=slippage_bps, max_slippage_bps=max_slippage_bps,
        max_price_impact_bps=max_price_impact_bps,
        available_at_ms=available_at_ms, decision_at_ms=decision_at_ms,
        max_priority_fee_lamports=max_priority_fee_lamports,
        message_sha256=hashlib.sha256(prepared.message).hexdigest())
    semantic_digest = hashlib.sha256(json.dumps(semantic, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return PreparedLaunchLabOrder(prepared, side, amount_in, minimum_out,
        expected_output, slippage_bps, price_impact_bps, max_price_impact_bps,
        mint, pool_address, wallet, side == 'BUY', context_slot,
        available_at_ms, decision_at_ms, semantic_digest, base_ata, quote_account,
        network_fee, rent, base_balance, wallet_balance, account_digest,
        tuple(sorted(SOURCE_PINS.items())), request_json)


def validate_prepared_order(order):
    """Rebuild wire/intent from immutable retained raw request, never flags.

    This catches modification of a prepared amount, account, program or
    message. It does not attest source transport or refresh the bank. The
    execution boundary must separately reacquire/revalidate chain state and
    enforce the still-valid authorization envelope before signing/submission.
    """
    if type(order) is not PreparedLaunchLabOrder:
        raise ValueError('router_generated_order_required')
    try:
        request = json.loads(order.rebuild_request_json)
        rebuilt = build_launchlab_order(**request)
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('prepared_route_rebuild_failed') from None
    if rebuilt != order:
        raise ValueError('prepared_route_or_wire_modified')
    return rebuilt
