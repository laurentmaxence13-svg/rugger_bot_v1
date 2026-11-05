"""Exact-input CPMM post-graduation SELL instruction, using pinned Raydium IDL.

This builds the actual 13-account SwapBaseInput instruction for an existing
classic-SPL mint to native wrapped SOL. No on-chain pool data is silently
trusted here: the caller MUST independently verify migration provenance, the
pool account's CPMM owner/discriminator/slot, both vault token accounts,
the configuration and fees, output estimate, user token inventory and WSOL
creation/close transaction before treating it as an executable route.

An instruction is NOT a complete transaction, signature, fill, quote, exit
guarantee or LIVE_READY_TO_ARM approval.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from bot.p3.certification import _decode, find_program_address
from bot.p3.quotes import SOL_MINT
from bot.live.route import TOKEN_PROGRAM, associated_token_address, ephemeral_wsol_address
from bot.live.wire import AccountMeta, Instruction


CPMM_PROGRAM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
CPMM_SWAP_BASE_INPUT = bytes((143, 190, 90, 218, 196, 30, 51, 222))
SOURCE_PIN = dict(
    repository="https://github.com/raydium-io/raydium-idl",
    commit="e7e0c96fe77bcf6a020b84a44c47a722aac8e359",
    path="raydium_cpmm/raydium_cp_swap.json",
    instruction="swap_base_input",
)
CPMM_SWAP_ROLES = (
    "payer", "authority", "amm_config", "pool_state", "input_token_account",
    "output_token_account", "input_vault", "output_vault",
    "input_token_program", "output_token_program", "input_token_mint",
    "output_token_mint", "observation_state",
)
CPMM_WRITABLE_ROLES = frozenset((
    "pool_state", "input_token_account", "output_token_account",
    "input_vault", "output_vault", "observation_state",
))


def _u64(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        raise ValueError("exact_u64_required")
    return value


@dataclass(frozen=True)
class CpmmSellInstruction:
    instruction: Instruction
    amount_in_atomic: int
    minimum_out_lamports: int
    expected_output_lamports: int
    pool: str
    amm_config: str
    wallet: str
    base_ata: str
    ephemeral_wsol_account: str
    migration_source_verified: bool = False
    transaction_complete: bool = False
    provider_quote_verified: bool = False
    trading_allowed: bool = False


def build_cpmm_sell_instruction(
    *,
    wallet: str,
    mint: str,
    pool: str,
    amm_config_index: int,
    token_0_mint: str,
    token_1_mint: str,
    input_vault: str,
    output_vault: str,
    observation_state: str,
    amount_in_atomic: int,
    expected_output_lamports: int,
    slippage_bps: int,
    decision_id: str,
) -> CpmmSellInstruction:
    """Prepare the exact Raydium CPMM swap instruction; never access network.

    The expected amount is a *caller-provided hypothesis*. It is NOT proof of
    a fresh slot, spendable liquidity or current CPMM fee calculation.
    """
    for key in (wallet, mint, pool, token_0_mint, token_1_mint,
                input_vault, output_vault, observation_state):
        _decode(key)
    if (mint == SOL_MINT or mint == token_1_mint == token_0_mint
            or {token_0_mint, token_1_mint} != {mint, SOL_MINT}
            or not _decode(token_0_mint) < _decode(token_1_mint)):
        raise ValueError("exact_sorted_classic_SPL_SOL_pair_required")
    amount_in_atomic = _u64(amount_in_atomic, positive=True)
    expected_output_lamports = _u64(expected_output_lamports, positive=True)
    if (type(amm_config_index) is not int or not 0 <= amm_config_index <= 65535
            or type(slippage_bps) is not int or not 0 <= slippage_bps < 10000):
        raise ValueError("bounded_config_and_slippage_required")
    minimum_out = expected_output_lamports * (10000-slippage_bps) // 10000
    _u64(minimum_out, positive=True)
    authority = find_program_address(
        (b"vault_and_lp_mint_auth_seed",), program_id=CPMM_PROGRAM)[0]
    config = find_program_address(
        (b"amm_config", amm_config_index.to_bytes(2,"big")),
        program_id=CPMM_PROGRAM)[0]
    expected_input_vault = find_program_address(
        (b"pool_vault", _decode(pool), _decode(mint)), program_id=CPMM_PROGRAM)[0]
    expected_output_vault = find_program_address(
        (b"pool_vault", _decode(pool), _decode(SOL_MINT)),
        program_id=CPMM_PROGRAM)[0]
    expected_observation = find_program_address(
        (b"observation", _decode(pool)), program_id=CPMM_PROGRAM)[0]
    if (input_vault != expected_input_vault
            or output_vault != expected_output_vault
            or observation_state != expected_observation):
        raise ValueError("CPMM_vault_or_observation_PDA_mismatch")
    input_ata = associated_token_address(wallet, mint)
    output_wsol, _ = ephemeral_wsol_address(wallet, decision_id)
    keys = (
        wallet, authority, config, pool, input_ata, output_wsol,
        input_vault, output_vault, TOKEN_PROGRAM, TOKEN_PROGRAM,
        mint, SOL_MINT, observation_state,
    )
    if any(k in (wallet, input_ata, output_wsol) for k in
           (pool, config, input_vault, output_vault, observation_state)):
        raise ValueError("user_and_CPMM_pool_accounts_must_not_alias")
    instruction = Instruction(
        CPMM_PROGRAM,
        tuple(AccountMeta(
            key, role == "payer", role in CPMM_WRITABLE_ROLES)
            for role, key in zip(CPMM_SWAP_ROLES, keys, strict=True)),
        CPMM_SWAP_BASE_INPUT + struct.pack("<QQ", amount_in_atomic, minimum_out),
    )
    return CpmmSellInstruction(
        instruction, amount_in_atomic, minimum_out,
        expected_output_lamports, pool, config,
        wallet, input_ata, output_wsol,
    )
