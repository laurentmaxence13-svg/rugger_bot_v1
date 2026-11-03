"""Frozen master proposals cannot bypass evidence, sizing or entry protections."""
from copy import deepcopy
import json

import pytest

from bot.master_decision import MasterDecisionOrchestrator,POLICY,CLASSIFICATION_POLICY,orchestrate,policy_hash
from bot.p4_experiment import assess_curve_costs
from bot.economic_demo import _load_api,_quote_observation
from test_p4_experiment import cost_frame


def qualified():
    frame=cost_frame();frame['data_kind']='synthetic'
    at=frame['available_at_ms'];bank=frame['bank_state']
    bank.update(identity_qualified=True,supply_verified=True,creation_verified=True)
    fees=dict(entry_extra_lamports=5000,exit_extra_lamports=10000,failed_attempt_lamports=[],
        quote_amounts_net_of_pool_fees=True,extra_fees_exclude_pool_fees=True,provenance='synthetic')
    frame['inventory_context']={'fees':fees}
    quantity=assess_curve_costs(frame)['sizes'][-1]['same_state_own_entry_model']['buy_output_atomic']
    api=_load_api()
    buy=_quote_observation(api,side='buy',mint=frame['mint'],pool=frame['pool'],
        amount=1000000000,output=int(quantity),requested=at-40,index=1,case='master')
    sell=_quote_observation(api,side='sell',mint=frame['mint'],pool=frame['pool'],
        amount=int(quantity),output=965306249,requested=at-20,index=2,case='master')
    buy['id']='master-buy';sell['id']='master-sell'
    frame['size_contexts']={'1000000000':{'buy_observation':buy,'sell_observations':[sell]}}
    core=MasterDecisionOrchestrator()
    frame['research_evidence']=dict(available_at_ms=at-1,training_end_ms=at-100,
        policy_sha256=core.policy_sha256,qualified_economic_cycles=50,independent_creator_groups=20,
        gross_proceeds_return_lower_bound=.50,report_sha256='a'*64,
        provenance='synthetic_fixture',data_kind='synthetic')
    health=dict(allow_new_entries=True,blocking_reasons=[],observed_at_ms=at)
    capital=dict(available_cash_lamports=10_000_000_000,open_positions=0,entries_today=0,
        daily_loss_limit_reached=False,financial_entry_allowed=True,observed_at_ms=at)
    return core,frame,health,capital


def test_positive_fixture_only_proposes_shadow_action_with_twelve_questions_and_four_options():
    core,frame,health,capital=qualified();before=deepcopy((frame,health,capital))
    result=core.evaluate(frame,health=health,capital=capital)
    assert result['action']=='ENTER' and result['selected_strategy']=='adaptive_hybrid', (result['reasons'],result['size_assessments'][-1]['reasons'],[(a['strategy'],a.get('entry_intent')) for a in result['alternatives']])
    assert result['input_lamports']=='1000000000'
    assert result['quantity_atomic']==frame['size_contexts']['1000000000']['buy_observation']['payload']['output_amount_atomic']
    assert len(result['questions'])==12 and [q['number'] for q in result['questions']]==list(range(1,13))
    assert len(result['alternatives'])==4
    assert result['questions'][10]['status']=='UNKNOWN'  # No causal early-vs-wait proof is invented.
    for key in ('promotion_allowed','active_policy_changed','execution_authorized','execution_verified','ledger_credited'):
        assert result[key] is False
    assert result['strict_economic_cycles']==0
    assert (frame,health,capital)==before
    json.dumps(result,allow_nan=False)


def test_missing_information_explicitly_waits_without_fabricating_costs_edge_or_features():
    result=orchestrate({'id':'unknown','mint':'m','pool':'p','available_at_ms':100})
    assert result['action']=='WAIT' and result['selected_strategy'] is None
    assert 'additional_costs_unknown' in result['reasons']
    assert 'qualified_past_edge_evidence_unavailable' in result['reasons']
    assert result['questions'][0]['status']=='UNKNOWN'


@pytest.mark.parametrize('damage',['emergency','capital_guard','daily_loss','open_count','entry_count','unknown_daily'])
def test_capital_health_and_daily_limits_cannot_be_overridden(damage):
    core,frame,health,capital=qualified()
    if damage=='emergency':health['allow_new_entries']=False
    elif damage=='capital_guard':capital['financial_entry_allowed']=False
    elif damage=='daily_loss':capital['daily_loss_limit_reached']=True
    elif damage=='open_count':capital['open_positions']=3
    elif damage=='entry_count':capital['entries_today']=20
    else:capital['daily_loss_limit_reached']=None
    result=core.evaluate(frame,health=health,capital=capital)
    assert result['action']!='ENTER' and result['input_lamports'] is None


def test_existing_creator_risk_veto_wins_even_over_positive_synthetic_evidence():
    core,frame,health,capital=qualified();frame['features']['dev_sales']=1
    result=core.evaluate(frame,health=health,capital=capital)
    assert result['action']=='NO_TRADE'
    assert result['questions'][1]['status']=='YES'
    assert 'existing_risk_or_score_veto' in result['reasons']


@pytest.mark.parametrize('damage',['future_features','future_evidence','unknown_costs','wrong_quantity','stale_quotes','missing_creation','unmatched_policy'])
def test_unavailable_evidence_and_unmatched_full_lot_cannot_become_entry(damage):
    core,frame,health,capital=qualified()
    if damage=='future_features':frame['features_available_at_ms']+=1
    elif damage=='future_evidence':frame['research_evidence']['available_at_ms']+=100
    elif damage=='unknown_costs':frame['inventory_context']['fees']['exit_extra_lamports']=None
    elif damage=='wrong_quantity':
        # A valid quote for a different lot cannot stand in for our modeled lot.
        frame['bank_state']['fee_rates_ppm']=[100000,10000,5000]
    elif damage=='stale_quotes':
        frame['available_at_ms']+=6000;frame['features_available_at_ms']+=6000
        frame['features']['observed_at']+=6;frame['bank_state']['available_at_ms']+=6000
        health['observed_at_ms']+=6000
    elif damage=='missing_creation':frame['bank_state']['creation_verified']=False
    else:frame['research_evidence']['policy_sha256']='b'*64
    result=core.evaluate(frame,health=health,capital=capital)
    assert result['action']=='WAIT' and result['input_lamports'] is None


def test_future_history_does_not_change_a_current_decision_and_history_is_bounded():
    core,frame,health,capital=qualified()
    future=deepcopy(frame);future['available_at_ms']+=100000;future['features']['price_usd']=100000
    a=core.evaluate(frame,health=health,capital=capital)
    b=core.evaluate(frame,[future],health=health,capital=capital)
    assert a==b
    with pytest.raises(ValueError,match='bounded history'):
        core.evaluate(frame,[future]*33,health=health,capital=capital)


def test_policies_cannot_relax_hard_limits_and_inspection_does_not_mutate_frozen_policy():
    core=MasterDecisionOrchestrator();sha=core.policy_sha256
    view=core.policy;view['max_open']=100
    assert core.policy['max_open']==3 and core.policy_sha256==sha
    invalid=deepcopy(POLICY);invalid['max_open']=4
    with pytest.raises(ValueError):MasterDecisionOrchestrator(invalid)


def test_synthetic_research_evidence_cannot_be_relabelled_as_market_validation():
    core,frame,health,capital=qualified();frame['data_kind']='market_observation'
    frame['research_evidence']['data_kind']='market_observation'
    assert core.evaluate(frame,health=health,capital=capital)['action']=='WAIT'


@pytest.mark.parametrize('clock',['missing','future','stale'])
def test_capital_snapshot_needs_a_fresh_causal_observation(clock):
    core,frame,health,capital=qualified()
    if clock=='missing':capital.pop('observed_at_ms')
    elif clock=='future':capital['observed_at_ms']+=1
    else:capital['observed_at_ms']-=5001
    result=core.evaluate(frame,health=health,capital=capital)
    assert result['action']=='WAIT'
    assert 'capital_or_loss_limits_unavailable_or_reached' in result['reasons']


def test_past_envelope_with_future_features_cannot_change_regime():
    core,frame,health,capital=qualified()
    past=deepcopy(frame);past['available_at_ms']-=1000
    past['features']['observed_at']-=1;past['features']['price_usd']=1e-308
    # The envelope was available, but these feature values were not.
    assert past['features_available_at_ms']>past['available_at_ms']
    without=core.evaluate(frame,health=health,capital=capital)
    assert core.evaluate(frame,[past],health=health,capital=capital)==without


def test_extreme_finite_history_price_has_a_finite_conservative_risk_proxy():
    core,frame,health,capital=qualified()
    past=deepcopy(frame);past['available_at_ms']-=1000
    past['features_available_at_ms']=past['available_at_ms']
    past['features']['observed_at']-=1;past['features']['price_usd']=1e-308
    frame['features']['price_usd']=1e308
    result=core.evaluate(frame,[past],health=health,capital=capital)
    assert result['regime']=='HIGH_VOLATILITY'
    assert result['action']=='WAIT'  # The only retained exact lot exceeds the cap.
    json.dumps(result,allow_nan=False)


def test_history_of_a_different_candidate_identity_cannot_steer_regime():
    core,frame,health,capital=qualified()
    past=deepcopy(frame);past['available_at_ms']-=1000
    past['features_available_at_ms']=past['available_at_ms']
    past['features']['observed_at']-=1;past['features']['price_usd']=1e-308
    past['creator']=past['features']['creator']='different-creator'
    without=core.evaluate(frame,health=health,capital=capital)
    assert core.evaluate(frame,[past],health=health,capital=capital)==without


def test_unlabelled_provenance_cannot_become_qualified_past_evidence():
    core,frame,health,capital=qualified()
    frame['data_kind']=frame['research_evidence']['data_kind']='unknown'
    frame['research_evidence']['provenance']='qualified_historical'
    result=core.evaluate(frame,health=health,capital=capital)
    assert result['action']=='WAIT'
    assert 'qualified_past_edge_evidence_unavailable' in result['reasons']


def situations(result):
    return {row['key']:row for row in result['regime_assessment']['situations']}


def growing_prefix():
    core,frame,health,capital=qualified()
    previous=deepcopy(frame);previous['id']='previous'
    previous['features']['momentum_60s']=.02
    previous['independent_buyers']=1
    frame['id']='current';frame['available_at_ms']+=15000
    frame['features_available_at_ms']=frame['slot_available_at_ms']=frame['available_at_ms']
    frame['features']['observed_at']+=15
    frame['features'].update(momentum_60s=.04,price_usd=1.02)
    frame['source_slot']+=1;frame['independent_buyers']=3
    frame['bank_state'].update(available_at_ms=frame['available_at_ms'],source_slot=frame['source_slot'])
    health['observed_at_ms']=capital['observed_at_ms']=frame['available_at_ms']
    return core,frame,previous,health,capital


def test_nine_descriptive_situations_have_explicit_version_and_do_not_change_policy_identity():
    core,frame,health,capital=qualified()
    result=core.evaluate(frame,health=health,capital=capital)
    assessment=result['regime_assessment'];rows=situations(result)
    assert len(rows)==9 and set(rows)==set(CLASSIFICATION_POLICY['primary_priority'])
    assert assessment['classification_policy_sha256']==policy_hash(CLASSIFICATION_POLICY)
    assert result['policy_sha256']==policy_hash(POLICY)
    assert assessment['classification_controls_entry'] is assessment['market_regime_certified'] is False
    assert all(row['status'] in ('OBSERVED','NOT_OBSERVED','UNKNOWN') for row in rows.values())
    assert all(row['as_of_ms']==frame['available_at_ms'] and row['source_ids']==[frame['id']] for row in rows.values())
    assert result['action']=='ENTER'  # Descriptive additions do not rewrite the frozen priority.


def test_growing_independent_activity_and_confirmed_momentum_require_a_causal_prefix():
    core,frame,previous,health,capital=growing_prefix()
    result=core.evaluate(frame,[previous],health=health,capital=capital)
    rows=situations(result)
    assert rows['EARLY_GROWING_ACTIVITY']['status']=='OBSERVED'
    assert rows['CONFIRMED_MOMENTUM']['status']=='OBSERVED'
    assert rows['EARLY_GROWING_ACTIVITY']['metrics']['previous_independent_buyers']==1
    assert rows['POSSIBLE_MANIPULATION']['status']=='UNKNOWN'
    no_history=situations(core.evaluate(frame,health=health,capital=capital))
    assert no_history['EARLY_GROWING_ACTIVITY']['status']=='UNKNOWN'
    assert no_history['CONFIRMED_MOMENTUM']['status']=='UNKNOWN'


def test_transaction_buys_never_substitute_for_independent_activity_evidence():
    core,frame,previous,health,capital=growing_prefix()
    frame.pop('independent_buyers');frame['features']['tx_buys_5m']=100000
    result=core.evaluate(frame,[previous],health=health,capital=capital)
    assert situations(result)['EARLY_GROWING_ACTIVITY']['status']=='UNKNOWN'
    assert situations(result)['CONFIRMED_MOMENTUM']['status']=='UNKNOWN'


@pytest.mark.parametrize('kind',['overextension','momentum_loss','coordination','liquidity'])
def test_regime_conditions_explain_observed_risks_without_claiming_future_reversal_or_manipulation(kind):
    core,frame,health,capital=qualified()
    if kind=='overextension':frame['features']['momentum_60s']=.4;key='OVEREXTENSION_RISK'
    elif kind=='momentum_loss':frame['features']['momentum_60s']=-.05;key='MOMENTUM_LOSS'
    elif kind=='coordination':frame['features']['same_slot_wallets']=3;key='POSSIBLE_MANIPULATION'
    else:frame['features']['liquidity_usd']=100;key='INSUFFICIENT_LIQUIDITY'
    result=core.evaluate(frame,health=health,capital=capital)
    assert situations(result)[key]['status']=='OBSERVED'
    assert situations(result)['POSSIBLE_MANIPULATION']['metrics']['manipulation_confirmed'] is False
    assert situations(result)['OVEREXTENSION_RISK']['metrics']['reversal_observed'] is False
    assert result['decision_evidence']['score'] is not None
    assert result['decision_evidence']['reference_exit_conditions']['sl_pct']>0
    assert result['decision_evidence']['financial_execution_authorized'] is False


def test_unfavorable_economics_requires_current_costs_and_qualified_past_evidence():
    core,frame,health,capital=qualified()
    frame['research_evidence']['gross_proceeds_return_lower_bound']=.001
    result=core.evaluate(frame,health=health,capital=capital)
    assert situations(result)['ECONOMICALLY_UNFAVORABLE']['status']=='OBSERVED'
    assert result['action']!='ENTER'
    frame.pop('research_evidence')
    result=core.evaluate(frame,health=health,capital=capital)
    assert situations(result)['ECONOMICALLY_UNFAVORABLE']['status']=='UNKNOWN'
    assert situations(result)['INSUFFICIENT_DATA']['status']=='OBSERVED'


def test_future_or_wrong_identity_observations_cannot_change_descriptive_situations():
    core,frame,previous,health,capital=growing_prefix()
    expected=core.evaluate(frame,[previous],health=health,capital=capital)
    future=deepcopy(frame);future['available_at_ms']+=1000
    future['features']['momentum_60s']=-.99
    foreign=deepcopy(previous);foreign['mint']=foreign['features']['mint']='other'
    assert core.evaluate(frame,[previous,future,foreign],health=health,capital=capital)==expected


def test_unavailable_current_features_cannot_leak_their_price_into_volatility():
    core,frame,previous,health,capital=growing_prefix()
    frame['features_available_at_ms']+=1;frame['features']['price_usd']=1e100
    result=core.evaluate(frame,[previous],health=health,capital=capital)
    assert situations(result)['HIGH_VOLATILITY']['status']=='UNKNOWN'
    assert result['questions'][3]['metrics']['causal_return_dispersion_proxy'] is None
    assert result['decision_evidence']['features_available_at_ms'] is None


def test_no_coordination_flags_is_only_not_observed_when_behavior_and_holder_data_exist():
    core,frame,health,capital=qualified()
    frame['features']['wallet_graph_transactions']=1
    result=core.evaluate(frame,health=health,capital=capital)
    assert situations(result)['POSSIBLE_MANIPULATION']['status']=='NOT_OBSERVED'
    frame['features']['holder_data_known']=False
    result=core.evaluate(frame,health=health,capital=capital)
    assert situations(result)['POSSIBLE_MANIPULATION']['status']=='UNKNOWN'
