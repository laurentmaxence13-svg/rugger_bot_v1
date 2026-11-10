"""Separate cleanup of our own base token account after a finalized total sale.

The SELL built by ``route.build_launchlab_order`` is not modified: it never
closes the base associated token account, so a third-party dust deposit can
never block an exit. This module prepares a *distinct* legacy transaction:
optional Token ``Burn`` of an explicitly bounded leftover, then Token
``CloseAccount`` returning the account's lamports to our wallet.

Scope of this version (offline only): builder, rebuild validator, read-only
journal eligibility and a standalone reconciliation. It is NOT a supported
execution route: ``route_dispatch.validate_execution_order`` refuses it, so
the engine can neither sign nor send it, and nothing here writes the journal.
The recovered rent is the return of a deposit paid at the BUY. It is never
sale proceeds and never market P&L; only the network fee is a cost.
"""
from dataclasses import dataclass
import hashlib
import json
import struct

from bot.live.journal import uint
from bot.live.route import (COMPUTE_BUDGET_PROGRAM, SYSTEM_PROGRAM, TOKEN_PROGRAM,
                            associated_token_address)
from bot.live.wire import AccountMeta as AM, Instruction, PreparedTransaction, compile_legacy
from bot.p3 import launchlab
from bot.p3.certification import _decode

TOKEN_BURN = 8
TOKEN_CLOSE_ACCOUNT = 9
# One whole token at the six decimals used by the routed curves. This is only
# a suggested value for the operator: the builder has NO default and the bound
# must be fixed in the retained request before any balance is observed.
SUGGESTED_MAX_DUST_BURN_ATOMIC = 1_000_000
CLEANUP_COMPUTE_UNIT_LIMIT = 20_000
# Orders in these states can no longer move tokens for their mint.
SETTLED_STATES = ('RECONCILED', 'EXPIRED', 'UNSENT_CANCELLED', 'SIMULATION_FAILED')


def _u64(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        raise ValueError('exact_atomic_u64_required')
    return value


@dataclass(frozen=True)
class PreparedBaseAccountCleanup:
    transaction: PreparedTransaction
    mint: str
    user: str
    base_token_account: str
    burn_amount: int
    max_dust_burn_atomic: int
    account_lamports_observed: int
    network_fee_upper_lamports: int
    wallet_lamports_before: int
    source_slot: int
    source_available_at_ms: int
    decision_at_ms: int
    source_account_digest: str
    semantic_digest: str
    rebuild_request_json: str


def journal_cleanup_refusal(journal, *, mint, wallet):
    """Read-only: why the journal forbids destroying/closing this account.

    Returns None only when the journal proves a finalized, fully sold position
    of this wallet for the mint and nothing for that mint can still move. The
    journal therefore expects a token balance of exactly zero; any observed
    leftover is foreign dust, bounded separately by the retained request.
    """
    _decode(mint); _decode(wallet)
    journal.verify_audit()
    if journal.killed:
        return 'persistent_kill_switch_active'
    positions = list(journal.con.execute('SELECT * FROM positions WHERE mint=?', (mint,)))
    if any(p['quantity_atomic'] != 0 for p in positions):
        return 'open_inventory_for_mint'
    if not positions:
        return 'no_journaled_closed_position_for_mint'
    bought = sold = False
    for row in journal.con.execute('SELECT state,order_json,reconciliation_json FROM orders'):
        order = json.loads(row['order_json'])
        if order.get('mint') != mint:
            continue
        if row['state'] not in SETTLED_STATES:
            return 'unsettled_order_for_mint'
        if row['state'] != 'RECONCILED':
            continue
        if order.get('user') != wallet:
            return 'journaled_position_belongs_to_another_wallet'
        if json.loads(row['reconciliation_json'])['chain_error'] is None:
            bought |= order['side'] == 'BUY'
            sold |= order['side'] == 'SELL'
    if not (bought and sold):
        return 'finalized_buy_and_total_sale_required'
    return None


def assert_cleanup_allowed(journal, *, mint, wallet):
    reason = journal_cleanup_refusal(journal, mint=mint, wallet=wallet)
    if reason:
        raise ValueError('cleanup_refused:' + reason)


def build_base_account_cleanup(*, accounts, mint, wallet, context_slot,
                               available_at_ms, decision_at_ms, recent_blockhash,
                               last_valid_block_height, decision_id,
                               max_dust_burn_atomic,
                               compute_unit_limit=CLEANUP_COMPUTE_UNIT_LIMIT,
                               priority_fee_micro_lamports=0,
                               max_priority_fee_lamports=0):
    """Build the unsigned Burn(optional)+CloseAccount message; nothing is sent.

    accounts MUST hold explicit observations of the wallet, the mint and our
    derived associated token account. ``max_dust_burn_atomic`` has no default:
    it is fixed by the caller before observation and retained in the request.
    A leftover above it refuses the whole cleanup (no Burn, no close): the
    account stays open and its rent stays a cost. The caller must separately
    prove, from the journal, that no inventory is held for this mint.
    """
    request_json = json.dumps(dict(locals()), sort_keys=True, separators=(',', ':'),
                              allow_nan=False)
    _decode(wallet); _decode(mint)
    if type(decision_id) is not str or not 1 <= len(decision_id) <= 128:
        raise ValueError('bounded_stable_decision_id_required')
    _u64(max_dust_burn_atomic)
    if (type(available_at_ms) is not int or type(decision_at_ms) is not int
            or not 0 <= decision_at_ms - available_at_ms <= 5000):
        raise ValueError('fresh_asof_raw_bank_required')
    if type(context_slot) is not int or context_slot <= 0:
        raise ValueError('observed_context_slot_required')
    if type(compute_unit_limit) is not int or not 0 < compute_unit_limit <= 1400000:
        raise ValueError('compute_unit_limit_invalid')
    _u64(priority_fee_micro_lamports); _u64(max_priority_fee_lamports)
    priority = (compute_unit_limit * priority_fee_micro_lamports + 999999) // 1000000
    if priority > max_priority_fee_lamports:
        raise ValueError('priority_fee_limit_exceeded')
    if type(accounts) is not dict:
        raise ValueError('same_bank_raw_account_mapping_required')
    base_ata = associated_token_address(wallet, mint)
    if len({wallet, mint, base_ata}) != 3:
        raise ValueError('cleanup_account_alias')
    if any(address not in accounts for address in (wallet, mint, base_ata)):
        raise ValueError('explicit_user_account_observations_required')
    mint_account = accounts[mint]
    if type(mint_account) is dict and mint_account.get('owner') == launchlab.TOKEN_2022_PROGRAM:
        raise ValueError('Token2022_cleanup_not_certified')
    try:
        launchlab._mint_state(mint_account, 'cleanup_mint')
    except launchlab.SnapshotEvidenceError:
        raise ValueError('classic_SPL_mint_required_for_cleanup') from None
    wallet_account = accounts[wallet]
    if (type(wallet_account) is not dict or wallet_account.get('owner') != SYSTEM_PROGRAM
            or wallet_account.get('executable') is not False
            or wallet_account.get('data') not in (['', 'base64'], ('', 'base64'))):
        raise ValueError('plain_system_wallet_account_required')
    wallet_balance = _u64(wallet_account.get('lamports'))
    observed = accounts[base_ata]
    if observed is None:
        raise ValueError('base_token_account_absent_nothing_to_close')
    try:
        decoded, _ = launchlab._vault(observed, 'user_base_token')
    except launchlab.SnapshotEvidenceError:
        raise ValueError('unsafe_or_foreign_user_base_ATA') from None
    if (decoded['mint'] != mint or decoded['authority'] != wallet
            or decoded['state'] != 1 or decoded['delegate_present']
            or decoded['close_authority_present'] or decoded['is_native']):
        raise ValueError('unsafe_or_foreign_user_base_ATA')
    leftover = decoded['amount_atomic']
    if leftover > max_dust_burn_atomic:
        raise ValueError('leftover_exceeds_retained_dust_bound_account_left_open')
    account_lamports = _u64(decoded['account_lamports'], positive=True)
    network_fee = 5000 + priority  # Exactly one required signer, no precompiles.
    if network_fee > wallet_balance:
        raise ValueError('wallet_insufficient_for_cleanup_fee')
    instructions = [
        Instruction(COMPUTE_BUDGET_PROGRAM, (), b'\x02' + struct.pack('<I', compute_unit_limit)),
        Instruction(COMPUTE_BUDGET_PROGRAM, (), b'\x03' + struct.pack('<Q', priority_fee_micro_lamports))]
    if leftover > 0:
        instructions.append(Instruction(TOKEN_PROGRAM,
            (AM(base_ata, False, True), AM(mint, False, True), AM(wallet, True)),
            bytes((TOKEN_BURN,)) + struct.pack('<Q', leftover)))
    instructions.append(Instruction(TOKEN_PROGRAM,
        (AM(base_ata, False, True), AM(wallet, False, True), AM(wallet, True)),
        bytes((TOKEN_CLOSE_ACCOUNT,))))
    prepared = compile_legacy(tuple(instructions), fee_payer=wallet,
        recent_blockhash=recent_blockhash, last_valid_block_height=last_valid_block_height)
    if prepared.required_signers != (wallet,):
        raise ValueError('unexpected_external_signer_required')
    account_digest = hashlib.sha256(json.dumps(accounts, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    semantic = dict(kind='BASE_ACCOUNT_CLEANUP', mint=mint, wallet=wallet,
        base_token_account=base_ata, burn_amount=leftover,
        max_dust_burn_atomic=max_dust_burn_atomic, context_slot=context_slot,
        source_account_digest=account_digest, decision_id=decision_id,
        available_at_ms=available_at_ms, decision_at_ms=decision_at_ms,
        max_priority_fee_lamports=max_priority_fee_lamports,
        message_sha256=hashlib.sha256(prepared.message).hexdigest())
    semantic_digest = hashlib.sha256(json.dumps(semantic, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return PreparedBaseAccountCleanup(prepared, mint, wallet, base_ata, leftover,
        max_dust_burn_atomic, account_lamports, network_fee, wallet_balance,
        context_slot, available_at_ms, decision_at_ms, account_digest,
        semantic_digest, request_json)


def validate_prepared_cleanup(cleanup):
    """Rebuild from the retained raw request; any changed byte or field fails."""
    if type(cleanup) is not PreparedBaseAccountCleanup:
        raise ValueError('builder_generated_cleanup_required')
    try:
        rebuilt = build_base_account_cleanup(**json.loads(cleanup.rebuild_request_json))
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('prepared_cleanup_rebuild_failed') from None
    if rebuilt != cleanup:
        raise ValueError('prepared_cleanup_or_wire_modified')
    return rebuilt


def _token_amount(value):
    if type(value) is not str or not value.isascii() or not value.isdigit() or str(int(value)) != value:
        raise ValueError('canonical_atomic_token_amount_required')
    return _u64(int(value))


def reconcile_cleanup(cleanup, signature, payload):
    """Bind a finalized payload to the exact cleanup; rent is not proceeds.

    Success requires: the signed message is the prepared one, the token
    account held exactly the burned leftover before, is absent from
    postTokenBalances with zero lamports after, and the wallet moved by
    exactly (account lamports - fee). Nothing is written anywhere.
    """
    cleanup = validate_prepared_cleanup(cleanup)
    from bot.live.engine import message_from_rpc
    if type(payload) is not dict or payload.get('version', 'legacy') not in ('legacy', None):
        raise ValueError('finalized_legacy_transaction_required')
    transaction, meta = payload.get('transaction'), payload.get('meta')
    if type(transaction) is not dict or type(meta) is not dict:
        raise ValueError('finalized_transaction_metadata_missing')
    if type(signature) is not str or transaction.get('signatures') != [signature]:
        raise ValueError('finalized_signature_binding_failed')
    if message_from_rpc(transaction) != cleanup.transaction.message:
        raise ValueError('finalized_message_differs_from_prepared_cleanup')
    keys = transaction['message']['accountKeys']
    wallet_index, base_index = keys.index(cleanup.user), keys.index(cleanup.base_token_account)
    before, after = meta.get('preBalances'), meta.get('postBalances')
    if type(before) is not list or type(after) is not list or len(before) != len(keys) or len(after) != len(keys):
        raise ValueError('complete_native_balances_required')
    for value in before + after:
        uint(value)
    tokens = {}
    for label in ('preTokenBalances', 'postTokenBalances'):
        entries = meta.get(label)
        if type(entries) is not list:
            raise ValueError('complete_token_balances_required')
        if any(type(e) is not dict or type(e.get('accountIndex')) is not int
               or e['accountIndex'] != base_index for e in entries) or len(entries) > 1:
            raise ValueError('cleanup_token_balance_entry_invalid')
        tokens[label] = entries
    fee = uint(meta.get('fee'), positive=True)
    if fee > cleanup.network_fee_upper_lamports:
        raise ValueError('actual_fee_exceeds_reserved_upper_bound')
    slot = uint(payload.get('slot'), positive=True)
    if slot < cleanup.source_slot:
        raise ValueError('finalized_slot_precedes_observed_intent')
    native_delta = after[wallet_index] - before[wallet_index]
    others_unchanged = all(a == b for i, (a, b) in enumerate(zip(before, after))
                           if i not in (wallet_index, base_index))
    result = dict(kind='BASE_ACCOUNT_CLEANUP', slot=slot, fee_lamports=fee,
        mint=cleanup.mint, base_token_account=cleanup.base_token_account,
        wallet_delta_lamports=native_delta, cost_lamports=fee,
        # A cleanup never sells: these are structurally zero, not measured.
        gross_output_lamports=0, sale_proceeds_lamports=0, market_pnl_lamports=0,
        realized_market_execution=False, economic_edge_proven=False)
    if meta.get('err') is not None:
        if (native_delta != -fee or not others_unchanged
                or before[base_index] != after[base_index]
                or tokens['preTokenBalances'] != tokens['postTokenBalances']):
            raise ValueError('failed_cleanup_has_unexplained_balance_change')
        return dict(result, chain_error=meta['err'], burned_atomic=0,
            deposit_returned_lamports=0, account_closed=False)
    if len(tokens['preTokenBalances']) != 1:
        raise ValueError('cleanup_token_balance_missing_before')
    entry = tokens['preTokenBalances'][0]
    if entry.get('mint') != cleanup.mint or entry.get('owner') != cleanup.user:
        raise ValueError('cleanup_token_identity_mismatch')
    if _token_amount(entry.get('uiTokenAmount', {}).get('amount')) != cleanup.burn_amount:
        raise ValueError('cleanup_burn_differs_from_finalized_leftover')
    if tokens['postTokenBalances'] or after[base_index] != 0:
        raise ValueError('base_token_account_not_closed_at_finality')
    returned = before[base_index]
    if returned <= 0 or not others_unchanged or native_delta != returned - fee:
        raise ValueError('cleanup_native_cash_flow_unexplained')
    return dict(result, chain_error=None, burned_atomic=cleanup.burn_amount,
        deposit_returned_lamports=returned, account_closed=True)

