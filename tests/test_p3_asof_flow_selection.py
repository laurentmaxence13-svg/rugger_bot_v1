"""Offline selection-orchestration tests.

These tests use controlled stubs for the original STRICT and RESEARCH_ONLY
functions. Full-repository integration and real decoded-account tests are
required before merging the experimental module.
"""
import copy
import sys
from types import ModuleType

import pytest

from bot.p3.asof_flow_selection import select_predecision_flow


def bank(mint,pool,slot,real_a,real_b,base,quote):
    return dict(mint=mint,pool_address=pool,context_slot=slot,
        evidence_profile='published_metadata_v1',risk_flags=[],
        facts=dict(account_context_basis='caller_supplied_single_getMultipleAccounts_response',
            supply_consistency=dict(matches=True),
            identity_certification=dict(account_discriminators_verified=True,
                program_derived_addresses_verified=False,
                checks=[dict(name='platform_pda',status='UNKNOWN')]),
            pool=dict(mint_a=mint,mint_b='So11111111111111111111111111111111111111112',
                total_sell_a='9000000',total_fundraising_b='10000000000',
                status='0',real_a=str(real_a),real_b=str(real_b)),
            base_vault=dict(amount_atomic=str(base)),
            quote_vault=dict(amount_atomic=str(quote)),
            config=dict(curve_type=0,trade_fee_rate_ppm=12500),
            platform=dict(platform_fee_rate_ppm=0,creator_fee_rate_ppm=0)))


@pytest.fixture
def fixture(monkeypatch):
    cohort=ModuleType('bot.p3.cohort')
    cohort.CRITERIA={'max_universe_rows':100,'target_candidates':2,'research_input_lamports':100000000}
    cohort.select_cohort=lambda universe,decision_at_ms:dict(
        schema='p3-active-cohort-selection-v1',
        selection_uses_provider_outcomes=False,market_collection_executed=False,
        decision_at_ms=decision_at_ms,
        records=[dict(universe_index=i,source_row=row,
            selection_reason='excluded_by_preregistered_activity_capacity_or_identity',
            screen={'screen_eligible':False}) for i,row in enumerate(universe)])
    gate=ModuleType('bot.p3.research_gate')
    gate.assess_research_only=lambda a,s:{'research_only':s is not None and a is not None}
    monkeypatch.setitem(sys.modules,'bot.p3.cohort',cohort)
    monkeypatch.setitem(sys.modules,'bot.p3.research_gate',gate)
    previous={}
    current=[]
    for n in range(3):
        mint,pool=f'Mint{n}',f'Pool{n}'
        previous[mint]=dict(pool=pool,available_at_ms=1000,
            snapshot=bank(mint,pool,10,1000,1000,2000,2000))
        delta=0 if n==0 else n*50
        current.append(dict(mint=mint,pool=pool,
            snapshot=bank(mint,pool,11,1000+delta,1000+delta,2000-delta,2000+delta),
            snapshot_available_at_ms=2000))
    strict=cohort.select_cohort(current,decision_at_ms=2001)
    return strict,previous


def test_predecision_net_movers_selected_without_future_or_ledger(fixture):
    strict,prev=fixture
    original=copy.deepcopy((strict,prev))
    selected=select_predecision_flow(strict,prev)
    assert selected['selected_count']==2
    assert [x['mint'] for x in selected['selected']]==['Mint1','Mint2']
    assert selected['assessments'][0]['reason']=='no_recent_net_buy_compatible_change'
    assert selected['universe_size']==3
    assert selected['selected_using_future_quotes_or_S2'] is False
    assert selected['trade_allowed'] is False
    assert selected['qualified_economic_cycles']==0
    assert (strict,prev)==original


def test_modified_strict_selection_cannot_retroactively_admit(fixture):
    strict,prev=fixture
    strict['records'][0]['selection_reason']='retroactive_selection'
    with pytest.raises(ValueError,match='original_strict_selection_mismatch'):
        select_predecision_flow(strict,prev)


def test_stale_or_later_S0_never_qualifies(fixture):
    strict,prev=fixture
    prev['Mint1']['available_at_ms']=-20000
    assert [x['mint'] for x in select_predecision_flow(strict,prev)['selected']]==['Mint2']
    prev['Mint1']['available_at_ms']=1000
    prev['Mint1']['snapshot']['context_slot']=11
    assert [x['mint'] for x in select_predecision_flow(strict,prev)['selected']]==['Mint2']


def test_S0_risk_failure_cannot_become_signal(fixture):
    strict,prev=fixture
    prev['Mint1']['snapshot']['risk_flags']=['freeze_authority']
    result=select_predecision_flow(strict,prev)
    assert [x['mint'] for x in result['selected']]==['Mint2']
    assert result['assessments'][1]['flow']['status']=='REJECTED'


def test_no_degenerate_span_and_no_missing_provenance(fixture):
    strict,prev=fixture
    with pytest.raises(ValueError,match='invalid_registered_predecision_span'):
        select_predecision_flow(strict,prev,max_observation_span_ms=0)
    prev['Mint1']['pool']='wrong'
    assert [x['mint'] for x in select_predecision_flow(strict,prev)['selected']]==['Mint2']
