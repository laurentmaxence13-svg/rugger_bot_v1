"""Same-source predeclared LaunchLab sizing, no AMM leakage or winner choice."""
from copy import deepcopy

from bot.p3.curve_size_grid import FROZEN_SIZES_LAMPORTS,sized_s1s2_cases,sized_summary
from bot.p3.quotes import SOL_MINT


def bank(slot,phase,*,real_a=10**13,has_vault=True):
    facts=dict(
        pool=dict(mint_b=SOL_MINT,status="0",
            virtual_a=str(10**15),virtual_b=str(30*10**9),
            real_a=str(real_a),real_b=str(5*10**9),
            total_sell_a=str(10**15),total_fundraising_b=str(100*10**9),
            decimals_a="6",protocol_fee_accrued="0",platform_fee_accrued="0"),
        config=dict(curve_type="0",trade_fee_rate_ppm="2500"),
        platform=dict(platform_fee_rate_ppm="10000",creator_fee_rate_ppm="5000"),
        base_vault=dict(amount_atomic=str(9*10**14)),
        quote_vault=dict(amount_atomic=str(5*10**9+3*10**6)),
        share_fee_assumption_ppm="0")
    if not has_vault:facts.pop("quote_vault")
    return dict(id=1 if phase=="initial" else 2,mint="fixture-mint",
        kind="candidate_decision",outcome="not_admitted",
        source_slot=slot,available_at_ms=slot*100,
        payload={"probe_phase":phase,
                 "analysis":dict(facts=facts,risk_flags=[])})


def source():
    return [bank(100,"initial"),bank(101,"followup",real_a=2*10**13)]


def test_predefined_grid_same_s1_data_all_sizes_preserved_without_best_selection():
    row=dict(ordinal=0,mint="fixture-mint")
    results=sized_s1s2_cases(source(),row)
    assert [x["size_lamports"] for x in results]==list(FROZEN_SIZES_LAMPORTS)
    assert len(results)==4
    assert results[0]["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
    assert results[1]["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
    assert results[2]["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
    assert results[3]["status"]=="UNQUALIFIED"
    assert results[3]["reason"]=="S2_sell_exceeds_observed_outstanding_curve_tokens"
    assert len({x["s1_curve_buy_atomic"] for x in results})==4
    assert all(x["actual_entry_filled"] is False and x["actual_exit_filled"] is False
               and x["realized_pnl_lamports"] is None for x in results)
    summary=sized_summary(source(),[row])
    assert summary["conditional_only_size_markouts"]==3
    assert summary["assessed_sizes"]==4
    assert summary["no_winner_selected"] is True
    assert summary["master_reference_actual_net_lamports"] is None
    assert summary["proven_profitability"] is False


def test_unrelated_amm_quotes_do_not_affect_launchlab_grid():
    row=dict(ordinal=0,mint="fixture-mint")
    baseline=sized_s1s2_cases(source(),row)
    unrelated=dict(id=3,mint="fixture-mint",kind="quote_attempt",outcome="quoted",
        source_slot=100,available_at_ms=10000,
        payload=dict(quote_side="buy",provider="raydium_trade_api",
                     output_amount_atomic=str(10**19)))
    assert sized_s1s2_cases(source()+[unrelated],row)==baseline


def test_missing_or_risky_bank_refuses_all_sizes_without_zero_filling():
    row=dict(ordinal=0,mint="fixture-mint")
    events=source()
    events[0]["payload"]["analysis"]["risk_flags"]=["unsupported_mint_extension"]
    data=sized_s1s2_cases(events,row)
    assert all(r["status"]=="UNQUALIFIED"
               and r["conditional_delta_before_extra_costs_lamports"] is None
               and r["reason"]=="S1_curve_bank_reserve_or_fee_facts_unqualified"
               for r in data)
    missing=source()
    missing[0]["payload"]["analysis"]["facts"].pop("quote_vault")
    data=sized_s1s2_cases(missing,row)
    assert all(r["status"]=="UNQUALIFIED" and
               r["reason"]=="S1_curve_bank_reserve_or_fee_facts_unqualified"
               for r in data)


def test_no_future_bank_and_nonactive_s2_do_not_invent_closures():
    row=dict(ordinal=0,mint="fixture-mint")
    assert all(r["reason"]=="missing_or_duplicated_followup_bank" for r in
               sized_s1s2_cases(source()[:1],row))
    wrong=source()
    wrong[1]["source_slot"]=100
    assert all(r["reason"]=="followup_not_causal_or_newer_bank" for r in
               sized_s1s2_cases(wrong,row))
    migrated=source()
    migrated[1]["payload"]["analysis"]["facts"]["pool"]["status"]="1"
    assert all(r["reason"]=="S2_active_constant_product_native_sol_required"
               for r in sized_s1s2_cases(migrated,row))


def test_sizing_does_not_depend_on_S2_outcome_before_freezing_S1():
    row=dict(ordinal=0,mint="fixture-mint")
    old=sized_s1s2_cases(source(),row)
    future=source()
    future[1]["payload"]["analysis"]["facts"]["pool"]["real_a"]=str(10**14)
    newer=sized_s1s2_cases(future,row)
    assert [r["s1_curve_buy_atomic"] for r in old]==[
           r["s1_curve_buy_atomic"] for r in newer]
    assert [r["size_lamports"] for r in old]==[
           r["size_lamports"] for r in newer]
    assert old[3]["status"]=="UNQUALIFIED"
    assert newer[3]["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
