"""Two-branch native LaunchLab model for a prospectively frozen PAPER buy.

Branch A: an exact-lot SELL against the untouched, actually observed S2
bank (may refuse if our paper inventory was never actually acquired).
Branch B: overlay the S1 hypothetical buy on the *later observed* S2
bank, then quote the exact owned token lot.

Branch B repairs the purely mechanical "sell exceeds observed real_a"
issue, but is NOT the market state that would have happened: third-party
trading, slippage, migration timing, fee accrual, and pool trajectories
are path-dependent. This is explicitly a conditional sensitivity, not a
provider-executable quote, transaction, verified fill, or Master P&L.
"""
from bot.p3.curve_size_grid import _s1_inputs,_u64
from bot.p3.launchlab import (
    SnapshotEvidenceError,constant_product_projection,observed_sell_projection)
from bot.p3.quotes import SOL_MINT

SUPPORTED_MINT_KEYS=("mint_a","mint_b","config","platform","vault_a","vault_b")
FEE_ACCRUAL_KEYS=("protocol_fee_accrued","platform_fee_accrued")


def _inputs(analysis):
    if (type(analysis) is not dict or
            analysis.get("risk_flags") != [] or
            type(analysis.get("context_slot")) is not int or
            analysis["context_slot"]<=0):
        raise ValueError("bank_risk_or_clock_unqualified")
    facts=analysis.get("facts")
    if type(facts) is not dict or type(facts.get("pool")) is not dict:
        raise ValueError("observed_pool_identity_missing")
    return _s1_inputs(analysis)


def own_buy_s2_overlay(*,s1_analysis,s2_analysis,input_lamports,
                       expected_mint,expected_pool):
    """Return two S2 model branches, keeping source and counterfactual distinct.

    Only an independently pinned, same-pool, active SOL curve with unchanged
    protocol fee schedule qualifies. Never tolerates mismatched mint supply,
    token programs, fee configuration, migration or vault insufficiency.
    """
    amount=_u64(input_lamports)
    if amount<=0 or type(expected_mint) is not str or not expected_mint:
        raise ValueError("nonzero_predeclared_lot_and_mint_required")
    if type(expected_pool) is not str or not expected_pool:
        raise ValueError("source_pool_address_required")
    for bank in (s1_analysis,s2_analysis):
        if (bank.get("pool_address")!=expected_pool or
                bank.get("mint")!=expected_mint or
                bank.get("evidence_profile")!="published_metadata_v1" or
                bank.get("identity_status")!="owner_layout_relations_and_supplied_pins_checked" or
                bank.get("facts",{}).get("program_derived_addresses_verified") is not True):
            raise ValueError("source_pool_or_mint_or_identity_unverified")
    if (s1_analysis["facts"].get("addresses")!=s2_analysis["facts"].get("addresses")
            or type(s1_analysis["facts"].get("addresses")) is not dict):
        raise ValueError("source_seven_account_graph_changed")
    i1,i2=_inputs(s1_analysis),_inputs(s2_analysis)
    if s2_analysis["context_slot"]<=s1_analysis["context_slot"]:
        raise ValueError("S2_source_slot_not_strictly_later")
    p1,p2=i1["pool"],i2["pool"]
    if (p1.get("mint_a")!=expected_mint or p2.get("mint_a")!=expected_mint
            or p1.get("mint_b")!=SOL_MINT or p2.get("mint_b")!=SOL_MINT):
        raise ValueError("source_mint_identity_changed")
    for key in SUPPORTED_MINT_KEYS:
        if p1.get(key)!=p2.get(key):
            raise ValueError("onchain_pool_identity_changed")
    for key in ("decimals_a","decimals_b","virtual_a","virtual_b",
                "total_sell_a","total_fundraising_b","supply"):
        if p1.get(key) is None or p2.get(key) is None or _u64(p1[key])!=_u64(p2[key]):
            raise ValueError("curve_invariants_changed_or_missing")
    if (i1["fee_rates_ppm"]!=i2["fee_rates_ppm"] or
            i1["share_fee_rate_ppm"]!=i2["share_fee_rate_ppm"]):
        raise ValueError("source_fee_config_changed")
    buy=constant_product_projection(
        p1,input_lamports=amount,
        fee_rates_ppm=i1["fee_rates_ppm"],
        base_vault_atomic=i1["base_vault_atomic"],
        quote_vault_lamports=i1["quote_vault_lamports"],
        share_fee_rate_ppm=i1["share_fee_rate_ppm"])
    bought=int(buy["buy_output_atomic"])
    net_in=int(buy["buy_effective_input_lamports"])
    if (p2["real_a"]+bought>p2["total_sell_a"] or
            p2["real_b"]+net_in>=p2["total_fundraising_b"]):
        raise ValueError("overlay_would_cross_curve_completion_or_migration")
    if i2["base_vault_atomic"]<bought:
        raise ValueError("overlay_base_vault_cannot_cover_buy")
    if i2["quote_vault_lamports"]+net_in>=2**64:
        raise ValueError("overlay_quote_vault_u64_overflow")
    pool=dict(p2)
    for key in FEE_ACCRUAL_KEYS:
        pool[key]=_u64(p2.get(key))
    pool["real_a"]+=bought
    pool["real_b"]+=net_in
    if pool["status"]!=0:
        raise ValueError("nonactive_overlay_pool_refused")
    observed=None
    observed_reason=None
    try:
        exact=observed_sell_projection(
            dict(p2,**{k:pool[k] for k in FEE_ACCRUAL_KEYS}),
            input_token_atomic=bought,
            fee_rates_ppm=i2["fee_rates_ppm"],
            quote_vault_lamports=i2["quote_vault_lamports"],
            curve_type=0,share_fee_rate_ppm=i2["share_fee_rate_ppm"])
        observed=exact["output_lamports"]
    except (SnapshotEvidenceError,ValueError) as exc:
        observed_reason=str(exc)
        if not observed_reason.replace("_","").isalnum() or len(observed_reason)>100:
            observed_reason="observed_source_quote_unqualified"
    overlay=observed_sell_projection(
        pool,input_token_atomic=bought,
        fee_rates_ppm=i2["fee_rates_ppm"],
        quote_vault_lamports=i2["quote_vault_lamports"]+net_in,
        curve_type=0,share_fee_rate_ppm=i2["share_fee_rate_ppm"])
    proceed=int(overlay["output_lamports"])
    return dict(schema="p3-own-buy-adjusted-S2-sensitivity-v1",
        source_mint=expected_mint,source_pool=expected_pool,
        S1_slot=s1_analysis["context_slot"],S2_slot=s2_analysis["context_slot"],
        fixed_S1_buy_lamports=str(amount),
        paper_bought_tokens_atomic=str(bought),
        effective_S1_buy_sol_after_curve_fee_lamports=str(net_in),
        S1_buy_curve_fee_lamports=buy["buy_curve_fee_lamports"],
        untouched_S2_bank_exact_lot_sell_lamports=observed,
        untouched_S2_bank_sell_refusal=observed_reason,
        hypothetical_own_buy_added_real_a_atomic=str(bought),
        hypothetical_own_buy_added_real_b_lamports=str(net_in),
        overlay_S2_sell_lamports=str(proceed),
        overlay_S2_delta_before_extra_costs_lamports=str(proceed-amount),
        observation_is_a_two_bank_real_source=True,
        counterfactual_reserves_are_not_observed=True,
        intervening_swaps_repriced_under_own_buy=False,
        original_migration_and_token_program_verified=False,
        provider_executable_buy_quote_verified=False,
        provider_executable_full_lot_exit_verified=False,
        actual_paper_fills=0,
        complete_fee_attribution_verified=False,
        net_Master_pnl_lamports=None,
        net_reference_pnl_lamports=None,
        true_Master_edge_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)
