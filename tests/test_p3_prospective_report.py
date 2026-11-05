"""Preserve all prospectively selected cases, including missing/refused exits."""
import asyncio
import json

import pytest

from bot.p3.collect import _record_quote
from bot.p3.prospective_report import (build_prospective_report, prospective_assignment,
                                       P4_SCOPE, P4_HOLDOUT)
from bot.p3.store import CaptureStore
from test_p3_quotes import Session, Response, RaydiumQuoteClient, quote_payload, SOL_MINT, USDC, TOKEN


def corpus(tmp_path, *, partial=False, late=False, bad_assignment=False, refused=False, reference_cash=10_000_000_000):
    plan=dict(plan_id='prospective-exit-008',sample_size=3,registered_at_ms=800,source_revision='a'*40,
              reference_cash_lamports=reference_cash,p4_scope=P4_SCOPE,p4_holdout_policy=P4_HOLDOUT)
    candidates=[dict(ordinal=n,mint=mint,pool='pool'+str(n),creator='same-creator' if n<2 else None)
                for n,mint in enumerate((USDC,TOKEN,'11111111111111111111111111111111'))]
    clock=[850]
    with CaptureStore(tmp_path/'corpus.sqlite',clock_ms=lambda:clock[0]) as store:
        def append(kind,**event): return store.append(kind,provenance='synthetic',**event)
        append('checkpoint',received_at_ms=850,outcome='registered_prospective_plan',payload={'plan':plan})
        def prefix():
            clock[0]=900
            mapping=prospective_assignment(plan,candidates)
            append('checkpoint',received_at_ms=900,outcome='prospective_prefix_fixed',payload={
                'candidates':candidates,'p4_assignment_sha256':'0'*64 if bad_assignment else mapping['sha256']})
        if not late: prefix()
        def quote(side,body,requested,phase,scope=None,buy_id=None,response_override=None):
            wall=iter((requested,requested+20));ticks=iter((0,1_000_000))
            q=asyncio.run(RaydiumQuoteClient(Session(Response(body if response_override is None else response_override)),clock_ms=lambda:next(wall),
                monotonic_ns=lambda:next(ticks)).quote(body['data']['inputMint'],body['data']['outputMint'],
                                                     body['data']['inputAmount'],100))
            clock[0]=requested+20
            def linked(kind,**event):
                event['payload'].update(probe_phase=phase,exit_scope=scope,
                    inventory_buy_observation_id=buy_id,prospective_ordinal=0)
                return append(kind,**event)
            assert _record_quote(linked,q,side,'synthetic-pair')
            return store.events()[-1]['id']
        buy=quote('buy',quote_payload(),1000,'initial')
        if late: prefix()
        clock[0]=1030
        append('checkpoint',received_at_ms=1030,mint=USDC,outcome='projected_inventory_fixed',payload={
            'acquired_atomic':'25000000','minimum_atomic':'24750000','partial_diagnostic_atomic':'10000000',
            'buy_observation_id':buy})
        amount='10000000' if partial else '25000000'
        scope='partial_diagnostic' if partial else 'full_expected'
        quote('sell',quote_payload(USDC,SOL_MINT,amount,'990000000','980100000'),1100,'followup',scope,buy,
              {'success':False,'msg':'INSUFFICIENT_LIQUIDITY'} if refused else None)
        if partial:
            quote('sell',quote_payload(USDC,SOL_MINT,amount,'990000000','980100000'),1200,'followup',scope,buy)
        clock[0]=1300
        append('candidate_decision',received_at_ms=1300,mint=TOKEN,outcome='not_admitted',
            reason='bank_unqualified',payload={'analysis':{'risk_flags':['supply_mismatch'],'facts':{}}})
        return plan,store.events(),store.verify_integrity()


def test_all_prefix_candidates_remain_denominator_without_fake_net_or_independence(tmp_path):
    plan,events,tail=corpus(tmp_path)
    report=build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)
    assert report['selected_corpus_size']==3
    assert report['records']==len(events) and report['source_revision']=='a'*40
    assert report['candidates_analyzed']==1
    assert report['candidates_with_projected_entry']==1
    assert report['full_sell_quotes']==report['full_sell_observation_attempts']==1
    assert report['qualified_economic_quote_scenarios']==0
    assert report['net_pnl_sol'] is None
    assert report['cases'][2]['case_state']=='not_reached'
    assert report['creator_groups_observed']==1 and report['unknown_creator_candidates']==1
    assert report['effective_independent_sample_size'] is None
    assert report['p4']['assignment_preregistered'] is True
    assert report['p4']['holdout_candidates']==0 and report['p4']['model_selected'] is False
    assert 'additional_execution_costs_unknown' in report['cases'][0]['admission_reasons']
    json.dumps(report,allow_nan=False)


def test_repeated_partial_quotes_do_not_add_up_to_liquidation(tmp_path):
    plan,events,tail=corpus(tmp_path,partial=True)
    report=build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)
    assert report['partial_sell_quotes']==2 and report['full_sell_quotes']==0
    assert report['cases'][0]['max_quoted_inventory_fraction_by_phase']=={'followup':'2/5'}
    assert report['cases'][0]['full_sell_quote_availability'] is None
    assert report['settled_positions']==0


@pytest.mark.parametrize('defect',['late_prefix','changed_assignment','unverified_tail'])
def test_invalid_preregistration_or_evidence_cannot_get_a_measured_release_report(tmp_path,defect):
    plan,events,tail=corpus(tmp_path,late=defect=='late_prefix',bad_assignment=defect=='changed_assignment')
    with pytest.raises(ValueError):
        build_prospective_report(plan,events,integrity_verified=defect!='unverified_tail',expected_tail=tail)


def test_provider_liquidity_refusal_is_kept_in_attempt_denominator_and_reason_code(tmp_path):
    plan,events,tail=corpus(tmp_path,refused=True)
    report=build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)
    assert report['selected_corpus_size']==3
    assert report['full_sell_observation_attempts']==1
    assert report['full_sell_quotes']==0 and report['refused_sell_quotes']==1
    assert report['cases'][0]['full_sell_quote_availability']==0
    assert report['cases'][0]['provider_refusal_codes']=={'INSUFFICIENT_LIQUIDITY':1}
    assert report['net_pnl_sol'] is None and report['settled_positions']==0


def stopped_before_prefix(tmp_path, *, empty_observed=False, unclosed=False):
    plan=dict(plan_id='prospective-exit-008',sample_size=3,registered_at_ms=800,
              reference_cash_lamports=10_000_000_000,p4_scope=P4_SCOPE,p4_holdout_policy=P4_HOLDOUT)
    clock=[850]
    with CaptureStore(tmp_path/'stopped.sqlite',clock_ms=lambda:clock[0]) as store:
        store.append('checkpoint',received_at_ms=850,outcome='prospective_plan_registered',
                     payload={'plan':plan},provenance='synthetic')
        clock[0]=900
        if empty_observed:
            store.append('discovery',received_at_ms=900,outcome='observed',payload={'rows':[],
                'received_row_count':0},provenance='synthetic')
            store.append('checkpoint',received_at_ms=900,outcome='prospective_prefix_fixed',payload={
                'candidates':[],'p4_assignment_sha256':prospective_assignment(plan,[])['sha256']},provenance='synthetic')
        else:
            store.append('request',received_at_ms=900,outcome='error',reason='http_429',
                payload={'http_status':429,'latency_ms':20},provenance='synthetic')
        if not unclosed:
            store.append('checkpoint',received_at_ms=900,outcome='prospective_closed',payload={
                'stop_reason':None if empty_observed else 'source_error_after_persisted_receipt',
                'requests_used':1,'elapsed_ms':20,'position_acquired':False},provenance='synthetic')
        return plan,store.events(),store.verify_integrity()


@pytest.mark.parametrize('empty_observed',[False,True])
def test_zero_case_report_preserves_discovery_failure_vs_observed_empty_without_fake_prefix(tmp_path,empty_observed):
    plan,events,tail=stopped_before_prefix(tmp_path,empty_observed=empty_observed)
    report=build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)
    assert report['selected_corpus_size']==0 and report['cases']==[]
    assert report['not_discovered'] is not empty_observed
    assert report['prefix_fixed'] is empty_observed
    assert report['indexed_rows_retained']==(0 if empty_observed else None)
    assert report['p4']['assignment_preregistered'] is False
    assert report['net_pnl_sol'] is None
    assert report['qualified_economic_quote_scenarios']==0
    assert report['collection_closed'] is True
    assert report['requests_used']==1 and report['elapsed_ms']==20
    assert report['stop_reason']==(None if empty_observed else 'source_error_after_persisted_receipt')
    json.dumps(report,allow_nan=False)


def test_missing_prefix_without_closed_source_error_is_not_silently_manufactured(tmp_path):
    plan,events,tail=stopped_before_prefix(tmp_path,unclosed=True)
    with pytest.raises(ValueError):
        build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)


def test_quote_finance_uses_only_the_registered_model_cash_reference(tmp_path,monkeypatch):
    import bot.p3.prospective_report as module
    plan,events,tail=corpus(tmp_path,reference_cash=12345)
    seen=[]; original=module.qualify_exit_quote_pair
    def capture(*args,**kwargs):
        seen.append(kwargs['available_cash_lamports'])
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'qualify_exit_quote_pair',capture)
    report=build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)
    assert seen==[12345]
    assert report['reference_cash_lamports']==12345


@pytest.mark.parametrize('mint',[None,'outside-selected-corpus'])
def test_prefix_cannot_be_fixed_after_unscoped_or_unselected_candidate_observations(tmp_path,mint):
    plan,events,_=corpus(tmp_path)
    # Preserve the verified envelope while exercising the semantic audit: an
    # unscoped bank or unrelated token is still information about outcomes.
    events[0]['kind']='pool_snapshot'
    events[0]['mint']=mint
    with pytest.raises(ValueError):
        build_prospective_report(plan,events,integrity_verified=True,expected_tail=events[-1]['record_hash'])


def test_missing_prefix_with_a_candidate_observation_is_never_a_zero_case_source_failure(tmp_path):
    plan,events,tail=stopped_before_prefix(tmp_path)
    events[1]['kind']='quote_attempt'
    with pytest.raises(ValueError):
        build_prospective_report(plan,events,integrity_verified=True,expected_tail=tail)
