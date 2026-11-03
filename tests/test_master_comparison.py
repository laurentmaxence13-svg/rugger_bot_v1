"""A/B replay must measure abstention and adaptive exits without future leaks."""
from copy import deepcopy
import json

import pytest

from bot import master_comparison as compare
from bot.economic_demo import _load_api,_quote_observation
from test_p4_experiment import corpus
from test_master_decision import qualified


def plan(**kwargs):
    return compare.make_plan(registered_at_ms=1,development_end_ms=200000,holdout_end_ms=500000,**kwargs)


def available_corpus():
    value=corpus()
    for frame in value['frames']:
        frame['health']=dict(allow_new_entries=True,observed_at_ms=frame['available_at_ms'])
    return value


def qualified_corpus(*,partial=False,refused=False):
    _,first,health,_=qualified();first['health']=health
    first['size_contexts']['1000000000']['token_decimals']=6
    quantity=int(first['size_contexts']['1000000000']['buy_observation']['payload']['output_amount_atomic'])
    api=_load_api();frames=[first];buy_id='master-buy'
    steps=[(15000,1.02,quantity//2,550000000)] if partial else []
    steps.append((30000,1.2,quantity,1200000000))
    for i,(delta,price,q,proceeds) in enumerate(steps,2):
        frame=deepcopy(first);at=first['available_at_ms']+delta
        frame.update(id='future-'+str(i),available_at_ms=at,features_available_at_ms=at,
            slot_available_at_ms=at,source_slot=100+i,health=dict(allow_new_entries=True,observed_at_ms=at))
        frame['features'].update(observed_at=at//1000,price_usd=price,
            momentum_60s=-5 if partial and i==2 else 2,tx_buys_5m=1,tx_sells_5m=4 if partial and i==2 else 0)
        frame.pop('bank_state');frame.pop('size_contexts');frame.pop('inventory_context')
        quantities=[q,quantity-quantity//2] if partial and delta==30000 else [q]
        frame['sell_contexts']=[]
        for j,amount in enumerate(dict.fromkeys(quantities)):
            event=_quote_observation(api,side='sell',mint=frame['mint'],pool=frame['pool'],
                amount=amount,output=None if refused else (600000000 if amount!=quantity and delta==30000 else proceeds),
                requested=at-20,index=i,case='comparison')
            event['id']=f'exit-{i}-{j}'
            frame['sell_contexts'].append(dict(inventory_buy_observation_id=buy_id,sell_observation=event,
                requested_quantity_atomic=str(amount),fees=deepcopy(first['inventory_context']['fees'])))
        frames.append(frame)
    return dict(data_kind='synthetic',frames=frames)


def development(report,fee=1,delay=0):
    return next(p for p in report['pairs'] if p['split']=='development' and p['fee_multiplier']==fee and p['decision_delay_ms']==delay)


def test_same_tape_and_native_book_measure_master_abstention_without_inventing_edge():
    source=available_corpus();before=deepcopy(source)
    report=compare.evaluate_comparison(source,plan());pair=development(report)
    assert source==before and report['same_financial_implementation'] is True
    assert pair['reference']['closed_positions']==1 and pair['master']['entered_positions']==0
    assert pair['opportunities'][0]['master']['conditional_net_lamports']=='0'
    assert pair['opportunities'][0]['conditional_delta_lamports']=='-199985000'
    assert any(d['reference_action']=='BUY' and d['master_action']=='WAIT' for d in pair['decisions'])
    assert pair['master']['shadow_comparison_audit']['master_reference_comparison']['paired_decisions']==4
    assert report['ranking'] is None and report['promotion_allowed'] is False
    assert report['strict_market_economic_cycles']==report['network_requests']==0
    json.dumps(report,allow_nan=False)


def test_qualified_fixture_closes_same_exact_lot_and_cost_stress_is_applied_before_deciding():
    report=compare.evaluate_comparison(qualified_corpus(),plan(sensitivity=True))
    for fee in (1,2):
        pair=development(report,fee)
        for arm in ('reference','master'):
            run=pair[arm]
            assert run['closed_positions']==1 and run['positions'][0]['remaining_atomic']=='0'
            assert run['known_modeled_extra_costs_lamports']==str(15000*fee)
        snapshot=pair['master']['trace'][0]['decision_snapshot']
        assert snapshot['action']=='ENTER'
        assert snapshot['size_assessments'][-1]['additional_costs']['total_lamports']==15000*fee
        assert pair['master']['trace'][-1]['decision_snapshot']['position_plan']['quote_refusals']==[]
        assert pair['decisions'][-1]['reference_action']==pair['decisions'][-1]['master_action']=='TAKE_PROFIT'
        assert pair['opportunities'][0]['conditional_delta_lamports']=='0'


def test_adaptive_partial_exit_has_real_ledger_cost_and_remainder_not_scaled_proceeds():
    pair=development(compare.evaluate_comparison(qualified_corpus(partial=True),plan()))
    assert pair['master']['trace'][1]['decision_snapshot']['action']=='REDUCE'
    assert pair['reference']['trace'][1]['decision_snapshot']['action']=='HOLD'
    assert len(pair['master']['legs'])==2 and len(pair['reference']['legs'])==1
    assert pair['master']['positions'][0]['remaining_atomic']=='0'
    assert sum(int(leg['quantity_atomic']) for leg in pair['master']['legs'])==int(pair['master']['positions'][0]['acquired_atomic'])
    assert pair['master']['known_modeled_extra_costs_lamports']=='25000'
    assert pair['master']['realized_pnl_sol']==pytest.approx(.149975)
    assert pair['opportunities'][0]['conditional_delta_lamports']=='-50010000'


def test_refusals_keep_inventory_and_total_pnl_unknown():
    pair=development(compare.evaluate_comparison(qualified_corpus(refused=True),plan()))
    assert pair['master']['closed_positions']==pair['reference']['closed_positions']==0
    assert pair['opportunities'][0]['conditional_delta_lamports'] is None
    assert pair['master']['exit_attempts']>=1
    assert pair['master']['positions'][0]['remaining_atomic']!='0'


def test_future_prices_do_not_change_frozen_prior_decisions():
    source=qualified_corpus(partial=True);changed=deepcopy(source)
    changed['frames'][-1]['features']['price_usd']=.0001
    a=development(compare.evaluate_comparison(source,plan()))
    b=development(compare.evaluate_comparison(changed,plan()))
    for arm in ('reference','master'):
        assert a[arm]['trace'][:2]==b[arm]['trace'][:2]


def test_missing_health_blocks_both_arms_and_creator_overlap_is_preserved():
    source=available_corpus()
    for frame in source['frames']:frame.pop('health')
    report=compare.evaluate_comparison(source,plan())
    assert all(p[a]['entered_positions']==0 for p in report['pairs'] for a in ('reference','master'))
    source=available_corpus();creator=source['frames'][0]['creator']
    for frame in source['frames'][4:]:frame['creator']=frame['features']['creator']=creator
    report=compare.evaluate_comparison(source,plan())
    assert report['excluded_creator_overlap']==1
    assert all(p['reference']['candidate_count']==0 for p in report['pairs'] if p['split']=='validation')


def test_registration_tampering_and_future_exit_past_cutoff_cannot_be_used():
    p=plan();p['initial_capital_lamports']='20000000000'
    with pytest.raises(ValueError,match='Exact registered'):compare.evaluate_comparison(available_corpus(),p)
    p=compare.make_plan(registered_at_ms=1,development_end_ms=120000,holdout_end_ms=500000)
    pair=development(compare.evaluate_comparison(qualified_corpus(),p))
    assert pair['reference']['closed_positions']==pair['master']['closed_positions']==0
    assert pair['opportunities'][0]['conditional_delta_lamports'] is None


def test_reference_retains_actual_ten_percent_sizing_after_profit_and_never_scales_a_quote():
    p=compare.make_plan(registered_at_ms=1,development_end_ms=500000,holdout_end_ms=800000)
    pair=development(compare.evaluate_comparison(available_corpus(),p))
    assert pair['reference']['entered_positions']==1
    later=pair['reference']['trace'][4]['decision_snapshot']
    assert later['input_lamports']=='1019998500'  # 10% of10.199985SOL.
    assert 'buy_inventory_evidence_missing' in pair['reference']['trace'][4]['message']


def test_future_identity_with_backdated_detection_cannot_quarantine_a_past_validation_candidate():
    original=available_corpus();modified=deepcopy(original)
    future=deepcopy(original['frames'][0]);future['mint']='future-mint';future['id']='future-id'
    future['creator']=original['frames'][4]['creator']
    future['features'].update(mint=future['mint'],creator=future['creator'],observed_at=600)
    future.update(available_at_ms=600000,features_available_at_ms=600000,slot_available_at_ms=600000)
    modified['frames'].append(future)
    a=compare.evaluate_comparison(original,plan());b=compare.evaluate_comparison(modified,plan())
    assert a['pairs']==b['pairs']
    assert b['assignments']['future-mint']=='excluded_outside_window'
