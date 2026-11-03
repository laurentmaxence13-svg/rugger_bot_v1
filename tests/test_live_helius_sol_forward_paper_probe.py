"""No-network pre-outcome genuine-score freeze and conditional SOL research ledger."""
from copy import deepcopy

import pytest

from bot.live.helius_sol_forward_paper_probe import (
    _freeze_before_followup,evaluate_probe,run,SCHEMA,SIZING_LAMPORTS)
from test_p3_curve_size_grid import bank


MINT="source-valid-test-mint"
POOL="source-valid-test-pool"
CREATOR="source-creator-public-key"
REG="a"*64


def source_s1(*,risk=False):
    analysis=deepcopy(bank(101,"initial")["payload"]["analysis"])
    analysis["facts"]["pool"]["mint_a"]=MINT
    # Source fixture is an analysis-only bank and intentionally omits the
    # observed source buy projection. Build that *from the same S1 facts*,
    # never from future S2 observations.
    from bot.p3.curve_size_grid import _s1_inputs
    from bot.p3.launchlab import constant_product_projection
    inputs=_s1_inputs(analysis)
    analysis["conditional_projection"]=constant_product_projection(
        inputs["pool"],input_lamports=SIZING_LAMPORTS,
        fee_rates_ppm=inputs["fee_rates_ppm"],
        base_vault_atomic=inputs["base_vault_atomic"],
        quote_vault_lamports=inputs["quote_vault_lamports"],
        share_fee_rate_ppm=inputs["share_fee_rate_ppm"])
    if risk:
        analysis["risk_flags"]=["mint_supply_or_decimals_mismatch"]
        analysis["conditional_projection"]=None
    return dict(registration_sha256=REG,s1_slot=101,
        s1_received_at_ms=300000,
        selected_before_S1=[dict(mint=MINT,pool=POOL,creator_claim=CREATOR)],
        s1_observations=[dict(row=dict(
            mint=MINT,pool=POOL,creator_claim=CREATOR,
            s1_slot=101,s1_analysis_sha256="b"*64),
            s1_analysis=analysis)])


def prospective(*,risk=False,with_exit=True):
    s1=source_s1(risk=risk)
    frozen=_freeze_before_followup(s1)
    action=frozen["frozen_actions"][0]
    qty=action["hypothetical_probe_token_quantity_atomic"]
    ladder=[dict(entry_lamports=str(SIZING_LAMPORTS),
        s1_exact_buy_quantity_atomic=qty,
        s2_conditional_sell_lamports="60000000" if with_exit else None,
        s2_refusal="no_source_verified_exact_lot_S2_sell")]
    return dict(status="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE",
        registration_sha256=REG,first_bank_slot=101,second_bank_slot=102,
        preregistered_research_freeze=frozen,
        S1_research_freeze_before_S2_sha256=_hash_test(frozen),
        observations=[dict(mint=MINT,pool=POOL,s1_slot=101,s2_slot=102,
                           research_size_ladder=ladder,s2_risk_flags=[])])


def _hash_test(doc):
    import hashlib,json
    return hashlib.sha256(json.dumps(doc,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def test_actual_master_and_reference_decisions_frozen_before_future_prices():
    freeze=_freeze_before_followup(source_s1())
    assert freeze["schema"]==SCHEMA
    assert freeze["S2_available_at_ms"] is None
    assert freeze["frozen_before_any_S2_reads"] is True
    assert freeze["financial_order_submitted"] is False
    record=freeze["frozen_actions"][0]
    assert record["actual_Master_action"] in ("WAIT","NO_TRADE")
    assert record["actual_reference_action"]=="WAIT"
    assert record["hypothetical_research_probe_action"]=="ENTER_CONDITIONAL_MODEL"
    assert int(record["hypothetical_probe_token_quantity_atomic"])>0
    assert record["hypothetical_probe_size_lamports"]==50_000_000
    assert record["hypothetical_S1_buy_fill_executed"] is False


def test_model_roundtrip_conditional_fees_does_not_mislabel_master_profit():
    r=evaluate_probe(prospective())
    assert r["status"]=="REAL_SOL_S1S2_PAPER_MODEL_MARKOUTS"
    assert r["exact_model_roundtrips"]==1
    case=r["cases"][0]
    assert case["conditional_markout_before_extra_costs_lamports"]=="10000000"
    assert [s["conditional_net_lamports"] for s in case["extra_cost_scenarios"]]==[
        "10000000","9985000","9000000","0"]
    assert r["measured_Master_minus_reference_edge_lamports"] is None
    assert r["exact_net_Master_pnl_lamports"] is None
    assert case["actual_paper_buy_fill_count"]==0
    assert r["profitability_demonstrated"] is False
    assert r["financial_order_submitted"] is False


def test_missing_exit_censors_position_never_zero_pnl():
    r=evaluate_probe(prospective(with_exit=False))
    assert r["exact_model_roundtrips"]==0
    assert r["cases"][0]["status"]=="CENSORED_OPEN_HYPOTHETICAL_PROBE_NO_S2_EXIT"
    assert r["cases"][0]["extra_cost_scenarios"]==[]
    assert r["cases"][0]["conditional_markout_before_extra_costs_lamports"] is None


def test_source_risk_blocks_even_fixed_probe_action():
    r=evaluate_probe(prospective(risk=True))
    assert r["exact_model_roundtrips"]==0
    assert r["cases"][0]["status"]=="S1_RESEARCH_PROBE_NOT_ADMISSIBLE"
    assert r["cases"][0]["true_Master_net_pnl_lamports"] is None
    assert r["cases"][0]["hypothetical_probe_action"]=="REJECT"


def test_tamper_frozen_receipt_and_future_slot_refused():
    source=prospective()
    source["preregistered_research_freeze"]["frozen_actions"][0][
        "hypothetical_probe_token_quantity_atomic"]="1000"
    with pytest.raises(ValueError,match="prospective_S1_freeze"):
        evaluate_probe(source)
    source=prospective()
    source["second_bank_slot"]=source["first_bank_slot"]
    with pytest.raises(ValueError,match="prospective_S1_freeze"):
        evaluate_probe(source)


def test_real_runner_calls_s1_freezer_only_from_source_collector(monkeypatch):
    seen=[]
    def fake_cohort(rpc,**kwargs):
        assert kwargs["prefer_root_activity"] is True
        assert kwargs["research_ladder"] is True
        assert kwargs["sample_page"]==2
        snapshot=source_s1()
        receipt=kwargs["freeze_at_s1"](snapshot)
        seen.append(receipt)
        source=prospective()
        source["preregistered_research_freeze"]=receipt
        source["S1_research_freeze_before_S2_sha256"]=_hash_test(receipt)
        return source
    monkeypatch.setattr("bot.live.helius_sol_forward_paper_probe.observe_active_survivor_cohort",
                        fake_cohort)
    output=run(rpc=object(),sample_page=2,wait_seconds=12)
    assert len(seen)==1
    assert output["paper_model_report"]["exact_model_roundtrips"]==1
    assert output["paper_model_report"]["actual_Master_research_executed_orders"]==0


def test_zero_admissible_pools_is_a_valid_full_denominator_no_trade(monkeypatch):
    called=[]
    def fake_cohort(rpc,**kwargs):
        called.append(kwargs)
        return dict(status="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE",
            selected_count=0,observations=[],registration_sha256=REG,
            first_bank_slot=None,second_bank_slot=None,
            discovery_denominator=[dict(selection_reason="root_not_supported")],
            financial_order_submitted=False,live_ready_to_arm=False)
    monkeypatch.setattr("bot.live.helius_sol_forward_paper_probe.observe_active_survivor_cohort",
                        fake_cohort)
    report=run(rpc=object(),sample_page=1)
    assert len(called)==1
    assert report["status"]=="NO_QUALIFIED_ACTIVE_SOL_POOLS_IN_PREDECLARED_SLICE"
    assert report["paper_model_report"]["exact_model_roundtrips"]==0
    assert report["paper_model_report"]["number_of_frozen_cases"]==0
    assert report["paper_model_report"]["measured_Master_minus_reference_edge_lamports"] is None
    assert report["exact_net_Master_pnl_lamports"] is None
    assert report["financial_order_submitted"] is False


def test_own_buy_overlay_model_is_separate_from_unquoted_untouched_s2_and_master():
    raw=prospective(with_exit=False)
    row=raw["observations"][0]["research_size_ladder"][0]
    row["s2_own_buy_overlay_status"]="MODEL_CONDITIONAL_NOT_EXECUTABLE"
    row["s2_own_buy_overlay_sell_lamports"]="56000000"
    row["s2_own_buy_overlay_delta_before_extra_costs_lamports"]="6000000"
    row["s2_own_buy_overlay_receipt_sha256"]="c"*64
    report=evaluate_probe(raw)
    case=report["cases"][0]
    assert report["exact_model_roundtrips"]==0
    assert report["own_buy_overlay_conditional_models"]==1
    assert report["own_buy_overlay_source_replay_verified_models"]==0
    assert case["own_buy_overlay_public_bank_replay_verified"] is False
    assert case["status"]=="CENSORED_OPEN_HYPOTHETICAL_PROBE_NO_S2_EXIT"
    assert case["own_buy_overlay_status"]=="CONDITIONAL_PATH_DEPENDENT_MODEL_ONLY"
    assert case["own_buy_overlay_sell_lamports"]=="56000000"
    assert case["own_buy_overlay_cost_scenarios"][0]["conditional_net_lamports"]=="6000000"
    assert case["own_buy_overlay_cost_scenarios"][-1]["conditional_net_lamports"]=="-4000000"
    assert case["true_Master_net_pnl_lamports"] is None
    assert report["measured_Master_minus_reference_edge_lamports"] is None
    assert report["actual_Master_research_executed_orders"]==0


def test_tampered_overlay_markout_cannot_enter_a_profitable_summary():
    raw=prospective(with_exit=False)
    row=raw["observations"][0]["research_size_ladder"][0]
    row["s2_own_buy_overlay_status"]="MODEL_CONDITIONAL_NOT_EXECUTABLE"
    row["s2_own_buy_overlay_sell_lamports"]="56000000"
    row["s2_own_buy_overlay_delta_before_extra_costs_lamports"]="999999999"
    with pytest.raises(ValueError,match="S2_own_buy_overlay_markout_inconsistent"):
        evaluate_probe(raw)


def test_archived_public_bank_digest_tamper_aborts_overlay_reporting():
    raw=prospective(with_exit=False)
    row=raw["observations"][0]["research_size_ladder"][0]
    row.update(s2_own_buy_overlay_status="MODEL_CONDITIONAL_NOT_EXECUTABLE",
               s2_own_buy_overlay_sell_lamports="56000000",
               s2_own_buy_overlay_delta_before_extra_costs_lamports="6000000",
               s2_own_buy_overlay_receipt_sha256="c"*64)
    rec=raw["observations"][0]
    rec["s1_decoded_public_bank_replay"]={"corrupted_by_relay":True}
    rec["s2_decoded_public_bank_replay"]={"corrupted_by_relay":True}
    rec["s2_decoded_public_bank_sha256"]="a"*64
    with pytest.raises(ValueError,match="archived_public_S1_S2_bank_digest_mismatch"):
        evaluate_probe(raw)
