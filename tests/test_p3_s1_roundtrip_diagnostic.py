"""Counterfactual same-S1 LaunchLab roundtrip costs are not realized P&L."""
import json
from copy import deepcopy

import pytest

from bot.p3.s1_roundtrip_diagnostic import (
    immediate_roundtrip_cases, report_events, replay)
from bot.p3.store import CaptureStore
from test_p3_curve_size_grid import source as bank_source


def row():
    return dict(ordinal=0,mint="fixture-mint",pool="fixture-pool")


def test_same_bank_own_buy_injected_into_sell_model_not_historical_circulation():
    initial=bank_source()[0]
    initial["payload"]["analysis"]["facts"]["pool"]["real_a"]="0"
    # Historical no-buys circulation=0: an S2 observed sell would be
    # rejected, but a modeled buy->immediate reversal alters the S1 bank.
    result=immediate_roundtrip_cases([initial],row())
    assert len(result)==4
    for item in result:
        assert item["status"]=="S1_CONDITIONAL_IMMEDIATE_ROUNDTRIP_ONLY"
        assert int(item["buy_output_atomic"])>0
        assert 0 < int(item["immediate_full_sell_model_lamports"]) < int(
            item["input_lamports"])
        assert int(item["roundtrip_curve_friction_lamports"])>0
        assert int(item["roundtrip_curve_friction_bps"])>=0
        assert item["onchain_state_changed"] is False
        assert item["order_submitted"] is False
        assert item["entry_fill_verified"] is False
        assert item["exit_fill_verified"] is False
        assert item["Master_reference_net_PnL_lamports"] is None
        assert item["unknown_execution_fees_included"] is False


def test_no_s2_price_can_change_s1_baseline():
    initial,followup=bank_source()
    baseline=immediate_roundtrip_cases([initial],row())
    followup["payload"]["analysis"]["facts"]["pool"]["real_a"]=str(10**14)
    assert immediate_roundtrip_cases([initial,followup],row())==baseline
    initial_risk=deepcopy(initial)
    initial_risk["payload"]["analysis"]["risk_flags"]=["fake_mint_extension"]
    refused=immediate_roundtrip_cases([initial_risk],row())
    assert all(x["status"]=="UNQUALIFIED" and
               x["roundtrip_curve_friction_lamports"] is None for x in refused)


def test_undecodable_bank_or_missing_fee_does_not_fabricate_zero_cost():
    initial=bank_source()[0]
    initial["payload"]["analysis"]["facts"]["platform"].pop(
        "platform_fee_rate_ppm")
    refused=immediate_roundtrip_cases([initial],row())
    assert len(refused)==4
    assert all(x["status"]=="UNQUALIFIED" for x in refused)
    assert all(x["roundtrip_curve_friction_lamports"] is None for x in refused)


def test_immutable_old_capture_local_replay_and_no_master_edge(tmp_path):
    path=tmp_path/"friction.sqlite"
    mint="fixture-mint"
    with CaptureStore(path,clock_ms=lambda:100) as db:
        db.append("checkpoint",received_at_ms=800,outcome="prospective_prefix_fixed",
                  provenance="synthetic",
                  payload={"candidates":[row()]})
        a=bank_source()[0]["payload"]["analysis"]
        db.append("candidate_decision",received_at_ms=1000,
                  source_slot=100,mint=mint,outcome="not_admitted",
                  provenance="synthetic",
                  payload={"probe_phase":"initial","analysis":a})
        tail=db.verify_integrity()
        events=db.events()
    before=path.read_bytes()
    report=report_events(events,expected_tail=tail)
    assert report["selected_tokens"]==1
    assert report["scenario_count"]==4
    assert report["modeled_same_state_roundtrips"]>0
    assert report["actual_Master_minus_reference_net_lamports"] is None
    assert report["qualified_executable_cycles"]==0
    assert report["market_profitability_verified"] is False
    out=tmp_path/"friction.json"
    summary=replay(path,out)
    assert summary["modeled_same_state_roundtrips"]==report[
        "modeled_same_state_roundtrips"]
    assert json.loads(out.read_text())["source_tail_sha256"]==tail
    assert before==path.read_bytes()
    with pytest.raises(ValueError,match="unused separate JSON"):
        replay(path,out)
    with pytest.raises(ValueError,match="Verified immutable"):
        report_events(events,expected_tail="0"*64)


def test_partial_sample_no_survivor_selection(tmp_path):
    first=bank_source()[0]
    second=deepcopy(first)
    second["mint"]="another-token"
    second["payload"]["analysis"]["risk_flags"]=["unknown_extension"]
    results=immediate_roundtrip_cases([first],row())
    refused=immediate_roundtrip_cases([second],dict(
        ordinal=1,mint="another-token",pool="pool-2"))
    assert len(results)==len(refused)==4
    assert all(s["status"]=="UNQUALIFIED" for s in refused)
