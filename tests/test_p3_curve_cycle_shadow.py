"""Venue-correct S1/S2 research model: no routed AMM inventory or fill claims."""
import copy
import json

import pytest

from bot.p3.curve_cycle_shadow import conditional_curve_case,replay,replay_events
from bot.p3.store import CaptureStore
from bot.p3.quotes import SOL_MINT


MINT="TestPublicMint"
POOL="TestPublicPool"


def sample_analysis(phase, *, projected=True, status="0", outstanding="200000"):
    analysis=dict(context_slot=100 if phase=="initial" else 101,
        facts=dict(pool=dict(status=status,mint_b=SOL_MINT,
                virtual_a="1000000",virtual_b="1000000000",
                real_a=outstanding,real_b="500000000",
                protocol_fee_accrued="0",platform_fee_accrued="0"),
            config=dict(curve_type="0",trade_fee_rate_ppm="2500"),
            platform=dict(platform_fee_rate_ppm="10000",creator_fee_rate_ppm="5000"),
            quote_vault=dict(amount_atomic="500000000"),
            share_fee_assumption_ppm="0"),
        risk_flags=[],blocking_reasons=[])
    if phase=="initial":
        analysis["conditional_projection"]=(dict(
            kind="conditional_constant_product_projection",
            buy_input_lamports="100000000",
            buy_output_atomic="10000",
            position_acquired=False,execution_verified=False)
            if projected else None)
    else:
        analysis["conditional_projection"]=None
    return analysis


def journal(tmp_path,*,no_projection=False,no_s2=False,s2_status="0",
            s2_outstanding="200000",out_of_order=False):
    path=tmp_path/"campaign.sqlite"
    # Keep synthetic receipt availability ordered: CaptureStore uses the max
    # of receipt and ingestion clock, so a fixed future clock would flatten
    # S1/S2 into the same availability timestamp.
    with CaptureStore(path,clock_ms=lambda:100) as store:
        def append(kind,**kwargs):
            return store.append(kind,provenance="synthetic",**kwargs)
        append("checkpoint",received_at_ms=1000,
            outcome="prospective_prefix_fixed",
            payload={"candidates":[{"ordinal":0,"mint":MINT,"pool":POOL}]})
        append("candidate_decision",received_at_ms=1100,
            mint=MINT,source_slot=100,outcome="not_admitted",
            reason="prospective_instrumentation_not_strategy_entry",
            payload={"probe_phase":"initial",
                     "analysis":sample_analysis("initial",projected=not no_projection)})
        # This intentionally large AMM buy quantity is WRONG for LaunchLab:
        # it must NEVER enter the S1 curve scenario.
        append("quote_attempt",received_at_ms=1200,mint=MINT,
            outcome="quoted",payload={"provider":"raydium_trade_api",
                "quote_side":"buy","input_amount_atomic":"1000000000",
                "output_amount_atomic":"90000000000000"})
        if not no_s2:
            append("candidate_decision",received_at_ms=1300,
                mint=MINT,source_slot=99 if out_of_order else 101,
                outcome="not_admitted",reason="prospective_instrumentation_not_strategy_entry",
                payload={"probe_phase":"followup",
                         "analysis":dict(sample_analysis("followup",
                              status=s2_status,outstanding=s2_outstanding),
                              context_slot=99 if out_of_order else 101)})
        return path,store.events(),store.verify_integrity()


def test_source_correct_curve_qty_never_uses_amm_buy_quantity(tmp_path):
    path,events,tail=journal(tmp_path)
    report=replay_events(events,expected_tail=tail)
    case=report["cases"][0]
    assert report["selected_tokens"]==1
    assert report["conditional_curve_markouts"]==1
    assert case["status"]=="CONDITIONAL_CURVE_MARKOUT_ONLY"
    assert case["curve_s1_buy_quantity_atomic"]=="10000"
    assert case["curve_s1_buy_quantity_atomic"]!="90000000000000"
    assert int(case["curve_s2_sell_output_lamports"])>0
    assert int(case["conditional_market_markout_before_extra_costs_lamports"])<0
    assert case["s1_bank_slot"]==100 and case["s2_bank_slot"]==101
    assert case["s1_model_frozen_before_s2"] is True
    assert case["own_hypothetical_buy_not_applied_to_observed_s2_bank"] is True
    assert case["actual_sell_executed"] is False
    assert case["actual_acquired_inventory"] is False
    assert report["realized_net_pnl_lamports"] is None
    assert report["real_master_and_reference_net_comparison_lamports"] is None
    assert report["qualified_executable_cycles"] == 0
    assert report["economic_profitability_verified"] is False
    assert report["live_ready_to_arm"] is False


@pytest.mark.parametrize("settings,reason",[
    ({"no_projection":True},"initial_curve_buy_projection_missing_or_blocked"),
    ({"no_s2":True},"missing_or_duplicated_followup_bank"),
    ({"out_of_order":True},"followup_not_causal_or_newer_bank"),
    ({"s2_status":"1"},"followup_curve_sell_active_constant_product_native_sol_required"),
    ({"s2_outstanding":"5"},"followup_curve_sell_sell_exceeds_observed_outstanding_curve_tokens"),
])
def test_source_missing_out_of_order_or_migration_censors_not_profitable(tmp_path,settings,reason):
    _,events,tail=journal(tmp_path,**settings)
    report=replay_events(events,expected_tail=tail)
    case=report["cases"][0]
    assert case["status"]=="UNQUALIFIED"
    assert case["reason"]==reason
    assert case["conditional_market_markout_before_extra_costs_lamports"] is None
    assert case["net_pnl_lamports"] is None
    assert report["conditional_curve_markouts"]==0
    assert report["qualified_executable_cycles"]==0


def test_historic_database_replay_is_read_only_and_never_overwrites(tmp_path):
    path,events,tail=journal(tmp_path)
    before=path.read_bytes()
    out=tmp_path/"curve-replay.json"
    summary=replay(path,out)
    assert summary["conditional_curve_markouts"]==1
    assert summary["qualified_executable_cycles"]==0
    assert summary["actual_master_reference_edge_lamports"] is None
    assert json.loads(out.read_text())["verified_tail_sha256"]==tail
    assert path.read_bytes()==before
    with pytest.raises(ValueError,match="unused JSON"):
        replay(path,out)


def test_no_cherry_picking_duplicate_bank_and_immutable_prefix(tmp_path):
    _,events,tail=journal(tmp_path)
    source=next(e for e in events if e.get("kind")=="candidate_decision"
                and e.get("payload",{}).get("probe_phase")=="followup")
    row=events[0]["payload"]["candidates"][0]
    copied=copy.deepcopy(source)
    copied["id"]=source["id"]+100
    assert conditional_curve_case([*events,copied],row)["reason"]==(
        "missing_or_duplicated_followup_bank")
    with pytest.raises(ValueError,match="Immutable verified"):
        replay_events(events,expected_tail="0"*64)
    altered=copy.deepcopy(events)
    altered[0]["payload"]["candidates"][0]["ordinal"]=5
    with pytest.raises(ValueError,match="Invalid original candidate"):
        replay_events(altered,expected_tail=tail)
