"""Raydium CPMM migration quote: fee-on directional and full lot safeguards."""
from copy import deepcopy

import pytest

from bot.p3.quotes import SOL_MINT
from bot.p4.cpmm_quote_adapter import cpmm_sell_source_quote,CPMM_MAINNET
from bot.p4.live_like_paper_ledger import PaperLedger,freeze_decision

MINT="fixture-migrated-token"
OLD_POOL="fixture-launchlab-curve"
CPMM_POOL="fixture-signed-cpmm-pool"


def migration():
    return dict(mint=MINT,from_pool=OLD_POOL,to_pool=CPMM_POOL,
        source_slot=129,signed_transaction_verified=True,
        transaction_sha256="a"*64)


def bank(*,fee_on="BothToken",token0=MINT,trade=2500,creator=1000):
    return dict(pool=CPMM_POOL,owner_program=CPMM_MAINNET,
        token0_mint=token0,token1_mint=SOL_MINT if token0==MINT else MINT,
        token_mint=MINT,sol_mint=SOL_MINT,
        vault_token_atomic=1_000_000_000,vault_sol_lamports=10_000_000_000,
        accrued_protocol_token=10_000,accrued_fund_token=1000,
        accrued_creator_token=2000,
        accrued_protocol_sol=100_000,accrued_fund_sol=10_000,
        accrued_creator_sol=20_000,
        trade_fee_rate_ppm=trade,creator_fee_rate_ppm=creator,
        creator_fee_on=fee_on,token_transfer_fee_input_atomic=0,
        sol_transfer_fee_output_lamports=0,
        token2022_extensions_verified=True,source_bank_owner_verified=True,
        source_slot=130,available_at_ms=3000,source_sha256="b"*64)


def paper_quote(b,**kw):
    return cpmm_sell_source_quote(
        bank=b,mint=MINT,curve_pool=OLD_POOL,token_amount_atomic=1_000_000,
        migration=migration(),
        network_and_priority_fee_lamports=5000,
        account_creation_fee_lamports=0,failed_attempt_fee_lamports=0,**kw)


def test_cpmm_fee_on_input_vs_output_produces_different_exact_token_lot():
    source=bank()
    entry=paper_quote(source)
    assert entry["paper_quote"]["venue"]=="RAYDIUM_CPMM"
    assert entry["paper_quote"]["input_atomic"]==1_000_000
    assert entry["fee_details"]["creator_fee_token_atomic"]!="0"
    assert entry["fee_details"]["creator_fee_sol_lamports"]=="0"
    output_fee=paper_quote(bank(fee_on="OnlyToken1"))
    assert output_fee["fee_details"]["creator_fee_token_atomic"]=="0"
    assert int(output_fee["fee_details"]["creator_fee_sol_lamports"])>0
    assert entry["paper_quote"]["output_atomic"]!=output_fee["paper_quote"]["output_atomic"]
    assert entry["quote_is_conditional_bank_model"] is True
    assert entry["actual_transaction_executed"] is False


def test_cpmm_fees_accrued_removed_from_raw_vaults_and_token_transfer_charged_once():
    plain=paper_quote(bank())
    fee_bank=bank()
    fee_bank["token_transfer_fee_input_atomic"]=1000
    taxed=paper_quote(fee_bank)
    assert taxed["paper_quote"]["output_atomic"]<plain["paper_quote"]["output_atomic"]
    assert int(plain["fee_details"]["net_sol_reserve_lamports"])==(
        10_000_000_000-130_000)
    assert int(plain["fee_details"]["net_token_reserve_atomic"])==(
        1_000_000_000-13_000)


def test_unsigned_wrong_pool_or_wrong_cpmm_owner_fail_closed():
    bad=bank()
    bad["owner_program"]="AMM-v4"
    with pytest.raises(ValueError,match="wrong_cpmm_program"):
        paper_quote(bad)
    bad=bank()
    bad["token2022_extensions_verified"]=False
    with pytest.raises(ValueError,match="unverified_extensions"):
        paper_quote(bad)
    bad=bank()
    bad["source_bank_owner_verified"]=False
    with pytest.raises(ValueError,match="unverified_extensions"):
        paper_quote(bad)
    bad=bank()
    bad["accrued_protocol_sol"]=10_000_000_000
    with pytest.raises(ValueError,match="accrued_cpmm_fees"):
        paper_quote(bad)
    with pytest.raises(ValueError,match="verified_cpmm_bank_and_migration"):
        cpmm_sell_source_quote(bank=bank(),mint=MINT,curve_pool=OLD_POOL,
            token_amount_atomic=1_000_000,migration=None,
            network_and_priority_fee_lamports=5000,
            account_creation_fee_lamports=0,
            failed_attempt_fee_lamports=0)


def test_precommitted_master_paper_position_exits_on_signed_cpmm_quote():
    frozen=freeze_decision(dict(
        id="m1",mint=MINT,creator="fixture-creator",pool=OLD_POOL,
        source_slot=100,available_at_ms=1000,
        entry_size_lamports=100_000_000,
        decisions=dict(master="ENTER",reference="WAIT"),
        signed_creator_verified=True,asof_features_verified=True,
        source_quote_clock_verified=True,policy_sha256="f"*64))
    exchange=PaperLedger()
    exchange.register(frozen)
    buy=dict(id="launchlab-model-buy",mint=MINT,pool=OLD_POOL,
             venue="LAUNCHLAB_CURVE",side="BUY",
             input_atomic=100_000_000,output_atomic=1_000_000,
             source_slot=110,available_at_ms=1800,source_produced_at_ms=1800,
             source_observation_sha256="d"*64,
             provenance="OBSERVED_CHAIN_MODEL",
             network_and_priority_fee_lamports=5000,
             account_creation_fee_lamports=0,failed_attempt_fee_lamports=0,
             migration_proof=None)
    exchange.quote("m1","master","BUY",buy)
    cpmm=paper_quote(bank())["paper_quote"]
    exchange.quote("m1","master","SELL",cpmm)
    summary=exchange.snapshot()
    assert summary["accounts"]["master"]["closed_paper_cycles"]==1
    assert summary["accounts"]["master"]["open_positions"]==0
    assert summary["accounts"]["master"]["closed_trades"][0]["migration_to_cpmm"] is True
    assert summary["accounts"]["reference"]["complete_cycle_net_pnl_lamports"]==0
    assert summary["policy_paired_model_net_edge_lamports"]==(
        summary["accounts"]["master"]["complete_cycle_net_pnl_lamports"])
    assert summary["actual_sol_spent"]==0 and summary["exact_live_profitability_verified"] is False


def test_cpmm_combined_input_fee_ceil_once_on_small_lot():
    # For 101 atoms, trade and creator independent ceil would cost 2 atoms;
    # the verified Raydium combined fee is exactly ceil(101*3500/1e6) = 1.
    result=cpmm_sell_source_quote(
        bank=bank(trade=2500,creator=1000),mint=MINT,
        curve_pool=OLD_POOL,token_amount_atomic=101,
        migration=migration(),network_and_priority_fee_lamports=5000,
        account_creation_fee_lamports=0,failed_attempt_fee_lamports=0)
    parts=result["fee_details"]
    assert int(parts["swap_trade_fee_token_atomic"])+int(
        parts["creator_fee_token_atomic"])==1
    assert result["paper_quote"]["output_atomic"]>0
    assert result["actual_transaction_executed"] is False
