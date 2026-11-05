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


@pytest.mark.parametrize('start,end',[(199999,500000),(200001,500000),(100000,200001),
    (499999,800000),(210000,490000)])
def test_consumed_holdout_rejects_shifted_overlapping_windows_before_replay(start,end,monkeypatch):
    original=research.evaluate_research(corpus(),plan())
    shifted=research.make_plan(registered_at_ms=1,development_end_ms=start,holdout_end_ms=end)
    monkeypatch.setattr(p4,'_api',lambda:pytest.fail('Overlapping holdout reached ledger replay'))
    with pytest.raises(ValueError,match='overlaps a consumed'):
        research.evaluate_research(corpus(),shifted,registry=original['registry'])


@pytest.mark.parametrize('start,end',[(100000,200000),(500000,800000)])
def test_consumed_holdout_permits_adjacent_disjoint_windows_and_preserves_input_registry(start,end):
    original=research.evaluate_research(corpus(),plan())
    retained=deepcopy(original['registry'])
    adjacent=research.make_plan(registered_at_ms=1,development_end_ms=start,holdout_end_ms=end)
    result=research.evaluate_research(corpus(),adjacent,registry=original['registry'])
    assert original['registry']==retained
    assert len(result['registry']['evaluated_windows'])==2
    assert result['registry']['evaluated_windows'][0]['development_end_ms']==200000
    assert result['registry']['evaluated_windows'][1]['development_end_ms']==start
    assert result['registry']['evaluated_windows'][1]['holdout_end_ms']==end


def test_legacy_consumed_hashes_without_bounds_fail_closed_but_empty_registry_can_upgrade():
    original=research.evaluate_research(corpus(),plan())
    legacy=deepcopy(original['registry']);legacy.pop('evaluated_windows')
    future=research.make_plan(registered_at_ms=1,development_end_ms=500000,holdout_end_ms=800000)
    with pytest.raises(ValueError,match='Legacy consumed holdout bounds are unknown'):
        research.evaluate_research(corpus(),future,registry=legacy)
    # Pointer maintenance reads no new outcomes and can still roll back legacy state.
    selected=research.choose_shadow(original,original['frozen_candidate_ids'][0],registry=legacy)
    assert research.rollback_shadow(selected)['current_shadow'] is None
    empty=research.empty_registry();empty.pop('evaluated_windows')
    upgraded=research.evaluate_research(corpus(),plan(),registry=empty)
    assert len(upgraded['registry']['evaluated_windows'])==1


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(version=True),lambda r:r.update(version=-1),lambda r:r.update(version=1.5),
    lambda r:r.update(previous_shadows='invalid'),lambda r:r.update(evaluated_holdouts=[{}]),
    lambda r:r.update(evaluated_windows=None),lambda r:r.update(active_policy_changed=True),
    lambda r:r.update(current_shadow={})])
def test_untrusted_registry_types_and_versions_reject_before_replay(mutation,monkeypatch):
    state=research.empty_registry();mutation(state)
    monkeypatch.setattr(p4,'_api',lambda:pytest.fail('Invalid registry reached ledger replay'))
    with pytest.raises(ValueError):research.evaluate_research(corpus(),plan(),registry=state)


def test_registry_rejects_tampered_consumed_bounds_and_versions_never_rewind():
    original=research.evaluate_research(corpus(),plan())
    damaged=deepcopy(original['registry']);damaged['evaluated_windows'][0]['holdout_end_ms']+=1
    with pytest.raises(ValueError,match='bounds or fingerprint'):
        research.evaluate_research(corpus(),plan(),registry=damaged)
    selected=research.choose_shadow(original,original['frozen_candidate_ids'][0])
    damaged=deepcopy(selected);damaged['version']=0
    with pytest.raises(ValueError,match='monotone integer version'):research.rollback_shadow(damaged)
    assert selected['version']==1
    rolled=research.rollback_shadow(selected)
    assert rolled['version']==2
    again=research.choose_shadow(original,original['frozen_candidate_ids'][0],registry=rolled)
    assert again['version']==3


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


def long_corpus(sequence):
    """Fresh exact-quantity observations, with disjoint declared creator groups."""
    api=_load_api();frames=[]
    templates=(corpus()['frames'][0],corpus()['frames'][4])
    for template,start in zip(templates,(100000,4000000)):
        buy_id=template['mint']+'-long-buy'
        for index,(offset,price,proceeds) in enumerate(sequence):
            at=start+offset;frame=deepcopy(template)
            frame.update(id=template['mint']+'-long-'+str(index),detected_at_ms=start,
                available_at_ms=at,features_available_at_ms=at,source_slot=100+index,
                slot_available_at_ms=at,buy_context=None,sell_contexts=[])
            frame['features'].update(signal_time=start//1000,observed_at=at//1000,price_usd=price)
            fees=dict(entry_extra_lamports=5000,exit_extra_lamports=10000,
                failed_attempt_lamports=[],provenance='synthetic')
            observation=_quote_observation(api,side='buy' if index==0 else 'sell',
                mint=frame['mint'],pool=frame['pool'],amount=1000000000 if index==0 else 1000,
                output=1000 if index==0 else proceeds,requested=at-20,index=index+1,case='research_long')
            observation['id']=buy_id if index==0 else frame['id']+'-sell'
            if index==0:
                frame['buy_context']=dict(buy_observation=observation,token_decimals=6,fees=fees)
            else:
                frame['sell_contexts']=[dict(inventory_buy_observation_id=buy_id,
                    sell_observation=observation,requested_quantity_atomic='1000',fees=fees)]
            frames.append(frame)
    return dict(data_kind='synthetic',frames=frames)


def extended_plan(**kwargs):
    return research.make_plan(registered_at_ms=1,development_end_ms=3000000,
        holdout_end_ms=8000000,research_exit_horizon_ms=3600000,**kwargs)


def candidate_run(report,name):
    return next(row['run'] for row in report['development'] if row['candidate']['id']=='early_sniping:'+name)


def exit_message(run):
    return next(row for row in run['trace'] if (row['message'] or '').startswith('EXIT '))


def test_preregistered_extended_horizon_distinguishes900_and1800_second_holds_with_same_exact_lot():
    sequence=((0,1.,None),(60000,1.04,1040000000),(900000,1.03,1030000000),
        (1800000,1.02,1020000000))
    data=long_corpus(sequence);report=research.evaluate_research(data,extended_plan())
    assert report['research_exit_horizon_ms']==3600000
    short=candidate_run(report,'confirmation-exit');baseline=candidate_run(report,'baseline')
    assert exit_message(short)['decision_at_ms']==1000000
    assert exit_message(baseline)['decision_at_ms']==1900000
    assert 'reason=TIMEOUT' in exit_message(short)['message']
    assert 'reason=TIMEOUT' in exit_message(baseline)['message']
    assert short['legs'][0]['quantity_atomic']==baseline['legs'][0]['quantity_atomic']=='1000'
    assert short['known_modeled_extra_costs_lamports']==baseline['known_modeled_extra_costs_lamports']=='15000'
    assert short['realized_pnl_sol']==pytest.approx(.029985)
    assert baseline['realized_pnl_sol']==pytest.approx(.019985)
    assert report['promotion_allowed'] is False
    # An unregistered call retains the original30s horizon and different exit.
    p=research.make_plan(registered_at_ms=1,development_end_ms=3000000,holdout_end_ms=8000000)
    legacy=candidate_run(research.evaluate_research(data,p),'baseline')
    assert exit_message(legacy)['decision_at_ms']==160000
    assert 'reason=RESEARCH_HORIZON' in exit_message(legacy)['message']


def test_extended_horizon_preserves_frozen_trailing_stops_before_time_limits():
    sequence=((0,1.,None),(60000,1.08,1080000000),(120000,1.04,1040000000),
        (180000,1.02,1020000000))
    report=research.evaluate_research(long_corpus(sequence),extended_plan())
    tighter=candidate_run(report,'confirmation-exit');baseline=candidate_run(report,'baseline')
    assert exit_message(tighter)['decision_at_ms']==220000
    assert exit_message(baseline)['decision_at_ms']==280000
    assert 'reason=TRAILING_STOP' in exit_message(tighter)['message']
    assert 'reason=TRAILING_STOP' in exit_message(baseline)['message']
    assert tighter['realized_pnl_sol']==pytest.approx(.039985)
    assert baseline['realized_pnl_sol']==pytest.approx(.019985)
    assert tighter['all_entered_positions_liquidated'] is True
    assert baseline['all_entered_positions_liquidated'] is True


@pytest.mark.parametrize('price,proceeds,reason',[(1.2,1200000000,'TP'),(.9,900000000,'SL')])
def test_extended_horizon_preserves_entry_take_profit_and_stop_loss(price,proceeds,reason):
    report=research.evaluate_research(long_corpus(((0,1.,None),(60000,price,proceeds))),extended_plan())
    run=candidate_run(report,'baseline')
    assert exit_message(run)['decision_at_ms']==160000
    assert 'reason='+reason+' ' in exit_message(run)['message']
    assert run['legs'][0]['quantity_atomic']=='1000'
    assert run['realized_pnl_sol']==pytest.approx((proceeds-1000015000)/1e9)


def test_extended_horizon_cannot_use_exit_beyond_development_or_holdout_end_or_unlock_window():
    data=long_corpus(((0,1.,None),(60000,1.04,1040000000),(900000,1.03,1030000000),
        (1800000,1.02,1020000000)))
    p=research.make_plan(registered_at_ms=1,development_end_ms=1500000,
        holdout_end_ms=5500000,research_exit_horizon_ms=3600000)
    result=research.evaluate_research(data,p)
    baseline=candidate_run(result,'baseline')
    assert baseline['closed_positions']==0
    assert baseline['positions'][0]['remaining_atomic']=='1000'
    assert baseline['portfolio_pnl_sol'] is None
    validation=next(row for row in result['holdout'] if row['candidate']['id']=='early_sniping:baseline')
    assert validation['run']['closed_positions']==0
    assert validation['metrics']['eligible'] is False
    changed=deepcopy(data)
    for frame in changed['frames']:
        if frame['available_at_ms']>=1500000:frame['features']['price_usd']=100
    again=research.evaluate_research(changed,p)
    assert again['development']==result['development']
    changed_horizon=deepcopy(p);changed_horizon['research_exit_horizon_ms']=3500000
    with pytest.raises(ValueError,match='already evaluated'):
        research.evaluate_research(data,changed_horizon,registry=result['registry'])


@pytest.mark.parametrize('horizon',[True,29999,3600001,30000.0])
def test_research_horizon_is_bounded_and_isolated_from_original_replay(horizon):
    with pytest.raises(ValueError,match='Research exit horizon'):
        research.make_plan(registered_at_ms=1,development_end_ms=200000,
            holdout_end_ms=500000,research_exit_horizon_ms=horizon)
    with pytest.raises(ValueError,match='research-only'):
        p4._run_arm(corpus(),{},'early_sniping','development',fee_multiplier=1,
            decision_delay_ms=0,development_end_ms=200000,api=p4._api(),research_exit_horizon_ms=3600000)


def paired_plan(**changes):
    return research.make_plan(registered_at_ms=1,development_end_ms=200000,
        holdout_end_ms=500000,paired_validation=True,**changes)


def test_paired_validation_is_preregistered_without_changing_default_design_or_active_policy():
    assert 'paired_validation' not in plan()
    p=paired_plan();design=p['paired_validation']
    assert design['hypothesis_family_size']==24
    assert design['familywise_alpha']=={'numerator':1,'denominator':20}
    assert design['per_hypothesis_alpha']=={'numerator':1,'denominator':480}
    original=deepcopy(p4.POLICY)
    result=research.evaluate_research(corpus(),p)
    measured=result['paired_validation']
    assert len(measured['scenarios'])==12  # Three frozen comparisons, four registered stresses.
    assert measured['selection_uses_sensitivities'] is False
    assert measured['development_frozen_candidate_ids']==result['frozen_candidate_ids']
    assert measured['market_winner'] is None and measured['promotion_allowed'] is False
    assert p4.POLICY==original
    broken=deepcopy(p);broken['paired_validation']['hypothesis_family_size']=3
    with pytest.raises(ValueError,match='frozen candidate design'):
        research.evaluate_research(corpus(),broken)


def test_paired_stresses_use_same_lots_fixed_costs_and_exact_creator_deltas():
    result=research.evaluate_research(corpus(),paired_plan())
    for scenario in result['paired_validation']['scenarios']:
        measurement=scenario['paired']
        assert scenario['initial_capital_lamports']=='10000000000'
        assert measurement['complete_creator_groups']==1
        assert measurement['total_conditional_delta_lamports']=='0'
        assert measurement['p_value'] is measurement['confidence_interval'] is None
        assert scenario['familywise_claim_allowed'] is False
        assert 'synthetic_outcomes_only' in scenario['inference_blockers']
        expected='15000' if scenario['fee_multiplier']==1 else '30000'
        assert scenario['reference_summary']['full_extra_costs_lamports']==expected
        assert scenario['candidate_summary']['full_extra_costs_lamports']==expected
        row=measurement['opportunity_pairs'][0]
        pnl='199985000' if scenario['fee_multiplier']==1 else '199970000'
        assert row['candidate']['net_pnl_lamports']==row['reference']['net_pnl_lamports']==pnl
        assert row['candidate']['remaining_atomic']=='0'


def test_frozen_nonbaseline_candidate_has_exact_paired_delta_through_native_ledger():
    data=long_corpus(((0,1.,None),(60000,1.08,1080000000),
        (120000,1.04,1040000000),(180000,1.02,1020000000)))
    result=research.evaluate_research(data,extended_plan(paired_validation=True))
    scenarios=[s for s in result['paired_validation']['scenarios']
        if s['reference_id']=='early_sniping:baseline']
    assert len(scenarios)==4
    assert all(s['candidate_id']=='early_sniping:tp7-sl5' for s in scenarios)
    assert all(s['paired']['total_conditional_delta_lamports']=='60000000' for s in scenarios)
    assert all(s['paired']['complete_creator_groups']==1 for s in scenarios)
    assert all(s['familywise_claim_allowed'] is False for s in scenarios)
    assert result['paired_validation']['market_winner'] is None


def test_sensitivity_results_cannot_change_frozen_candidates_and_delay_cannot_cross_holdout_cutoff():
    data=corpus();p=paired_plan();p['holdout_end_ms']=330100
    # A fresh plan must be constructed, rather than mutating its registered design.
    p=research.make_plan(registered_at_ms=1,development_end_ms=200000,
        holdout_end_ms=330100,paired_validation=True)
    result=research.evaluate_research(data,p)
    plain=research.evaluate_research(data,research.make_plan(registered_at_ms=1,
        development_end_ms=200000,holdout_end_ms=330100))
    assert result['development']==plain['development']
    assert result['frozen_candidate_ids']==plain['frozen_candidate_ids']
    scenarios=result['paired_validation']['scenarios']
    now=[s for s in scenarios if s['decision_delay_ms']==0]
    delayed=[s for s in scenarios if s['decision_delay_ms']==250]
    assert all(s['paired']['total_conditional_delta_lamports']=='0' for s in now)
    assert all(s['paired']['total_conditional_delta_lamports'] is None for s in delayed)
    assert all(s['paired']['unknown_creator_groups']==1 for s in delayed)
    assert all('unknown_or_unliquidated_opportunities' in s['inference_blockers'] for s in delayed)


def test_creator_pairing_keeps_abstention_cashflow_separate_from_unknown_opportunity_cost():
    def run(positions):
        return dict(positions=positions,trace=[],full_extra_costs_lamports='15000')
    def position(mint,pnl,left='0'):
        return dict(mint=mint,realized_pnl_lamports=str(pnl),remaining_atomic=left,entry_cost_known=True)
    reference=run([position('m1',100),position('m2',300)])
    candidate=run([position('m1',150)])
    paired=research._paired_holdout(candidate,reference,{'m1':'same_creator','m2':'same_creator'})
    assert paired['complete_creator_groups']==1
    assert len(paired['opportunity_pairs'])==2
    assert paired['creator_groups'][0]['conditional_delta_lamports']=='-250'
    assert paired['complete_group_signs']==dict(positive=0,negative=1,tied=0)
    abstention=paired['opportunity_pairs'][1]['candidate']
    assert abstention['state']=='NO_POSITION_CASHFLOW_ONLY'
    assert abstention['opportunity_cost_lamports']=='300'  # Conditional paper comparison only.
    incomplete=research._paired_holdout(run([]),run([position('m1',150,'10')]),{'m1':'c'})
    row=incomplete['opportunity_pairs'][0]
    assert row['candidate']['net_pnl_lamports']=='0'
    assert row['candidate']['opportunity_cost_lamports'] is None
    assert row['conditional_delta_lamports'] is None
    assert incomplete['total_conditional_delta_lamports'] is None


@pytest.mark.parametrize('damage',['unknown_fees','refused_sell','partial_unfinished'])
def test_paired_validation_preserves_missing_costs_refusals_and_inventory_instead_of_filling_gains(damage):
    data=corpus(fees_unknown=damage=='unknown_fees',refused=damage=='refused_sell',
        partial=damage=='partial_unfinished')
    if damage=='partial_unfinished':data['frames']=data['frames'][:-1]
    result=research.evaluate_research(data,paired_plan())
    assert result['paired_validation']['promotion_allowed'] is False
    coverage=result['paired_validation']['baseline_coverage']
    assert len(coverage)==12
    assert all(row['coverage']['total_conditional_delta_lamports'] is None for row in coverage)
    assert all(row['coverage']['unknown_creator_groups']==1 for row in coverage)
    if damage=='refused_sell':
        assert all(row['coverage']['opportunity_pairs'][0]['reference']['refusal_count']>0 for row in coverage)
        assert all(row['coverage']['opportunity_pairs'][0]['reference']['refusals'] for row in coverage)
    for scenario in result['paired_validation']['scenarios']:
        assert scenario['paired']['p_value'] is None
        assert scenario['paired']['strict_qualified_market_pairs']==0
        assert scenario['familywise_claim_allowed'] is False


def test_declared_market_creator_independence_does_not_unlock_inference():
    data=corpus();data['data_kind']='market_observation'
    for frame in data['frames']:frame['creator_independence_verified']=True
    result=research.evaluate_research(data,paired_plan())
    assert result['paired_validation']['creator_independence_verified'] is False
    assert all('independent_market_evidence_not_audited' in s['inference_blockers']
        for s in result['paired_validation']['scenarios'])
    assert all(s['paired']['p_value'] is None and s['familywise_claim_allowed'] is False
        for s in result['paired_validation']['scenarios'])


@pytest.mark.parametrize('option',[1,None,'true'])
def test_paired_validation_flag_rejects_ambiguous_types(option):
    with pytest.raises(ValueError,match='explicit Boolean'):
        research.make_plan(registered_at_ms=1,development_end_ms=200000,
            holdout_end_ms=500000,paired_validation=option)
