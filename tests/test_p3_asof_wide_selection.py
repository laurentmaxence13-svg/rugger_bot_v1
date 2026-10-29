"""Expanded as-of selection with the actual pinned parser and original STRICT selector.

The eight pools are synthetic decoded bank states, not live transactions.
Preselection was fixed before any hypothetical S2 outcome was calculated.
"""
from bot.p3.asof_wide_selection import select_twelve_prefix_asof_research
from bot.p3.cohort import select_cohort
from bot.p3.quotes import SOL_MINT
from test_p3_research_integration import research_snapshot
from test_p3_asof_real_decoder_integration import _advance_accounts,_analysis


def _universe():
    rows=[];previous={}
    for i in range(8):
        accounts,addresses,s0,_=research_snapshot(index=i,return_accounts=True)
        # First six intentionally have no net activity between S0 and S1.
        changed=_advance_accounts(accounts,addresses,token_atomic=1000000,
                                  sol_lamports=1000000) if i>=6 else accounts
        s1=_analysis(changed,addresses,s0['context_slot']+1)
        row=dict(mint=addresses['mint_a'],pool=addresses['pool'],
                 quote_mint_claim=SOL_MINT,creator_claim=s1['facts']['pool']['creator'],
                 snapshot=s1,snapshot_available_at_ms=2000)
        rows.append(row)
        previous[row['mint']]=dict(pool=row['pool'],snapshot=s0,
                                    available_at_ms=1000)
    return rows,previous


def test_widened_research_find_two_predecision_movers_after_six_static_pools():
    universe,previous=_universe()
    strict=select_cohort(universe,decision_at_ms=2100)
    assert strict['screened_prefix_count']==6
    assert strict['selected_count']==0
    result=select_twelve_prefix_asof_research(universe,previous,decision_at_ms=2100)
    assert result['universe_size']==8
    assert result['screened_valid_pool_count']==8
    assert result['selected_count']==2
    assert [x['universe_index'] for x in result['selected']]==[6,7]
    assert all(x['reason']=='no_predecision_net_buy_compatible_change'
               for x in result['assessments'][:6])
    assert result['original_strict_selection']==strict
    assert result['original_strict_selection_unchanged']
    assert not result['trade_allowed']


def test_widened_selection_keeps_static_pool_denominator_and_no_lookahead():
    universe,previous=_universe()
    first=select_twelve_prefix_asof_research(universe,previous,decision_at_ms=2100,
                                            screen_prefix=6)
    assert first['selected_count']==0
    assert first['universe_size']==8
    assert first['assessments'][6]['reason']=='outside_fixed_twelve_prefix'
    assert not first['selected_using_future_quotes_or_S2']
