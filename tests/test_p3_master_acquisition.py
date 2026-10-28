"""Prospective capture inputs become causal comparison frames, never fills."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from bot.p3.cohort import (CRITERIA,make_acquisition_plan,validate_acquisition_plan,
    select_cohort,build_comparison_corpus)
from bot.p3.cohort import retain_comparison_inputs
from bot.p3.store import CaptureStore
from bot.economic_demo import _load_api,_quote_observation
from test_p3_cohort import row


def capture(tmp_path, *, features=True, own_fees=True, proxy=False, unknown_clock=False,
            refused=False, future_features=False, bad_reference=False, invalid_features=False,
            provenance='synthetic', future_analysis=False, fee_provenance='synthetic'):
    source=row(0);source['snapshot_available_at_ms']=100000
    selection=select_cohort([source,row(1,active=False)],decision_at_ms=100000)
    mint,pool,creator=source['mint'],source['pool'],source['creator_claim']
    clock=[100000];api=_load_api()
    with CaptureStore(tmp_path/'inputs.sqlite',clock_ms=lambda:clock[0]) as store:
        def append(kind,**kwargs):
            return store.append(kind,received_at_ms=clock[0],provenance=provenance,**kwargs)
        slot=source['snapshot']['context_slot']
        snapshot_id=append('pool_snapshot',mint=mint,source_slot=slot,outcome='observed',
            payload={'retained_snapshot_fixture':True})
        analysis_body=dict(snapshot_observation_id=snapshot_id,analysis=deepcopy(source['snapshot']))
        if not future_analysis:
            analysis_id=append('candidate_decision',mint=mint,source_slot=slot,
                outcome='not_admitted',payload=analysis_body)
        else:analysis_id=None
        def quote(side,requested,*,buy_id=None):
            observation=_quote_observation(api,side=side,mint=mint,pool=pool,
                amount=100000000 if side=='buy' else 1000,
                output=1000 if side=='buy' else None if refused else 120000000,
                requested=requested,index=1 if side=='buy' else 2,case='acquisition')
            clock[0]=requested+11
            if unknown_clock:
                observation['source_time_ms']=None;observation['source_slot']=None
            if side=='sell':
                observation['payload']['inventory_buy_observation_id']=buy_id
            accepted=('outcome','source_time_ms','source_slot','mint','reason','payload','request_id')
            return append('quote_attempt',**{k:observation[k] for k in accepted if k in observation})
        buy_id=quote('buy',100010)
        sell_id=quote('sell',100025,buy_id=buy_id)
        fee_id=None
        if own_fees:
            clock[0]=100038
            fee_id=append('checkpoint',mint=mint,outcome='own_position_costs',payload=dict(
                buy_observation_id=buy_id,proxy=proxy,applicable_to_projected_position=True,
                fees=dict(entry_extra_lamports=5000,exit_extra_lamports=10000,
                    failed_attempt_lamports=[],provenance=fee_provenance)))
        if features:
            def feature(at,price):
                clock[0]=at
                values=asdict(api['engine'].build_features([],mint,creator,100,at//1000,
                    [],api['MarketQuote'](12000,price,pool),prior_launches=5))
                values.update(behavior_known=True,holder_data_known=True,holder_count=10,top_holder_share=.1)
                ids=[snapshot_id,buy_id,sell_id]
                if bad_reference:ids.append(999)
                next_identity=store.events()[-1]['id']+1
                return append('checkpoint',mint=mint,outcome='master_frame_inputs_v1',payload=dict(
                    creator=creator,pool=pool,detected_at_ms=100000,
                    features={} if invalid_features else values,source_observation_ids=ids,
                    snapshot_analysis_observation_id=(next_identity+1 if future_analysis else analysis_id),
                    token_decimals=6))
            feature_id=feature(100040,1.0)
            if future_analysis:
                analysis_id=append('candidate_decision',mint=mint,source_slot=slot,
                    outcome='not_admitted',payload=analysis_body)
            if future_features:feature(101000,100)
        else:feature_id=None
        return selection,store.events(),store.verify_integrity(),dict(
            buy=buy_id,sell=sell_id,feature=feature_id,fee=fee_id,snapshot=snapshot_id,analysis=analysis_id)


def build(selection,events,tail,at=100040):
    return build_comparison_corpus(selection,events,as_of_ms=at,
        integrity_verified=True,expected_tail=tail)


@pytest.mark.parametrize('damage',[None,'future','inconsistent_ready'])
def test_retained_supervision_reaches_comparison_only_when_available_and_consistent(tmp_path,damage):
    selection,events,tail,ids=capture(tmp_path)
    first=build(selection,events,tail)['corpus']['frames'][0]
    clock=[100050]
    health=dict(schema='rugger-paper-operational-health-v1',observed_at_ms=100050,
        allow_new_entries=True,blocking_reasons=[],source_health={
            name:dict(healthy=True) for name in ('scanner','rpc','websocket')})
    if damage=='future':health['observed_at_ms']=100061
    if damage=='inconsistent_ready':health['source_health']['rpc']['healthy']=False
    with CaptureStore(tmp_path/'inputs.sqlite',clock_ms=lambda:clock[0]) as store:
        health_id=store.append('checkpoint',received_at_ms=clock[0],provenance='synthetic',
            outcome='operational_health_v1',payload=dict(health=health))
        clock[0]=100060
        kwargs=dict(mint=first['mint'],pool=first['pool'],creator=first['creator'],detected_at_ms=100000,
            features=first['features'],source_observation_ids=[ids['snapshot'],ids['buy']],
            received_at_ms=clock[0],health_observation_id=health_id)
        before=len(store.events())
        if damage:
            with pytest.raises(ValueError,match='health'):retain_comparison_inputs(store,**kwargs)
            assert len(store.events())==before
        else:
            retain_comparison_inputs(store,**kwargs)
            retained=build(selection,store.events(),store.verify_integrity(),at=100060)
            assert 'health' not in retained['corpus']['frames'][0]
            assert retained['corpus']['frames'][1]['health']==health
            assert retained['corpus']['frames'][1]['source_evidence']['health_observation_id']==health_id


def test_p3_envelope_keeps_rejected_universe_and_unknowns_through_paired_replay(tmp_path):
    from bot.master_comparison import evaluate_acquired_comparison,make_plan
    selection,events,tail,_=capture(tmp_path,features=False)
    acquisition=build(selection,events,tail)
    report=evaluate_acquired_comparison(acquisition,make_plan(
        registered_at_ms=1,development_end_ms=200000,holdout_end_ms=500000))
    assert report['acquisition_universe']['denominator']==selection['records']
    assert report['acquisition_universe']['universe_size']==2
    assert report['acquisition_universe']['unknown_candidate_count']==1
    assert report['observed_frames']==0
    assert report['strict_market_economic_cycles']==0


def test_prepared_plan_reuses_global_source_budget_and_cannot_silently_widen_it():
    plan=make_acquisition_plan(registered_at_ms=1,source_revision='a'*40)
    assert plan['criteria']['max_requests']==20
    assert sum(plan['criteria']['request_budget'].values())==20
    assert plan['criteria']['max_elapsed_ms']==60000
    assert plan['status']=='PREPARED_NOT_EXECUTED' and plan['market_collection_executed'] is False
    assert len(validate_acquisition_plan(plan,first_observation_at_ms=2))==64
    altered=deepcopy(plan);altered['criteria']['max_requests']=21
    with pytest.raises(ValueError,match='fixed source'):
        validate_acquisition_plan(altered)
    with pytest.raises(ValueError,match='follow declared'):
        validate_acquisition_plan(plan,first_observation_at_ms=1)
    assert CRITERIA['status']=='PREPARED_NOT_EXECUTED'


def test_complete_universe_and_observed_bank_are_preserved_without_own_entry_mutation(tmp_path):
    selection,events,tail,ids=capture(tmp_path)
    original=deepcopy((selection,events))
    report=build(selection,events,tail);frame=report['corpus']['frames'][0]
    assert report['universe_size']==len(report['denominator'])==2
    assert report['frame_count']==1 and report['unknown_candidate_count']==0
    assert frame['bank_state']['observation_id']==ids['snapshot']
    assert frame['bank_state']['pool_state']['real_a']==int(selection['records'][0]['source_row']['snapshot']['facts']['pool']['real_a'])
    assert frame['bank_state']['creation_verified'] is False
    assert frame['bank_state']['identity_qualified'] is frame['bank_state']['supply_verified'] is None
    assert frame['bank_state']['raw_snapshot_replayed'] is False
    assert frame['independent_buyers'] is None
    context=frame['size_contexts']['100000000']
    assert context['buy_observation']['payload']['input_amount_atomic']=='100000000'
    assert context['sell_observations'][0]['payload']['input_amount_atomic']=='1000'
    assert frame['buy_context']['fees']['entry_extra_lamports']==5000
    assert frame['source_evidence']['own_fee_observation_ids']==[ids['fee']]
    assert report['qualified_economic_cycles']==0 and report['execution_verified'] is False
    assert report['provider_clocks_inferred_from_RPC'] is False
    assert (selection,events)==original


def test_future_features_do_not_change_earlier_frame_or_its_quote_and_cost_contexts(tmp_path):
    selection,events,tail,ids=capture(tmp_path,future_features=True)
    early=build(selection,events,tail)
    later=build(selection,events,tail,at=101000)
    assert len(early['corpus']['frames'])==1 and len(later['corpus']['frames'])==2
    assert later['corpus']['frames'][0]==early['corpus']['frames'][0]
    assert early['future_observations_excluded']==1
    assert early['corpus']['frames'][0]['features']['price_usd']==1


def test_same_timestamp_analysis_retained_after_decision_is_not_available_to_it(tmp_path):
    selection,events,tail,_=capture(tmp_path,future_analysis=True)
    frame=build(selection,events,tail)['corpus']['frames'][0]
    assert 'bank_state' not in frame and frame['source_slot'] is None


@pytest.mark.parametrize('option',[dict(own_fees=False),dict(proxy=True),dict(fee_provenance='observed')])
def test_missing_other_transaction_or_mislabelled_fees_stay_unknown(tmp_path,option):
    selection,events,tail,_=capture(tmp_path,**option)
    context=build(selection,events,tail)['corpus']['frames'][0]['buy_context']
    assert context['fees'] is None


def test_missing_provider_clock_cannot_be_repaired_with_the_observed_rpc_bank(tmp_path):
    selection,events,tail,_=capture(tmp_path,unknown_clock=True)
    frame=build(selection,events,tail)['corpus']['frames'][0]
    assert frame['source_slot'] is not None
    quote=frame['buy_context']['buy_observation']
    assert quote['source_slot'] is quote['source_time_ms'] is None


def test_refused_sell_survives_as_a_failure_and_not_an_executed_liquidation(tmp_path):
    selection,events,tail,ids=capture(tmp_path,refused=True)
    report=build(selection,events,tail)
    assert report['refused_quote_observation_ids']==[ids['sell']]
    sell=report['corpus']['frames'][0]['sell_contexts'][0]['sell_observation']
    assert sell['outcome']=='unavailable' and sell['payload']['output_amount_atomic'] is None
    assert report['qualified_economic_cycles']==0


@pytest.mark.parametrize('option',[dict(features=False),dict(bad_reference=True),dict(invalid_features=True)])
def test_insufficient_inputs_leave_candidate_unknown_and_keep_the_denominator(tmp_path,option):
    selection,events,tail,_=capture(tmp_path,**option)
    report=build(selection,events,tail)
    assert report['frame_count']==0 and report['unknown_candidate_count']==1
    assert report['universe_size']==2 and report['selected_count']==1
    assert report['denominator']==selection['records']


@pytest.mark.parametrize('damage',['payload','anchor','selection','attestation'])
def test_capture_corruption_or_selection_changes_are_refused_before_comparison(tmp_path,damage):
    selection,events,tail,_=capture(tmp_path)
    verified=True
    if damage=='payload':events[0]['payload']['retained_snapshot_fixture']=False
    elif damage=='anchor':tail='f'*64
    elif damage=='selection':selection['selected'][0]['pool']='different'
    else:verified=False
    with pytest.raises(ValueError):
        build_comparison_corpus(selection,events,as_of_ms=100040,
            integrity_verified=verified,expected_tail=tail)


def test_explicit_live_provenance_remains_market_observation_without_profit_or_cost_certification(tmp_path):
    selection,events,tail,_=capture(tmp_path,provenance='live')
    report=build(selection,events,tail)
    assert report['corpus']['data_kind']=='market_observation'
    assert report['corpus']['frames'][0]['buy_context']['fees'] is None
    assert report['qualified_economic_cycles']==0


def test_producer_retains_existing_scanner_inputs_and_later_own_costs_never_rewrite_prior_decision(tmp_path):
    selection,events,tail,ids=capture(tmp_path,own_fees=False)
    early=build(selection,events,tail)
    first=early['corpus']['frames'][0]
    clock=[100050]
    with CaptureStore(tmp_path/'inputs.sqlite',clock_ms=lambda:clock[0]) as store:
        store.append('checkpoint',received_at_ms=clock[0],mint=first['mint'],provenance='synthetic',
            outcome='own_position_costs',payload=dict(buy_observation_id=ids['buy'],proxy=False,
                applicable_to_projected_position=True,fees=dict(entry_extra_lamports=5000,
                    exit_extra_lamports=10000,failed_attempt_lamports=[],provenance='synthetic')))
        clock[0]=100060
        identity=retain_comparison_inputs(store,mint=first['mint'],pool=first['pool'],creator=first['creator'],
            detected_at_ms=first['detected_at_ms'],features=first['features'],received_at_ms=100060,
            source_observation_ids=[ids['snapshot'],ids['buy'],ids['sell']],
            snapshot_analysis_observation_id=ids['analysis'],token_decimals=6)
        assert store.events()[-1]['id']==identity
        after=build(selection,store.events(),store.verify_integrity(),at=100060)
    assert after['corpus']['frames'][0]==first
    assert first['buy_context']['fees'] is None
    assert after['corpus']['frames'][1]['buy_context']['fees']['exit_extra_lamports']==10000
    assert after['corpus']['frames'][1]['source_evidence']['feature_observation_id']==identity


def append_creation(store, *, mint, pool, creator, at, forged=False):
    from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID
    signature='3'*88
    keys=['payer',creator,'a','b','c',pool,mint]
    raw=dict(slot=100,blockTime=99,meta={'err':None},transaction=dict(signatures=[signature],
        message=dict(accountKeys=keys,instructions=[dict(programId=RAYDIUM_LAUNCHPAD_PROGRAM_ID,
            accounts=keys,parsed={'type':'initialize_v2'})])))
    tx=store.append('transaction',received_at_ms=at,source_slot=100,signature=signature,
        outcome='observed',provenance='synthetic',payload={'raw_transaction':raw})
    launch=store.append('launch',received_at_ms=at,source_slot=100,signature=signature,mint=mint,
        outcome='observed',provenance='synthetic',payload=dict(transaction_observation_id=tx,
            mint=mint,pool_state='different' if forged else pool,creator=creator,payer='payer'))
    return [tx,launch]


@pytest.mark.parametrize('forged',[False,True])
def test_creation_requires_a_prior_linked_raw_transaction_reparsed_with_the_existing_parser(tmp_path,forged):
    selection,events,tail,ids=capture(tmp_path)
    first=build(selection,events,tail)['corpus']['frames'][0]
    clock=[100050]
    with CaptureStore(tmp_path/'inputs.sqlite',clock_ms=lambda:clock[0]) as store:
        creation_ids=append_creation(store,mint=first['mint'],pool=first['pool'],creator=first['creator'],at=clock[0],forged=forged)
        clock[0]=100060
        retain_comparison_inputs(store,mint=first['mint'],pool=first['pool'],creator=first['creator'],
            detected_at_ms=first['detected_at_ms'],features=first['features'],received_at_ms=clock[0],
            source_observation_ids=[ids['snapshot'],ids['buy'],ids['sell']],
            snapshot_analysis_observation_id=ids['analysis'],token_decimals=6)
        report=build(selection,store.events(),store.verify_integrity(),at=clock[0])
    assert report['corpus']['frames'][0]['bank_state']['creation_verified'] is False
    assert report['corpus']['frames'][1]['bank_state']['creation_verified'] is (not forged)
    assert report['corpus']['frames'][1]['source_evidence']['creation_observation_ids']==([] if forged else creation_ids)


@pytest.mark.parametrize('alter_raw',[False,True])
def test_original_rpc_bytes_are_reparsed_and_upstream_certification_claims_do_not_override_them(tmp_path,alter_raw):
    from test_p3_qualification import qualified_fixture,qualify
    from test_p3_launchlab import mutate_account
    from bot.p3.quotes import SOL_MINT
    accounts,addresses=qualified_fixture();analysis=qualify(accounts,addresses)
    # Selection is an upstream instrumental claim. The new frame adapter must
    # independently retain the parser's actual incomplete platform identity.
    analysis['facts']['identity_certification']['program_derived_addresses_verified']=True
    source=dict(mint=addresses['mint_a'],pool=addresses['pool'],quote_mint_claim=SOL_MINT,
        creator_claim='synthetic_creator',snapshot=analysis,snapshot_available_at_ms=100000)
    selection=select_cohort([source],decision_at_ms=100000)
    assert selection['selected_count']==1
    if alter_raw:mutate_account(accounts,addresses['vault_b'],64,123,'<Q')
    api=_load_api();clock=[100000]
    with CaptureStore(tmp_path/'raw-bank.sqlite',clock_ms=lambda:clock[0]) as store:
        ordered=list(accounts)
        snapshot=store.append('pool_snapshot',received_at_ms=clock[0],mint=source['mint'],source_slot=1234,
            outcome='observed',provenance='synthetic',payload=dict(requested_addresses=ordered,
                raw_rpc_result=dict(context={'slot':1234},value=[accounts[a] for a in ordered])))
        identity=store.append('candidate_decision',received_at_ms=clock[0],mint=source['mint'],source_slot=1234,
            outcome='not_admitted',provenance='synthetic',payload=dict(snapshot_observation_id=snapshot,analysis=analysis))
        values=api['engine'].build_features([],source['mint'],source['creator_claim'],100,100,
            [],api['MarketQuote'](12000,1,source['pool']),prior_launches=5)
        retain_comparison_inputs(store,mint=source['mint'],pool=source['pool'],creator=source['creator_claim'],
            detected_at_ms=100000,features=values,received_at_ms=100000,
            source_observation_ids=[snapshot],snapshot_analysis_observation_id=identity)
        report=build(selection,store.events(),store.verify_integrity(),at=100000)
    frame=report['corpus']['frames'][0]
    if alter_raw:assert 'bank_state' not in frame
    else:
        assert frame['bank_state']['raw_snapshot_replayed'] is True
        assert frame['bank_state']['supply_verified'] is True
        assert frame['bank_state']['identity_qualified'] is False
        assert frame['bank_state']['certification_scope']=='pinned_parser_replay'


@pytest.mark.parametrize('damage',['source_missing','source_future','creator','features','decimals'])
def test_producer_rejects_unavailable_inputs_before_appending_a_checkpoint(tmp_path,damage):
    selection,events,tail,ids=capture(tmp_path)
    frame=build(selection,events,tail)['corpus']['frames'][0]
    refs=[ids['snapshot']];at=100040;creator=frame['creator'];features=frame['features'];decimals=6
    if damage=='source_missing':refs=[999]
    elif damage=='source_future':refs=[ids['feature']];at=100039
    elif damage=='creator':creator='different'
    elif damage=='features':features={}
    else:decimals=True
    with CaptureStore(tmp_path/'inputs.sqlite',clock_ms=lambda:100050) as store:
        before=store.events()
        with pytest.raises(ValueError):
            retain_comparison_inputs(store,mint=frame['mint'],pool=frame['pool'],creator=creator,
                detected_at_ms=frame['detected_at_ms'],features=features,received_at_ms=at,
                source_observation_ids=refs,token_decimals=decimals)
        assert store.events()==before
