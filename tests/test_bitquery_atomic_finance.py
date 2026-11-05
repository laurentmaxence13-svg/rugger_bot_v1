"""Atomic arithmetic and source-only Bitquery normalization contract."""
from decimal import Decimal

import pytest

from bot.p3.bitquery_atomic_finance import (
    PROGRAMS, exact_atomic, exact_sol_lamports, source_reported_direct_sol_trade,
)


SOL = "So11111111111111111111111111111111111111112"
MINT = "ChWZ8yNvMh31yHtkZh3fSjWZaQiv62bHr1WPnUPLvuLF"
SIGNER = "HxM1EeyZ9z71m8mu5x9bsUdtTP1f9qtT7mo9D5tB3xwM"
POOL = "EBA8nnnHuFRMHd3Ac9HMMCNTi52E3GXT7HDreXwvhnCu"
SIGNATURE = "5qqLenzDgNbLkuN482pPEzoZLyygQYsdLzdMZ2cuKqbpXyXRbXZCASRGw2gWNK91cpBZgorjThhJAhiCtwJk6hUk"


def buy():
    return {
        "Trade_Dex_ProgramAddress": PROGRAMS["raydium_launchpad"],
        "Transaction_Result_Success": True,
        "Trade_Buy_Currency_MintAddress": MINT,
        "Trade_Sell_Currency_MintAddress": SOL,
        "Trade_Buy_Amount": "123456.000001",
        "Trade_Sell_Amount": "0.050000001",
        "Trade_Buy_Currency_Decimals": 6,
        "Trade_Sell_Currency_Decimals": 9,
        "Transaction_Signature": SIGNATURE,
        "Trade_Market_MarketAddress": POOL,
        "Transaction_Signer": SIGNER,
        "Transaction_FeePayer": SIGNER,
        "Block_Slot": 464432476,
        "Transaction_Index": 0,
        "Instruction_Index": 1,
        "Trade_Index": 0,
        "Transaction_Fee": "0.000005",
    }


def test_sol_precision_is_integer_lamports():
    assert exact_sol_lamports("0.050000001") == 50_000_001
    assert exact_sol_lamports(Decimal("0.000000001")) == 1
    assert exact_atomic("123456.000001", 6) == 123_456_000_001


@pytest.mark.parametrize("value", ["0.0000000001", "NaN", "Inf", 0.1, "-1", None])
def test_refuse_rounding_floats_nonfinite_negative(value):
    with pytest.raises(ValueError):
        exact_sol_lamports(value)


def test_one_bought_exact_lot_is_not_master_trade():
    rec = source_reported_direct_sol_trade(buy(), program="raydium_launchpad")
    assert rec["direction"] == "BUY_TOKEN_PAY_SOL"
    assert rec["sol_amount_lamports"] == 50_000_001
    assert rec["token_amount_atomic"] == 123_456_000_001
    assert rec["network_fee_per_signature_lamports"] == 5000
    assert rec["provider_reported_only"] is True
    assert rec["is_actual_master_trade"] is False
    assert rec["protocol_fees_fully_reconciled"] is False
    assert rec["financial_order_submitted"] is False


def test_reverse_sol_sale_has_exact_atomic_direction():
    row = buy()
    row["Trade_Buy_Currency_MintAddress"] = SOL
    row["Trade_Sell_Currency_MintAddress"] = MINT
    row["Trade_Buy_Amount"], row["Trade_Sell_Amount"] = (
        "0.060000001", "123456.000001")
    row["Trade_Buy_Currency_Decimals"] = 9
    row["Trade_Sell_Currency_Decimals"] = 6
    rec = source_reported_direct_sol_trade(row, program="raydium_launchpad")
    assert rec["direction"] == "SELL_TOKEN_RECEIVE_SOL"
    assert rec["sol_amount_lamports"] == 60_000_001
    assert rec["token_amount_atomic"] == 123_456_000_001


def test_wrong_program_missing_origin_and_failed_tx_are_not_accepted():
    with pytest.raises(ValueError, match="wrong_raydium_program"):
        source_reported_direct_sol_trade(buy(), program="raydium_cpmm")
    row=buy();row["Transaction_Result_Success"]=False
    assert source_reported_direct_sol_trade(row,program="raydium_launchpad") is None
    row=buy();row["Transaction_Signature"]="not_base58"
    with pytest.raises(ValueError, match="invalid_source_address"):
        source_reported_direct_sol_trade(row, program="raydium_launchpad")


def test_non_sol_quote_is_explicitly_excluded():
    row=buy();row["Trade_Sell_Currency_MintAddress"]=MINT
    assert source_reported_direct_sol_trade(row, program="raydium_launchpad") is None


def test_network_fee_is_source_level_not_net_master_profit():
    a=source_reported_direct_sol_trade(buy(),program="raydium_launchpad")
    b=source_reported_direct_sol_trade(buy(),program="raydium_launchpad")
    assert a["signature"] == b["signature"]
    assert a["network_fee_per_signature_lamports"] == b["network_fee_per_signature_lamports"]
    assert "net_master_profit_lamports" not in a
    assert "net_master_profit_lamports" not in b


def test_actual_vendor_varchar_boolean_is_decoded_without_truthiness_bug():
    row = buy()
    row["Transaction_Result_Success"] = "true"
    assert source_reported_direct_sol_trade(
        row, program="raydium_launchpad")["sol_amount_lamports"] == 50_000_001
    row["Transaction_Result_Success"] = "false"
    assert source_reported_direct_sol_trade(
        row, program="raydium_launchpad") is None
    for invalid in ("TRUE", "1", 1, None, ""):
        row["Transaction_Result_Success"] = invalid
        with pytest.raises(ValueError, match="missing_or_unknown_source_transaction_success"):
            source_reported_direct_sol_trade(row, program="raydium_launchpad")
