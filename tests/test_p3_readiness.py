"""Synthetic manifest admission, without filesystem, transport or ledger access."""
from copy import deepcopy
import json

import pytest

from bot.p3.readiness import MAX_SNAPSHOT_AGE_MS, MIN_FOLLOWUP_DELAY_MS, evaluate_readiness


def manifest():
    return {
        'data_kind': 'live',
        'plan': {'plan_id': 'synthetic-plan', 'plan_sha256': 'a' * 64,
                 'registered_at_ms': 100, 'started_at_ms': 200,
                 'max_requests': 20, 'max_elapsed_ms': 40_000, 'sample_size': 1,
                 'followup_delay_ms': 15_000},
        'run': {'requests_used': 10, 'elapsed_ms': 20_000,
                'anonymous_transport': True, 'wire_retry_disabled': True,
                'financial_methods_used': [], 'integrity_verified': True,
                'tail_anchor_verified': True, 'open_gaps': 0, 'selected_count': 1,
                'independent_reference_complete': True},
        'policy': {'max_snapshot_age_ms': 5_000},
        'candidates': [{
            'mint': 'synthetic-mint', 'creation_verified': True,
            'coherent_snapshot_count': 2, 'all_account_links_verified': True,
            'account_discriminators_certified': True, 'native_sol': True,
            'token_transfer_restrictions_known': True, 'exit_liquidity_checked': True,
            'fees_complete': True, 'network_fee_bound_known': True,
            'snapshot_source_age_ms': 5_000, 'source_clock_bound_known': True,
            'pit_decision_order_verified': True, 'exit_observation_available': True,
            'snapshots': [
                {'context_slot': 10, 'received_at_ms': 1_000, 'available_at_ms': 1_005,
                 'analysis_at_ms': 1_010, 'source_time_ms': 0, 'coherent': True},
                {'context_slot': 20, 'received_at_ms': 16_000, 'available_at_ms': 16_000,
                 'analysis_at_ms': 16_000, 'source_time_ms': 11_000, 'coherent': True},
            ],
        }],
    }


def criterion(report, name):
    return next(item for item in report['criteria'] if item['name'] == name)


def test_fully_attested_live_manifest_can_admit_prospective_paper_data_only():
    value = manifest()
    original = deepcopy(value)
    report = evaluate_readiness(value)
    assert report['collection_readiness'] == report['economic_readiness'] == 'GO'
    assert report['p3_go'] is True
    assert report['economic_verdict'] == 'INSUFFICIENT DATA'
    assert 'profitability' in report['scope']
    assert all(item['status'] == 'PASS' for item in report['criteria'])
    assert all(item['evidence_count'] == item['required_count'] for item in report['criteria'])
    assert report['reasons'] == []
    assert value == original
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('kind', ['synthetic', 'historical_replay', '', None, True])
def test_only_live_data_admits_collection_or_economic_readiness(kind):
    value = manifest()
    value['data_kind'] = kind
    report = evaluate_readiness(value)
    assert report['collection_readiness'] == report['economic_readiness'] == 'NO-GO'
    assert report['p3_go'] is False


@pytest.mark.parametrize('section', ['plan', 'run', 'policy', 'candidates'])
def test_missing_sections_remain_unknown_and_never_pass(section):
    value = manifest()
    del value[section]
    report = evaluate_readiness(value)
    assert report['p3_go'] is False
    assert any(item['status'] == 'UNKNOWN' for item in report['criteria'])


@pytest.mark.parametrize('value', [None, False, 1, 'live', [], float('nan')])
def test_non_mapping_manifest_yields_inspectable_unknown_no_go(value):
    report = evaluate_readiness(value)
    assert report['collection_readiness'] == report['economic_readiness'] == 'NO-GO'
    assert report['economic_verdict'] == 'INSUFFICIENT DATA'
    assert all(item['status'] == 'UNKNOWN' for item in report['criteria'])
    json.dumps(report, allow_nan=False)


_RUN_BOOLEANS = ('anonymous_transport', 'wire_retry_disabled', 'integrity_verified',
                 'tail_anchor_verified', 'independent_reference_complete')
_CANDIDATE_BOOLEANS = ('creation_verified', 'all_account_links_verified',
    'account_discriminators_certified', 'native_sol', 'token_transfer_restrictions_known',
    'exit_liquidity_checked', 'fees_complete', 'network_fee_bound_known',
    'source_clock_bound_known', 'pit_decision_order_verified', 'exit_observation_available')


@pytest.mark.parametrize('section,field', [('run', name) for name in _RUN_BOOLEANS]
                         + [('candidate', name) for name in _CANDIDATE_BOOLEANS])
@pytest.mark.parametrize('state,expected', [(False, 'FAIL'), (None, 'UNKNOWN'),
    (1, 'UNKNOWN'), ('true', 'UNKNOWN'), (float('nan'), 'UNKNOWN')])
def test_each_boolean_requires_explicit_true(section, field, state, expected):
    value = manifest()
    target = value['run'] if section == 'run' else value['candidates'][0]
    target[field] = state
    report = evaluate_readiness(value)
    assert criterion(report, field)['status'] == expected
    assert report['p3_go'] is False
    assert criterion(report, field)['evidence_count'] == 0
    if section == 'candidate' or field == 'independent_reference_complete':
        assert report['collection_readiness'] == 'GO'
    else:
        assert report['collection_readiness'] == 'NO-GO'


@pytest.mark.parametrize('section,field', [('run', name) for name in _RUN_BOOLEANS]
                         + [('candidate', name) for name in _CANDIDATE_BOOLEANS])
def test_missing_boolean_is_unknown(section, field):
    value = manifest()
    del (value['run'] if section == 'run' else value['candidates'][0])[field]
    report = evaluate_readiness(value)
    assert criterion(report, field)['status'] == 'UNKNOWN'
    assert report['p3_go'] is False


@pytest.mark.parametrize('section,field,state,name', [
    ('plan', 'plan_id', '', 'registered_plan_identity'),
    ('plan', 'plan_sha256', 'g' * 64, 'registered_plan_identity'),
    ('plan', 'registered_at_ms', 200, 'preregistration'),
    ('plan', 'registered_at_ms', 201, 'preregistration'),
    ('plan', 'registered_at_ms', -1, 'preregistration'),
    ('plan', 'max_requests', 0, 'request_budget'),
    ('run', 'requests_used', 21, 'request_budget'),
    ('run', 'requests_used', -1, 'request_budget'),
    ('plan', 'max_elapsed_ms', 0, 'duration_budget'),
    ('run', 'elapsed_ms', 40_001, 'duration_budget'),
    ('run', 'elapsed_ms', -1, 'duration_budget'),
    ('plan', 'sample_size', 0, 'selected_rows_accounted'),
    ('plan', 'followup_delay_ms', 14_999, 'declared_followup_delay'),
    ('run', 'selected_count', 0, 'selected_rows_accounted'),
    ('run', 'selected_count', 2, 'selected_rows_accounted'),
    ('run', 'open_gaps', 1, 'no_open_gaps'),
    ('run', 'open_gaps', -1, 'no_open_gaps'),
    ('run', 'financial_methods_used', ['sendTransaction'], 'no_financial_methods'),
    ('policy', 'max_snapshot_age_ms', 0, 'declared_snapshot_age_bound'),
    ('policy', 'max_snapshot_age_ms', 5_001, 'declared_snapshot_age_bound'),
    ('candidate', 'coherent_snapshot_count', 1, 'coherent_snapshot_periods'),
    ('candidate', 'snapshot_source_age_ms', -1, 'snapshot_source_freshness'),
    ('candidate', 'snapshot_source_age_ms', 5_001, 'snapshot_source_freshness'),
])
def test_explicit_broken_requirement_fails_its_gate(section, field, state, name):
    value = manifest()
    (value['candidates'][0] if section == 'candidate' else value[section])[field] = state
    report = evaluate_readiness(value)
    assert criterion(report, name)['status'] == 'FAIL'
    assert report['p3_go'] is False
    assert report['reasons']


@pytest.mark.parametrize('section,field,name', [
    ('plan', 'registered_at_ms', 'preregistration'),
    ('plan', 'started_at_ms', 'preregistration'),
    ('plan', 'max_requests', 'request_budget'),
    ('run', 'requests_used', 'request_budget'),
    ('plan', 'max_elapsed_ms', 'duration_budget'),
    ('run', 'elapsed_ms', 'duration_budget'),
    ('plan', 'sample_size', 'selected_rows_accounted'),
    ('plan', 'followup_delay_ms', 'declared_followup_delay'),
    ('run', 'selected_count', 'selected_rows_accounted'),
    ('run', 'open_gaps', 'no_open_gaps'),
    ('policy', 'max_snapshot_age_ms', 'declared_snapshot_age_bound'),
    ('candidate', 'coherent_snapshot_count', 'coherent_snapshot_periods'),
    ('candidate', 'snapshot_source_age_ms', 'snapshot_source_freshness'),
])
@pytest.mark.parametrize('state', [None, True, '1', 1.0, float('nan')])
def test_numeric_evidence_never_coerces_strings_floats_or_booleans(section, field, name, state):
    value = manifest()
    (value['candidates'][0] if section == 'candidate' else value[section])[field] = state
    report = evaluate_readiness(value)
    assert criterion(report, name)['status'] == 'UNKNOWN'
    assert report['p3_go'] is False
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('state', [None, False, '', 0, {}])
def test_financial_method_evidence_requires_explicit_list(state):
    value = manifest()
    value['run']['financial_methods_used'] = state
    report = evaluate_readiness(value)
    assert criterion(report, 'no_financial_methods')['status'] == 'UNKNOWN'
    assert report['p3_go'] is False


def test_zero_candidates_cannot_pass_by_vacuous_all_checks():
    value = manifest()
    value['candidates'] = []
    value['run']['selected_count'] = 0
    report = evaluate_readiness(value)
    assert report['collection_readiness'] == report['economic_readiness'] == 'NO-GO'
    assert criterion(report, 'creation_verified')['status'] == 'UNKNOWN'


@pytest.mark.parametrize('bad_row', [None, [], 'mint', {}, {'mint': 'other-mint'}])
def test_every_selected_row_is_checked_including_malformed_rows(bad_row):
    value = manifest()
    value['plan']['sample_size'] = value['run']['selected_count'] = 2
    value['candidates'].append(bad_row)
    report = evaluate_readiness(value)
    creation = criterion(report, 'creation_verified')
    assert creation['status'] == 'UNKNOWN'
    assert creation['evidence_count'] == 1
    assert creation['required_count'] == 2
    assert report['p3_go'] is False


def test_duplicate_mint_does_not_inflate_candidate_coverage():
    value = manifest()
    value['plan']['sample_size'] = value['run']['selected_count'] = 2
    value['candidates'].append(deepcopy(value['candidates'][0]))
    report = evaluate_readiness(value)
    assert criterion(report, 'selected_mint_identity')['status'] == 'FAIL'
    assert report['p3_go'] is False


def test_more_than_one_candidate_requires_every_candidate_to_pass():
    value = manifest()
    value['plan']['sample_size'] = value['run']['selected_count'] = 2
    value['candidates'].append(deepcopy(value['candidates'][0]))
    value['candidates'][1]['mint'] = 'second-synthetic-mint'
    value['candidates'][1]['fees_complete'] = False
    report = evaluate_readiness(value)
    assert report['collection_readiness'] == 'GO'
    assert criterion(report, 'fees_complete')['evidence_count'] == 1
    assert criterion(report, 'fees_complete')['required_count'] == 2
    assert report['economic_readiness'] == 'NO-GO'


def test_tighter_preregistered_age_bound_is_respected_at_exact_boundary():
    value = manifest()
    value['policy']['max_snapshot_age_ms'] = 1_000
    value['candidates'][0]['snapshot_source_age_ms'] = 1_000
    value['candidates'][0]['snapshots'][0]['source_time_ms'] = 10
    value['candidates'][0]['snapshots'][1]['source_time_ms'] = 15_000
    assert evaluate_readiness(value)['p3_go'] is True
    value['candidates'][0]['snapshot_source_age_ms'] += 1
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_source_freshness')['status'] == 'FAIL'
    assert MAX_SNAPSHOT_AGE_MS == 5_000


@pytest.mark.parametrize('snapshots,expected', [
    (None, 'UNKNOWN'), (False, 'UNKNOWN'), ({}, 'UNKNOWN'),
    ([], 'FAIL'), ([{}], 'FAIL'),
])
def test_snapshot_period_evidence_is_required(snapshots, expected):
    value = manifest()
    value['candidates'][0]['snapshots'] = snapshots
    report = evaluate_readiness(value)
    assert criterion(report, 'coherent_snapshot_periods')['status'] == expected
    assert report['economic_readiness'] == 'NO-GO'
    assert report['collection_readiness'] == 'GO'


def test_omitted_snapshot_list_cannot_be_replaced_by_true_attestations():
    value = manifest()
    del value['candidates'][0]['snapshots']
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'UNKNOWN'
    assert report['p3_go'] is False


@pytest.mark.parametrize('field', ['context_slot', 'received_at_ms', 'available_at_ms',
    'analysis_at_ms', 'source_time_ms', 'coherent'])
@pytest.mark.parametrize('state', [None, 1.0, '1', float('nan')])
def test_invalid_snapshot_fields_are_unknown(field, state):
    value = manifest()
    value['candidates'][0]['snapshots'][0][field] = state
    report = evaluate_readiness(value)
    name = 'snapshot_source_time_evidence' if field == 'source_time_ms' else 'snapshot_temporal_evidence'
    assert criterion(report, name)['status'] == 'UNKNOWN'
    assert report['p3_go'] is False
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('field', ['context_slot', 'received_at_ms', 'available_at_ms',
    'analysis_at_ms', 'source_time_ms'])
def test_snapshot_timestamps_and_slots_reject_boolean_integer_aliases(field):
    value = manifest()
    value['candidates'][0]['snapshots'][0][field] = True
    report = evaluate_readiness(value)
    name = 'snapshot_source_time_evidence' if field == 'source_time_ms' else 'snapshot_temporal_evidence'
    assert criterion(report, name)['status'] == 'UNKNOWN'
    assert report['p3_go'] is False


@pytest.mark.parametrize('period,field,state', [
    (0, 'context_slot', -1),
    (0, 'received_at_ms', -1),
    (0, 'available_at_ms', 999),
    (0, 'analysis_at_ms', 1_004),
    (0, 'coherent', False),
    (1, 'context_slot', 10),
    (1, 'context_slot', 9),
    (1, 'received_at_ms', 15_999),
])
def test_contradictory_snapshot_periods_fail(period, field, state):
    value = manifest()
    value['candidates'][0]['snapshots'][period][field] = state
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'FAIL'
    assert report['p3_go'] is False


def test_source_timestamp_after_receipt_fails_even_with_positive_aggregate_age():
    value = manifest()
    value['candidates'][0]['snapshots'][0]['source_time_ms'] = 1_001
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_source_time_evidence')['status'] == 'FAIL'
    assert report['p3_go'] is False


def test_observation_cannot_predate_campaign_start():
    value = manifest()
    value['plan']['started_at_ms'] = 1_001
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'FAIL'


def test_previous_analysis_must_finish_before_the_next_observation():
    value = manifest()
    value['candidates'][0]['snapshots'][0]['analysis_at_ms'] = 16_001
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'FAIL'


def test_count_must_match_retained_periods_and_duplicate_cannot_supply_followup():
    value = manifest()
    value['candidates'][0]['coherent_snapshot_count'] = 3
    report = evaluate_readiness(value)
    assert criterion(report, 'coherent_snapshot_periods')['status'] == 'FAIL'
    value['candidates'][0]['snapshots'].append(deepcopy(value['candidates'][0]['snapshots'][1]))
    report = evaluate_readiness(value)
    assert criterion(report, 'coherent_snapshot_periods')['status'] == 'PASS'
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'FAIL'
    assert report['p3_go'] is False


def test_declared_age_cannot_mask_old_retained_source_data():
    value = manifest()
    value['candidates'][0]['snapshots'][1]['source_time_ms'] = 10_999
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_source_freshness')['status'] == 'FAIL'
    assert report['p3_go'] is False


def test_tighter_declared_period_spacing_is_enforced():
    value = manifest()
    value['plan']['followup_delay_ms'] = 15_001
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'FAIL'
    assert MIN_FOLLOWUP_DELAY_MS == 15_000


def test_analysis_cannot_occur_after_the_declared_completed_collection():
    value = manifest()
    value['run']['elapsed_ms'] = 15_799
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'FAIL'
    assert report['p3_go'] is False


def test_followup_cannot_be_longer_than_the_entire_preregistered_collection():
    value = manifest()
    value['plan']['followup_delay_ms'] = 40_001
    report = evaluate_readiness(value)
    assert criterion(report, 'declared_followup_delay')['status'] == 'FAIL'


def test_fresh_at_receipt_does_not_allow_analysis_after_source_freshness_expires():
    value = manifest()
    value['candidates'][0]['snapshots'][1]['available_at_ms'] = 20_000
    value['candidates'][0]['snapshots'][1]['analysis_at_ms'] = 20_200
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_source_freshness')['status'] == 'PASS'
    assert criterion(report, 'snapshot_temporal_evidence')['status'] == 'PASS'
    assert criterion(report, 'snapshot_decision_freshness')['status'] == 'FAIL'
    assert report['economic_readiness'] == 'NO-GO'
    assert report['collection_readiness'] == 'GO'


def test_missing_source_time_cannot_be_replaced_by_the_aggregate_age():
    value = manifest()
    value['candidates'][0]['snapshots'][1]['source_time_ms'] = None
    report = evaluate_readiness(value)
    assert criterion(report, 'snapshot_source_time_evidence')['status'] == 'UNKNOWN'
    assert criterion(report, 'snapshot_decision_freshness')['status'] == 'UNKNOWN'
    assert report['p3_go'] is False


def test_gap_and_reference_failures_preserve_bounded_collection_readiness():
    value = manifest()
    value['run']['open_gaps'] = 1
    value['run']['independent_reference_complete'] = False
    report = evaluate_readiness(value)
    assert report['collection_readiness'] == 'GO'
    assert report['economic_readiness'] == 'NO-GO'
    assert report['economic_verdict'] == 'INSUFFICIENT DATA'
