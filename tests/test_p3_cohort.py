"""Fixed activity screen keeps failures and the entire instrumental universe."""
from copy import deepcopy

import pytest

from bot.p3.cohort import CRITERIA, classify_snapshot, select_cohort
from bot.p3.quotes import SOL_MINT
from test_p3_launchlab import fixture, analyze, encode


def snapshot(index=0,*,active=True,identity=True):
    accounts,addresses=fixture()
    result=analyze(accounts,addresses)
    # The pure selector consumes prior validated analysis; this fixture supplies
    # an explicit synthetic upstream identity attestation, never a market proof.
    mint=encode(bytes([20+index])*32);pool=encode(bytes([80+index])*32)
    result['mint']=mint;result['pool_address']=pool
    result['facts']['addresses'].update(mint_a=mint,pool=pool)
    result['facts']['pool']['mint_a']=mint
    result['evidence_profile']='published_metadata_v1'
    result['facts']['identity_certification']={
        'program_derived_addresses_verified':identity,'account_discriminators_verified':True}
    result['facts']['supply_consistency']={'matches':True}
    result['facts']['share_fee_assumption_ppm']='0'
    if not active:
        result['facts']['pool'].update(real_a='0',real_b='0')
    return result


def row(index,**options):
    analysis=snapshot(index,**options)
    return {'mint':analysis['mint'],'pool':analysis['pool_address'],
        'quote_mint_claim':SOL_MINT,'creator_claim':'synthetic_creator',
        'snapshot':analysis,'snapshot_available_at_ms':1000}


def screen(analysis,**options):
    return classify_snapshot(analysis,available_at_ms=1000,decision_at_ms=1000,**options)


def test_no_circulation_is_cohort_exclusion_but_own_entry_exit_remains_conditional():
    original=snapshot(active=False);before=deepcopy(original)
    result=screen(original)
    assert result['activity_state']=='no_observed_circulation'
    assert result['screen_eligible'] is False
    assert result['own_entry_projection']['sell_output_lamports'] is not None
    assert result['observed_full_exit_capacity'] is False
    assert result['economic_cycle_qualified'] is result['execution_verified'] is False
    assert original==before


def test_active_bank_full_expected_size_capacity_is_measured_not_projected_fill():
    result=screen(snapshot())
    assert result['screen_eligible'] is True
    assert result['observed_full_exit_capacity'] is True
    assert result['own_entry_projection']['buy_output_atomic']==result['observed_exit_projection']['input_token_atomic']
    assert result['positions_acquired']==0 and result['source_age_verified'] is False


def test_unknown_platform_identity_is_retained_with_reasons_and_not_selected():
    result=screen(snapshot(identity=False))
    assert result['screen_eligible'] is False
    assert result['observed_full_exit_capacity'] is True
    assert result['own_entry_projection'] is not None
    assert result['selection_reasons']==['identity_supply_or_permissions_unqualified']


@pytest.mark.parametrize('damage',['future','stale','missing'])
def test_snapshot_availability_guards_prevent_future_or_stale_decisions(damage):
    at={'future':1001,'stale':0,'missing':None}[damage]
    result=classify_snapshot(snapshot(),available_at_ms=at,decision_at_ms=6000 if damage=='stale' else 1000)
    assert result['screen_eligible'] is False and result['own_entry_projection'] is None


def test_same_bank_identity_mint_and_curve_boundaries_cannot_be_relabelled():
    analysis=snapshot();analysis['facts']['pool']['mint_a']=SOL_MINT
    assert 'decoded_snapshot_identity_relations_inconsistent' in screen(analysis)['selection_reasons']
    analysis=snapshot();analysis['facts']['pool']['status']='1'
    assert screen(analysis)['screen_eligible'] is False
    analysis=snapshot();analysis['facts']['config']['curve_type']='1'
    assert screen(analysis)['own_entry_projection'] is None


def test_all_universe_rows_failures_duplicates_and_not_reached_prefix_remain():
    universe=[row(i,active=i not in (0,3)) for i in range(9)]
    universe.insert(1,deepcopy(universe[0]))
    source=deepcopy(universe)
    result=select_cohort(universe,decision_at_ms=1000)
    assert result['universe_size']==len(result['records'])==10
    assert result['screened_prefix_count']==6 and result['selected_count']==2
    assert [item['universe_index'] for item in result['selected']]==[2,3]
    assert result['records'][0]['screen']['activity_state']=='no_observed_circulation'
    assert result['records'][1]['selection_reason']=='duplicate_mint_or_pool'
    assert result['records'][-1]['selection_reason']=='outside_fixed_screen_prefix'
    assert [item['source_row'] for item in result['records']]==source
    assert universe==source


def test_other_quote_row_cannot_consume_native_sol_prefix_and_outcomes_do_not_select():
    first=row(0);outside=deepcopy(first);outside['quote_mint_claim']='other_currency'
    universe=[outside,first,row(1),row(2)]
    before=select_cohort(universe,decision_at_ms=1000)
    for item in universe:item['future_sell_pnl_sol']=-100000000
    after=select_cohort(universe,decision_at_ms=1000)
    assert before['selected']==after['selected']
    assert before['records'][0]['selection_reason']=='invalid_or_outside_native_SOL_scope'
    assert before['selected'][0]['universe_index']==1


def test_observed_activity_without_capacity_is_preserved_and_not_replaced_beyond_six():
    universe=[row(i) for i in range(7)]
    for item in universe[:6]:item['snapshot']['facts']['pool']['real_a']='1'
    result=select_cohort(universe,decision_at_ms=1000)
    assert result['selected_count']==0 and result['universe_size']==7
    assert result['records'][-1]['selection_reason']=='outside_fixed_screen_prefix'
    assert all(not item['screen']['observed_full_exit_capacity'] for item in result['records'][:6])


def test_three_008_like_zero_circulation_banks_keep_denominator_without_network():
    universe=[row(i,active=False,identity=i!=1) for i in range(3)]
    result=select_cohort(universe,decision_at_ms=1000)
    assert result['universe_size']==result['screened_prefix_count']==3
    assert result['selected_count']==result['qualified_economic_cycles']==0
    assert result['market_collection_executed'] is False
    assert len(result['records'])==3


def test_global_prepared_budget_includes_all_sources_and_has_no_execution_entrypoint():
    assert sum(CRITERIA['request_budget'].values())==CRITERIA['max_requests']==20
    assert CRITERIA['max_elapsed_ms']==60000
    assert CRITERIA['status']=='PREPARED_NOT_EXECUTED'
    with pytest.raises(ValueError):select_cohort([{}]*101,decision_at_ms=1000)
