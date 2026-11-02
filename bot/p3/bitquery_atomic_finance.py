"""Exact-atomic integer intake for source-reported Bitquery Solana DEX rows.

Only READS historical provider claims. These are NOT Master trades, executable
quotes, signed-creator identity proofs, or prospective S1 feature availability.
Financial amounts are converted with Decimal, never binary float, and failures
are refused instead of rounding. Network fees are per TRANSACTION signature,
not per DEX instruction row: do not double-charge them on multi-hop events.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

SOL = frozenset((
    "So11111111111111111111111111111111111111112",
    "11111111111111111111111111111111",
))
PROGRAMS = {
    "raydium_launchpad": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    "raydium_cpmm": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
}
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,100}$")


def decimal_amount(value, *, nonnegative=True):
    if type(value) is float or isinstance(value, bool) or value is None:
        raise ValueError("binary_float_or_missing_financial_amount_refused")
    if type(value) not in (str, int, Decimal):
        raise ValueError("unexpected_financial_amount_type")
    if type(value) is str and len(value) > 70:
        raise ValueError("financial_amount_string_too_large")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("invalid_decimal_financial_amount") from None
    if not amount.is_finite() or abs(amount) > Decimal("100000000000000000000"):
        raise ValueError("nonfinite_or_extreme_financial_amount")
    if nonnegative and amount < 0:
        raise ValueError("negative_financial_amount")
    return amount


def exact_atomic(value, decimals, *, positive=False):
    """Tokens and SOL: preserve all atomic units without rounding."""
    if type(decimals) is not int or not 0 <= decimals <= 18:
        raise ValueError("invalid_token_decimal_scale")
    amount = decimal_amount(value)
    units = amount * (10 ** decimals)
    if units != units.to_integral_value():
        raise ValueError("fractional_atomic_unit_refused")
    if positive and units <= 0:
        raise ValueError("nonpositive_trade_amount")
    return int(units)


def exact_sol_lamports(value, *, positive=False):
    return exact_atomic(value, 9, positive=positive)


def _address(value):
    if type(value) is not str or BASE58.fullmatch(value) is None:
        raise ValueError("invalid_source_address")
    return value


def _index(row, field):
    value = row.get(field)
    if type(value) is not int or value < 0:
        raise ValueError("invalid_event_index:" + field)
    return value


def source_reported_direct_sol_trade(row, *, program):
    """Normalize ONE onchain DEX ROW, never assume it was our own fill.

    Non-SOL pairs return None. Multi-leg signatures must be reconciled against
    exact signer receipts before a historical fee/position claim is made.
    """
    if type(row) is not dict:
        raise ValueError("dex_trade_row_not_mapping")
    if program not in PROGRAMS:
        raise ValueError("unsupported_raydium_program")
    if row.get("Trade_Dex_ProgramAddress") != PROGRAMS[program]:
        raise ValueError("wrong_raydium_program")
    if row.get("Transaction_Result_Success") is not True:
        return None  # failed transactions never produce a fulfilled swap
    bought = _address(row.get("Trade_Buy_Currency_MintAddress"))
    sold = _address(row.get("Trade_Sell_Currency_MintAddress"))
    if (bought in SOL) == (sold in SOL):
        return None
    buy_decimals = row.get("Trade_Buy_Currency_Decimals")
    sell_decimals = row.get("Trade_Sell_Currency_Decimals")
    token_buy = sold in SOL
    sol_amount = (row.get("Trade_Sell_Amount") if token_buy
                  else row.get("Trade_Buy_Amount"))
    token_amount = (row.get("Trade_Buy_Amount") if token_buy
                    else row.get("Trade_Sell_Amount"))
    token_decimals = buy_decimals if token_buy else sell_decimals
    if token_buy and sell_decimals != 9:
        raise ValueError("wrong_sol_decimals")
    if not token_buy and buy_decimals != 9:
        raise ValueError("wrong_sol_decimals")
    signature = _address(row.get("Transaction_Signature"))
    market = _address(row.get("Trade_Market_MarketAddress"))
    signer = _address(row.get("Transaction_Signer"))
    fee_payer = _address(row.get("Transaction_FeePayer"))
    slot = row.get("Block_Slot")
    if type(slot) is not int or slot < 1:
        raise ValueError("invalid_source_slot")
    return {
        "schema": "rugger-bitquery-direct-sol-historical-hint-v1",
        "provider_reported_only": True,
        "is_actual_master_trade": False,
        "is_executable_asof_quote": False,
        "is_creator_identity_verified": False,
        "program": program,
        "pool": market,
        "mint": bought if token_buy else sold,
        "signature": signature,
        "signer": signer,
        "fee_payer": fee_payer,
        "source_slot": slot,
        "order_key": (
            slot, _index(row, "Transaction_Index"),
            _index(row, "Instruction_Index"),
            _index(row, "Trade_Index")),
        "direction": "BUY_TOKEN_PAY_SOL" if token_buy else "SELL_TOKEN_RECEIVE_SOL",
        "sol_amount_lamports": exact_sol_lamports(sol_amount, positive=True),
        "token_amount_atomic": exact_atomic(token_amount, token_decimals,
                                               positive=True),
        "network_fee_per_signature_lamports": exact_sol_lamports(
            row.get("Transaction_Fee")),
        "protocol_fees_fully_reconciled": False,
        "trade_fill_verified_for_master": False,
        "financial_order_submitted": False,
    }
