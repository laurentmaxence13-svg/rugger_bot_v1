"""Economic no-go for quoted losses even before unknown additional fees."""
import pytest
from bot.p3.signed_creator_cost_upper_bound import cost_upper_bounds

def join(delta="-3081155",proceeds="96918845",repeat=False):
    row=dict(mint="public-mint",creator_claim="creator",
        authenticated_outer_creation=True,
        indicative_full_lot_quote_scenarios=[dict(phase="initial",
            estimated_proceeds_lamports=proceeds,
            conditional_delta_before_unknown_costs_lamports=delta)])
    if repeat:
        row["indicative_full_lot_quote_scenarios"].append(dict(
            phase="followup",estimated_proceeds_lamports=proceeds,
            conditional_delta_before_unknown_costs_lamports=delta))
    return dict(schema="rugger-signed-creators-and-quotes-evidence-join-v1",
        financial_order_submitted=False,qualified_economic_cycles=0,
        market_profitability_verified=False,master_net_pnl_lamports=None,
        rows=[row])


def test_negative_quotes_remain_negative_under_any_nonnegative_unknown_fee():
    r=cost_upper_bounds(join(repeat=True))
    assert r["quoted_roundtrip_scenarios_all_negative_before_extra_costs"] is True
    assert r["conditional_quote_scenarios"]==2
    assert r["distinct_token_pool_candidates"]==1
    assert r["independently_verified_creators_in_this_join"]==1
    assert r["scenarios_are_not_independent_creators"] is True
    assert r["rows"][0]["scenarios"][0][
        "best_case_delta_if_additional_costs_nonnegative_lamports"]=="-3081155"
    assert r["rows"][0]["scenarios"][0]["break_even_additional_cost_budget_lamports"] is None
    assert r["realized_net_master_pnl_lamports"] is None
    assert r["future_strategy_profitability_verified"] is False


def test_positive_quote_requires_real_cost_evidence_not_automatic_go():
    r=cost_upper_bounds(join(delta="100000",proceeds="100100000"))
    assert r["quoted_roundtrip_scenarios_all_negative_before_extra_costs"] is False
    assert r["rows"][0]["scenarios"][0]["break_even_additional_cost_budget_lamports"]=="100000"
    assert r["future_strategy_profitability_verified"] is False


def test_tampered_buylot_cannot_be_negative():
    with pytest.raises(ValueError,match="unqualified_implicit_buy_input"):
        cost_upper_bounds(join(delta="1000000000"))


def test_duplicate_phase_is_not_an_independent_second_opportunity():
    j=join(repeat=True)
    j["rows"][0]["indicative_full_lot_quote_scenarios"][1]["phase"]="initial"
    with pytest.raises(ValueError,match="quote_phase_duplicate"):
        cost_upper_bounds(j)


def test_negative_additional_cost_does_not_get_inferred():
    j=join(delta="0")
    r=cost_upper_bounds(j)
    assert r["quoted_roundtrip_scenarios_all_negative_before_extra_costs"] is False
    assert r["future_strategy_profitability_verified"] is False


def test_open_missing_exit_never_called_lose_zero():
    j=join()
    j["rows"][0]["indicative_full_lot_quote_scenarios"]=[]
    r=cost_upper_bounds(j)
    assert r["conditional_quote_scenarios"]==0
    assert r["quoted_roundtrip_scenarios_all_negative_before_extra_costs"] is False
    assert r["realized_net_master_pnl_lamports"] is None


def test_lying_real_execution_not_accepted():
    j=join()
    j["financial_order_submitted"]=True
    with pytest.raises(ValueError,match="signed_creator_quote_only"):
        cost_upper_bounds(j)


def test_invalid_decimal_or_quote_overflow_rejected():
    j=join(delta="-0")
    with pytest.raises(ValueError,match="delta_canonical"):
        cost_upper_bounds(j)


def test_wrong_schema_refused():
    j=join();j["schema"]="not-authorized"
    with pytest.raises(ValueError,match="signed_creator_quote_only"):
        cost_upper_bounds(j)
