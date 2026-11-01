"""No-network curve sell diagnostics on a retained on-chain bank, not fills."""
import json

import pytest

from bot.p3.curve_quote_audit import indicative_curve_sell, curve_exit_diagnostics
from bot.p3.store import CaptureStore
from bot.p3.venue_audit import venue_audit
from bot.p3.quotes import SOL_MINT


def facts(*, status="0", curve_type="0", real_a="200000",
          real_b="500000000", flags=None):
    return dict(facts=dict(
        pool=dict(status=status,mint_b=SOL_MINT,
            virtual_a="1000000",virtual_b="1000000000",
            real_a=real_a,real_b=real_b,
            protocol_fee_accrued="0",platform_fee_accrued="0"),
        config=dict(curve_type=curve_type,trade_fee_rate_ppm="2500"),
        platform=dict(platform_fee_rate_ppm="10000",
                      creator_fee_rate_ppm="5000"),
        quote_vault=dict(amount_atomic="500000000"),
        share_fee_assumption_ppm="0"),
        risk_flags=[] if flags is None else flags)


def test_observed_curve_sell_is_conditionally_calculated_without_fake_fill():
    estimate=indicative_curve_sell(facts(),quantity_atomic="100000")
    assert estimate["curve_estimate_available"] is True
    assert int(estimate["sell_gross_lamports"]) == 100000*1500000000//900000
    assert 0 < int(estimate["sell_output_lamports"]) < int(estimate["sell_gross_lamports"])
    assert estimate["source"]=="observed_onchain_bank_model_not_provider_executable_quote"
    assert estimate["position_acquired"] is False
    assert estimate["executable_sell_verified"] is False
    assert estimate["net_pnl_lamports"] is None
    assert estimate["own_buy_reserve_effect_not_applied"] is True
    json.dumps(estimate,allow_nan=False)


@pytest.mark.parametrize("change,expected",[
    (dict(status="1"),"active_constant_product_native_sol_required"),
    (dict(curve_type="2"),"active_constant_product_native_sol_required"),
    (dict(real_a="200"),"sell_exceeds_observed_outstanding_curve_tokens"),
    (dict(real_b="1"),"observed_exit_liquidity_insufficient")])
def test_unsupported_curve_or_insufficient_observed_bank_fail_closed(change,expected):
    estimate=indicative_curve_sell(facts(**change),quantity_atomic="100000")
    assert estimate["reason"]==expected
    assert not estimate["curve_estimate_available"]
    assert estimate["sell_output_lamports"] is None
    assert estimate["net_pnl_lamports"] is None


def test_unknown_fees_or_vault_cannot_be_replaced_with_zero():
    state=facts()
    state["facts"]["quote_vault"]["amount_atomic"]=None
    estimate=indicative_curve_sell(state,quantity_atomic="100000")
    assert estimate["reason"]=="invalid_strict_unsigned_account_fact"
    assert not estimate["curve_estimate_available"]


def make_journal(tmp_path,*,missing_followup=False,unsafe_late_buy=False):
    path=tmp_path/"curve.sqlite"
    mint="FixtureTokenMint"
    with CaptureStore(path,clock_ms=lambda:2000) as store:
        def append(kind,**kw):
            return store.append(kind,provenance="synthetic",**kw)
        append("checkpoint",received_at_ms=800,outcome="prospective_prefix_fixed",
              payload={"candidates":[{"ordinal":0,"mint":mint,"pool":"FixturePool"}]})
        if unsafe_late_buy and not missing_followup:
            append("candidate_decision",mint=mint,received_at_ms=900,
                source_slot=101,outcome="not_admitted",
                payload={"probe_phase":"followup","analysis":facts()})
        buy_id=append("quote_attempt",received_at_ms=1000,mint=mint,
            outcome="quoted",payload={"provider":"raydium_trade_api",
                "quote_side":"buy","output_amount_atomic":"100000"})
        append("checkpoint",received_at_ms=1100,mint=mint,
            outcome="projected_inventory_fixed",payload={
                "buy_observation_id":buy_id,"acquired_atomic":"100000"})
        if not missing_followup and not unsafe_late_buy:
            append("candidate_decision",mint=mint,received_at_ms=1300,
                source_slot=102,outcome="not_admitted",
                payload={"probe_phase":"followup","analysis":facts()})
        append("quote_attempt",received_at_ms=1400,mint=mint,
            outcome="unavailable",reason="provider_rejected",
            payload={"provider":"raydium_trade_api","quote_side":"sell",
                "probe_phase":"followup","exit_scope":"full_expected",
                "retained_sanitized_response":{"success":False,
                                               "msg":"INSUFFICIENT_LIQUIDITY"}})
        return store.events(),store.verify_integrity()


def test_followup_observed_curve_quote_remains_separate_from_provider_refusal(tmp_path):
    events,tail=make_journal(tmp_path)
    rows=curve_exit_diagnostics(events,"FixtureTokenMint")
    assert len(rows)==1
    assert rows[0]["curve_estimate_available"] is True
    assert rows[0]["source_slot"]==102
    report=venue_audit(events,expected_tail=tail)
    assert report["observed_curve_sell_estimates"]==1
    assert report["cases"][0]["trade_api_refusal_counts"]=={"INSUFFICIENT_LIQUIDITY":1}
    assert report["venue_aware_executable_cycle_count"]==0
    assert report["strategy_profitability_verified"] is False


@pytest.mark.parametrize("kwargs",[
    dict(missing_followup=True),dict(unsafe_late_buy=True)])
def test_no_followup_bank_after_projection_produces_no_scenario(tmp_path,kwargs):
    events,tail=make_journal(tmp_path,**kwargs)
    rows=curve_exit_diagnostics(events,"FixtureTokenMint")
    assert len(rows)==1
    assert rows[0]["reason"]=="causal_followup_curve_bank_missing"
    report=venue_audit(events,expected_tail=tail)
    assert report["observed_curve_sell_estimates"]==0
