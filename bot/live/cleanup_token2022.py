"""Token-2022 variant of the base-account cleanup BUILDER (OFFLINE ONLY).

Separate code: ``cleanup.build_base_account_cleanup`` is unchanged and keeps
refusing Token-2022 (``Token2022_cleanup_not_certified``). This variant
prepares a distinct legacy transaction: optional Burn of an explicitly
bounded leftover, then CloseAccount returning the account's lamports (the
2,074,080 lamport deposit of the 170-byte ATA) to our wallet. Burn and
CloseAccount are addressed to the Token-2022 program.

It is NOT wired into the engine: ``ExecutionEngine.cleanup`` validates with
``cleanup.validate_prepared_cleanup`` (exact type ``PreparedBaseAccountCleanup``)
and ``route_dispatch`` refuses this distinct type. The recovered rent is the
return of a deposit, never sale proceeds and never market P&L.
"""
from dataclasses import dataclass
import hashlib
import json
import struct

from bot.live.cleanup import (CLEANUP_COMPUTE_UNIT_LIMIT, TOKEN_BURN, TOKEN_CLOSE_ACCOUNT,
                              _token_amount, _u64, assert_cleanup_allowed,
                              journal_cleanup_refusal)
from bot.live.journal import uint
from bot.live.route import COMPUTE_BUDGET_PROGRAM, SYSTEM_PROGRAM
from bot.live.route_token2022 import (decode_token2022_ata, token2022_associated_token_address,
                                      token2022_mint_refusal)
from bot.live.wire import AccountMeta as AM, Instruction, PreparedTransaction, compile_legacy
from bot.p3.certification import _decode
from bot.p3.token2022 import TOKEN_2022_PROGRAM

# Read-only journal eligibility is identical (mint/wallet based): reuse it.
__all__ = ('PreparedBaseAccountCleanupToken2022', 'build_base_account_cleanup_token2022',
           'validate_prepared_cleanup_token2022', 'reconcile_cleanup_token2022',
           'journal_cleanup_refusal', 'assert_cleanup_allowed')


@dataclass(frozen=True)
class PreparedBaseAccountCleanupToken2022:
    """Distinct type on purpose: the engine's cleanup route refuses it."""
    transaction: PreparedTransaction
    mint: str
    user: str
    base_token_account: str
    token_program: str
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


def build_base_account_cleanup_token2022(*, accounts, mint, wallet, context_slot,
                                         available_at_ms, decision_at_ms, recent_blockhash,
                                         last_valid_block_height, decision_id,
                                         max_dust_burn_atomic,
                                         compute_unit_limit=CLEANUP_COMPUTE_UNIT_LIMIT,
                                         priority_fee_micro_lamports=0,
                                         max_priority_fee_lamports=0):
    """Unsigned Burn(optional)+CloseAccount on Token-2022; nothing is sent.

    Mirrors ``cleanup.build_base_account_cleanup``. The mint must be in the
    Token-2022 allowlist and our ATA must be the exact 170-byte ImmutableOwner
    layout. The caller must separately prove from the journal that no
    inventory is held for this mint (``assert_cleanup_allowed``).
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
    base_ata = token2022_associated_token_address(wallet, mint)
    if len({wallet, mint, base_ata}) != 3:
        raise ValueError('cleanup_account_alias')
    if any(address not in accounts for address in (wallet, mint, base_ata)):
        raise ValueError('explicit_user_account_observations_required')
    refusal = token2022_mint_refusal(accounts[mint], mint)
    if refusal:
        raise ValueError('cleanup_' + refusal)
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
        decoded, _ = decode_token2022_ata(observed)
    except ValueError:
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
        instructions.append(Instruction(TOKEN_2022_PROGRAM,
            (AM(base_ata, False, True), AM(mint, False, True), AM(wallet, True)),
            bytes((TOKEN_BURN,)) + struct.pack('<Q', leftover)))
    instructions.append(Instruction(TOKEN_2022_PROGRAM,
        (AM(base_ata, False, True), AM(wallet, False, True), AM(wallet, True)),
        bytes((TOKEN_CLOSE_ACCOUNT,))))
    prepared = compile_legacy(tuple(instructions), fee_payer=wallet,
        recent_blockhash=recent_blockhash, last_valid_block_height=last_valid_block_height)
    if prepared.required_signers != (wallet,):
        raise ValueError('unexpected_external_signer_required')
    account_digest = hashlib.sha256(json.dumps(accounts, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    semantic = dict(kind='BASE_ACCOUNT_CLEANUP_TOKEN2022', token_program=TOKEN_2022_PROGRAM,
        mint=mint, wallet=wallet,
        base_token_account=base_ata, burn_amount=leftover,
        max_dust_burn_atomic=max_dust_burn_atomic, context_slot=context_slot,
        source_account_digest=account_digest, decision_id=decision_id,
        available_at_ms=available_at_ms, decision_at_ms=decision_at_ms,
        max_priority_fee_lamports=max_priority_fee_lamports,
        message_sha256=hashlib.sha256(prepared.message).hexdigest())
    semantic_digest = hashlib.sha256(json.dumps(semantic, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return PreparedBaseAccountCleanupToken2022(prepared, mint, wallet, base_ata,
        TOKEN_2022_PROGRAM, leftover, max_dust_burn_atomic, account_lamports, network_fee,
        wallet_balance, context_slot, available_at_ms, decision_at_ms, account_digest,
        semantic_digest, request_json)


def validate_prepared_cleanup_token2022(cleanup):
    """Rebuild from the retained raw request; any changed byte or field fails."""
    if type(cleanup) is not PreparedBaseAccountCleanupToken2022:
        raise ValueError('token2022_builder_generated_cleanup_required')
    try:
        rebuilt = build_base_account_cleanup_token2022(**json.loads(cleanup.rebuild_request_json))
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('prepared_cleanup_rebuild_failed') from None
    if rebuilt != cleanup:
        raise ValueError('prepared_cleanup_or_wire_modified')
    return rebuilt


def reconcile_cleanup_token2022(cleanup, signature, payload):
    """Standalone: bind a finalized payload to the exact cleanup; rent is not proceeds.

    Same rules as ``cleanup.reconcile_cleanup``: the signed message is the
    prepared one, the token account held exactly the burned leftover before,
    is absent from postTokenBalances with zero lamports after, and the wallet
    moved by exactly (account lamports - fee). When a token-balance entry
    names its programId it must be Token-2022. Nothing is written anywhere.
    """
    cleanup = validate_prepared_cleanup_token2022(cleanup)
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
               or e['accountIndex'] != base_index
               or e.get('programId', TOKEN_2022_PROGRAM) != TOKEN_2022_PROGRAM
               for e in entries) or len(entries) > 1:
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
    result = dict(kind='BASE_ACCOUNT_CLEANUP_TOKEN2022', token_program=TOKEN_2022_PROGRAM,
        slot=slot, fee_lamports=fee,
        mint=cleanup.mint, base_token_account=cleanup.base_token_account,
        wallet_delta_lamports=native_delta, cost_lamports=fee,
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
