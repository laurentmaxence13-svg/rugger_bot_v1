"""Predeclared multi-size LaunchLab curve PAPER sensitivity, never a fill.

Each sizing option is fixed in source code, calculated from the SAME initial
S1 bank and evaluated on the SAME observed S2 bank. No hindsight selection,
no AMM/API buy quantity substituted, no P&L without execution costs/fills.

When replayed on old capture it is explicitly RETROSPECTIVE sensitivity,
not an auditable pre-outcome strategy decision or Master/reference result.
"""
from collections import Counter

from bot.p3.curve_quote_audit import indicative_curve_sell
from bot.p3.curve_cycle_shadow import _bank_analysis
from bot.p3.launchlab import constant_product_projection, SnapshotEvidenceError
from bot.p3.quotes import SOL_MINT


# Frozen research candidates, not executable position sizes.
FROZEN_SIZES_LAMPORTS=(50_000_000,100_000_000,250_000_000,1_000_000_000)


def _u64(value):
    if type(value) is int and 0<=value<2**64:
        return value
    if type(value) is str and 1<=len(value)<=20 and value.isdecimal():
        number=int(value)
        if number<2**64:return number
    raise ValueError("missing_or_invalid_signed_curve_account_fact")


def _s1_inputs(analysis):
    if (type(analysis) is not dict or type(analysis.get("facts")) is not dict
            or type(analysis.get("risk_flags")) is not list
            or analysis["risk_flags"]):
        raise ValueError("S1_curve_bank_missing_or_flagged")
    facts=analysis["facts"]
    pool=facts.get("pool");cfg=facts.get("config")
    platform=facts.get("platform")
    base=facts.get("base_vault");quote=facts.get("quote_vault")
    if any(type(x) is not dict for x in (pool,cfg,platform,base,quote)):
        raise ValueError("S1_curve_bank_reserve_or_fee_facts_missing")
    if (pool.get("mint_b")!=SOL_MINT
            or _u64(pool.get("status"))!=0
            or _u64(cfg.get("curve_type"))!=0):
        raise ValueError("S1_not_supported_active_SOL_curve")
    copy=dict(pool)
    for k in ("virtual_a","virtual_b","real_a","real_b","total_sell_a",
              "total_fundraising_b","decimals_a"):
        copy[k]=_u64(pool.get(k))
    rates=tuple(_u64(row) for row in (
        cfg.get("trade_fee_rate_ppm"),
        platform.get("platform_fee_rate_ppm"),
        platform.get("creator_fee_rate_ppm")))
    return dict(pool=copy,fee_rates_ppm=rates,
                base_vault_atomic=_u64(base.get("amount_atomic")),
                quote_vault_lamports=_u64(quote.get("amount_atomic")),
                share_fee_rate_ppm=_u64(facts.get("share_fee_assumption_ppm")))


def sized_s1s2_cases(events,row):
    """Never optimize after S2; return one row for every frozen requested size."""
    if type(row) is not dict or type(row.get("mint")) is not str:
        raise ValueError("Frozen public candidate identity required")
    mint=row["mint"]
    s1,s1_error=_bank_analysis(events,mint,"initial")
    s2,s2_error=_bank_analysis(events,mint,"followup")
    if s1_error is None and s2_error is None and (
        s2["id"]<=s1["id"] or s2["source_slot"]<=s1["source_slot"]
        or s2["available_at_ms"]<=s1["available_at_ms"]):
        s2_error="followup_not_causal_or_newer_bank"
    try:
        inputs=_s1_inputs(s1["payload"]["analysis"]) if s1_error is None else None
        input_error=None
    except (ValueError,TypeError,KeyError):
        inputs=None
        input_error="S1_curve_bank_reserve_or_fee_facts_unqualified"
    results=[]
    for amount in FROZEN_SIZES_LAMPORTS:
        result=dict(size_lamports=amount,size_sol=f"{amount/1e9:.8f}",
            s1_bank_observation_id=s1["id"] if s1 else None,
            s2_bank_observation_id=s2["id"] if s2 else None,
            s1_source_slot=s1["source_slot"] if s1 else None,
            s2_source_slot=s2["source_slot"] if s2 else None,
            source="S1_LaunchLab_curve_buy_and_S2_observed_curve_sell",
            s1_curve_buy_atomic=None,s2_curve_sell_lamports=None,
            conditional_delta_before_extra_costs_lamports=None,
            status="UNQUALIFIED",reason=None,
            source_risk_flags_preserved=True,
            retrospective_fixed_grid_not_strategy_decision=True,
            own_buy_effect_missing_from_S2_bank=True,
            additional_network_priority_ATA_failure_costs_known=False,
            actual_entry_filled=False,actual_exit_filled=False,
            realized_pnl_lamports=None,net_profit_qualified=False)
        if s1_error is not None:
            result["reason"]=s1_error
        elif s2_error is not None:
            result["reason"]=s2_error
        elif input_error is not None:
            result["reason"]=input_error
        else:
            try:
                buy=constant_product_projection(inputs["pool"],
                    input_lamports=amount,fee_rates_ppm=inputs["fee_rates_ppm"],
                    base_vault_atomic=inputs["base_vault_atomic"],
                    quote_vault_lamports=inputs["quote_vault_lamports"],
                    share_fee_rate_ppm=inputs["share_fee_rate_ppm"])
                quantity=int(buy["buy_output_atomic"])
                result["s1_curve_buy_atomic"]=str(quantity)
                sell=indicative_curve_sell(s2["payload"]["analysis"],
                    quantity_atomic=quantity)
                if sell.get("curve_estimate_available") is True:
                    proceeds=int(sell["sell_output_lamports"])
                    result.update(
                        status="CONDITIONAL_CURVE_MARKOUT_ONLY",
                        reason="observed_S2_bank_excludes_hypothetical_own_buy",
                        s2_curve_sell_lamports=str(proceeds),
                        conditional_delta_before_extra_costs_lamports=str(proceeds-amount),
                        buy_curve_fee_lamports=buy["buy_curve_fee_lamports"],
                        sell_curve_fee_lamports=sell["curve_fee_lamports"])
                else:
                    result["reason"]="S2_"+str(sell.get("reason","curve_unqualified"))
            except (ValueError,TypeError,KeyError,SnapshotEvidenceError) as exc:
                reason=str(exc)
                result["reason"]=("S1_"+reason if reason.replace("_","").isalnum()
                                  and len(reason)<=96 else "S1_curve_model_unqualified")
        results.append(result)
    return results


def sized_summary(events,candidates):
    """Full denominator across candidates and fixed sizes; NEVER choose best."""
    if type(events) is not list or type(candidates) is not list:
        raise ValueError("Verified event series and frozen candidate list required")
    cases=[]
    for row in candidates:
        subset=[e for e in events if e.get("mint")==row["mint"]]
        initial,issue=_bank_analysis(subset,row["mint"],"initial")
        receipts=[e for e in subset if e.get("kind")=="checkpoint"
                  and e.get("outcome")=="initial_curve_size_grid_frozen"]
        if len(receipts)>1:
            raise ValueError("Duplicated pre-followup S1 size-grid receipt")
        preregistered=False
        if receipts:
            if issue is not None:
                raise ValueError("Size grid registered without qualified initial S1")
            source_id=initial["payload"].get("snapshot_observation_id")
            if type(source_id) is not int:
                raise ValueError("Frozen S1 bank observation ID missing")
            expected=freeze_size_grid_at_s1(
                analysis=initial["payload"]["analysis"],mint=row["mint"],
                ordinal=row["ordinal"],snapshot_observation_id=source_id,
                source_slot=initial["source_slot"])
            receipt=receipts[0]
            if (receipt["payload"]!=expected or receipt["id"]<=initial["id"]
                    or receipt["available_at_ms"]<initial["available_at_ms"]
                    or any(e.get("kind")=="candidate_decision"
                           and e.get("payload",{}).get("probe_phase")=="followup"
                           and e["id"]<=receipt["id"] for e in subset)):
                raise ValueError("Pre-followup curve-size grid evidence mismatch")
            preregistered=True
        cases.append(dict(ordinal=row["ordinal"],mint=row["mint"],
            pre_followup_size_grid_frozen_verified=preregistered,
            predetermined_size_grid=sized_s1s2_cases(subset,row)))
    counts=Counter()
    for case in cases:
        for row in case["predetermined_size_grid"]:
            if row["status"]!="CONDITIONAL_CURVE_MARKOUT_ONLY":
                counts[row["reason"] or "unqualified"]=counts[row["reason"] or "unqualified"]+1
    return dict(schema="p3-LaunchLab-fixed-size-retrospective-sensitivity-v1",
        size_grid_lamports=list(FROZEN_SIZES_LAMPORTS),
        sampled_candidates=len(cases),
        assessed_sizes=len(cases)*len(FROZEN_SIZES_LAMPORTS),
        conditional_only_size_markouts=sum(
            row["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
            for c in cases for row in c["predetermined_size_grid"]),
        pre_followup_size_grids_verified=sum(
            c["pre_followup_size_grid_frozen_verified"] for c in cases),
        blocked_size_reasons=dict(sorted(counts.items())),
        no_winner_selected=True,
        historical_replay_not_prospective_preadmission=(
            not all(c["pre_followup_size_grid_frozen_verified"] for c in cases)),
        no_executable_trades=True,
        master_reference_actual_net_lamports=None,
        proven_profitability=False,cases=cases)


def freeze_size_grid_at_s1(*, analysis, mint, ordinal,
                           snapshot_observation_id, source_slot):
    """Freeze fixed S1 curve buy quantities BEFORE any S2 market data arrives.

    A hash-chained journal checkpoint owns this document; the whole fixed grid
    stays visible, including failed sizes. No actual order can be submitted.
    """
    if (type(mint) is not str or not mint or type(ordinal) is not int or ordinal<0
            or type(snapshot_observation_id) is not int or snapshot_observation_id<=0
            or type(source_slot) is not int or source_slot<=0
            or type(analysis) is not dict or analysis.get("context_slot")!=source_slot):
        raise ValueError("S1 certified-bank identity and clock required")
    try:
        inputs=_s1_inputs(analysis)
    except (ValueError,TypeError,KeyError):
        inputs=None
    rows=[]
    for amount in FROZEN_SIZES_LAMPORTS:
        rec=dict(size_lamports=amount,buy_quantity_atomic=None,
                 buy_curve_fee_lamports=None,status="UNQUALIFIED",
                 reason="S1_curve_bank_reserve_or_fee_facts_unqualified")
        if inputs is not None:
            try:
                buy=constant_product_projection(inputs["pool"],
                    input_lamports=amount,fee_rates_ppm=inputs["fee_rates_ppm"],
                    base_vault_atomic=inputs["base_vault_atomic"],
                    quote_vault_lamports=inputs["quote_vault_lamports"],
                    share_fee_rate_ppm=inputs["share_fee_rate_ppm"])
                rec.update(buy_quantity_atomic=buy["buy_output_atomic"],
                    buy_curve_fee_lamports=buy["buy_curve_fee_lamports"],
                    status="S1_MODEL_QUOTED_NOT_FILLED",reason=None)
            except (SnapshotEvidenceError,ValueError,TypeError,KeyError) as exc:
                reason=str(exc)
                rec["reason"]=("S1_"+reason if reason.replace("_","").isalnum()
                               and len(reason)<=96 else "S1_curve_model_unqualified")
        rows.append(rec)
    return dict(schema="p3-S1-frozen-curve-sizes-v1",
        mint=mint,ordinal=ordinal,initial_bank_observation_id=snapshot_observation_id,
        source_slot=source_slot,size_grid_lamports=list(FROZEN_SIZES_LAMPORTS),
        frozen_buy_models=rows,contains_S2_evidence=False,
        all_sizes_retain_no_selection=True,actual_entry_filled=False,
        financial_order_submitted=False,net_pnl_lamports=None)
