"""Causal variants settle retained quantities through the shared native book."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from bot import p4_experiment as p4
from bot.economic_demo import _load_api,_public_address,_quote_observation


def protocol():
    return {'development_end_ms':200000,'registered_at_ms':1,'policy_sha256':p4._hash(p4.POLICY)}


def corpus(*,known=True,refused=False,fees_unknown=False,partial=False):
    api=_load_api();frames=[]
    for n,start in ((1,100000),(10,300000)):
        mint,creator,pool=(_public_address(v) for v in (n,n+1,n+2))
        contexts=[]
        for i,(delta,price,quantity) in enumerate(((0,1.,1000),(15000,1.02,900),(30000,1.2,None),(45000,1.2,None))):
            at=start+delta
            features=api['engine'].build_features([],mint,creator,start//1000,at//1000,
                [],api['MarketQuote'](12000,price,pool),prior_launches=5)
            values=asdict(features)
            values.update(behavior_known=known,holder_data_known=known,holder_count=10,
                top_holder_share=.1 if known else None)
            frame={'id':f'{mint}-{i}','mint':mint,'creator':creator,'pool':pool,
                'detected_at_ms':start,'available_at_ms':at,'source_slot':100+i,
                'slot_available_at_ms':at,'features_available_at_ms':at,'features':values,
                'independent_buyers':3 if i else 1,'sell_contexts':[]}
            fees={'entry_extra_lamports':None if fees_unknown else 5000,'exit_extra_lamports':10000,
                'failed_attempt_lamports':[],'provenance':'synthetic'}
            if quantity:
                event=_quote_observation(api,side='buy',mint=mint,pool=pool,
                    amount=1000000000,output=quantity,requested=at-20,index=i+1,case='p4')
                event['id']=f'{mint}-buy-{i}'
                frame['buy_context']={'buy_observation':event,'token_decimals':6,'fees':deepcopy(fees)}
                contexts.append((event['id'],quantity))
            else:
                for buy_id,q in contexts:
                    q=(q//2 if partial and i==2 else q-q//2 if partial else q)
                    proceeds=(600000000 if partial else 1200000000)
                    event=_quote_observation(api,side='sell',mint=mint,pool=pool,
                        amount=q,output=None if refused else proceeds,requested=at-20,index=i+1,case='p4')
                    event['id']=f'{mint}-sell-{buy_id}-{i}'
                    frame['sell_contexts'].append({'inventory_buy_observation_id':buy_id,
                        'sell_observation':event,'requested_quantity_atomic':str(q),'fees':deepcopy(fees)})
            frames.append(frame)
    return {'data_kind':'synthetic','frames':frames}


def base_runs(report,split='development'):
    return {run['strategy']:run for run in report['runs'] if run['split']==split
            and run['fee_multiplier']==1 and run['decision_delay_ms']==0}


def test_three_frozen_variants_use_each_own_lot_and_common_native_ledger():
    report=p4.evaluate_experiment(corpus(),protocol(),include_sensitivity=False)
    runs=base_runs(report)
    assert all(run['closed_positions']==1 for run in runs.values())
    assert runs['early_sniping']['positions'][0]['acquired_atomic']=='1000'
    assert runs['adaptive_hybrid']['positions'][0]['acquired_atomic']=='1000'
    assert runs['confirmed_momentum']['positions'][0]['acquired_atomic']=='900'
    for run in runs.values():
        assert run['entered_positions']==run['candidate_count']==1
        assert run['realized_pnl_sol']==pytest.approx(.199985)
        assert run['realized_capital_sol']==pytest.approx(10.199985)
        assert run['known_modeled_extra_costs_lamports']=='15000'
        assert run['legs'][0]['quantity_atomic']==run['positions'][0]['acquired_atomic']
    assert report['network_requests']==0 and report['ranking'] is None
    assert report['economic_profitability_verified'] is False


def test_unknown_creator_waits_for_confirmation_and_developer_sale_is_vetoed():
    data=corpus(known=False)
    report=p4.evaluate_experiment(data,protocol(),include_sensitivity=False)
    runs=base_runs(report)
    assert runs['adaptive_hybrid']['positions'][0]['acquired_atomic']=='900'
    assert runs['early_sniping']['positions'][0]['acquired_atomic']=='1000'
    for frame in data['frames']:frame['features']['dev_sales']=1
    veto=p4.evaluate_experiment(data,protocol(),include_sensitivity=False)
    assert all(run['entered_positions']==0 for run in veto['runs'])
    assert all(t['decision_reason']=='active_risk_or_score_refusal' for r in veto['runs'] for t in r['trace'])


def test_prefix_invariance_and_future_information_rejected():
    original=corpus();changed=deepcopy(original)
    for frame in changed['frames'][2:]:frame['features']['price_usd']=100000
    a=p4.evaluate_experiment(original,protocol(),include_sensitivity=False)
    b=p4.evaluate_experiment(changed,protocol(),include_sensitivity=False)
    for strategy,run in base_runs(a).items():
        assert run['trace'][:2]==base_runs(b)[strategy]['trace'][:2]
    changed=deepcopy(original)
    changed['frames'][0]['features_available_at_ms']+=1
    with pytest.raises(ValueError,match='Future information'):
        p4.evaluate_experiment(changed,protocol())
    with pytest.raises(ValueError,match='Noncausal'):
        p4.evaluate_experiment({'data_kind':'synthetic','frames':original['frames'][::-1]},protocol())


def test_newer_slot_and_independent_buyers_required_not_elapsed_time_alone():
    data=corpus(known=False)
    for frame in data['frames']:
        frame['source_slot']=100;frame['independent_buyers']=1
    runs=base_runs(p4.evaluate_experiment(data,protocol(),include_sensitivity=False))
    assert runs['early_sniping']['entered_positions']==1
    assert runs['confirmed_momentum']['entered_positions']==0
    assert runs['adaptive_hybrid']['entered_positions']==0


@pytest.mark.parametrize('option',['refused','fees_unknown'])
def test_illiquid_and_unknown_fee_positions_remain_open_not_zero_return(option):
    report=p4.evaluate_experiment(corpus(**{option:True}),protocol(),include_sensitivity=False)
    for run in report['runs']:
        assert run['entered_positions']==1 and run['closed_positions']==0
        assert run['positions'][0]['remaining_atomic']!='0'
        assert run['portfolio_return'] is run['portfolio_pnl_sol'] is run['win_rate'] is None
        assert run['legs']==[]
        assert run['qualification_failures']==2
        assert run['realized_capital_sol']==10


def test_partial_quantities_credit_each_leg_once_and_full_book_reconciles():
    report=p4.evaluate_experiment(corpus(partial=True),protocol(),include_sensitivity=False)
    for run in report['runs']:
        assert len(run['legs'])==2 and run['closed_positions']==1
        assert run['positions'][0]['remaining_atomic']=='0'
        assert sum(int(leg['quantity_atomic']) for leg in run['legs'])==int(run['positions'][0]['acquired_atomic'])
        assert run['realized_pnl_sol']==pytest.approx(.199975)
        assert run['known_modeled_extra_costs_lamports']=='25000'


def test_creator_overlap_quarantined_and_sensitivity_never_selects_winner():
    data=corpus();dev_creator=data['frames'][0]['creator']
    for frame in data['frames'][4:]:
        frame['creator']=dev_creator;frame['features']['creator']=dev_creator
    report=p4.evaluate_experiment(data,protocol())
    assert report['validation_creator_groups']==0
    assert any(group=='excluded_creator_overlap' for group in report['assignments'].values())
    assert all(run['candidate_count']==0 for run in report['runs'] if run['split']=='validation')
    assert len(report['runs'])==24 and report['ranking'] is None
    normal=base_runs(report)['early_sniping']
    stress=next(run for run in report['runs'] if run['strategy']=='early_sniping' and run['split']=='development'
        and run['fee_multiplier']==2 and run['decision_delay_ms']==0)
    assert normal['realized_pnl_sol']-stress['realized_pnl_sol']==pytest.approx(.000015)


def test_mismatched_sell_inventory_does_not_liquidate_another_entry():
    data=corpus()
    for frame in data['frames']:
        for context in frame['sell_contexts']:context['inventory_buy_observation_id']='unrelated-buy'
    report=p4.evaluate_experiment(data,protocol(),include_sensitivity=False)
    assert all(run['closed_positions']==0 and run['legs']==[] for run in report['runs'])


def test_development_positions_cannot_use_validation_prices_for_exit():
    data=corpus()
    data['frames'][2]['available_at_ms']=210000
    data['frames'][2]['features_available_at_ms']=210000
    data['frames'][2]['slot_available_at_ms']=210000
    data['frames'][2]['features']['observed_at']=210
    data['frames'][3]['available_at_ms']=215000
    data['frames'][3]['features_available_at_ms']=215000
    data['frames'][3]['slot_available_at_ms']=215000
    data['frames'][3]['features']['observed_at']=215
    result=p4.evaluate_experiment(data,protocol(),include_sensitivity=False)
    assert all(run['closed_positions']==0 and len(run['trace'])==2 for run in base_runs(result).values())


def test_declared_observation_cannot_postdate_feature_availability():
    data=corpus();data['frames'][0]['features']['observed_at']+=1
    runs=base_runs(p4.evaluate_experiment(data,protocol(),include_sensitivity=False))
    assert all(run['trace'][0]['decision_reason']=='features_identity_or_asof_mismatch' for run in runs.values())


@pytest.mark.parametrize('name',['momentum_60s','momentum_300s','slippage_bps_est','volume_5m_usd'])
def test_nonfinite_feature_rejected_before_economic_decisions_and_serialization(name):
    data=corpus();frame=data['frames'][0];frame['features'][name]=float('nan')
    decision=p4.decide_prefix('early_sniping',frame,[])
    assert decision['enter'] is False and decision['reason']=='features_invalid'
    with pytest.raises(ValueError,match='Nonfinite'):
        p4.evaluate_experiment(data,protocol())


def test_confirmation_baseline_excludes_malformed_or_rejected_historical_signals():
    data=corpus(known=False);frames=data['frames'][:3]
    bad=deepcopy(frames[0]);bad['features']['dev_sales']=1
    decision=p4.decide_prefix('confirmed_momentum',frames[1],[bad])
    assert decision['enter'] is False and decision['reason']=='awaiting_observed_confirmation'
    stale=deepcopy(frames[0]);stale['features_available_at_ms']-=6000
    decision=p4.decide_prefix('confirmed_momentum',frames[1],[stale])
    assert decision['enter'] is False
    assert p4.decide_prefix('confirmed_momentum',frames[2],[bad,frames[1]])['enter'] is True


def test_positive_momentum_does_not_override_low_sol_proceeds_or_double_count_route_fees():
    # Synthetic fee-rich quote scenario, inspired by008's own-entry model.
    # No claim that these quote bodies were observed in008.
    import hashlib,json
    from bot.p3.replay import _normalize_retained_body
    data=corpus();api=_load_api()
    for frame in data['frames']:
        for context in frame['sell_contexts']:
            previous=context['sell_observation'];q=context['requested_quantity_atomic']
            event=_quote_observation(api,side='sell',mint=frame['mint'],pool=frame['pool'],
                amount=int(q),output=888306249,requested=frame['available_at_ms']-20,index=3,case='p4-fee-rich')
            event['id']=previous['id']
            payload=event['payload'];raw=payload['retained_sanitized_response']
            route=raw['data']['routePlan'][0]
            route.update(feeRate=57500,feeAmount=str(int(q)*57500//1000000))
            payload.update(_normalize_retained_body(payload,raw))
            payload['sanitized_response_sha256']=hashlib.sha256(json.dumps(raw,sort_keys=True,allow_nan=False).encode()).hexdigest()
            context['sell_observation']=event
    report=p4.evaluate_experiment(data,protocol(),include_sensitivity=False)
    for run in report['runs']:
        assert run['closed_positions']==1
        assert run['realized_pnl_sol']==pytest.approx(-.111708751)
        assert run['known_modeled_extra_costs_lamports']=='15000'
        assert run['full_extra_costs_lamports']=='15000'


def test_direct_strategy_api_refuses_future_availability_without_corpus_wrapper():
    frame=corpus()['frames'][0]
    frame['features_available_at_ms']+=1
    assert p4.decide_prefix('early_sniping',frame,[])['enter'] is False
    frame['features_available_at_ms']-=1
    frame['slot_available_at_ms']+=1
    assert p4.decide_prefix('early_sniping',frame,[])['enter'] is False
