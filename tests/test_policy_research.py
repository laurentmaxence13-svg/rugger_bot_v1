"""Frozen policy search uses the shared native book and preserves holdout scope."""
from copy import deepcopy

import pytest

from bot import policy_research as research
from bot import p4_experiment as p4
from bot.economic_demo import _load_api, _quote_observation
from test_p4_experiment import corpus


def plan():
    return research.make_plan(registered_at_ms=1,development_end_ms=200000,holdout_end_ms=500000)


def test_structured_search_keeps_active_policy_and_native_inventory_and_freezes_before_validation():
    original=deepcopy(p4.POLICY)
    result=research.evaluate_research(corpus(),plan())
    assert len(result['development'])==24
    assert len(result['frozen_candidate_ids'])==3
    assert len(result['holdout'])<=6
    assert result['promotion_allowed'] is False and result['market_winner'] is None
    assert result['network_requests']==0 and p4.POLICY==original
    smaller=[r for r in result['development'] if r['candidate']['id'].endswith('size-0.10')]
    assert all(r['run']['entered_positions']==0 for r in smaller)  # No rescaled1SOL quote.
    assert all(not r['metrics']['eligible'] for r in smaller)
    baseline=next(r for r in result['development'] if r['candidate']['id']=='early_sniping:baseline')
    assert baseline['run']['positions'][0]['acquired_atomic']=='1000'
    assert baseline['run']['legs'][0]['quantity_atomic']=='1000'
    assert baseline['run']['realized_pnl_sol']==pytest.approx(.199985)
    assert 'synthetic_results_only' in result['promotion_blockers']


def test_changing_holdout_does_not_change_frozen_development_candidates_and_cannot_unlock_second_look():
    original=corpus();changed=deepcopy(original)
    for frame in changed['frames'][4:]:
        frame['features']['price_usd']=.01
    a=research.evaluate_research(original,plan())
    b=research.evaluate_research(changed,plan())
    assert a['development']==b['development'] and a['frozen_candidate_ids']==b['frozen_candidate_ids']
    with pytest.raises(ValueError,match='already evaluated'):
        research.evaluate_research(changed,plan(),registry=a['registry'])
    reregistered=research.make_plan(registered_at_ms=2,development_end_ms=200000,holdout_end_ms=500000)
    with pytest.raises(ValueError,match='already evaluated'):
        research.evaluate_research(changed,reregistered,registry=a['registry'])


def test_unknown_costs_and_unliquidated_lots_prevent_objective_and_selection():
    result=research.evaluate_research(corpus(fees_unknown=True),plan())
    assert all(r['metrics']['objective'] is None for r in result['development'])
    assert result['frozen_candidate_ids']==[]
    assert all(r['run']['portfolio_pnl_sol'] is None for r in result['holdout'])
    assert result['promotion_allowed'] is False


def test_small_position_uses_its_own_quote_lot_and_fixed_fees_without_rescaling_reference():
    data=corpus();api=_load_api();small_lots={}
    for frame in data['frames']:
        at=frame['available_at_ms']
        if frame.get('buy_context'):
            original=frame['buy_context']['buy_observation']
            quantity=int(original['payload']['output_amount_atomic'])//10
            observation=_quote_observation(api,side='buy',mint=frame['mint'],pool=frame['pool'],
                amount=100000000,output=quantity,requested=at-20,index=1,case='research_small')
            observation['id']=original['id']+'-small'
            frame['size_contexts']={'100000000':dict(buy_observation=observation,
                token_decimals=6,fees=deepcopy(frame['buy_context']['fees']))}
            small_lots[original['id']]=(observation['id'],quantity)
        for retained in list(frame['sell_contexts']):
            buy_id,quantity=small_lots[retained['inventory_buy_observation_id']]
            observation=_quote_observation(api,side='sell',mint=frame['mint'],pool=frame['pool'],
                amount=quantity,output=120000000,requested=at-20,index=2,case='research_small')
            observation['id']=retained['sell_observation']['id']+'-small'
            frame['sell_contexts'].append(dict(inventory_buy_observation_id=buy_id,
                sell_observation=observation,requested_quantity_atomic=str(quantity),
                fees=deepcopy(retained['fees'])))
    result=research.evaluate_research(data,plan())
    baseline=next(r['run'] for r in result['development'] if r['candidate']['id']=='early_sniping:baseline')
    small=next(r['run'] for r in result['development'] if r['candidate']['id']=='early_sniping:size-0.10')
    assert baseline['positions'][0]['acquired_atomic']=='1000'
    assert small['positions'][0]['acquired_atomic']=='100'
    assert small['legs'][0]['quantity_atomic']=='100'
    assert small['all_entered_positions_liquidated'] is True
    assert baseline['known_modeled_extra_costs_lamports']==small['known_modeled_extra_costs_lamports']=='15000'
    assert small['realized_pnl_sol']==pytest.approx(.019985)
    assert baseline['realized_pnl_sol']==pytest.approx(.199985)
    assert small['realized_pnl_sol']/.1 < baseline['realized_pnl_sol']
    assert result['promotion_allowed'] is False


def test_creator_overlap_is_quarantined_and_open_development_positions_cannot_use_future_exit():
    data=corpus();creator=data['frames'][0]['creator']
    for frame in data['frames'][4:]:
        frame['creator']=creator;frame['features']['creator']=creator
    result=research.evaluate_research(data,plan())
    assert result['validation_creator_groups']==0
    assert all(r['run']['candidate_count']==0 for r in result['holdout'])
    data=corpus();data['frames'][2]['available_at_ms']=210000
    data['frames'][2]['features_available_at_ms']=210000;data['frames'][2]['features']['observed_at']=210
    data['frames'][2]['slot_available_at_ms']=210000
    data['frames'][3]['available_at_ms']=215000
    data['frames'][3]['features_available_at_ms']=215000;data['frames'][3]['features']['observed_at']=215
    data['frames'][3]['slot_available_at_ms']=215000
    result=research.evaluate_research(data,plan())
    assert all(r['run']['closed_positions']==0 for r in result['development'])


def test_registry_can_select_and_roll_back_shadow_without_touching_active_policy():
    report=research.evaluate_research(corpus(),plan())
    candidate=report['frozen_candidate_ids'][0]
    selected=research.choose_shadow(report,candidate)
    assert selected['current_shadow']['candidate_id']==candidate
    reverted=research.rollback_shadow(selected)
    assert reverted['current_shadow'] is None and reverted['version']==2
    assert reverted['active_policy_changed'] is False
    assert report['registry']['current_shadow'] is None
    with pytest.raises(ValueError):research.choose_shadow(report,'unseen-candidate')


def test_risk_adjusted_objective_penalizes_extreme_loss_and_unknowns():
    def arm(values):
        return {'positions':[{'realized_pnl_lamports':str(int(v*1e9))} for v in values],
            'all_entered_positions_liquidated':True,'full_extra_costs_lamports':'10000',
            'max_realized_drawdown':min(0,min(values)/10)}
    stable=research._objective(arm([.1,.1,.1]))
    risky=research._objective(arm([1,1,-1]))
    assert risky['expectancy_sol']>stable['expectancy_sol']
    assert risky['objective']<stable['objective']


def test_drift_uses_position_outcomes_available_by_clock_and_retains_unknowns():
    outcomes=[dict(position_id='a',creator='c',policy_id='p',available_at_ms=10,
        net_pnl_lamports=5,economic_qualified=True),dict(position_id='b',creator='c',policy_id='p',
        available_at_ms=30,net_pnl_lamports=-10,economic_qualified=True),
        dict(position_id='unknown',available_at_ms=20,economic_qualified=False)]
    report=research.measure_drift(outcomes,as_of_ms=25,split_ms=15)
    assert report['unknown_outcomes']==1 and len(report['groups'])==1
    assert report['groups'][0]['net_pnl_lamports']=='5'
    assert report['automatic_policy_change'] is False
    with pytest.raises(ValueError,match='Repeated position'):
        research.measure_drift([outcomes[0],outcomes[0]],as_of_ms=25,split_ms=15)


def test_plan_tampering_and_budgets_reject_before_replay():
    p=plan();p['candidates'].append(deepcopy(p['candidates'][0]))
    with pytest.raises(ValueError,match='frozen candidate'):
        research.evaluate_research(corpus(),p)
    with pytest.raises(ValueError):research.make_plan(registered_at_ms=True,development_end_ms=2,holdout_end_ms=3)
    api=p4._api()
    with pytest.raises(ValueError,match='preserve baseline'):
        p4._run_arm(corpus(),{},'early_sniping','development',fee_multiplier=1,decision_delay_ms=0,
            development_end_ms=200000,api=api,research_overrides={'min_score':1})
