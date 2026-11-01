"""Offline prospective-corpus accounting without survivor selection or fills.

The prefix checkpoint is the denominator, including interrupted and rejected
cases. Repeated quotations are observations, never extra independent trades or
settled inventory. The caller verifies the bundle against its retained anchor.
"""
from collections import Counter
import hashlib
import json
import math
from fractions import Fraction
import re

from bot.p3.accounting import SolFeeBreakdown, accounting_json_safe
from bot.p3.exit_qualification import qualify_exit_quote_pair
from bot.p3.liquidity_screen import (initial_full_exit_liquidity_screen,
                                     recorded_initial_full_exit_route_passed)


P4_SCOPE = 'instrumental_development_only'
P4_HOLDOUT = 'future_preregistered_after_model_freeze_excluding_development_creators'


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def prospective_assignment(plan, candidates):
    """Hash the assignment fixed before outcomes, without claiming a holdout.

    Every candidate of this instrumental control belongs to development. A
    future holdout needs a separately registered model freeze and new campaigns;
    this function does not manufacture independence or statistical power from N=3.
    """
    assignments = [dict(ordinal=row['ordinal'],mint=row['mint'],
                        creator_claim=row.get('creator',row.get('creator_claim')),
                        cohort='development') for row in candidates]
    body = dict(plan_id=plan.get('plan_id'),scope=P4_SCOPE,holdout_policy=P4_HOLDOUT,
                assignments=assignments)
    return dict(body,sha256=_hash(body))


def _amount(value):
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and re.fullmatch('[0-9]{1,40}',value):
        return int(value)
    return None


def _latency(events):
    values = [e.get('payload',{}).get('latency_ms') for e in events
              if e.get('kind') in ('request','quote_attempt')]
    good = sorted(v for v in values if type(v) in (int,float) and math.isfinite(v) and v >= 0)
    return dict(sample_count=len(good),missing_or_invalid=len(values)-len(good),unit='ms',
        method='nearest_rank_of_measured_request_latency_not_provider_data_age',
        **{label:good[max(0,math.ceil(len(good)*p)-1)] if good else None
           for label,p in (('p50',.5),('p95',.95),('p99',.99))})


def _applicable_fees(events, mint):
    # RPC priority-fee samples / signature-fee references are proxies. They do
    # not establish this projected position's network, ATA or failed-attempt fees.
    rows = [e['payload'] for e in events if e.get('mint') == mint
            and e.get('kind') == 'checkpoint' and e.get('outcome') == 'additional_fee_reference']
    for row in reversed(rows):
        if row.get('proxy') is not False or row.get('applicable_to_projected_position') is not True:
            continue
        fee = row.get('fees')
        if type(fee) is dict:
            try:
                fee = dict(fee)
                if type(fee.get('failed_attempt_lamports')) is list:
                    fee['failed_attempt_lamports'] = tuple(fee['failed_attempt_lamports'])
                return SolFeeBreakdown(**fee)
            except TypeError:
                pass
    return None


def build_prospective_report(plan, events, *, integrity_verified, expected_tail):
    """Build measured cohort, coverage, missingness and conditional-net results.

    Events use the collector's fixed prefix, projected-inventory checkpoints and
    normalized quote links. No price, fee, sold quantity or liquidation is filled
    in when absent. Net projections require the existing strict quote bridge,
    two bank periods, identity/supply checks and a verified creation observation.
    """
    if (integrity_verified is not True or type(expected_tail) is not str
            or re.fullmatch('[0-9a-f]{64}',expected_tail) is None
            or type(events) is not list or not events
            or events[-1].get('record_hash') != expected_tail
            or len({e.get('id') for e in events}) != len(events)):
        raise ValueError('A separately verified retained evidence tail is required')
    plan_records = [e for e in events if e.get('kind') == 'checkpoint'
                    and type(e.get('payload',{}).get('plan')) is dict]
    if any(e['payload']['plan'] != plan for e in plan_records):
        raise ValueError('Retained collection plan differs from report plan')
    registered_time = (type(plan.get('registered_at_ms')) is int and
                       0 <= plan['registered_at_ms'] < min(e['received_at_ms'] for e in events))
    closed = [e for e in events if e.get('kind') == 'checkpoint' and e.get('outcome') == 'prospective_closed']
    close = closed[-1] if closed else None
    prefixes = [e for e in events if e.get('kind') == 'checkpoint'
                and e.get('outcome') == 'prospective_prefix_fixed']
    if len(prefixes) > 1:
        raise ValueError('At most one immutable prospective prefix is permitted')
    candidate_observations = [e for e in events if e.get('kind') in
        ('pool_snapshot','quote_attempt','candidate_decision','launch','transaction')
        or e.get('outcome') in ('projected_inventory_fixed','initial_full_exit_liquidity_screen')]
    prefix = prefixes[0] if prefixes else None
    if prefix is None:
        errors = [e for e in events if e.get('kind') == 'request' and
                  (e.get('outcome') == 'error' or (type(e.get('payload',{}).get('http_status')) is int
                   and not 200 <= e['payload']['http_status'] < 300))]
        if (not plan_records or not registered_time or candidate_observations or not errors
                or close is None or close['id'] != events[-1]['id']
                or close['payload'].get('stop_reason') != 'source_error_after_persisted_receipt'
                or min(e['id'] for e in errors) <= max(e['id'] for e in plan_records)):
            raise ValueError('Missing prefix requires a registered closed source-error receipt before candidate observations')
        rows = []
        cutoff_id = min(e['id'] for e in errors)
    else:
        rows = prefix['payload'].get('candidates')
        if type(rows) is not list or any(type(r) is not dict for r in rows):
            raise ValueError('The selected prefix must be explicit identity records')
        if not rows:
            empty_discovery = any(e.get('kind') == 'discovery' and e.get('outcome') == 'observed'
                and type(e.get('payload',{}).get('rows')) is list and e['id'] < prefix['id'] for e in events)
            if not empty_discovery or candidate_observations:
                raise ValueError('An empty prefix requires observed discovery and no unaccounted candidate events')
        cutoff_id = prefix['id']
    mints = [r.get('mint') for r in rows]
    if (any(type(r.get('ordinal')) is not int or r['ordinal'] != n
            or type(r.get('mint')) is not str or not r['mint'].strip()
            or type(r.get('pool')) is not str or not r['pool'].strip() for n,r in enumerate(rows))
            or len(set(mints)) != len(mints)
            or (type(plan.get('sample_size')) is int and len(rows)>plan['sample_size'])):
        raise ValueError('Prospective prefix identities/ordinals are inconsistent')
    if any(e.get('mint') is not None and e.get('mint') not in mints for e in candidate_observations):
        raise ValueError('Candidate observation is outside the fixed prospective prefix')
    if prefix is not None and any(e['id'] <= prefix['id'] or e['available_at_ms'] < prefix['available_at_ms'] for e in candidate_observations):
        raise ValueError('The cohort was not fixed before candidate observation')
    assignment = prospective_assignment(plan,rows)
    retained_assignment = prefix['payload'].get('p4_assignment_sha256') if prefix else None
    if retained_assignment is not None and retained_assignment != assignment['sha256']:
        raise ValueError('Retained P4 candidate assignment differs from the fixed scope')
    plan_registered = bool(plan_records) and registered_time and all(e['id'] < cutoff_id for e in plan_records)
    assignment_registered = (bool(rows) and plan_registered and retained_assignment == assignment['sha256']
        and plan.get('p4_scope') == P4_SCOPE and plan.get('p4_holdout_policy') == P4_HOLDOUT)
    by_id = {e['id']:e for e in events}
    cases, route_fees = [], Counter()
    for selected in rows:
        mint = selected['mint']; candidate_events = [e for e in events if e.get('mint') == mint]
        quotes = [e for e in candidate_events if e.get('kind') == 'quote_attempt'
                  and e.get('payload',{}).get('provider') == 'raydium_trade_api']
        if any(e['payload'].get('prospective_ordinal') != selected['ordinal'] for e in quotes):
            raise ValueError('Quote is not linked to its preregistered candidate ordinal')
        analyses = [e['payload']['analysis'] for e in candidate_events
                    if e.get('kind') == 'candidate_decision' and type(e.get('payload',{}).get('analysis')) is dict]
        snapshots = [e for e in candidate_events if e.get('kind') == 'pool_snapshot'
                     and type(e.get('payload',{}).get('requested_addresses')) is list]
        slots = sorted({e.get('source_slot') for e in snapshots if type(e.get('source_slot')) is int})
        creation = any(e.get('kind') == 'launch' and e.get('outcome') == 'observed' for e in candidate_events)
        identity = bool(analyses) and all(
            a.get('facts',{}).get('identity_certification',{}).get('program_derived_addresses_verified') is True
            and a.get('facts',{}).get('identity_certification',{}).get('account_discriminators_verified') is True
            and a.get('facts',{}).get('supply_consistency',{}).get('matches') is True
            and not a.get('risk_flags') for a in analyses)
        projection_rows = [e for e in candidate_events if e.get('kind') == 'checkpoint'
                           and e.get('outcome') == 'projected_inventory_fixed']
        inventories = {}
        for e in projection_rows:
            p=e['payload']; buy_id=p.get('buy_observation_id'); buy=by_id.get(buy_id)
            acquired, minimum = _amount(p.get('acquired_atomic')), _amount(p.get('minimum_atomic'))
            if (buy is None or buy.get('mint') != mint or buy.get('outcome') != 'quoted'
                    or buy['id'] >= e['id'] or acquired is None or acquired <= 0 or minimum is None
                    or acquired != _amount(buy['payload'].get('output_amount_atomic'))
                    or minimum != _amount(buy['payload'].get('min_output_amount_atomic'))):
                raise ValueError('Projected inventory does not match the retained earlier buy')
            if buy_id in inventories:
                raise ValueError('Duplicate inventory fixation would inflate projected entries')
            inventories[buy_id] = dict(acquired_atomic=str(acquired),minimum_atomic=str(minimum),
                checkpoint_id=e['id'],buy_observation_id=buy_id)
        # Replay initial full-size screens from retained event evidence.
        # Follow-up and partial quotes cannot retroactively pass this gate.
        receipts = [e for e in candidate_events if e.get('kind') == 'checkpoint'
                    and e.get('outcome') == 'initial_full_exit_liquidity_screen']
        if receipts:
            receipt_buy_ids=[e.get('payload',{}).get('buy_observation_id') for e in receipts]
            if (len(receipts) != len(inventories)
                    or len(set(receipt_buy_ids)) != len(receipts)
                    or set(receipt_buy_ids) != set(inventories)):
                raise ValueError('Initial full-exit screen receipts must cover every projected inventory')
        screens = []
        for inv in inventories.values():
            buy_id = inv['buy_observation_id']
            initial = [e for e in quotes if e['payload'].get('quote_side') == 'sell'
                       and e['payload'].get('probe_phase') == 'initial'
                       and e['payload'].get('exit_scope') == 'full_expected'
                       and e['payload'].get('inventory_buy_observation_id') == buy_id]
            # Never cherry-pick a favorable quote from duplicate observations.
            chosen = initial[0] if len(initial) == 1 else None
            screen = initial_full_exit_liquidity_screen(
                mint=mint,acquired_atomic=inv['acquired_atomic'],
                buy_observation_id=buy_id,sell_event=chosen)
            registered = [e for e in receipts if e.get('payload',{}).get('buy_observation_id') == buy_id]
            if registered:
                receipt = registered[0]
                if (len(registered) != 1 or receipt.get('payload') != screen
                        or receipt['id'] <= inv['checkpoint_id']
                        or receipt['available_at_ms'] < by_id[inv['checkpoint_id']]['available_at_ms']
                        or (chosen is not None and (
                            chosen['id'] <= inv['checkpoint_id']
                            or chosen['id'] >= receipt['id']
                            or chosen['available_at_ms'] > receipt['available_at_ms']))):
                    raise ValueError('Initial full-exit screen receipt differs from observed quote')
            screens.append(dict(screen,gate_recorded=bool(registered)))
        screens_by_buy_id={screen['buy_observation_id']: screen for screen in screens}
        full, partial, refused, unattempted, errors, unavailable_other = [], [], [], [], [], []
        full_attempts = sum(e['payload'].get('quote_side') == 'sell' and e['payload'].get('exit_scope') == 'full_expected' and e.get('outcome') != 'not_attempted' for e in quotes)
        partial_attempts = sum(e['payload'].get('quote_side') == 'sell' and e['payload'].get('exit_scope') == 'partial_diagnostic' and e.get('outcome') != 'not_attempted' for e in quotes)
        coverage = {}; net_projections=[]; admission_reasons=set(); refusal_codes=Counter()
        fees = _applicable_fees(events,mint)
        if fees is None: admission_reasons.add('additional_execution_costs_unknown')
        if not creation: admission_reasons.add('creation_transaction_unverified')
        if not identity: admission_reasons.add('identity_supply_or_permissions_unqualified')
        if len(slots)<2: admission_reasons.add('two_distinct_observed_bank_periods_missing')
        if inventories and not any(recorded_initial_full_exit_route_passed(s) for s in screens):
            admission_reasons.add('initial_full_exit_liquidity_gate_not_passed')
        for e in quotes:
            p=e['payload']; side=p.get('quote_side'); scope=p.get('exit_scope'); outcome=e.get('outcome')
            for fee in p.get('fee_details',{}).get('route_fees',[]):
                amount=_amount(fee.get('fee_amount_atomic')); currency=fee.get('fee_mint')
                if amount is not None and type(currency) is str: route_fees[currency] += amount
            if side != 'sell': continue
            if outcome == 'not_attempted': unattempted.append(e['id']); continue
            if outcome == 'error': errors.append(e['id'])
            if outcome == 'unavailable':
                message=p.get('retained_sanitized_response')
                message=message.get('msg') if type(message) is dict else None
                if type(message) is str and re.fullmatch('[A-Z0-9_]{1,100}',message): refusal_codes[message]+=1
                (refused if e.get('reason') in ('provider_rejected','route_unavailable') else unavailable_other).append(e['id'])
            buy_id=p.get('inventory_buy_observation_id'); inventory=inventories.get(buy_id)
            quantity=_amount(p.get('input_amount_atomic'))
            if inventory is None or quantity is None:
                admission_reasons.add('sell_inventory_link_or_quantity_missing'); continue
            acquired=int(inventory['acquired_atomic'])
            if scope not in ('full_expected','partial_diagnostic') or (scope == 'full_expected' and quantity != acquired) or (scope == 'partial_diagnostic' and quantity >= acquired) or quantity>acquired:
                raise ValueError('Sell scope/quantity differs from its retained inventory')
            if outcome == 'quoted':
                (full if scope == 'full_expected' else partial).append(e['id'])
                phase=p.get('probe_phase','unknown')
                coverage[phase]=max(coverage.get(phase,Fraction(0)),Fraction(quantity,acquired))
            buy=by_id[buy_id]
            verdict=qualify_exit_quote_pair(buy,e,inventory_basis='expected_buy_output',
                entry_decision_at_ms=inventory_event_time(by_id,inventory),
                exit_decision_at_ms=e['available_at_ms'],max_source_age_ms=5000,
                fees=fees,available_cash_lamports=plan.get('reference_cash_lamports'))
            admission_reasons.update(verdict['reasons'])
            projection=verdict['conditional_accounting_projection']
            # A FOLLOWUP full-size quote cannot rescue a position whose
            # initial full-inventory liquidity screen was absent or refused.
            initial_gate=screens_by_buy_id[buy_id]
            if (scope == 'full_expected' and p.get('probe_phase') == 'followup'
                    and recorded_initial_full_exit_route_passed(initial_gate)
                    and creation and identity and len(slots)>=2 and projection is not None):
                net_projections.append(dict(sell_observation_id=e['id'],
                    buy_observation_id=buy_id,projection=accounting_json_safe(projection),
                    basis='conditional_quote_amounts_not_executed_cashflows'))
        cases.append(dict(ordinal=selected['ordinal'],mint=mint,pool=selected['pool'],
            creator_claim=selected.get('creator',selected.get('creator_claim')),
            analyzed=bool(analyses),projected_entries=list(inventories.values()),
            initial_full_exit_liquidity_screens=screens,
            initial_full_exit_route_quoted=sum(s['initial_full_exit_route_quoted'] for s in screens),
            initial_full_exit_gates_recorded=sum(s['gate_recorded'] for s in screens),
            distinct_bank_slots=slots,creation_verified=creation,identity_supply_permissions_qualified=identity,
            full_sell_quote_ids=full,partial_sell_quote_ids=partial,refused_sell_quote_ids=refused,
            full_sell_observation_attempts=full_attempts,partial_sell_observation_attempts=partial_attempts,
            full_sell_quote_availability=len(full)/full_attempts if full_attempts else None,
            partial_sell_quote_availability=len(partial)/partial_attempts if partial_attempts else None,
            unavailable_other_sell_quote_ids=unavailable_other,provider_refusal_codes=dict(sorted(refusal_codes.items())),
            unattempted_sell_quote_ids=unattempted,sell_error_quote_ids=errors,
            max_quoted_inventory_fraction_by_phase={k:str(v) for k,v in sorted(coverage.items())},
            quote_source_times_unknown=sum(e['payload'].get('source_time_ms') is None for e in quotes),
            quote_source_slots_unknown=sum(e['payload'].get('source_slot') is None for e in quotes),
            additional_fees_applicable=fees is not None,admission_reasons=sorted(admission_reasons),
            conditional_net_projections=net_projections,latency=_latency(candidate_events),
            case_state='net_projection_available' if net_projections else 'observed_unqualified' if candidate_events else 'not_reached'))
    discovery=[e['payload'] for e in events if e.get('kind')=='discovery' and type(e.get('payload',{}).get('rows')) is list]
    creators=[c['creator_claim'] for c in cases if type(c['creator_claim']) is str and c['creator_claim'].strip()]
    return dict(schema='p3-prospective-corpus-report-v1',plan_id=plan.get('plan_id'),plan_sha256=_hash(plan),
        source_revision=plan.get('source_revision'),records=len(events),
        integrity_basis='caller_verified_bundle_and_retained_tail',tail_hash=expected_tail,
        plan_registration_recorded=plan_registered,prefix_fixed=prefix is not None,
        not_discovered=prefix is None,cohort_status='not_discovered_source_error' if prefix is None else 'observed_empty_prefix' if not rows else 'prefix_fixed',
        reference_cash_lamports=plan.get('reference_cash_lamports'),
        reference_cash_scope='registered_model_reference_not_wallet_or_observed_cash',
        collection_closed=close is not None,stop_reason=close['payload'].get('stop_reason') if close else None,
        requests_used=close['payload'].get('requests_used') if close else None,
        elapsed_ms=close['payload'].get('elapsed_ms') if close else None,
        selected_corpus_size=len(cases),indexed_rows_retained=sum(len(d['rows']) for d in discovery) if discovery else None,
        candidates_analyzed=sum(c['analyzed'] for c in cases),
        candidates_with_projected_entry=sum(bool(c['projected_entries']) for c in cases),
        projected_entry_observations=sum(len(c['projected_entries']) for c in cases),
         initial_full_exit_route_quoted=sum(c['initial_full_exit_route_quoted'] for c in cases),
         initial_full_exit_gates_recorded=sum(c['initial_full_exit_gates_recorded'] for c in cases),
         initial_full_exit_screen_scope='initial_quote_only_not_fills_or_executable_approval',
        full_sell_quotes=sum(len(c['full_sell_quote_ids']) for c in cases),
        partial_sell_quotes=sum(len(c['partial_sell_quote_ids']) for c in cases),
        refused_sell_quotes=sum(len(c['refused_sell_quote_ids']) for c in cases),
        full_sell_observation_attempts=sum(c['full_sell_observation_attempts'] for c in cases),
        partial_sell_observation_attempts=sum(c['partial_sell_observation_attempts'] for c in cases),
        unavailable_other_sells=sum(len(c['unavailable_other_sell_quote_ids']) for c in cases),
        unattempted_sells=sum(len(c['unattempted_sell_quote_ids']) for c in cases),
        candidates_with_full_sell_quote=sum(bool(c['full_sell_quote_ids']) for c in cases),
        qualified_economic_quote_scenarios=sum(bool(c['conditional_net_projections']) for c in cases),
        net_pnl_sol=None,net_pnl_scope='see_admissible_conditional_scenarios_only; missing_cases_not_zero',
        settled_positions=0,execution_verified=False,market_universe_coverage_verified=False,
        quoted_route_fees_already_in_output_by_mint={k:str(v) for k,v in sorted(route_fees.items())},
        route_fee_scope='quote_observations_not_fees_paid; repeated_quotes_not_summed_as_costs',
        creator_groups_observed=len(set(creators)),creator_identity_claims_not_certified=True,
        unknown_creator_candidates=len(cases)-len(creators),effective_independent_sample_size=None,
        session_groups_observed=1,latency=_latency(events),cases=cases,
        p4=dict(assignment,assignment_preregistered=assignment_registered,holdout_candidates=0,
            model_selected=False,statistical_power_claimed=False),
        economic_verdict='INSUFFICIENT DATA',model_eligible=False)


def inventory_event_time(by_id, inventory):
    return by_id[inventory['checkpoint_id']]['available_at_ms']
