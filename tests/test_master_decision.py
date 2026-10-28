"""Frozen master proposals cannot bypass evidence, sizing or entry protections."""
from copy import deepcopy
import json

import pytest

from bot.master_decision import MasterDecisionOrchestrator,POLICY,orchestrate
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
