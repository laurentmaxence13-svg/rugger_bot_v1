"""P3-012 preregistration cannot be changed retroactively or launch network."""
from copy import deepcopy
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
    assert p['max_S0_receipt_age_ms']>=p['first_interval_minimum_ms']
    assert p['max_S1_receipt_age_ms']<p['max_S0_receipt_age_ms']
    assert p['snapshots']==('S0_predecision','S1_predecision','S2_postdecision')
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
