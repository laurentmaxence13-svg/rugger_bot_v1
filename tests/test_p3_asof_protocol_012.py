"""P3-012 preregistration cannot be changed retroactively or launch network."""
from copy import deepcopy
import json
import pytest

from bot.p3.asof_protocol_012 import FIXED,make_plan,validate_plan


def test_plan_binds_budget_selection_and_research_only():
    p=make_plan(registered_at_ms=1000,source_revision='a'*40)
    original=deepcopy(p)
    digest=validate_plan(p,first_observation_at_ms=1001)
    assert len(digest)==64
    assert p==original
    assert sum(p['request_budget'].values())==20
    assert p['unique_native_SOL_prefix']==12
    assert p['snapshots']==['S0_predecision','S1_predecision','S2_postdecision']
    assert p['selection_known_before_S2']
    assert not p['provider_quotes_authorized']
    assert not p['external_orders_authorized']
    assert not p['ledger_mutation'] and not p['trade_allowed']
    assert p['own_buy_impact_on_actual_S2'].startswith('unmodeled')


@pytest.mark.parametrize('field,value',[
    ('max_requests',21),('unique_native_SOL_prefix',13),
    ('selection_known_before_S2',False),('provider_quotes_authorized',True),
    ('ledger_mutation',True),('no_retry',False),('request_budget',{}),
    ('second_interval_minimum_ms',0)])
def test_published_plan_may_not_be_mutated_after_registration(field,value):
    p=make_plan(registered_at_ms=1000,source_revision='b'*40)
    p[field]=value
    with pytest.raises(ValueError,match='altered_or_unsupported'):
        validate_plan(p)


def test_capture_must_follow_registration_and_commit_is_exact():
    p=make_plan(registered_at_ms=1000,source_revision='b'*40)
    with pytest.raises(ValueError,match='first_observation_must_follow'):
        validate_plan(p,first_observation_at_ms=1000)
    with pytest.raises(ValueError):
        make_plan(registered_at_ms=1000,source_revision='not_a_real_commit')


def test_exact_published_JSON_roundtrip_retains_the_same_immutable_plan():
    plan=make_plan(registered_at_ms=1000,source_revision='a'*40)
    assert validate_plan(json.loads(json.dumps(plan)))==validate_plan(plan)
    assert plan['max_S0_receipt_age_at_decision_ms']>plan['first_interval_minimum_ms']
    assert sum(plan['request_budget'].values())==20
    assert plan['provider_quotes_authorized'] is False


@pytest.mark.parametrize('mutation',[
    lambda p:p.__setitem__('max_requests',20.0),
    lambda p:p.__setitem__('provider_quotes_authorized',0),
    lambda p:p.__setitem__('primary_model_input_lamports',100000000.0),
    lambda p:p['cost_assumptions'].__setitem__('buy_signatures',True),
    lambda p:p['request_budget'].__setitem__('discovery',1.0),
    lambda p:p.__setitem__('snapshots',tuple(p['snapshots'])),
    lambda p:p['snapshots'].append('unregistered_S3'),
    lambda p:p['position_sizes_lamports'].__setitem__(0,100000000.0),
])
def test_exact_JSON_types_and_array_shape_cannot_alias_the_registered_plan(mutation):
    plan=make_plan(registered_at_ms=1000,source_revision='a'*40)
    mutation(plan)
    with pytest.raises(ValueError,match='altered_or_unsupported'):
        validate_plan(plan)
