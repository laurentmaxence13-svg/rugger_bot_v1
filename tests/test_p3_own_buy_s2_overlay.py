"""Conditional self-buy-reserve overlay is not mistaken for an executed PAPER fill."""
from copy import deepcopy

import pytest

from bot.p3.own_buy_s2_overlay import own_buy_s2_overlay
from test_p3_curve_size_grid import bank

MINT="fixture-verified-sol-mint"
POOL="fixture-verified-launchlab-pool"
AMOUNT=50_000_000


def snap(slot,*,real_a=1_000_000_000_000,real_b=5_000_000_000):
    analysis=deepcopy(bank(slot,"initial",real_a=real_a)["payload"]["analysis"])
    pool=analysis["facts"]["pool"]
    pool.update(mint_a=MINT,mint_b=pool["mint_b"],
        supply="1000000000000000",decimals_b="9",config="fixture-config",
        platform="fixture-platform",vault_a="fixture-base-vault",
        vault_b="fixture-quote-vault")
    pool["real_b"]=str(real_b)
    analysis.update(pool_address=POOL,mint=MINT,
        identity_status="owner_layout_relations_and_supplied_pins_checked",
        evidence_profile="published_metadata_v1")
    analysis["facts"]["program_derived_addresses_verified"]=True
    analysis["facts"]["addresses"]=dict(
        pool=POOL,config="fixture-config",platform="fixture-platform",
        mint_a=MINT,mint_b=pool["mint_b"],
        vault_a="fixture-base-vault",vault_b="fixture-quote-vault")
    analysis["facts"]["base_vault"]["amount_atomic"]=str(10**15)
    return analysis


def project(a,b):
    return own_buy_s2_overlay(
        s1_analysis=a,s2_analysis=b,input_lamports=AMOUNT,
        expected_mint=MINT,expected_pool=POOL)


def test_own_buy_overlay_can_quote_when_untouched_observed_s2_lacks_owned_tokens():
    s1=snap(100,real_a=10**13)
    s2=snap(101,real_a=10**12)
    p=project(s1,s2)
    assert p["S1_slot"]==100 and p["S2_slot"]==101
    assert p["untouched_S2_bank_exact_lot_sell_lamports"] is None
    assert p["untouched_S2_bank_sell_refusal"]=="sell_exceeds_observed_outstanding_curve_tokens"
    assert int(p["paper_bought_tokens_atomic"])>10**12
    assert int(p["overlay_S2_sell_lamports"])>0
    assert p["overlay_S2_delta_before_extra_costs_lamports"]==str(
        int(p["overlay_S2_sell_lamports"])-AMOUNT)
    assert p["observation_is_a_two_bank_real_source"] is True
    assert p["counterfactual_reserves_are_not_observed"] is True
    assert p["intervening_swaps_repriced_under_own_buy"] is False
    assert p["provider_executable_full_lot_exit_verified"] is False
    assert p["actual_paper_fills"]==0
    assert p["net_Master_pnl_lamports"] is None
    assert p["true_Master_edge_verified"] is False
    assert p["live_ready_to_arm"] is False


def test_two_models_are_reported_separately_when_both_support_exact_sell():
    a=snap(100,real_a=10**13)
    b=snap(101,real_a=10**13)
    p=project(a,b)
    assert int(p["untouched_S2_bank_exact_lot_sell_lamports"])>0
    assert p["untouched_S2_bank_sell_refusal"] is None
    assert int(p["overlay_S2_sell_lamports"])>0
    assert int(p["overlay_S2_sell_lamports"])!=int(
        p["untouched_S2_bank_exact_lot_sell_lamports"])


@pytest.mark.parametrize("kind",[
    "risk","mint","pool","graph","config","changed_fee","completion",
    "slot","insufficient_base","vault_overflow","schema"])
def test_dangerous_counterfactual_assumptions_refused(kind):
    s1=snap(100,real_a=10**13)
    s2=snap(101,real_a=10**12)
    if kind=="risk":s2["risk_flags"]=["mint_supply_or_decimals_mismatch"]
    if kind=="mint":s2["mint"]="other"
    if kind=="pool":s2["pool_address"]="other"
    if kind=="graph":s2["facts"]["addresses"]["vault_b"]="new-vault"
    if kind=="config":s2["facts"]["pool"]["config"]="other-config"
    if kind=="changed_fee":s2["facts"]["config"]["trade_fee_rate_ppm"]="5000"
    if kind=="completion":s2["facts"]["pool"]["real_b"]=str(99_999_999_999)
    if kind=="slot":s2["context_slot"]=100
    if kind=="insufficient_base":s2["facts"]["base_vault"]["amount_atomic"]="1"
    if kind=="vault_overflow":s2["facts"]["quote_vault"]["amount_atomic"]=str(2**64-1)
    if kind=="schema":s2["evidence_profile"]="legacy"
    with pytest.raises(ValueError):
        project(s1,s2)


def test_no_master_profit_even_if_overlay_theoretically_positive():
    p=project(snap(100,real_a=10**13),snap(101,real_a=10**12))
    assert p["net_Master_pnl_lamports"] is None
    assert p["net_reference_pnl_lamports"] is None
    assert p["financial_order_submitted"] is False
    assert p["complete_fee_attribution_verified"] is False
