"""Integration with real LaunchLab decoder and STRICT/RESEARCH selectors.

All accounts are synthetic. This test performs NO RPC, quote, wallet or ledger
operation, and makes no live profitability claim.
"""
from copy import deepcopy
import json
import pytest

from bot.p3 import certification, launchlab
from bot.p3.asof_flow_selection import select_predecision_flow
from bot.p3.asof_slot_markout import evaluate_asof_slot_markout
from bot.p3.cohort import select_cohort
from bot.p3.observed_activity import classify_predecision_reserve_change
from bot.p3.quotes import SOL_MINT
from test_p3_launchlab import mutate_account
from test_p3_research_integration import research_snapshot


def _advance_accounts(accounts, addresses, *, token_atomic, sol_lamports):
    """Construct a coherent *synthetic* second bank, not a recorded swap."""
    updated=deepcopy(accounts)
    pool=addresses['pool'];base=addresses['vault_a'];quote=addresses['vault_b']
    # Pool layout fixed by pinned LaunchLab IDL: real_a=53, real_b=61.
    current=launchlab._pool(updated[pool])[0]
    assert current['real_a']+token_atomic<current['total_sell_a']
    mutate_account(updated,pool,53,current['real_a']+token_atomic,'<Q')
    mutate_account(updated,pool,61,current['real_b']+sol_lamports,'<Q')
    # SPL token-account amount at offset 64.
    from bot.p3.launchlab import _vault
    base_amount=_vault(updated[base],'base_vault')[0]['amount_atomic']
    quote_amount=_vault(updated[quote],'quote_vault')[0]['amount_atomic']
    assert base_amount>token_atomic
    mutate_account(updated,base,64,base_amount-token_atomic,'<Q')
    mutate_account(updated,quote,64,quote_amount+sol_lamports,'<Q')
    updated[quote]['lamports']+=sol_lamports
    return updated


def _analysis(accounts,addresses,slot):
    return launchlab.analyze_snapshot(accounts,context_slot=slot,
        expected_mint=addresses['mint_a'],pool_address=addresses['pool'],
        input_lamports=100000000,evidence_profile='published_metadata_v1')


def test_redecoded_real_module_S0_S1_then_future_S2_markout():
    accounts,addresses,s0,screen=research_snapshot(return_accounts=True)
    assert s0['risk_flags']==[] and s0['facts']['supply_consistency']['matches']
    s1_accounts=_advance_accounts(accounts,addresses,token_atomic=1000000,sol_lamports=1000000)
    s1=_analysis(s1_accounts,addresses,s0['context_slot']+1)
    assert s1['risk_flags']==[]
    r=classify_predecision_reserve_change(s0,s1,
        before_available_at_ms=1000,after_available_at_ms=2000,decision_at_ms=2100)
    assert r['status']=='OBSERVED'
    assert r['signal']=='NET_BUY_COMPATIBLE_CHANGE'
    assert r['trade_allowed'] is False
    row={'mint':addresses['mint_a'],'pool':addresses['pool'],
         'quote_mint_claim':SOL_MINT,'creator_claim':s1['facts']['pool']['creator'],
         'snapshot':s1,'snapshot_available_at_ms':2000}
    strict=select_cohort([row],decision_at_ms=2100)
    assert strict['screened_prefix_count']==1
    result=select_predecision_flow(strict,
        {row['mint']:{'pool':row['pool'],'snapshot':s0,'available_at_ms':1000}})
    assert result['selected_count']==1
    assert result['selected'][0]['admission_lane']=='RESEARCH_ONLY'
    s2_accounts=_advance_accounts(s1_accounts,addresses,token_atomic=1000000,sol_lamports=1000000)
    s2=_analysis(s2_accounts,addresses,s1['context_slot']+1)
    marked=evaluate_asof_slot_markout(result,s2,s2_available_at_ms=3200,
        exit_decision_at_ms=3300,budget_lamports=100000000,
        extra_cost_lower_lamports=10000,extra_cost_upper_lamports=1000000)
    assert marked['status']=='CONDITIONAL_BANK_MARKOUT',marked
    assert marked['entry_slot']<marked['exit_slot']
    assert int(marked['net_conditional_lower_lamports']) <= int(marked['net_conditional_upper_lamports'])
    assert marked['economic_cycle_qualified'] is False
    assert marked['market_profitability_verified'] is False
    assert marked['net_market_pnl_sol'] is None


def test_decoder_unchanged_banks_do_not_select_static_liquidity():
    accounts,addresses,s0,_=research_snapshot(return_accounts=True)
    s1=_analysis(accounts,addresses,s0['context_slot']+1)
    assert classify_predecision_reserve_change(s0,s1,
        before_available_at_ms=1000,after_available_at_ms=2000,
        decision_at_ms=2100)['signal']=='NO_NET_RESERVE_CHANGE_OBSERVED'
    row={'mint':addresses['mint_a'],'pool':addresses['pool'],
         'quote_mint_claim':SOL_MINT,'creator_claim':s1['facts']['pool']['creator'],
         'snapshot':s1,'snapshot_available_at_ms':2000}
    strict=select_cohort([row],decision_at_ms=2100)
    chosen=select_predecision_flow(strict,
        {row['mint']:{'pool':row['pool'],'snapshot':s0,'available_at_ms':1000}})
    assert chosen['selected_count']==0
    assert chosen['assessments'][0]['reason']=='no_recent_net_buy_compatible_change'


def _selected_case():
    accounts,addresses,s0,_=research_snapshot(return_accounts=True)
    s1accounts=_advance_accounts(accounts,addresses,token_atomic=1000000,sol_lamports=1000000)
    s1=_analysis(s1accounts,addresses,s0['context_slot']+1)
    row=dict(mint=addresses['mint_a'],pool=addresses['pool'],quote_mint_claim=SOL_MINT,
        creator_claim=s1['facts']['pool']['creator'],snapshot=s1,snapshot_available_at_ms=16500)
    strict=select_cohort([row],decision_at_ms=17000)
    prior={row['mint']:dict(pool=row['pool'],snapshot=s0,available_at_ms=1000)}
    selection=select_predecision_flow(strict,prior)
    s2=_analysis(_advance_accounts(s1accounts,addresses,token_atomic=1000000,
        sol_lamports=1000000),addresses,s1['context_slot']+1)
    return selection,s1,s2,strict,prior


def test_real_network_delay_after_minimum15seconds_fits_registered_prior_window():
    selection,s1,s2,strict,prior=_selected_case()
    assert selection['selected_count']==1
    assert select_predecision_flow(strict,prior,max_observation_span_ms=15000)['selected_count']==0
    assert select_predecision_flow(strict,prior,max_observation_span_ms=30000)['selected_count']==1


def test_decoded_string_pool_uses_exact_integer_sale_and_each_own_entry_size():
    selection,s1,s2,_,_=_selected_case()
    before=deepcopy((selection,s1,s2))
    from bot.p3.cohort import classify_snapshot
    marks=[]
    for budget in (100000000,1000000000):
        result=evaluate_asof_slot_markout(selection,s2,s2_available_at_ms=33000,
            exit_decision_at_ms=33100,budget_lamports=budget,
            extra_cost_lower_lamports=10000,extra_cost_upper_lamports=1000000)
        assert result['status']=='CONDITIONAL_BANK_MARKOUT',result
        screen=classify_snapshot(s1,size_lamports=budget,available_at_ms=16500,
            decision_at_ms=17000,expected_mint=s1['mint'],expected_pool=s1['pool_address'])
        quantity=int(screen['own_entry_projection']['buy_output_atomic'])
        facts=s2['facts'];pool=dict(facts['pool'])
        for key in ('status','virtual_a','virtual_b','real_a','real_b','protocol_fee_accrued','platform_fee_accrued'):
            pool[key]=int(pool[key])
        direct=launchlab.observed_sell_projection(pool,input_token_atomic=quantity,
            fee_rates_ppm=(2500,10000,5000),quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
            curve_type=0,share_fee_rate_ppm=0)
        assert result['projected_entry_quantity_atomic']==str(quantity)
        assert result['S2_sell_proceeds_lamports']==direct['output_lamports']
        delta=int(direct['output_lamports'])-budget
        assert int(result['net_conditional_upper_lamports'])==delta-10000
        assert int(result['net_conditional_lower_lamports'])==delta-1000000
        assert result['economic_cycle_qualified'] is result['execution_verified'] is False
        json.dumps(result,allow_nan=False);marks.append(result)
    assert int(marks[1]['projected_entry_quantity_atomic'])!=10*int(marks[0]['projected_entry_quantity_atomic'])
    assert (selection,s1,s2)==before


@pytest.mark.parametrize('damage',[
    'fee','vault_link','vault_authority','supply','missing_identity','other_unknown',
    'bool_reserve','float_reserve','leading_zero_reserve','oversized_reserve','curve_change',
])
def test_actual_decoder_markout_refuses_changed_terms_or_noncanonical_atoms(damage):
    selection,s1,s2,_,_=_selected_case()
    facts=s2['facts']
    if damage=='fee':facts['config']['trade_fee_rate_ppm']='2501'
    elif damage=='vault_link':facts['pool']['vault_a']=facts['addresses']['vault_b']
    elif damage=='vault_authority':facts['base_vault']['authority']='different'
    elif damage=='supply':
        facts['pool']['supply']=str(int(facts['pool']['supply'])-1)
        facts['base_mint']['supply_atomic']=facts['pool']['supply']
    elif damage=='missing_identity':facts['identity_certification']['checks'].pop(0)
    elif damage=='other_unknown':facts['identity_certification']['checks'][0]['status']='UNKNOWN'
    elif damage=='curve_change':facts['pool']['virtual_a']=str(int(facts['pool']['virtual_a'])+1)
    else:facts['pool']['real_a']={'bool_reserve':True,'float_reserve':1.5,
        'leading_zero_reserve':'001','oversized_reserve':'9'*10000}[damage]
    marked=evaluate_asof_slot_markout(selection,s2,s2_available_at_ms=33000,
        exit_decision_at_ms=33100,budget_lamports=100000000,
        extra_cost_lower_lamports=10000,extra_cost_upper_lamports=1000000)
    assert marked['status']=='REFUSED'
    assert marked['economic_cycle_qualified'] is False


def test_later_full_exit_liquidity_refusal_preserves_known_projected_lot():
    selection,s1,s2,_,_=_selected_case()
    # An independently pinned future bank may have very little sold inventory;
    # it cannot quote a larger historical projected lot as a full liquidation.
    s2['facts']['pool']['real_a']='1'
    s2['facts']['pool']['real_b']='1'
    s2['facts']['base_vault']['amount_atomic']=str(int(s2['facts']['pool']['supply'])-1)
    marked=evaluate_asof_slot_markout(selection,s2,s2_available_at_ms=33000,
        exit_decision_at_ms=33100,budget_lamports=100000000,
        extra_cost_lower_lamports=10000,extra_cost_upper_lamports=1000000)
    assert marked['status']=='REFUSED'
    assert marked['reasons']==['S2_curve_model_refused:sell_exceeds_observed_outstanding_curve_tokens']
    assert int(marked['projected_entry_quantity_atomic'])>1
    assert marked['modeled_unliquidated_quantity_atomic']==marked['projected_entry_quantity_atomic']
    assert marked['modeled_sold_quantity_atomic']=='0' and marked['inventory_acquired'] is False


@pytest.mark.parametrize('share', ['100',True,1.0,'001',str(2**64)])
def test_share_fee_hypothesis_cannot_change_or_coerce_between_entry_and_exit(share):
    selection,s1,s2,_,_=_selected_case()
    assert s1['facts']['share_fee_assumption_ppm']=='0'
    s2['facts']['share_fee_assumption_ppm']=share
    marked=evaluate_asof_slot_markout(selection,s2,s2_available_at_ms=33000,
        exit_decision_at_ms=33100,budget_lamports=100000000,
        extra_cost_lower_lamports=10000,extra_cost_upper_lamports=1000000)
    assert marked['status']=='REFUSED'
    assert marked['modeled_sold_quantity_atomic']=='0'
    assert marked['modeled_unliquidated_quantity_atomic']==marked['projected_entry_quantity_atomic']
    assert marked['economic_cycle_qualified'] is False


@pytest.mark.parametrize('phase', ['S1','S2'])
def test_share_fee_is_bounded_by_the_configured_maximum_in_both_banks(phase):
    from bot.p3.observed_activity import snapshot_safety_reason
    selection,s1,s2,_,_=_selected_case()
    state=s1 if phase=='S1' else s2
    maximum=int(state['facts']['config']['max_share_fee_rate_ppm'])
    state['facts']['share_fee_assumption_ppm']=str(maximum+1)
    assert snapshot_safety_reason(state)=='share_fee_exceeds_configured_maximum'


def test_share_fee_configured_maximum_change_is_not_silently_accepted():
    selection,s1,s2,_,_=_selected_case()
    s2['facts']['config']['max_share_fee_rate_ppm']=str(
        int(s2['facts']['config']['max_share_fee_rate_ppm'])+1)
    marked=evaluate_asof_slot_markout(selection,s2,s2_available_at_ms=33000,
        exit_decision_at_ms=33100,budget_lamports=100000000,
        extra_cost_lower_lamports=10000,extra_cost_upper_lamports=1000000)
    assert marked['status']=='REFUSED'
    assert marked['reasons']==['S1_S2_terms_or_safety_unqualified:curve_or_fee_configuration_changed']


def test_pinned_buy_arithmetic_increases_outstanding_tokens_and_decreases_base_vault():
    accounts,addresses,s0,_=research_snapshot(return_accounts=True)
    pool=launchlab._pool(accounts[addresses['pool']])[0]
    base=launchlab._vault(accounts[addresses['vault_a']],'base_vault')[0]['amount_atomic']
    quote=launchlab._vault(accounts[addresses['vault_b']],'quote_vault')[0]['amount_atomic']
    projection=launchlab.constant_product_projection(pool,input_lamports=1000000,
        fee_rates_ppm=(2500,10000,5000),base_vault_atomic=base,quote_vault_lamports=quote)
    bought=int(projection['buy_output_atomic']);effective=int(projection['buy_effective_input_lamports'])
    changed=_advance_accounts(accounts,addresses,token_atomic=bought,sol_lamports=effective)
    s1=_analysis(changed,addresses,s0['context_slot']+1)
    result=classify_predecision_reserve_change(s0,s1,before_available_at_ms=1000,
        after_available_at_ms=2000,decision_at_ms=2100)
    assert result['status']=='OBSERVED' and result['candidate_recent_net_buy_change']
    assert int(result['observed_net_deltas']['real_a_atomic'])==bought
    assert int(result['observed_net_deltas']['base_vault_atomic'])==-bought
