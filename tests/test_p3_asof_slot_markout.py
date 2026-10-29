"""Isolated slot-markout orchestration tests, not economic market evidence.

Full repository tests with real LaunchLab account decoding remain required.
"""
import copy
import sys
from types import ModuleType
import pytest

from bot.p3.asof_slot_markout import evaluate_asof_slot_markout as markout


@pytest.fixture
def case(monkeypatch):
    cohort=ModuleType('bot.p3.cohort')
    def screen(a, *, size_lamports,available_at_ms,decision_at_ms,expected_mint,expected_pool):
        assert size_lamports in (100000000,1000000000)
        assert available_at_ms==900 and decision_at_ms==1000
        assert a['mint']==expected_mint and a['pool_address']==expected_pool
        return {'own_entry_projection':{'buy_output_atomic':str(size_lamports*10)},
                'observed_full_exit_capacity':True}
    cohort.classify_snapshot=screen
    cohort._uint=lambda value,positive=False: int(value)
    launchlab=ModuleType('bot.p3.launchlab')
    launchlab.SnapshotEvidenceError=type('SnapshotEvidenceError',(ValueError,),{})
    def sell(pool,*,input_token_atomic,fee_rates_ppm,quote_vault_lamports,curve_type,share_fee_rate_ppm):
        assert fee_rates_ppm==(12500,0,0)
        assert quote_vault_lamports==10000000000
        assert curve_type==0 and share_fee_rate_ppm==0
        return {'output_lamports':str(input_token_atomic//10+10000)}
    launchlab.observed_sell_projection=sell
    monkeypatch.setitem(sys.modules,'bot.p3.cohort',cohort)
    monkeypatch.setitem(sys.modules,'bot.p3.launchlab',launchlab)
    pool={'mint_a':'Mint1','mint_b':'So11111111111111111111111111111111111111112',
          'supply':'1000000000000','total_sell_a':'900000000000',
          'total_fundraising_b':'9000000000','virtual_a':'1000000000000',
          'virtual_b':'10000000000','real_a':'100000000000','real_b':'1000000000',
          'protocol_fee_accrued':'0','platform_fee_accrued':'0','status':'0'}
    s1={'mint':'Mint1','pool_address':'Pool1','context_slot':101,
        'facts':{'pool':copy.deepcopy(pool),
                 'config':{'curve_type':'0','trade_fee_rate_ppm':'12500'},
                 'platform':{'platform_fee_rate_ppm':'0','creator_fee_rate_ppm':'0'},
                 'share_fee_assumption_ppm':'0'}}
    s2={'mint':'Mint1','pool_address':'Pool1','context_slot':102,
        'evidence_profile':'published_metadata_v1','risk_flags':[],
        'facts':{'account_context_basis':'caller_supplied_single_getMultipleAccounts_response',
                 'supply_consistency':{'matches':True},
                 'identity_certification':{'account_discriminators_verified':True,
                   'checks':[{'status':'UNKNOWN','name':'platform_pda'}]},
                 'pool':copy.deepcopy(pool),
                 'config':{'curve_type':'0','trade_fee_rate_ppm':'12500'},
                 'platform':{'platform_fee_rate_ppm':'0','creator_fee_rate_ppm':'0'},
                 'quote_vault':{'amount_atomic':'10000000000'},
                 'share_fee_assumption_ppm':'0'}}
    selected={'schema':'p3-asof-flow-research-selection-v1',
              'selected_using_future_quotes_or_S2':False,
              'trade_allowed':False,'original_strict_selection_unchanged':True,
              'decision_at_ms':1000,
              'selected':[{'mint':'Mint1','pool':'Pool1','decision_slot':101,
                           'universe_index':0,'trade_allowed':False}],
              'original_strict_selection':{'records':[{'universe_index':0,
                    'source_row':{'snapshot':s1,'snapshot_available_at_ms':900}}]}}
    return selected,s2


def go(selection,s2,**changes):
    params=dict(s2_available_at_ms=2000,exit_decision_at_ms=2001,
                budget_lamports=100000000,
                extra_cost_lower_lamports=5000,extra_cost_upper_lamports=30000)
    params.update(changes)
    return markout(selection,s2,**params)


def test_markout_is_conditional_not_profit_or_fills(case):
    sel,s2=case; original=copy.deepcopy((sel,s2))
    r=go(sel,s2)
    assert r['status']=='CONDITIONAL_BANK_MARKOUT'
    assert r['entry_slot']==101 and r['exit_slot']==102
    assert r['projected_entry_quantity_atomic']=='1000000000'
    assert r['S2_sell_proceeds_lamports']=='100010000'
    assert r['net_conditional_upper_lamports']=='5000'
    assert r['net_conditional_lower_lamports']=='-20000'
    assert r['net_market_pnl_sol'] is None and r['market_profitability_verified'] is False
    assert r['missing_self_entry_market_impact'] is True
    assert r['execution_verified'] is False
    assert (sel,s2)==original


@pytest.mark.parametrize('change',[
    {'s2_available_at_ms':999}, {'exit_decision_at_ms':1999},
    {'exit_decision_at_ms':8000}, {'budget_lamports':0},
    {'extra_cost_lower_lamports':40000}, {'extra_cost_upper_lamports':-1},
])
def test_inconsistent_clocks_or_costs_refused(case,change):
    sel,s2=case
    assert go(sel,s2,**change)['status']=='REFUSED'


def test_same_slot_not_future_evidence(case):
    sel,s2=case;s2['context_slot']=101
    assert go(sel,s2)['status']=='REFUSED'


def test_wrong_pool_or_mint_refused(case):
    sel,s2=case;s2['pool_address']='OtherPool'
    assert go(sel,s2)['status']=='REFUSED'


def test_safety_flags_and_supply_failure_not_ignored(case):
    sel,s2=case;s2['risk_flags']=['freeze_authority']
    assert go(sel,s2)['status']=='REFUSED'
    s2['risk_flags']=[]
    s2['facts']['supply_consistency']['matches']=False
    assert go(sel,s2)['status']=='REFUSED'


def test_exact_size_changes_quantity_and_result(case):
    sel,s2=case
    r=go(sel,s2,budget_lamports=1000000000)
    assert r['projected_entry_quantity_atomic']=='10000000000'
    assert r['S2_sell_proceeds_lamports']=='1000010000'
    assert r['net_market_pnl_sol'] is None


def test_changed_fee_terms_are_refused_not_used_for_markout(case):
    sel,s2=case
    s2['facts']['config']['trade_fee_rate_ppm']='25000'
    r=go(sel,s2)
    assert r['status']=='REFUSED'
    assert r['reasons']==['S2_fee_or_curve_config_changed']


def test_changed_immutable_pool_terms_are_refused(case):
    sel,s2=case
    s2['facts']['pool']['total_sell_a']='9999'
    assert go(sel,s2)['reasons']==['S2_pool_identity_or_terms_changed']
