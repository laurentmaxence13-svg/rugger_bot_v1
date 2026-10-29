"""Integration with real LaunchLab decoder and STRICT/RESEARCH selectors.

All accounts are synthetic. This test performs NO RPC, quote, wallet or ledger
operation, and makes no live profitability claim.
"""
from copy import deepcopy

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
    assert current['real_a']>token_atomic
    mutate_account(updated,pool,53,current['real_a']-token_atomic,'<Q')
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
