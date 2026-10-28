"""Offline activity/capacity screen retaining the complete prospective universe.

This selects an observation cohort, never a trading strategy or executed entry.
A curve without circulation is excluded from this particular provider-capacity
experiment, without claiming our hypothetical buy could not later be sold.
"""
from copy import deepcopy
import hashlib
import json
import re

from bot.p3.launchlab import (
    SnapshotEvidenceError, constant_product_projection, observed_sell_projection,
)
from bot.p3.quotes import SOL_MINT, _mint


CRITERIA = {
    'schema':'p3-active-cohort-criteria-v1',
    'status':'PREPARED_NOT_EXECUTED',
    'index_sort':'new', 'max_universe_rows':100, 'screen_prefix':6,
    'target_candidates':2, 'research_input_lamports':100000000,
    'max_local_snapshot_age_ms':5000,
    'selection':'first_two_identity_qualified_active_capacity_cases_in_fixed_six_prefix',
    'activity':'observed_real_a_positive_and_real_b_positive',
    'capacity':'own_buy_expected_quantity_has_observed_full_sell_capacity_same_bank',
    'evidence_profile':'published_metadata_v1',
    'max_requests':20, 'max_elapsed_ms':60000, 'followup_delay_ms':15000,
    'source_error_policy':'stop_after_persisting_first_http_transport_or_malformed_error',
    'creation_lookup':'one_bounded_page_and_one_matching_creation_transaction_per_candidate',
    'creation_signature_limit':1000,
    'request_budget':{
        'discovery':1, 'six_pool_roots':1, 'initial_group_bank_and_block_time':2,
        'two_buys_and_initial_full_sells':4, 'followup_bank_and_block_time':2,
        'two_followup_full_sells':2, 'creation_pages_and_matching_bodies':4,
        'one_fee_reference_page_and_body':2, 'optional_prefixed_quarter_diagnostics':2,
    },
    'sources':{
        'discovery':'https://launch-mint-v1.raydium.io/get/list',
        'rpc':'https://api.mainnet-beta.solana.com',
        'quotes':'https://transaction-v1.raydium.io/compute/swap-base-in',
    },
    'p4_scope':'development_only; no independent_holdout_claim',
    'missing_provider_clock_or_applicable_costs':'keep_unknown_and_zero_strict_qualified_cycles',
}


def criteria_sha256():
    return hashlib.sha256(json.dumps(CRITERIA,sort_keys=True,separators=(',',':'),
                                    allow_nan=False).encode()).hexdigest()


def _uint(value, *, positive=False):
    if type(value) is str and re.fullmatch('[0-9]{1,20}',value):
        value=int(value)
    if type(value) is not int or not (1 if positive else 0)<=value<2**64:
        raise ValueError('explicit_unsigned_integer_required')
    return value


def classify_snapshot(analysis, *, size_lamports=100000000,
                      available_at_ms, decision_at_ms,
                      expected_mint=None, expected_pool=None):
    """Classify a retained same-bank analysis before provider quote outcomes.

    Availability age is a LOCAL measurement, not a provider clock or source-age
    certificate. The caller must retain account bytes and the shared bank link.
    Unknown identity blocks selection, while conditional arithmetic is retained.
    """
    if (type(size_lamports) is not int or not 0<size_lamports<2**64
            or type(decision_at_ms) is not int or decision_at_ms<0):
        raise ValueError('Explicit position size and decision clock required')
    reasons=[]
    result={'schema':'p3-active-cohort-screen-v1', 'screen_eligible':False,
        'activity_state':'unknown', 'observed_full_exit_capacity':None,
        'size_lamports':str(size_lamports), 'projected_quantity_atomic':None,
        'own_entry_projection':None, 'observed_exit_projection':None,
        'identity_supply_permissions_qualified':False,
        'local_snapshot_age_ms':None, 'source_age_verified':False,
        'source_freshness_scope':'local_receipt_age_only_not_provider_quote_time',
        'selection_reasons':reasons, 'economic_cycle_qualified':False,
        'economic_unresolved_reasons':['provider_source_clock_unknown',
            'applicable_additional_execution_costs_unknown', 'creation_not_proven_by_snapshot'],
        'positions_acquired':0, 'execution_verified':False,
        'scope':'prospective_observation_cohort_only_not_active_strategy'}
    if type(available_at_ms) is not int or not 0<=available_at_ms<=decision_at_ms:
        reasons.append('snapshot_unavailable_at_decision')
        return result
    age=decision_at_ms-available_at_ms;result['local_snapshot_age_ms']=age
    if age>CRITERIA['max_local_snapshot_age_ms']:
        reasons.append('local_snapshot_receipt_stale')
        return result
    if type(analysis) is not dict:
        reasons.append('snapshot_analysis_missing')
        return result
    try:
        facts=analysis['facts'];pool=facts['pool'];config=facts['config'];platform=facts['platform']
        if (analysis.get('evidence_profile')!='published_metadata_v1'
                or facts.get('account_context_basis')!='caller_supplied_single_getMultipleAccounts_response'):
            reasons.append('same_bank_published_evidence_profile_required')
        _uint(analysis.get('context_slot'),positive=True)
        if ((expected_mint is not None and analysis.get('mint')!=expected_mint)
                or (expected_pool is not None and analysis.get('pool_address')!=expected_pool)):
            reasons.append('snapshot_identity_differs_from_fixed_universe')
        addresses=facts.get('addresses',{})
        if (addresses.get('mint_a')!=analysis.get('mint')
                or addresses.get('pool')!=analysis.get('pool_address')
                or pool.get('mint_a')!=analysis.get('mint')):
            reasons.append('decoded_snapshot_identity_relations_inconsistent')
        identity=facts.get('identity_certification',{})
        qualified=(identity.get('program_derived_addresses_verified') is True
            and identity.get('account_discriminators_verified') is True
            and facts.get('supply_consistency',{}).get('matches') is True
            and analysis.get('risk_flags')==[])
        result['identity_supply_permissions_qualified']=qualified
        if not qualified:reasons.append('identity_supply_or_permissions_unqualified')
        numeric_pool=dict(pool)
        for key in ('virtual_a','virtual_b','real_a','real_b','total_sell_a',
                    'total_fundraising_b','protocol_fee_accrued','platform_fee_accrued',
                    'decimals_a','status'):
            numeric_pool[key]=_uint(pool.get(key))
        rates=tuple(_uint(item.get(key)) for item,key in (
            (config,'trade_fee_rate_ppm'),(platform,'platform_fee_rate_ppm'),
            (platform,'creator_fee_rate_ppm')))
        curve_type=_uint(config.get('curve_type'))
        share=_uint(facts.get('share_fee_assumption_ppm'))
        base_vault=_uint(facts['base_vault']['amount_atomic'])
        quote_vault=_uint(facts['quote_vault']['amount_atomic'])
        if numeric_pool.get('mint_b')!=SOL_MINT or numeric_pool['status']!=0 or curve_type!=0:
            reasons.append('active_native_SOL_constant_product_required')
            return result
        circulating=numeric_pool['real_a'];raised=numeric_pool['real_b']
        result.update(observed_circulating_atomic=str(circulating),observed_raised_lamports=str(raised))
        active=circulating>0 and raised>0
        result['activity_state']='active' if active else 'no_observed_circulation' if not circulating else 'no_observed_quote_reserve'
        if not active:reasons.append('observed_activity_insufficient')
        own=constant_product_projection(numeric_pool,input_lamports=size_lamports,
            fee_rates_ppm=rates,base_vault_atomic=base_vault,
            quote_vault_lamports=quote_vault,share_fee_rate_ppm=share)
        result['own_entry_projection']=own
        result['projected_quantity_atomic']=own['buy_output_atomic']
        try:
            result['observed_exit_projection']=observed_sell_projection(numeric_pool,
                input_token_atomic=int(own['buy_output_atomic']),fee_rates_ppm=rates,
                quote_vault_lamports=quote_vault,curve_type=curve_type,share_fee_rate_ppm=share)
            result['observed_full_exit_capacity']=True
        except SnapshotEvidenceError as error:
            result['observed_full_exit_capacity']=False
            reasons.append('observed_full_exit_capacity_unavailable:'+str(error))
        result['screen_eligible']=not reasons
    except (ValueError,TypeError,KeyError,AttributeError) as error:
        reasons.append('snapshot_or_curve_evidence_unusable')
        if isinstance(error,SnapshotEvidenceError):result['model_refusal_reason']=str(error)
    return result


def select_cohort(universe, *, decision_at_ms):
    """Retain every original row; screen only the fixed first-six SOL prefix.

    Expected rows contain mint,pool,quote_mint_claim and optionally snapshot plus
    snapshot_available_at_ms. No external quote response or future outcome is
    consulted. Beyond-prefix and unsuccessful cases remain denominator records.
    """
    if type(universe) is not list or len(universe)>CRITERIA['max_universe_rows']:
        raise ValueError('At most the complete registered 100-row universe is supported')
    if type(decision_at_ms) is not int or decision_at_ms<0:
        raise ValueError('Explicit decision clock required')
    records=[];selected=[];seen_mints=set();seen_pools=set();screened=0
    for index,row in enumerate(universe):
        if type(row) is not dict:raise ValueError('Universe rows must be explicit records')
        record={'universe_index':index,'source_row':deepcopy(row),'selection_reason':None,'screen':None}
        records.append(record)
        try:
            mint=_mint(row.get('mint'));pool=_mint(row.get('pool'))
            valid=mint!=SOL_MINT and row.get('quote_mint_claim')==SOL_MINT
        except ValueError:valid=False
        if not valid:
            record['selection_reason']='invalid_or_outside_native_SOL_scope';continue
        if mint in seen_mints or pool in seen_pools:
            record['selection_reason']='duplicate_mint_or_pool';continue
        seen_mints.add(mint);seen_pools.add(pool)
        if screened>=CRITERIA['screen_prefix']:
            record['selection_reason']='outside_fixed_screen_prefix';continue
        screened+=1
        screen=classify_snapshot(row.get('snapshot'),size_lamports=CRITERIA['research_input_lamports'],
            available_at_ms=row.get('snapshot_available_at_ms'),decision_at_ms=decision_at_ms,
            expected_mint=mint,expected_pool=pool)
        record['screen']=screen
        if not screen['screen_eligible']:
            record['selection_reason']='excluded_by_preregistered_activity_capacity_or_identity';continue
        if len(selected)>=CRITERIA['target_candidates']:
            record['selection_reason']='outside_fixed_selected_count';continue
        record['selection_reason']='selected_before_provider_outcomes'
        selected.append({'ordinal':len(selected),'universe_index':index,'mint':mint,'pool':pool,
                         'creator_claim':row.get('creator_claim'),
                         'size_lamports':str(CRITERIA['research_input_lamports'])})
    return {'schema':'p3-active-cohort-selection-v1','criteria_sha256':criteria_sha256(),
        'criteria_status':CRITERIA['status'],'universe_size':len(universe),
        'screened_prefix_count':screened,'selected_count':len(selected),
        'excluded_or_not_reached_count':len(universe)-len(selected),
        'records':records,'selected':selected,'decision_at_ms':decision_at_ms,
        'selection_uses_provider_outcomes':False,'market_collection_executed':False,
        'qualified_economic_cycles':0,'execution_verified':False}
