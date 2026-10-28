"""Retained bank-to-research adaptation is causal and tied to account bytes."""
from copy import deepcopy

import pytest

from bot.p3.launchlab import analyze_snapshot
from bot.p3.size_study import frames_from_events,build_size_study
from test_p3_launchlab import fixture


def events():
    accounts,addresses=fixture();ordered=list(addresses.values())
    analysis=analyze_snapshot(accounts,context_slot=10,expected_mint=addresses['mint_a'],
        pool_address=addresses['pool'])
    common={'mint':addresses['mint_a'],'source_slot':10,'received_at_ms':1000,'available_at_ms':1001}
    group={'id':1,'kind':'pool_snapshot','outcome':'observed','payload':{
        'purpose':'prospective_grouped_bank','requested_addresses':ordered,
        'raw_rpc_result':{'context':{'slot':10},'value':[accounts[k] for k in ordered]}},**common}
    snapshot={'id':2,'kind':'pool_snapshot','outcome':'observed','payload':{
        'source_group_observation_id':1,'addresses':addresses,'requested_addresses':ordered,
        'raw_rpc_result':deepcopy(group['payload']['raw_rpc_result']),
        'period':'initial','evidence_profile':'legacy'},**common}
    decision={'id':3,'kind':'candidate_decision','outcome':'not_admitted','payload':{
        'snapshot_observation_id':2,'analysis':analysis},**common}
    close={'id':4,'kind':'checkpoint','outcome':'closed','payload':{},'record_hash':'a'*64,**common}
    return [group,snapshot,decision,close]


def adapt(rows):
    return frames_from_events(rows,run_id='synthetic',expected_tail='a'*64,integrity_verified=True)


def test_same_bank_adapter_preserves_unknown_identity_and_original_availability():
    rows=events();before=deepcopy(rows)
    frames=adapt(rows)
    assert rows==before and len(frames)==1
    f=frames[0]
    assert f['source_slot']==10 and f['available_at_ms']==1001
    assert f['bank_state']['identity_qualified'] is False
    assert f['bank_state']['creation_verified'] is False
    result=build_size_study(frames)
    assert result['bank_size_cases']==4 and result['admissible_model_cases']==4
    assert result['strict_economic_cycles']==result['new_market_requests']==0
    assert result['selected_size'] is result['net_market_pnl_sol'] is None
    assert all(d['enter_intent'] is None for d in result['cases'][0]['strategy_decisions'].values())
    assert all(r['model']['modeled_net_pnl_lamports'] is None for r in result['cases'][0]['sizes'])


@pytest.mark.parametrize('damage',['bytes','slot','ordering','future','analysis','tail'])
def test_detached_or_future_evidence_is_rejected(damage):
    rows=events()
    if damage=='bytes':rows[1]['payload']['raw_rpc_result']['value'][0]['lamports']+=1
    elif damage=='slot':rows[0]['source_slot']=9
    elif damage=='ordering':rows[1]['payload']['requested_addresses'].reverse()
    elif damage=='future':rows[0]['available_at_ms']=1002
    elif damage=='analysis':rows[2]['payload']['analysis']['conditional_projection']['buy_output_atomic']='1'
    else:rows[-1]['record_hash']='b'*64
    with pytest.raises(ValueError):adapt(rows)
