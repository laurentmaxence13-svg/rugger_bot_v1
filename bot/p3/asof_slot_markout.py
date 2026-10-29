"""Causal PAPER markouts across observed bank slots (not executed trades).

Given S1 known at entry and S2 acquired later, price the precise projected
S1 entry inventory using S2's observed constant-product reserves. The output
is NOT a self-impact-corrected counterfactual; an actual S1 buy would have
changed reserves and potentially subsequent market behavior. Never classify
these markouts as fills, strict P3 economic cycles or verified market PnL.
"""


def evaluate_asof_slot_markout(flow_selection, s2, *,
                                s2_available_at_ms, exit_decision_at_ms,
                                budget_lamports, extra_cost_lower_lamports,
                                extra_cost_upper_lamports):
    """Return exact-lamport conditional interval, or fail closed.

    The S1 analysis and receipt clock are recovered from the frozen selection,
    not supplied ad hoc. No future quote can select the original entry.
    """
    result = dict(schema='p3-asof-bank-markout-v1',status='REFUSED',reasons=[],
                  valuation_basis='S1_projected_buy_versus_S2_observed_reserve_sell',
                  missing_self_entry_market_impact=True,
                  economic_cycle_qualified=False,trade_allowed=False,
                  execution_verified=False,strict_identity_verified=False,
                  net_market_pnl_sol=None,market_profitability_verified=False,
                  independent_market_edge_verified=False,
                  extra_cost_basis='explicit_hypothetical_range_not_execution_evidence')

    def refuse(why):
        return {**result,'reasons':[why]}

    if (type(flow_selection) is not dict
            or flow_selection.get('schema')!='p3-asof-flow-research-selection-v1'
            or flow_selection.get('selected_using_future_quotes_or_S2') is not False
            or flow_selection.get('trade_allowed') is not False
            or flow_selection.get('original_strict_selection_unchanged') is not True):
        return refuse('frozen_asof_research_selection_required')
    if (type(s2) is not dict
            or any(type(v) is not int for v in
                   (s2_available_at_ms,exit_decision_at_ms,budget_lamports,
                    extra_cost_lower_lamports,extra_cost_upper_lamports))
            or not 0 < budget_lamports < 2**64
            or not 0 <= extra_cost_lower_lamports <= extra_cost_upper_lamports < 2**64):
        return refuse('invalid_economic_inputs')
    entry_ms=flow_selection.get('decision_at_ms')
    if (type(entry_ms) is not int
            or not entry_ms < s2_available_at_ms <= exit_decision_at_ms
            or exit_decision_at_ms-s2_available_at_ms > 5000):
        return refuse('S2_unavailable_or_stale_at_exit')
    selected=flow_selection.get('selected')
    if type(selected) is not list:
        return refuse('missing_preadmitted_flow_candidates')
    matching=[p for p in selected if type(p) is dict
              and p.get('mint')==s2.get('mint')
              and p.get('pool')==s2.get('pool_address')]
    if len(matching)!=1:
        return refuse('S2_not_selected_before_outcome')
    choice=matching[0]
    if choice.get('trade_allowed') is not False:
        return refuse('research_selection_unexpectedly_tradable')
    strict=flow_selection.get('original_strict_selection')
    rows=strict.get('records') if type(strict) is dict else None
    if type(rows) is not list:
        return refuse('original_S1_snapshot_not_retained')
    original=[r['source_row'] for r in rows if type(r) is dict
              and r.get('universe_index')==choice.get('universe_index')
              and type(r.get('source_row')) is dict]
    if len(original)!=1:
        return refuse('original_S1_record_missing_or_duplicate')
    s1=original[0].get('snapshot');s1_available=original[0].get('snapshot_available_at_ms')
    if (type(s1) is not dict or type(s1_available) is not int
            or not 0 <= s1_available <= entry_ms
            or s1.get('mint')!=s2.get('mint') or s1.get('pool_address')!=s2.get('pool_address')
            or s1.get('context_slot')!=choice.get('decision_slot')
            or type(s2.get('context_slot')) is not int
            or s2['context_slot']<=s1['context_slot']):
        return refuse('S1_S2_identity_slot_or_temporal_link_invalid')
    if (s2.get('evidence_profile') != 'published_metadata_v1'
            or s2.get('risk_flags') != []):
        return refuse('S2_pin_or_safety_not_verified')
    from bot.p3.cohort import classify_snapshot
    from bot.p3.launchlab import observed_sell_projection,SnapshotEvidenceError
    try:
        screen=classify_snapshot(s1,size_lamports=budget_lamports,
            available_at_ms=s1_available,decision_at_ms=entry_ms,
            expected_mint=choice['mint'],expected_pool=choice['pool'])
        entry=screen.get('own_entry_projection')
        if type(entry) is not dict or screen.get('observed_full_exit_capacity') is not True:
            return refuse('S1_projected_exact_entry_unavailable')
        facts=s2['facts']
        if (facts.get('account_context_basis')!='caller_supplied_single_getMultipleAccounts_response'
                or facts['supply_consistency'].get('matches') is not True
                or facts['identity_certification'].get('account_discriminators_verified') is not True
                or any(check.get('status')=='FAIL' for check in facts['identity_certification']['checks'])):
            return refuse('S2_identity_supply_or_safety_unqualified')
        if (facts['pool'].get('mint_a')!=choice['mint']
                or facts['pool'].get('mint_b')!='So11111111111111111111111111111111111111112'
                or int(facts['pool']['status'])!=0
                or int(facts['config']['curve_type'])!=0):
            return refuse('S2_pool_scope_different_or_inactive')
        # Parsed LaunchLab `facts` serializes every integer as a decimal
        # string; observed_sell_projection requires native unsigned integers.
        # Reuse the pinned cohort validator rather than reimplementing parsing.
        from bot.p3.cohort import _uint
        initial_facts = s1['facts']
        immutable = ('mint_a', 'mint_b', 'supply', 'total_sell_a',
                     'total_fundraising_b')
        if any(initial_facts['pool'].get(key) != facts['pool'].get(key)
               for key in immutable):
            return refuse('S2_pool_identity_or_terms_changed')
        for role, keys in (
                ('config', ('curve_type', 'trade_fee_rate_ppm')),
                ('platform', ('platform_fee_rate_ppm', 'creator_fee_rate_ppm'))):
            if any(initial_facts[role].get(k) != facts[role].get(k)
                   for k in keys):
                return refuse('S2_fee_or_curve_config_changed')
        if (initial_facts.get('share_fee_assumption_ppm')
                != facts.get('share_fee_assumption_ppm')):
            return refuse('S2_share_fee_assumption_changed')
        rate=tuple(_uint(facts[role][key]) for role,key in (
            ('config','trade_fee_rate_ppm'),
            ('platform','platform_fee_rate_ppm'),
            ('platform','creator_fee_rate_ppm')))
        share=_uint(facts['share_fee_assumption_ppm'])
        exact_pool=dict(facts['pool'])
        for key in ('virtual_a', 'virtual_b', 'real_a', 'real_b',
                    'protocol_fee_accrued', 'platform_fee_accrued', 'status'):
            exact_pool[key]=_uint(facts['pool'][key])
        quantity=_uint(entry['buy_output_atomic'],positive=True)
        sale=observed_sell_projection(exact_pool,input_token_atomic=quantity,
            fee_rates_ppm=rate,
            quote_vault_lamports=_uint(facts['quote_vault']['amount_atomic']),
            curve_type=_uint(facts['config']['curve_type']),
            share_fee_rate_ppm=share)
        received=int(sale['output_lamports'])
        if quantity<=0 or received<0 or received>=2**64:
            return refuse('invalid_S2_full_exit_projection')
    except (KeyError,TypeError,ValueError,OverflowError,SnapshotEvidenceError):
        return refuse('invalid_or_unqualified_observed_bank_model')
    conditional_drag=received-budget_lamports
    return {**result,'status':'CONDITIONAL_BANK_MARKOUT',
            'reasons':[], 'mint':choice['mint'], 'pool':choice['pool'],
            'entry_slot':s1['context_slot'],'exit_slot':s2['context_slot'],
            'S1_decision_at_ms':entry_ms,'S2_available_at_ms':s2_available_at_ms,
            'entry_budget_lamports':str(budget_lamports),
            'projected_entry_quantity_atomic':str(quantity),
            'S2_sell_proceeds_lamports':str(received),
            'gross_conditional_markout_lamports':str(conditional_drag),
            'net_conditional_upper_lamports':str(conditional_drag-extra_cost_lower_lamports),
            'net_conditional_lower_lamports':str(conditional_drag-extra_cost_upper_lamports),
            'extra_cost_lower_lamports':str(extra_cost_lower_lamports),
            'extra_cost_upper_lamports':str(extra_cost_upper_lamports),
            'S2_has_no_provider_quote_source_clock':True,
            'exit_modeled_against_actual_S2_bank_not_self_impact_adjusted':True,
            'cost_range_is_not_proven_real_executability':True}
