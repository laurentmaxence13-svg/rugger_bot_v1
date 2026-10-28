"""Offline position-size research on anchored, historically available banks.

Observed bytes, conditional models, indicative service quotes and executions
retain separate identities. This adapter never creates a fill or PAPER credit.
"""
from copy import deepcopy

from bot.p3.launchlab import analyze_snapshot, _pool


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def frames_from_events(events, *, run_id, expected_tail, integrity_verified):
    """Adapt a verified portable capture; verify every candidate-bank linkage.

    The caller verifies the archive against its independently retained index.
    Repeated banks stay repeated observations of the same mint, not trials.
    """
    _require(integrity_verified is True and events and events[-1]['record_hash']==expected_tail,
             'Verified retained evidence anchor required')
    by_id={event['id']:event for event in events}
    _require(len(by_id)==len(events),'Duplicate evidence identity')
    frames=[]
    for event in events:
        if event['kind']!='candidate_decision' or 'analysis' not in event['payload']:
            continue
        report=event['payload']['analysis']
        snapshot=by_id.get(event['payload'].get('snapshot_observation_id'))
        _require(snapshot is not None and snapshot['kind']=='pool_snapshot'
            and snapshot['mint']==event['mint'] and snapshot['outcome']=='observed'
            and snapshot['id']<event['id'] and snapshot['available_at_ms']<=event['available_at_ms'],
            'Analysis is not linked to an earlier available bank')
        payload=snapshot['payload'];raw=payload['raw_rpc_result']
        keys=payload['requested_addresses'];addresses=payload['addresses']
        _require(type(raw) is dict and type(raw.get('context')) is dict
            and raw['context'].get('slot')==snapshot['source_slot']==event['source_slot']
            and type(keys) is list and len(keys)==len(set(keys))==len(addresses)==7
            and set(keys)==set(addresses.values()) and len(raw['value'])==len(keys),
            'Bank address order or source context is inconsistent')
        accounts=dict(zip(keys,raw['value']))
        group_id=payload.get('source_group_observation_id')
        if group_id is not None:
            group=by_id.get(group_id)
            _require(group is not None and group['id']<snapshot['id']
                and group['available_at_ms']<=snapshot['available_at_ms'],
                'Grouped bank was unavailable before its subset')
            gp=group['payload'];bank=gp['raw_rpc_result'];ordered=gp['requested_addresses']
            _require(group['kind']=='pool_snapshot' and gp.get('purpose')=='prospective_grouped_bank'
                and group['source_slot']==snapshot['source_slot']
                and bank['context']==raw['context'] and len(ordered)==len(set(ordered))==len(bank['value']),
                'Grouped bank identity or context is inconsistent')
            full=dict(zip(ordered,bank['value']))
            _require(all(key in full and accounts[key]==full[key] for key in keys),
                'Subset account bytes differ from the grouped bank')
        # Decode the unchanged raw facts, rather than accepting numeric fields
        # detached from their source bank. Keep unknown platform evidence.
        replay=analyze_snapshot(accounts,context_slot=snapshot['source_slot'],
            expected_mint=event['mint'],pool_address=addresses['pool'],
            input_lamports=int((report.get('conditional_projection') or {}).get('buy_input_lamports','1000000000')),
            evidence_profile=payload['evidence_profile'])
        _require(replay==report,'Retained bank analysis does not reproduce')
        facts=report['facts'];pool,_=_pool(accounts[addresses['pool']])
        identity=facts.get('identity_certification',{})
        frame_id=run_id+':'+str(event['id'])
        bank_state=dict(mint=event['mint'],pool=addresses['pool'],source_slot=snapshot['source_slot'],
            available_at_ms=event['available_at_ms'],pool_state=pool,
            fee_rates_ppm=[int(facts[role][key]) for role,key in (
                ('config','trade_fee_rate_ppm'),('platform','platform_fee_rate_ppm'),
                ('platform','creator_fee_rate_ppm'))],
            base_vault_atomic=int(facts['base_vault']['amount_atomic']),
            quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
            curve_type=int(facts['config']['curve_type']),
            share_fee_rate_ppm=int(facts['share_fee_assumption_ppm']),
            provenance='retained_rpc_snapshot',observation_id=run_id+':'+str(snapshot['id']),
            identity_qualified=identity.get('program_derived_addresses_verified') is True,
            creation_verified=False,supply_verified=facts.get('supply_consistency',{}).get('matches') is True,
            evidence_tail_hash=expected_tail)
        frames.append(dict(id=frame_id,mint=event['mint'],pool=addresses['pool'],
            source_slot=snapshot['source_slot'],available_at_ms=event['available_at_ms'],
            captured_bank_available_at_ms=snapshot['available_at_ms'],bank_state=bank_state,
            run_id=run_id,phase=payload['period'],source_analysis_id=event['id'],
            identity_unknown_reasons=identity.get('blocking_reasons',[])))
    return frames


def _compact(model):
    names=('admissible','reason','buy_input_lamports','buy_output_atomic','buy_curve_fee_lamports',
        'buy_effective_input_lamports','sell_gross_output_lamports','sell_curve_fee_lamports',
        'sell_output_lamports','curve_pnl_lamports','round_trip_friction_lamports',
        'modeled_additional_costs_lamports','modeled_net_pnl_lamports',
        'break_even_extra_proceeds_lamports','break_even_required_net_proceeds_lamports',
        'break_even_required_gross_proceeds_lamports','break_even_required_gross_growth_ratio',
        'buy_output_shortfall_vs_spot_without_fees','fee_rate_total_ppm','cost_basis',
        'additional_costs_observed','strict_economic_cycle_qualified','observation_kind')
    return {name:deepcopy(model[name]) for name in names if name in model}


def build_size_study(frames):
    """Compare fixed research sizes; retain unknown intent, costs and failures."""
    from bot.p4_experiment import assess_curve_costs, CURVE_COST_POLICY
    from bot.p3.position_model import minimum_external_buy_for_break_even
    cases=[]
    for frame in frames:
        assessment=assess_curve_costs(frame)
        bank=frame['bank_state']
        kwargs={name:bank[name] for name in ('fee_rates_ppm','base_vault_atomic',
            'quote_vault_lamports','curve_type','share_fee_rate_ppm')}
        kwargs['pool']=bank['pool_state']
        rows=[]
        for row in assessment['sizes']:
            size=int(row['input_lamports'])
            searches=[]
            for costs in CURVE_COST_POLICY['hypothetical_additional_cost_lamports']:
                search=minimum_external_buy_for_break_even(input_lamports=size,
                    additional_costs_lamports=costs,max_external_buy_lamports=10_000_000_000,**kwargs)
                searches.append(dict(assumed_additional_costs_lamports=str(costs),**search))
            rows.append(dict(input_lamports=str(size),model=_compact(row['same_state_own_entry_model']),
                observed_state_sell_estimate=row['observed_state_sell_estimate'],
                observed_state_sell_refusal=row['observed_state_sell_refusal'],
                service_quotes_available_at_decision=row['provider_quotes'],
                hypothetical_cost_scenarios=[dict(assumed_additional_costs_lamports=r['additional_costs_lamports'],
                    model=_compact(r['model'])) for r in row['hypothetical_additional_costs']],
                hypothetical_reserve_sensitivity=[dict(external_buy_lamports=r['external_buy_lamports'],
                    model=_compact(r['model'])) for r in row['hypothetical_reserve_sensitivity']],
                break_even_external_buy_search=searches))
        cases.append(dict(frame_id=frame['id'],run_id=frame['run_id'],phase=frame['phase'],
            mint=frame['mint'],pool=frame['pool'],source_bank=assessment['source_bank'],
            identity_unknown_reasons=frame['identity_unknown_reasons'],
            observed_real_a_atomic=str(bank['pool_state']['real_a']),
            observed_real_b_lamports=str(bank['pool_state']['real_b']),
            strategy_decisions=assessment['strategy_decisions'],sizes=rows))
    return dict(schema='p3-archived-position-size-study-v1',data_kind='historical_market_banks_conditional_models',
        policy=deepcopy(CURVE_COST_POLICY),source_banks=len(cases),distinct_mints=len({r['mint'] for r in cases}),
        capture_sessions=len({r['run_id'] for r in cases}),
        bank_size_cases=sum(len(c['sizes']) for c in cases),
        admissible_model_cases=sum(r['model']['admissible'] for c in cases for r in c['sizes']),
        identity_qualified_banks=sum(c['source_bank']['identity_qualified'] is True for c in cases),
        observed_bank_sell_estimates=sum(r['observed_state_sell_estimate'] is not None for c in cases for r in c['sizes']),
        cases=cases,market_additional_execution_costs_known=False,strict_economic_cycles=0,
        net_market_pnl_sol=None,executed_transactions=0,new_market_requests=0,
        active_settings_changed=False,selected_size=None,selected_strategy=None,
        effective_independent_sample_size=None,
        scope='All retained candidate banks from the two latest completed protocols; repeated banks are not new trials.',
        model_limitations=['constant_product_only','no_intervening_activity_except_explicit_hypothetical_flows',
            'cost_scenarios_are_assumptions_not_fee_observations','source_bank_times_do_not_timestamp_external_quotes',
            'conditional_models_do_not_establish_fills_or_market_profitability'])
