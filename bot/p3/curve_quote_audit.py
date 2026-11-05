"""Offline indicative LaunchLab curve exits from *observed* on-chain bank states.

Never a wallet quote, executable sell, a fill, a counterfactual buy applied to
the chain, or a trading recommendation. It only evaluates fixed projected
inventory quantities against later observed curve reserves and explicit fees.
The historical snapshot's rejection cannot certify post-buy illiquidity.
"""
from bot.p3.launchlab import observed_sell_projection, SnapshotEvidenceError
from bot.p3.quotes import SOL_MINT


def _uint(value):
    if type(value) is int and 0 <= value < 2**64:
        return value
    if (type(value) is str and 1 <= len(value) <= 20
            and value.isdecimal() and int(value) < 2**64):
        return int(value)
    raise ValueError("invalid_strict_unsigned_account_fact")


def indicative_curve_sell(analysis, *, quantity_atomic):
    """Price a fixed quantity from the current observed state, with caveats.

    The model is intentionally independent of Raydium Trade API route quotes.
    Passing this diagnostic NEVER passes the executable full-exit liquidity gate.
    """
    basis=dict(kind="launchlab_observed_curve_sell_diagnostic_v1",
        source="observed_onchain_bank_model_not_provider_executable_quote",
        requested_sell_atomic=str(quantity_atomic),sell_output_lamports=None,
        curve_fee_lamports=None,quote_vault_spendable_lamports=None,
        reason="missing_verified_curve_facts",curve_estimate_available=False,
        additional_execution_costs_known=False,position_acquired=False,
        executable_sell_verified=False,net_pnl_lamports=None,
        migration_verified=False,own_buy_reserve_effect_not_applied=True)
    if type(analysis) is not dict or type(analysis.get("facts")) is not dict:
        return basis
    facts=analysis["facts"]
    pool=facts.get("pool"); config=facts.get("config")
    platform=facts.get("platform"); vault=facts.get("quote_vault")
    if any(type(x) is not dict for x in (pool,config,platform,vault)):
        return basis
    try:
        quantity=_uint(quantity_atomic)
        if quantity == 0:
            raise ValueError("zero_sell_quantity")
        status=_uint(pool.get("status"))
        curve_type=_uint(config.get("curve_type"))
        if status != 0 or curve_type != 0 or pool.get("mint_b") != SOL_MINT:
            basis["reason"]="active_constant_product_native_sol_required"
            return basis
        rates=[_uint(config.get("trade_fee_rate_ppm")),
               _uint(platform.get("platform_fee_rate_ppm")),
               _uint(platform.get("creator_fee_rate_ppm"))]
        share_rate=_uint(facts.get("share_fee_assumption_ppm"))
        quote_vault=_uint(vault.get("amount_atomic"))
        raw_pool=dict(pool)
        for key in ("virtual_a","virtual_b","real_a","real_b",
                    "protocol_fee_accrued","platform_fee_accrued"):
            raw_pool[key]=_uint(pool.get(key))
        raw_pool["status"]=status
        derived=observed_sell_projection(
            raw_pool,input_token_atomic=quantity,fee_rates_ppm=rates,
            quote_vault_lamports=quote_vault,curve_type=curve_type,
            share_fee_rate_ppm=share_rate)
    except (SnapshotEvidenceError,ValueError,TypeError,KeyError) as error:
        # Only known categorical local errors, never raw RPC response contents.
        reason=str(error)
        basis["reason"]=reason if (reason.replace("_","").isalnum()
                                   and len(reason) <= 96) else "curve_state_unqualified"
        return basis
    basis.update(curve_estimate_available=True,reason="model_only_not_executable",
        sell_output_lamports=derived["output_lamports"],
        curve_fee_lamports=derived["curve_fee_lamports"],
        quote_vault_spendable_lamports=derived["spendable_quote_vault_lamports"],
        sell_gross_lamports=derived["gross_output_lamports"],
        fee_rate_total_ppm=derived["fee_rate_total_ppm"],
        snapshot_risk_flags=list(analysis.get("risk_flags", []))
            if type(analysis.get("risk_flags")) is list else ["unknown_risk_flags"])
    return basis


def curve_exit_diagnostics(events, mint):
    """Use frozen projected quantity and later snapshot; never select winners."""
    if type(events) is not list or not isinstance(mint,str):
        raise ValueError("Verified capture events and mint required")
    same=[e for e in events if e.get("mint")==mint]
    fixed=[e for e in same if (e.get("kind")=="checkpoint"
           and e.get("outcome")=="projected_inventory_fixed")]
    out=[]
    by_id={e.get("id"):e for e in events}
    for checkpoint in fixed:
        p=checkpoint.get("payload")
        if type(p) is not dict:
            continue
        buy_id=p.get("buy_observation_id")
        buy=by_id.get(buy_id)
        if (type(buy_id) is not int or type(buy) is not dict
                or buy.get("mint")!=mint or buy.get("outcome")!="quoted"
                or buy.get("kind")!="quote_attempt" or buy["id"]>=checkpoint["id"]):
            out.append(dict(buy_observation_id=buy_id,status="unqualified",
                            reason="projected_buy_link_unverified"))
            continue
        try:
            quantity=_uint(p.get("acquired_atomic"))
            if quantity==0 or str(quantity)!=str(buy["payload"]["output_amount_atomic"]):
                raise ValueError("projected_inventory_mismatch")
        except (TypeError,KeyError,ValueError):
            out.append(dict(buy_observation_id=buy_id,status="unqualified",
                            reason="projected_inventory_mismatch"))
            continue
        followups=[e for e in same if e.get("kind")=="candidate_decision"
                   and e.get("payload",{}).get("probe_phase")=="followup"
                   and type(e.get("payload",{}).get("analysis")) is dict
                   and type(e.get("source_slot")) is int
                   and e["id"]>checkpoint["id"]
                   and e.get("available_at_ms",0)>=checkpoint.get("available_at_ms",0)]
        if not followups:
            out.append(dict(buy_observation_id=buy_id,status="unqualified",
                            reason="causal_followup_curve_bank_missing",
                            executable_sell_verified=False,net_pnl_lamports=None))
            continue
        # Report every follow-up (not a cherry-picked favorable result).
        for followup in followups:
            result=indicative_curve_sell(followup["payload"]["analysis"],
                                         quantity_atomic=quantity)
            result.update(buy_observation_id=buy_id,
                inventory_checkpoint_id=checkpoint["id"],
                followup_decision_observation_id=followup["id"],
                source_slot=followup["source_slot"],
                source_available_at_ms=followup["available_at_ms"],
                causal_basis="observed_bank_after_frozen_projected_inventory")
            out.append(result)
    return out
