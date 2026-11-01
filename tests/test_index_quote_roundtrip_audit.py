"""Offline falsification of indicative exact-lot public Raydium roundtrips."""
import copy
import pytest
from bot.p3.index_quote_roundtrip_audit import audit_quote_pairs

MINT="5AWBTmZzYZ3twtKQLe1eziWw9yMcUyUiR6iRnCpXPv7f"
SOL="So11111111111111111111111111111111111111112"
TAIL="f"*64


def fixtures():
    report=dict(schema="p3-active-cohort-result-v1",tail_hash=TAIL,
        positions_acquired=0,settled_legs=0,qualified_economic_cycles=0,
        net_pnl_sol=None,execution_verified=False,
        projected_positions=1,
        selection=dict(records=[dict(selection_reason="selected_before_provider_outcomes",
            source_row=dict(mint=MINT,creator_claim="one-public-creator"))]))
    def event(id,side,phase,input_amount,output_amount,when,ref=None):
        payload=dict(provider="raydium_trade_api",http_status=200,
            quote_kind="size_specific_route_estimate",
            quote_side=side,probe_phase=phase,executable_confirmed=False,
            execution_guaranteed=False,source_time_ms=None,source_slot=None,
            input_amount_atomic=str(input_amount),output_amount_atomic=str(output_amount),
            min_output_amount_atomic=str(output_amount-1),
            input_mint=SOL if side=="buy" else MINT,
            output_mint=MINT if side=="buy" else SOL)
        if ref is not None:payload.update(
            actual_input_amount_atomic=str(input_amount),
            inventory_buy_observation_id=ref,exit_scope="full_expected")
        return dict(id=id,available_at_ms=when,kind="quote_attempt",
            mint=MINT,outcome="quoted",payload=payload)
    records=[event(4,"buy","initial",100_000_000,3000,100),
        event(6,"sell","initial",3000,96_918_845,200,4),
        event(9,"sell","followup",3000,95_000_000,15000,4)]
    return report,records


def test_losses_are_measured_as_conditional_not_master_pnl():
    r,e=fixtures()
    x=audit_quote_pairs(r,e,expected_tail=TAIL)
    assert x["full_lot_provider_sell_quotes"]==2
    outcomes=x["rows"][0]["provider_roundtrip_deltas"]
    assert outcomes[0]["delta_before_unknown_costs_lamports"]=="-3081155"
    assert outcomes[0]["delta_pct_of_hypothetical_buy"]==-3.081155
    assert outcomes[1]["delta_before_unknown_costs_lamports"]=="-5000000"
    assert outcomes[1]["ms_after_buy_receipt"]==14900
    assert x["qualified_economic_cycles"]==0
    assert x["master_net_pnl_lamports"] is None
    assert x["financial_order_submitted"] is False


def test_missing_exit_is_explicit_not_zero_pnl():
    r,e=fixtures()
    r["projected_positions"]=1
    x=audit_quote_pairs(r,e[:1],expected_tail=TAIL)
    assert x["full_lot_provider_sell_quotes"]==0
    assert all(row["delta_before_unknown_costs_lamports"] is None
               for row in x["rows"][0]["provider_roundtrip_deltas"])


@pytest.mark.parametrize("field,bad",[
    ("input_amount_atomic","2999"),
    ("actual_input_amount_atomic","2999"),
    ("inventory_buy_observation_id",42),
    ("exit_scope","partial"),
    ("input_mint",SOL),
    ("output_mint",MINT),
])
def test_sell_must_be_exact_frozen_model_lot(field,bad):
    r,e=fixtures()
    e[1]["payload"][field]=bad
    with pytest.raises(ValueError,match="incorrect_lot"):
        audit_quote_pairs(r,e,expected_tail=TAIL)


def test_unverified_provider_quote_is_not_admitted():
    r,e=fixtures()
    e[1]["payload"]["executable_confirmed"]=True
    with pytest.raises(ValueError,match="unsafe_quote"):
        audit_quote_pairs(r,e,expected_tail=TAIL)


def test_source_clock_laundering_refused():
    r,e=fixtures()
    e[1]["payload"]["source_time_ms"]=200
    with pytest.raises(ValueError,match="source_clocks"):
        audit_quote_pairs(r,e,expected_tail=TAIL)


def test_same_quote_role_not_counted_twice():
    r,e=fixtures()
    e.append(copy.deepcopy(e[-1]))
    with pytest.raises(ValueError,match="repeated_provider_quote_role"):
        audit_quote_pairs(r,e,expected_tail=TAIL)


def test_backward_provider_receipt_refused():
    r,e=fixtures()
    e[1]["available_at_ms"]=99
    with pytest.raises(ValueError,match="noncausal"):
        audit_quote_pairs(r,e,expected_tail=TAIL)


def test_ledger_hash_mismatch_blocks_claim():
    r,e=fixtures()
    with pytest.raises(ValueError,match="hash_anchored"):
        audit_quote_pairs(r,e,expected_tail="e"*64)


def test_no_fabricated_inventory():
    r,e=fixtures()
    r["positions_acquired"]=1
    with pytest.raises(ValueError,match="hash_anchored"):
        audit_quote_pairs(r,e,expected_tail=TAIL)


def test_extra_unknown_costs_not_zeroed():
    r,e=fixtures()
    x=audit_quote_pairs(r,e,expected_tail=TAIL)
    assert x["own_additional_costs_verified"] is False
    assert x["market_profitability_verified"] is False
    assert x["creation_signed_cryptographic_proof_complete"] is False
