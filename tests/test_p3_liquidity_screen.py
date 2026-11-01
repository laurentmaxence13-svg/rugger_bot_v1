"""Offline adversarial tests: a route quote is not a fill or executable sale."""
import copy

import pytest

from bot.p3.liquidity_screen import initial_full_exit_liquidity_screen
from bot.p3.quotes import SOL_MINT
from bot.p3.prospective_report import build_prospective_report
from test_p3_prospective_report import corpus

MINT = "TokenTestMint"


def event(*, outcome="quoted", phase="initial", scope="full_expected",
          size="100", side="sell", response=None):
    return dict(
        id=12, kind="quote_attempt", mint=MINT, outcome=outcome,
        payload=dict(
            probe_phase=phase, exit_scope=scope, quote_side=side,
            inventory_buy_observation_id=4,
            input_mint=MINT, output_mint=SOL_MINT,
            input_amount_atomic=size, http_status=200,
            output_amount_atomic="400000000",
            min_output_amount_atomic="395000000",
            route=[dict(inputMint=MINT, outputMint=SOL_MINT)],
            retained_sanitized_response=response,
            executable_confirmed=False,
            execution_guaranteed=False,
        ),
    )


def screen(e):
    return initial_full_exit_liquidity_screen(
        mint=MINT, acquired_atomic="100",
        buy_observation_id=4, sell_event=e)


def test_exact_full_size_initial_route_only_passes_liquidity_not_execution():
    result=screen(event())
    assert result["initial_full_exit_route_quoted"] is True
    assert result["reason"] == "full_size_route_quoted_not_executed"
    assert result["full_sell_observation_id"] == 12
    assert result["position_acquired"] is False
    assert result["paper_entry_admitted"] is False
    assert result["exit_execution_verified"] is False
    assert result["net_pnl_lamports"] is None


@pytest.mark.parametrize("changed", [
    {"phase":"followup"}, {"scope":"partial_diagnostic"},
    {"size":"25"}, {"side":"buy"},
])
def test_followups_smaller_sales_wrong_side_cannot_pass(changed):
    assert screen(event(**changed))["initial_full_exit_route_quoted"] is False


def test_missing_exit_and_business_refusal_fail_closed_with_reason():
    missing=screen(None)
    assert not missing["initial_full_exit_route_quoted"]
    assert missing["reason"]=="initial_full_sell_not_observed"
    rejection=event(outcome="unavailable",
                    response={"success":False,"msg":"INSUFFICIENT_LIQUIDITY"})
    observed=screen(rejection)
    assert observed["rejection_code"]=="INSUFFICIENT_LIQUIDITY"
    assert observed["reason"]=="full_exit_quote_unavailable"
    assert not observed["initial_full_exit_route_quoted"]
    assert observed["full_sell_observation_id"]==12


@pytest.mark.parametrize("field,value", [
    ("http_status",429), ("route",[]), ("min_output_amount_atomic",None),
    ("output_amount_atomic","0"),
    ("min_output_amount_atomic","500000000"),
    ("inventory_buy_observation_id",7),
    ("output_mint",MINT),
])
def test_malformed_or_mismatched_quote_fails_closed(field,value):
    fake=event()
    fake["payload"][field]=value
    assert not screen(fake)["initial_full_exit_route_quoted"]


def test_rejected_event_cannot_be_promoted_by_later_quoted_partial():
    first=event(outcome="unavailable",
                response={"success":False,"msg":"INSUFFICIENT_LIQUIDITY"})
    partial=event(scope="partial_diagnostic",size="25")
    assert not screen(first)["initial_full_exit_route_quoted"]
    assert not screen(partial)["initial_full_exit_route_quoted"]


def test_old_report_without_initial_screen_remains_unqualified(tmp_path):
    plan,events,tail=corpus(tmp_path)
    report=build_prospective_report(
        plan,events,integrity_verified=True,expected_tail=tail)
    assert report["initial_full_exit_route_quoted"] == 0
    assert report["initial_full_exit_gates_recorded"] == 0
    assert report["cases"][0]["initial_full_exit_liquidity_screens"][0][
        "initial_full_exit_route_quoted"] is False
    assert "initial_full_exit_liquidity_gate_not_passed" in report["cases"][0][
        "admission_reasons"]
    assert report["settled_positions"]==0
    assert report["net_pnl_sol"] is None
