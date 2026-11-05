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


def make_acquisition_plan(*, registered_at_ms, source_revision):
    """Freeze the existing budget and the missing input contract before capture.

    This is a prepared plan, not an authorization or a network entry point.
    The timestamp and Git revision are caller declarations until separately
    published; this function cannot certify their publication.
    """
    if (type(registered_at_ms) is not int or registered_at_ms <= 0
            or type(source_revision) is not str or re.fullmatch('[0-9a-f]{40}', source_revision) is None):
        raise ValueError('Explicit registration clock and exact source revision required')
    return dict(schema='p3-master-acquisition-plan-v1',status='PREPARED_NOT_EXECUTED',
        registered_at_ms=registered_at_ms,source_revision=source_revision,
        criteria_sha256=criteria_sha256(),criteria=deepcopy(CRITERIA),
        maximum_feature_checkpoints=128,maximum_quote_attempts=20,
        feature_checkpoint='master_frame_inputs_v1',
        feature_sources='existing_scanner_and_retained_cache_only; no_extra_source_calls',
        costs='explicit_asof_own_position_cost_checkpoint_or_unknown',
        snapshot_time='local_availability_and_RPC_context; never_provider_quote_clock',
        observation_scope='indicative_quotes_and_conditional_models; no_fill_or_settlement',
        independent_buyers='unknown_until_separate_supported_wallet_evidence',
        market_collection_executed=False,active_policy_changed=False)


def validate_acquisition_plan(plan, *, first_observation_at_ms=None):
    if type(plan) is not dict:
        raise ValueError('Explicit prepared acquisition plan required')
    expected=make_acquisition_plan(registered_at_ms=plan.get('registered_at_ms'),
        source_revision=plan.get('source_revision'))
    if plan != expected:
        raise ValueError('Acquisition plan differs from the fixed source and global budget contract')
    if first_observation_at_ms is not None and (type(first_observation_at_ms) is not int
            or first_observation_at_ms <= plan['registered_at_ms']):
        raise ValueError('Acquisition observations must follow declared registration')
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _verified_capture_events(events, expected_tail):
    """Reuse CaptureStore's actual hash-chain verifier, without opening a DB."""
    from bot.p3.store import CaptureStore, _canonical
    if (type(events) is not list or not events or len(events)>5000
            or type(expected_tail) is not str or re.fullmatch('[0-9a-f]{64}', expected_tail) is None):
        raise ValueError('A bounded complete capture and retained tail anchor are required')
    records=[]
    metadata={'id','payload','payload_sha256','previous_hash','record_hash'}
    for event in events:
        if type(event) is not dict:
            raise ValueError('Explicit capture envelopes required')
        try:
            envelope={key:value for key,value in event.items() if key not in metadata}
            records.append((event['id'],event['available_at_ms'],_canonical(envelope),
                _canonical(event['payload']),event['payload_sha256'],
                event['previous_hash'],event['record_hash']))
        except (KeyError,TypeError):
            raise ValueError('Capture envelope metadata missing') from None
    if CaptureStore._verify_records(records) != expected_tail:
        raise ValueError('Capture differs from retained external tail anchor')
    return events


def retain_comparison_inputs(store, *, mint, pool, creator, detected_at_ms,
                             features, source_observation_ids, received_at_ms,
                             snapshot_analysis_observation_id=None, token_decimals=None,
                             health_observation_id=None):
    """Append available scanner/cache features to the existing capture journal.

    This producer adds no source request. It must be called after its referenced
    observations have committed, before the decision/outcome using those inputs.
    Commit order is explicit even when several events share one millisecond.
    """
    from dataclasses import asdict,is_dataclass
    from bot.p3.store import CaptureStore
    from bot.analyser.final_decision_engine import SignalFeatures
    from bot.p4_experiment import _features
    if not isinstance(store,CaptureStore):
        raise TypeError('The existing dedicated CaptureStore is required')
    if (type(received_at_ms) is not int or received_at_ms<=0
            or type(creator) is not str or not creator
            or type(detected_at_ms) is not int or not 0<detected_at_ms<=received_at_ms
            or (token_decimals is not None and (type(token_decimals) is not int or not 0<=token_decimals<=255))
            or type(source_observation_ids) is not list or not source_observation_ids
            or len(source_observation_ids)>128
            or any(type(identity) is not int or identity<=0 for identity in source_observation_ids)
            or len(set(source_observation_ids))!=len(source_observation_ids)):
        raise ValueError('Explicit bounded already-retained source references required')
    _mint(mint);_mint(pool)
    previous=store.events();by_id={event['id']:event for event in previous}
    if any(identity not in by_id or by_id[identity]['available_at_ms']>received_at_ms
            for identity in source_observation_ids):
        raise ValueError('Feature source is missing or unavailable before capture')
    references=list(source_observation_ids)
    if health_observation_id is not None:
        if type(health_observation_id) is not int or _retained_health(by_id.get(health_observation_id),received_at_ms) is None:
            raise ValueError('Operational health must be explicitly retained and causal')
        if health_observation_id not in references:references.append(health_observation_id)
    if snapshot_analysis_observation_id is not None:
        analysis=by_id.get(snapshot_analysis_observation_id)
        if (type(snapshot_analysis_observation_id) is not int or analysis is None
                or analysis.get('kind')!='candidate_decision' or analysis.get('mint')!=mint
                or analysis['available_at_ms']>received_at_ms
                or analysis.get('payload',{}).get('analysis',{}).get('pool_address')!=pool):
            raise ValueError('Snapshot analysis was not retained before feature capture')
        if snapshot_analysis_observation_id not in references:
            references.append(snapshot_analysis_observation_id)
    raw=asdict(features) if is_dataclass(features) else deepcopy(features)
    frame=dict(mint=mint,creator=creator,pool=pool,detected_at_ms=detected_at_ms,
        features=raw,features_available_at_ms=received_at_ms)
    checked,_reason=_features(frame,{'SignalFeatures':SignalFeatures},received_at_ms)
    if checked is None:
        raise ValueError('Feature identity, freshness or schema is unqualified')
    kinds={by_id[identity]['provenance'] for identity in references}
    if kinds=={'synthetic'}:provenance='synthetic'
    elif kinds and kinds<= {'live','historical_replay'}:
        provenance='live' if kinds=={'live'} else 'historical_replay'
    else:raise ValueError('Feature source provenance cannot mix synthetic and market inputs')
    if sum(event.get('outcome')=='master_frame_inputs_v1' for event in previous)>=128:
        raise ValueError('Prepared feature checkpoint budget exhausted')
    return store.append('checkpoint',received_at_ms=received_at_ms,mint=mint,
        provenance=provenance,outcome='master_frame_inputs_v1',payload=dict(
            creator=creator,pool=pool,detected_at_ms=detected_at_ms,features=raw,
            source_observation_ids=references,
            snapshot_analysis_observation_id=snapshot_analysis_observation_id,
            token_decimals=token_decimals,
            **({'health_observation_id':health_observation_id} if health_observation_id is not None else {})))


def _retained_health(event,at):
    """Read a local supervisor attestation; never infer RPC health from prices."""
    if (type(event) is not dict or event.get('kind')!='checkpoint'
            or event.get('outcome')!='operational_health_v1'
            or type(event.get('available_at_ms')) is not int or event['available_at_ms']>at):
        return None
    health=event.get('payload',{}).get('health')
    if type(health) is not dict:return None
    observed=health.get('observed_at_ms')
    if (health.get('schema')!='rugger-paper-operational-health-v1'
            or type(observed) is not int or not 0<=observed<=event['available_at_ms']<=at
            or at-observed>5000 or type(health.get('allow_new_entries')) is not bool):return None
    if health['allow_new_entries'] is True:
        sources=health.get('source_health')
        if (health.get('blocking_reasons')!=[] or type(sources) is not dict
                or any(type(sources.get(name)) is not dict or sources[name].get('healthy') is not True
                    for name in ('scanner','rpc','websocket'))):return None
    return deepcopy(health)


def _asof_bank(analysis_event, by_id, *, mint, pool, at, data_kind):
    """Convert one retained analysis, preserving its original observed bank."""
    if type(analysis_event) is not dict or analysis_event.get('kind')!='candidate_decision':
        return None
    try:
        body=analysis_event['payload'];analysis=body['analysis']
        snapshot=by_id[body['snapshot_observation_id']]
        if (snapshot['kind']!='pool_snapshot' or snapshot['mint']!=mint
                or analysis_event['mint']!=mint or analysis['mint']!=mint
                or analysis['pool_address']!=pool or analysis_event['available_at_ms']>at
                or snapshot['id']>=analysis_event['id']
                or snapshot['available_at_ms']>analysis_event['available_at_ms']
                or snapshot['source_slot']!=analysis.get('context_slot')
                or snapshot['source_slot']!=analysis_event['source_slot']):
            return None
        _uint(snapshot['source_slot'],positive=True)
        facts=analysis['facts'];raw=facts['pool'];state=deepcopy(raw)
        if (analysis.get('evidence_profile')!='published_metadata_v1'
                or facts.get('account_context_basis')!='caller_supplied_single_getMultipleAccounts_response'
                or facts['addresses']['pool']!=pool or facts['addresses']['mint_a']!=mint
                or state['mint_a']!=mint):
            return None
        for name in ('virtual_a','virtual_b','real_a','real_b','total_sell_a',
                'total_fundraising_b','protocol_fee_accrued','platform_fee_accrued','decimals_a','status'):
            state[name]=_uint(raw[name])
        # A retained analysis alone is an upstream claim. When original RPC
        # bytes are present, actually replay the pinned parser before carrying
        # forward its certifications; otherwise preserve UNKNOWN.
        certified=None;supply_verified=None;replayed=False
        snapshot_body=snapshot.get('payload',{})
        rpc=snapshot_body.get('raw_rpc_result') if type(snapshot_body) is dict else None
        ordered=snapshot_body.get('requested_addresses') if type(snapshot_body) is dict else None
        if type(rpc) is dict and type(ordered) is list:
            values=rpc.get('value');context=rpc.get('context',{})
            if (type(values) is not list or len(values)!=len(ordered) or len(set(ordered))!=len(ordered)
                    or type(context) is not dict or context.get('slot')!=snapshot['source_slot']):
                return None
            from bot.p3.launchlab import analyze_snapshot
            verified=analyze_snapshot(dict(zip(ordered,values)),context_slot=snapshot['source_slot'],
                expected_mint=mint,pool_address=pool,evidence_profile='published_metadata_v1',
                share_fee_rate_ppm=_uint(facts['share_fee_assumption_ppm']))
            vf=verified.get('facts',{})
            if any(vf.get(key)!=facts.get(key) for key in (
                    'pool','config','platform','addresses','base_vault','quote_vault')):
                return None
            identity=vf.get('identity_certification',{})
            certified=(identity.get('program_derived_addresses_verified') is True
                and identity.get('account_discriminators_verified') is True
                and verified.get('risk_flags')==[])
            supply_verified=vf.get('supply_consistency',{}).get('matches') is True
            replayed=True
        bank=dict(mint=mint,pool=pool,source_slot=snapshot['source_slot'],
            available_at_ms=analysis_event['available_at_ms'],pool_state=state,
            fee_rates_ppm=[_uint(facts['config']['trade_fee_rate_ppm']),
                _uint(facts['platform']['platform_fee_rate_ppm']),
                _uint(facts['platform']['creator_fee_rate_ppm'])],
            base_vault_atomic=_uint(facts['base_vault']['amount_atomic']),
            quote_vault_lamports=_uint(facts['quote_vault']['amount_atomic']),
            curve_type=_uint(facts['config']['curve_type']),
            share_fee_rate_ppm=_uint(facts['share_fee_assumption_ppm']),
            provenance='synthetic' if data_kind=='synthetic' else 'retained_rpc_snapshot',
            observation_id=snapshot['id'],analysis_observation_id=analysis_event['id'],
            identity_qualified=certified,supply_verified=supply_verified,
            raw_snapshot_replayed=replayed,
            certification_scope='pinned_parser_replay' if replayed else 'upstream_analysis_claim_only',
            creation_verified=False,source_time_scope='RPC_bank_not_provider_quote_time')
        return bank
    except (KeyError,TypeError,ValueError):
        return None


def _asof_own_fees(available, buy_id, mint, data_kind):
    """Other people's fees, future costs and missing costs cannot become ours."""
    from dataclasses import asdict
    from bot.p3.accounting import SolFeeBreakdown, _fees
    for event in reversed(available):
        payload=event.get('payload')
        if (event.get('kind')!='checkpoint' or event.get('outcome')!='own_position_costs'
                or event.get('mint')!=mint or type(payload) is not dict
                or payload.get('buy_observation_id')!=buy_id
                or payload.get('proxy') is not False
                or payload.get('applicable_to_projected_position') is not True):
            continue
        fee=payload.get('fees')
        try:
            fee=deepcopy(fee)
            if type(fee.get('failed_attempt_lamports')) is list:
                fee['failed_attempt_lamports']=tuple(fee['failed_attempt_lamports'])
            fee=SolFeeBreakdown(**fee);_fees(fee)
            if (data_kind=='synthetic') != (fee.provenance=='synthetic'):
                continue
            result=asdict(fee);result['failed_attempt_lamports']=list(result['failed_attempt_lamports'])
            return result,event['id']
        except (KeyError,TypeError,ValueError,AttributeError):
            continue
    return None,None


def _asof_creation(past, *, mint, pool, creator):
    """Reparse the linked original transaction, not a creation boolean claim."""
    from bot.scanner.transaction_parser import find_raydium_launches
    by_id={event['id']:event for event in past}
    for event in reversed(past):
        if event.get('kind')!='launch' or event.get('mint')!=mint or event.get('outcome')!='observed':
            continue
        try:
            body=event['payload'];transaction=by_id[body['transaction_observation_id']]
            raw=transaction['payload']['raw_transaction']
            signatures=raw['transaction']['signatures']
            expected=dict(mint=mint,pool_state=pool,creator=creator,payer=body['payer'])
            if (transaction['kind']!='transaction' or transaction['outcome']!='observed'
                    or transaction['id']>=event['id']
                    or transaction['available_at_ms']>event['available_at_ms']
                    or transaction['signature']!=event.get('signature')
                    or not signatures or signatures[0]!=event.get('signature')
                    or raw.get('slot')!=event.get('source_slot')
                    or transaction.get('source_slot')!=event.get('source_slot')
                    or type(raw.get('meta')) is not dict or raw['meta'].get('err') is not None
                    or any(body.get(key)!=value for key,value in expected.items())
                    or expected not in find_raydium_launches(raw)):
                continue
            _uint(event.get('source_slot'),positive=True)
            return [transaction['id'],event['id']]
        except (KeyError,TypeError,ValueError,AttributeError):
            continue
    return []


def build_comparison_corpus(selection, events, *, as_of_ms, integrity_verified, expected_tail):
    """Bridge retained prospective inputs to causal Master/P4 frames offline.

    Feature checkpoints must retain source observation IDs before use. No
    missing creator, creation time, wallet independence, feature, cost or source
    clock is inferred. Every selected/unselected universe row remains in the
    denominator even when it cannot yield a frame. No economic cycle is settled.
    """
    if (integrity_verified is not True or type(as_of_ms) is not int or as_of_ms<0
            or type(selection) is not dict or selection.get('schema')!='p3-active-cohort-selection-v1'
            or selection.get('criteria_sha256')!=criteria_sha256()
            or type(selection.get('records')) is not list
            or selection.get('universe_size')!=len(selection['records'])
            or type(selection.get('selected')) is not list
            or selection.get('selected_count')!=len(selection['selected'])
            or type(selection.get('decision_at_ms')) is not int
            or selection['decision_at_ms']>as_of_ms):
        raise ValueError('Fixed complete selection and explicit as-of capture proof required')
    events=_verified_capture_events(events,expected_tail)
    if (sum(e.get('outcome')=='master_frame_inputs_v1' for e in events)>128
            or sum(e.get('kind')=='quote_attempt' for e in events)>CRITERIA['max_requests']):
        raise ValueError('Prepared feature or quote work budget exceeded')
    kinds={e.get('provenance') for e in events}
    if kinds=={'synthetic'}:data_kind='synthetic'
    elif kinds and kinds<= {'live','historical_replay'}:data_kind='market_observation'
    else:raise ValueError('Synthetic and market capture provenance cannot be mixed or relabelled')
    by_id={event['id']:event for event in events}
    available=[event for event in events if event['available_at_ms']<=as_of_ms]
    denominator=deepcopy(selection['records']);frames=[];candidate_results=[]
    seen_indices=set()
    for ordinal,selected in enumerate(selection['selected']):
        index=selected.get('universe_index');mint=selected.get('mint');pool=selected.get('pool')
        if (type(index) is not int or not 0<=index<len(denominator)
                or index in seen_indices or selected.get('ordinal')!=ordinal
                or denominator[index].get('selection_reason')!='selected_before_provider_outcomes'
                or denominator[index]['source_row'].get('mint')!=mint
                or denominator[index]['source_row'].get('pool')!=pool):
            raise ValueError('Selected identity differs from retained universe')
        seen_indices.add(index)
        feature_events=[e for e in available if e.get('kind')=='checkpoint' and e.get('mint')==mint
            and e.get('outcome')=='master_frame_inputs_v1']
        reasons=[];made=[]
        for event in feature_events:
            body=event.get('payload',{});at=event['available_at_ms']
            if type(body) is not dict:
                reasons.append({'feature_observation_id':event['id'],'reason':'feature_payload_missing'})
                continue
            refs=body.get('source_observation_ids');detected=body.get('detected_at_ms')
            creator=body.get('creator');fixed_creator=selected.get('creator_claim')
            if (type(body) is not dict or body.get('pool')!=pool
                    or type(creator) is not str or not creator
                    or (fixed_creator is not None and creator!=fixed_creator)
                    or type(detected) is not int or not 0<detected<=at
                    or type(refs) is not list or not refs or len(refs)>128
                    or any(type(ref) is not int or ref not in by_id or ref>=event['id']
                        or by_id[ref]['available_at_ms']>at for ref in refs)
                    or at<selection['decision_at_ms']):
                reasons.append({'feature_observation_id':event['id'],'reason':'feature_identity_sources_or_chronology_unqualified'})
                continue
            past=[e for e in available if e['id']<event['id'] and e['available_at_ms']<=at]
            frame=dict(id='capture:'+str(event['id'])+':'+event['record_hash'],mint=mint,pool=pool,
                creator=creator,detected_at_ms=detected,available_at_ms=at,
                features_available_at_ms=at,features=deepcopy(body.get('features')),
                independent_buyers=None,source_slot=None,slot_available_at_ms=None,
                data_kind=data_kind,source_evidence=dict(feature_observation_id=event['id'],
                    source_observation_ids=deepcopy(refs),capture_record_hash=event['record_hash'],
                    identity_basis='retained_upstream_claim_not_new_authentication'))
            health_id=body.get('health_observation_id')
            if health_id is not None:
                health_event=by_id.get(health_id) if type(health_id) is int and health_id in refs else None
                if type(health_event) is dict and health_event['id']>=event['id']:health_event=None
                frame['health']=_retained_health(health_event,at)
                frame['source_evidence']['health_observation_id']=health_id
                frame['source_evidence']['health_basis']='retained_local_supervisor_attestation_not_provider_authentication'
            from bot.analyser.final_decision_engine import SignalFeatures
            from bot.p4_experiment import _features
            features,feature_reason=_features(frame,{'SignalFeatures':SignalFeatures},at)
            if features is None:
                reasons.append({'feature_observation_id':event['id'],'reason':feature_reason});continue
            analysis_id=body.get('snapshot_analysis_observation_id')
            analysis_event=by_id.get(analysis_id) if type(analysis_id) is int else None
            if type(analysis_event) is dict and analysis_event['id']>=event['id']:
                analysis_event=None
            bank=_asof_bank(analysis_event,by_id,
                mint=mint,pool=pool,at=at,data_kind=data_kind)
            if bank is not None:
                creation_ids=_asof_creation(past,mint=mint,pool=pool,creator=creator)
                bank['creation_verified']=bool(creation_ids)
                frame['bank_state']=bank;frame['source_slot']=bank['source_slot']
                frame['slot_available_at_ms']=bank['available_at_ms']
                frame['source_evidence']['creation_observation_ids']=creation_ids
            buys=[e for e in past if e.get('mint')==mint and e.get('kind')=='quote_attempt'
                and e.get('payload',{}).get('provider')=='raydium_trade_api'
                and e.get('payload',{}).get('quote_side')=='buy']
            size_contexts={};sell_contexts=[];quotes=[];fee_ids=[]
            for buy in buys:
                p=buy['payload'];size=p.get('input_amount_atomic')
                try:_uint(size,positive=True)
                except ValueError:continue
                fees,fee_id=_asof_own_fees(past,buy['id'],mint,data_kind)
                if fee_id is not None:fee_ids.append(fee_id)
                context=dict(buy_observation=deepcopy(buy),token_decimals=body.get('token_decimals'),fees=fees)
                sells=[e for e in past if e.get('mint')==mint and e.get('kind')=='quote_attempt'
                    and e.get('payload',{}).get('provider')=='raydium_trade_api'
                    and e.get('payload',{}).get('quote_side')=='sell'
                    and e['payload'].get('inventory_buy_observation_id')==buy['id']
                    and e['id']>buy['id']]
                size_contexts[str(size)]={**context,'sell_observations':deepcopy(sells)}
                quotes.extend([buy,*sells])
                for sell in sells:
                    sell_contexts.append(dict(sell_observation=deepcopy(sell),fees=deepcopy(fees),
                        inventory_buy_observation_id=buy['id'],requested_quantity_atomic=sell['payload'].get('input_amount_atomic')))
            frame['size_contexts']=size_contexts;frame['sell_contexts']=sell_contexts
            chosen=size_contexts.get(selected.get('size_lamports'))
            if chosen is not None:
                frame['buy_context']={k:deepcopy(v) for k,v in chosen.items() if k!='sell_observations'}
                frame['inventory_context']=deepcopy(frame['buy_context'])
            frame['source_evidence'].update(quote_observation_ids=[e['id'] for e in quotes],
                own_fee_observation_ids=fee_ids,bank_snapshot_observation_id=bank['observation_id'] if bank else None)
            frames.append(frame);made.append(frame['id'])
        candidate_results.append(dict(universe_index=index,mint=mint,pool=pool,frames=made,
            state='inputs_retained' if made else 'UNKNOWN',refusals=reasons,
            missing_reason=None if made else 'retained_features_and_sources_unavailable'))
    frames.sort(key=lambda frame:(frame['available_at_ms'],frame['id']))
    return dict(schema='p3-master-comparison-acquisition-v1',corpus=dict(data_kind=data_kind,frames=frames),
        denominator=denominator,universe_size=len(denominator),selected_count=len(selection['selected']),
        candidates=candidate_results,frame_count=len(frames),as_of_ms=as_of_ms,
        refused_quote_observation_ids=[e['id'] for e in available if e.get('kind')=='quote_attempt'
            and e.get('outcome')!='quoted'],unknown_candidate_count=sum(not row['frames'] for row in candidate_results),
        future_observations_excluded=sum(e['available_at_ms']>as_of_ms for e in events),
        retained_tail=expected_tail,integrity='verified_hash_chain_against_caller_retained_anchor_not_authenticated',
        market_collection_executed=False,execution_verified=False,qualified_economic_cycles=0,
        provider_clocks_inferred_from_RPC=False,active_policy_changed=False,
        scope='retained_asof_inputs_and_complete_cohort_denominator; no_fill_or_market_edge')
