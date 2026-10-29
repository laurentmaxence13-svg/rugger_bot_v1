"""Read-only selection of research pools using reserve changes known BEFORE decision.

The strict 100-row denominator is conserved. S0 and S1 are both available before
any quote or S2 outcome. This is not admission to trade or evidence of an actual
buyer or realized profitability. Only use under a newly published protocol.
"""
from copy import deepcopy

from bot.p3.observed_activity import classify_predecision_reserve_change


def select_predecision_flow(strict_selection, previous_by_mint, *, max_observation_span_ms=45000):
    """Choose at most the fixed cohort size using S0->S1, never S2.

    The caller must verify the original event journal and source provenance.
    This function recomputes the exact pre-existing STRICT selection but does
    not alter it. The source cohort comes from S1 before any quote outcomes.
    """
    from bot.p3.cohort import CRITERIA, select_cohort
    from bot.p3.research_gate import assess_research_only

    if type(strict_selection) is not dict or type(previous_by_mint) is not dict:
        raise ValueError('strict_selection_and_prior_snapshots_required')
    if (strict_selection.get('schema') != 'p3-active-cohort-selection-v1'
            or strict_selection.get('selection_uses_provider_outcomes') is not False
            or strict_selection.get('market_collection_executed') is not False
            or type(strict_selection.get('decision_at_ms')) is not int):
        raise ValueError('original_prospective_selection_required')
    original_records = strict_selection.get('records')
    if type(original_records) is not list or not 0 < len(original_records) <= CRITERIA['max_universe_rows']:
        raise ValueError('complete_frozen_universe_required')
    if any(type(r) is not dict or type(r.get('source_row')) is not dict for r in original_records):
        raise ValueError('source_rows_missing')
    universe = [r['source_row'] for r in original_records]
    rebuilt = select_cohort(universe, decision_at_ms=strict_selection['decision_at_ms'])
    if strict_selection != rebuilt:
        raise ValueError('original_strict_selection_mismatch')
    if (type(max_observation_span_ms) is not int
            or not 0 < max_observation_span_ms <= 60000):
        raise ValueError('invalid_registered_predecision_span')
    selected, assessments = [], []
    decision = strict_selection['decision_at_ms']
    for item in original_records:
        row, screen = item['source_row'], item['screen']
        mint, pool = row.get('mint'), row.get('pool')
        record = dict(universe_index=item['universe_index'], mint=mint, pool=pool,
                      original_reason=item['selection_reason'],
                      decision_at_ms=decision, flow=None, research_status=None,
                      selected=False, reason=None)
        if screen is None:
            record['reason'] = 'outside_original_fixed_screen_or_invalid'
        else:
            verdict = assess_research_only(row.get('snapshot'), screen)
            strict_ok = screen.get('screen_eligible') is True
            research_ok = verdict.get('research_only') is True
            record['research_status'] = ('STRICT_OBSERVATION' if strict_ok else
                                         'RESEARCH_ONLY' if research_ok else 'REFUSED')
            if not (strict_ok or research_ok):
                record['reason'] = 'not_research_eligible_at_S1'
            else:
                prior = previous_by_mint.get(mint)
                if (type(prior) is not dict or prior.get('pool') != pool
                        or type(prior.get('available_at_ms')) is not int
                        or type(row.get('snapshot_available_at_ms')) is not int):
                    record['reason'] = 'same_pool_prior_evidence_missing'
                elif not (0 <= decision-prior['available_at_ms'] <= max_observation_span_ms):
                    record['reason'] = 'predecision_window_too_old_or_future'
                else:
                    flow = classify_predecision_reserve_change(
                        prior.get('snapshot'), row.get('snapshot'),
                        before_available_at_ms=prior['available_at_ms'],
                        after_available_at_ms=row['snapshot_available_at_ms'],
                        decision_at_ms=decision)
                    record['flow'] = flow
                    if flow['status'] != 'OBSERVED':
                        record['reason'] = 'predecision_flow_unqualified:' + flow['reason']
                    elif not flow['candidate_recent_net_buy_change']:
                        record['reason'] = 'no_recent_net_buy_compatible_change'
                    elif len(selected) >= CRITERIA['target_candidates']:
                        record['reason'] = 'outside_fixed_selected_count'
                    else:
                        record['selected'] = True
                        record['reason'] = 'selected_before_provider_and_S2_results'
                        selected.append(dict(ordinal=len(selected),
                                             universe_index=item['universe_index'],
                                             mint=mint, pool=pool,
                                             creator_claim=row.get('creator_claim'),
                                             admission_lane=record['research_status'],
                                             before_slot=flow['observed_before_slot'],
                                             decision_slot=flow['observed_after_slot'],
                                             size_lamports=str(CRITERIA['research_input_lamports']),
                                             trade_allowed=False))
        assessments.append(record)
    return dict(schema='p3-asof-flow-research-selection-v1',
                scope='development_paper_only_not_trade_or_strict_cycle',
                decision_at_ms=decision, universe_size=len(assessments),
                selected_count=len(selected), selected=selected,
                assessments=assessments,
                original_strict_selection=deepcopy(strict_selection),
                original_strict_selection_unchanged=True,
                original_denominator_retained=True,
                selected_using_future_quotes_or_S2=False,
                net_change_is_not_independent_swap_evidence=True,
                trade_allowed=False, qualified_economic_cycles=0,
                market_profitability_verified=False)
