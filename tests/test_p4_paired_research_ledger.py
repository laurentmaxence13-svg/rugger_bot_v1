"""Adversarial causal matched Master/reference PAPER accounting tests."""
from copy import deepcopy
import pytest
from bot.p4.paired_research_ledger import freeze_pair, score_pair


def setup(master="ENTER",ref="WAIT",verified=True):
    case=dict(creator="creator",mint="mint",pool="pool",source_slot=200,
        asof_ms=5000,features_available_at_ms=4900,
        feature_receipt_sha256="a"*64,policy_sha256_master="b"*64,
        policy_sha256_reference="c"*64,
        master_action=master,reference_action=ref,
        hypothetical_buy_lamports=100000000,
        source_clock_verified=verified,signed_creator_verified=True)
    return case


def price(exit_kind="FULL_QUOTE",price=96918845,fees=None,failures=None):
    return dict(source_slot=201,available_at_ms=6000,
        entry_quote_lamports=100000000,exact_lot_atomic=3080513950670,
        exit_kind=exit_kind,exit_quote_lamports=price,
        extra_costs_lamports=fees,failure_costs_lamports=failures,
        provider_quote_source_clock_verified=False,
        actual_fills_verified=False)


def test_unknown_fees_and_reference_wait_do_not_imply_profitable_strategy():
    f=freeze_pair(setup())
    assert f["future_prices_consumed"] is False
    s=score_pair(f,price())
    assert s["modelled_full_quote_delta_before_unknown_costs_lamports"]==-3081155
    assert s["nonnegative_extra_costs_upper_bound_lamports"]==-3081155
    assert s["conditional_cost_adjusted_delta_lamports"] is None
    assert s["master_and_reference"]["master"]["conditional_net_if_all_costs_provided_lamports"] is None
    assert s["master_and_reference"]["reference"]["outcome_class"]=="NO_POSITION_POLICY_ABSTAINED"
    assert s["economically_validated_master_advantage_lamports"] is None
    assert s["qualified_executed_economic_cycles"]==0
    assert s["financial_order_submitted"] is False


def test_costs_and_failed_attempts_reduce_conditional_proceeds():
    f=freeze_pair(setup())
    s=score_pair(f,price(fees=6000,failures=12000))
    assert s["conditional_cost_adjusted_delta_lamports"]==-3099155
    assert s["master_and_reference"]["master"]["conditional_net_if_all_costs_provided_lamports"]==-3099155
    assert s["market_profitability_verified"] is False


@pytest.mark.parametrize("status",["OPEN_UNPRICED","FAILED_EXIT","MIGRATED_NO_QUOTE"])
def test_censored_exit_not_zero_trade_return(status):
    f=freeze_pair(setup())
    s=score_pair(f,price(exit_kind=status,price=None,fees=9000,failures=0))
    assert s["conditional_cost_adjusted_delta_lamports"] is None
    assert s["master_and_reference"]["master"]["outcome_class"]=="HYPOTHETICAL_"+status
    assert s["master_and_reference"]["master"]["unrealized_open_position_pnl_lamports"] is None
    assert s["qualified_executed_economic_cycles"]==0


def test_reference_and_master_both_enter_no_fake_advantage():
    f=freeze_pair(setup(ref="ENTER"))
    s=score_pair(f,price(fees=0,failures=0))
    assert s["candidate_both_enter_illustrative_delta_lamports"]==0
    assert s["economically_validated_master_advantage_lamports"] is None
    assert s["independent_scoring_engines_verified"] is False


def test_future_features_rejected_pre_registration():
    case=setup()
    case["features_available_at_ms"]=5001
    with pytest.raises(ValueError,match="future_features"):
        freeze_pair(case)


def test_outcome_in_registration_refused():
    case=setup()
    case["future_S2_price"]=50
    with pytest.raises(ValueError,match="exact_preoutcome"):
        freeze_pair(case)


def test_hash_mutation_never_changes_frozen_decision():
    f=freeze_pair(setup())
    f["research_case"]["master_action"]="WAIT"
    with pytest.raises(ValueError,match="freeze_integrity"):
        score_pair(f,price())


def test_earlier_outcome_rejected():
    f=freeze_pair(setup())
    result=price();result["available_at_ms"]=5000
    with pytest.raises(ValueError,match="after_frozen"):
        score_pair(f,result)


def test_same_chain_slot_rejected():
    f=freeze_pair(setup())
    result=price();result["source_slot"]=200
    with pytest.raises(ValueError,match="after_frozen"):
        score_pair(f,result)


def test_different_exit_size_rejected():
    f=freeze_pair(setup())
    result=price();result["entry_quote_lamports"]=250000000
    with pytest.raises(ValueError,match="same_buy_size"):
        score_pair(f,result)


def test_absent_full_quote_never_produces_net_pnl():
    f=freeze_pair(setup())
    result=price(exit_kind="FAILED_EXIT",price=100)
    with pytest.raises(ValueError,match="censored_exit"):
        score_pair(f,result)


def test_negative_or_unknowable_fees_do_not_turn_into_free_money():
    f=freeze_pair(setup())
    result=price(fees=-1,failures=0)
    with pytest.raises(ValueError,match="extra_costs"):
        score_pair(f,result)


def test_never_accept_real_fills_from_shadow_research():
    f=freeze_pair(setup())
    result=price();result["actual_fills_verified"]=True
    with pytest.raises(ValueError,match="provider_and_fills"):
        score_pair(f,result)


def test_unverified_source_clock_stays_false_even_for_verified_creator():
    f=freeze_pair(setup(verified=False))
    s=score_pair(f,price(fees=0,failures=0))
    assert s["source_decision_clock_verified"] is False
    assert s["signed_creator_verified"] is True
    assert s["economically_validated_master_advantage_lamports"] is None


def test_policy_must_be_explicit():
    case=setup();case["policy_sha256_master"]=None
    with pytest.raises(ValueError,match="frozen_evidence_hash"):
        freeze_pair(case)


def test_only_known_no_trade_or_enter_actions():
    case=setup();case["master_action"]="SELL_ALL"
    with pytest.raises(ValueError,match="causal_policy"):
        freeze_pair(case)
