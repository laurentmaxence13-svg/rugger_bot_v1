"""P3-012 preregisterable widened 12-pool PRE-DECISION observation selector.

The existing STRICT six-prefix cohort and its output remain untouched. This
new, read-only research selector evaluates 12 unique native-SOL pool rows from
the same retained 100-row universe, using S0 and S1 known before decision.
All later rows and outcomes remain part of the denominator. Zero S0->S1 net
movement is NOT a buy signal. No wallet or transaction code is imported.
"""
from copy import deepcopy

from bot.p3.observed_activity import classify_predecision_reserve_change


def select_twelve_prefix_asof_research(universe, prior_by_mint, *, decision_at_ms,
                                       screen_prefix=12, max_candidates=2,
                                       max_prior_age_ms=30000):
    from bot.p3.cohort import select_cohort,classify_snapshot,CRITERIA
    from bot.p3.research_gate import assess_research_only
    from bot.p3.quotes import SOL_MINT,_mint

    if (type(universe) is not list or not 0 < len(universe) <= 100
            or type(prior_by_mint) is not dict
            or type(decision_at_ms) is not int or decision_at_ms < 0
            or type(screen_prefix) is not int or not 1 <= screen_prefix <= 12
            or type(max_candidates) is not int or not 1 <= max_candidates <= 2
            or type(max_prior_age_ms) is not int or not 0 < max_prior_age_ms <= 60000):
        raise ValueError('P3_012_universe_or_preregistered_budget_invalid')
    strict=select_cohort(universe,decision_at_ms=decision_at_ms)
    selected=[];records=[];seen_mints=set();seen_pools=set();screened=0
    for index,row in enumerate(universe):
        if type(row) is not dict:
            raise ValueError('P3_012_explicit_discovery_records_required')
        record=dict(universe_index=index,mint=row.get('mint'),pool=row.get('pool'),
                    selected=False,reason=None,flow=None,admission_lane=None)
        try:
            mint=_mint(row.get('mint'));pool=_mint(row.get('pool'))
            valid=mint!=SOL_MINT and row.get('quote_mint_claim')==SOL_MINT
        except (TypeError,ValueError):
            valid=False
        if not valid:
            record['reason']='invalid_or_outside_native_SOL_scope'
        elif mint in seen_mints or pool in seen_pools:
            record['reason']='duplicate_mint_or_pool'
        else:
            seen_mints.add(mint);seen_pools.add(pool)
            if screened>=screen_prefix:
                record['reason']='outside_fixed_twelve_prefix'
            else:
                screened+=1
                screen=classify_snapshot(row.get('snapshot'),
                    size_lamports=CRITERIA['research_input_lamports'],
                    available_at_ms=row.get('snapshot_available_at_ms'),
                    decision_at_ms=decision_at_ms,
                    expected_mint=mint,expected_pool=pool)
                strict_pass=screen.get('screen_eligible') is True
                research_pass=assess_research_only(row.get('snapshot'),screen).get('research_only') is True
                record['admission_lane']='STRICT_OBSERVATION' if strict_pass else (
                    'RESEARCH_ONLY' if research_pass else 'REFUSED')
                if not (strict_pass or research_pass):
                    record['reason']='identity_or_capacity_unqualified_at_S1'
                else:
                    before=prior_by_mint.get(mint)
                    if (type(before) is not dict or before.get('pool')!=pool
                            or type(before.get('available_at_ms')) is not int
                            or type(row.get('snapshot_available_at_ms')) is not int
                            or not 0 <= decision_at_ms-before['available_at_ms'] <= max_prior_age_ms):
                        record['reason']='S0_missing_or_outside_published_predecision_window'
                    else:
                        flow=classify_predecision_reserve_change(
                            before.get('snapshot'),row.get('snapshot'),
                            before_available_at_ms=before['available_at_ms'],
                            after_available_at_ms=row['snapshot_available_at_ms'],
                            decision_at_ms=decision_at_ms)
                        record['flow']=flow
                        if flow.get('status')!='OBSERVED':
                            record['reason']='invalid_S0_S1_flow:'+str(flow.get('reason'))
                        elif not flow.get('candidate_recent_net_buy_change'):
                            record['reason']='no_predecision_net_buy_compatible_change'
                        elif len(selected)>=max_candidates:
                            record['reason']='beyond_published_candidate_count'
                        else:
                            record['reason']='selected_before_any_S2_or_quote'
                            record['selected']=True
                            selected.append(dict(universe_index=index,ordinal=len(selected),
                                mint=mint,pool=pool,creator_claim=row.get('creator_claim'),
                                before_slot=flow['observed_before_slot'],
                                decision_slot=flow['observed_after_slot'],
                                admission_lane=record['admission_lane'],trade_allowed=False,
                                size_lamports=str(CRITERIA['research_input_lamports'])))
        records.append(record)
    # Preserve the ORIGINAL unchanged strict selector and full universe for
    # subsequent S2 markout; no retroactive selection, no winning-only filter.
    return dict(schema='p3-asof-flow-research-selection-v1',protocol='P3-012',
        decision_at_ms=decision_at_ms,universe_size=len(records),
        fixed_screen_prefix=screen_prefix,screened_valid_pool_count=screened,
        selected_count=len(selected),selected=selected,assessments=records,
        original_strict_selection=deepcopy(strict),
        original_strict_selection_unchanged=True,
        original_denominator_retained=True,selected_using_future_quotes_or_S2=False,
        net_change_is_not_independent_swap_evidence=True,
        trade_allowed=False,qualified_economic_cycles=0,
        market_profitability_verified=False)
