"""Financial limits are explicit, exact, bound to fresh evidence and fail closed."""
from dataclasses import replace
import json

import pytest

from bot.live.safety import (
    AdmissionRequest, ArmingState, AuthorizationEnvelope, HealthEvidence,
    InventoryPosition, Mode, RiskSnapshot, UINT64_MAX, arm, arming_from_record, enable,
    evaluate_admission,
)
from bot.p3.certification import _encode


WALLET = _encode(bytes([11])*32)
GENESIS = _encode(bytes([12])*32)
PROGRAM = _encode(bytes([13])*32)
MINT = _encode(bytes([14])*32)
POOL = _encode(bytes([15])*32)
ENDPOINT = 'a'*64
NOW = 2000


def envelope(**changes):
    value = AuthorizationEnvelope(
        authorization_id='fixture-owner-authorization', approved_by='test-owner',
        cluster='mainnet-beta', genesis_hash=GENESIS, wallet=WALLET,
        rpc_endpoint_sha256=ENDPOINT, allowed_programs=(PROGRAM,),
        issued_at_ms=1000, expires_at_ms=10000,
        max_capital_lamports=2_000_000, max_entry_lamports=200_000,
        max_daily_spend_lamports=4_000_000, max_daily_loss_lamports=100_000,
        max_open_positions=4, max_in_flight_orders=2, max_slippage_bps=300,
        max_price_impact_bps=500,
        max_network_fee_lamports=10_000, max_priority_fee_lamports=5_000,
        max_compute_units=1_000_000, max_quote_age_ms=500, max_health_age_ms=1000,
        max_clock_skew_ms=100, max_consecutive_failures=3,
    )
    return replace(value, **changes)


def request(**changes):
    value = AdmissionRequest(
        decision_id='fixture-decision', side='buy', wallet=WALLET,
        cluster='mainnet-beta', genesis_hash=GENESIS,
        rpc_endpoint_sha256=ENDPOINT, program_id=PROGRAM, mint=MINT, pool=POOL,
        quote_source_id='fixture-raw-bank', quote_payload_sha256='b'*64,
        route_message_sha256='c'*64, quote_received_at_ms=1900,
        risk_checked_at_ms=1950, quote_context_slot=100, observed_bank_slot=100,
        amount_in_atomic=100_000, quote_input_atomic=100_000,
        quote_output_atomic=50_000, minimum_out_atomic=49_500,
        network_fee_upper_lamports=6_000, priority_fee_lamports=1_000,
        compute_units=200_000, slippage_bps=100, price_impact_bps=250,
        rent_deposit_upper_lamports=0, exit_capacity_atomic=50_000,
        identity_verified=True, route_verified=True, costs_known=True,
        anti_rug_reasons=(),
    )
    return replace(value, **changes)


def health(**changes):
    value = HealthEvidence(observed_at_ms=1950, scanner_heartbeat_at_ms=1900,
        rpc_success_at_ms=1950, websocket_heartbeat_at_ms=1940,
        scanner_connected=True, rpc_connected=True, websocket_connected=True,
        rpc_genesis_hash=GENESIS, rpc_endpoint_sha256=ENDPOINT, clock_offset_ms=0)
    return replace(value, **changes)


def risk(**changes):
    value = RiskSnapshot(observed_at_ms=1950, wallet_balance_lamports=10_000_000,
        reserved_lamports=0, capital_at_risk_lamports=0, day_spent_lamports=0,
        realized_daily_loss_lamports=0, pending_loss_lamports=0,
        open_positions=0, in_flight_orders=0, consecutive_failures=0,
        unresolved_orders=0, kill_switch=False, positions=())
    return replace(value, **changes)


def activation(env=None):
    env = env or envelope()
    armed = arm(env, now_ms=1500, arm_receipt='fixture-operator-arm')
    return enable(env, armed, now_ms=1600, enable_receipt='fixture-operator-enable')


def check(req=None, *, env=None, armed=None, service=None, book=None, now=NOW,
          require_enabled=True):
    env = env or envelope()
    return evaluate_admission(req or request(), envelope=env,
        arming=armed or activation(env), health=service or health(),
        risk=book or risk(), now_ms=now, require_enabled=require_enabled)


def test_no_owner_authorization_or_automatic_arm_is_possible():
    assert not evaluate_admission(request(), envelope=None, arming=None,
        health=health(), risk=risk(), now_ms=NOW).allowed
    result = evaluate_admission(request(), envelope=envelope(), arming=None,
        health=health(), risk=risk(), now_ms=NOW)
    assert result.reasons == ('explicit_arm_and_enable_required',)
    armed = arm(envelope(), now_ms=1500, arm_receipt='arm')
    assert armed.mode == Mode.LIVE_ARMED
    assert not check(armed=armed).allowed


def test_two_distinct_actions_bind_exact_authorization_and_current_scope():
    env = envelope()
    armed = arm(env, now_ms=1500, arm_receipt='arm')
    with pytest.raises(ValueError, match='distinct_enable'):
        enable(env, armed, now_ms=1600, enable_receipt='arm')
    with pytest.raises(ValueError, match='matching_explicit_arm'):
        enable(replace(env, max_entry_lamports=199_999), armed,
               now_ms=1600, enable_receipt='enable')
    with pytest.raises(ValueError, match='authorization_not_current'):
        enable(env, armed, now_ms=10_000, enable_receipt='enable')
    assert check().allowed
    assert check().cash_required_lamports == 106_000


@pytest.mark.parametrize('now', [999, 10_000, 10_001])
def test_authorization_expiry_is_half_open(now):
    assert check(now=now).reasons == ('authorization_not_current',)


def test_prepared_assessment_does_not_require_enabled_state():
    # This result is an assessment, not permission to sign or submit.
    assert evaluate_admission(request(), envelope=envelope(), arming=None,
        health=health(), risk=risk(), now_ms=NOW,
        require_enabled=False).allowed


@pytest.mark.parametrize('key,value', [
    ('max_capital_lamports', 0), ('max_entry_lamports', True),
    ('max_daily_loss_lamports', 0.5), ('max_daily_spend_lamports', -1),
    ('max_open_positions', '4'), ('max_slippage_bps', 10000),
    ('max_price_impact_bps', 10000), ('max_price_impact_bps', True),
    ('max_price_impact_bps', 1.0), ('max_price_impact_bps', -1),
    ('max_compute_units', 1_400_001), ('max_network_fee_lamports', 0),
    ('max_priority_fee_lamports', 10_001), ('expires_at_ms', 1000),
    ('issued_at_ms', UINT64_MAX+1), ('wallet', 'wallet-name'),
    ('rpc_endpoint_sha256', 'not-hash'), ('allowed_programs', ()),
])
def test_malformed_financial_scope_never_coerced(key, value):
    with pytest.raises(ValueError):
        envelope(**{key:value})


@pytest.mark.parametrize('key,value', [
    ('amount_in_atomic', True), ('amount_in_atomic', 100_000.0),
    ('minimum_out_atomic', 0), ('rent_deposit_upper_lamports', -1),
    ('network_fee_upper_lamports', 0), ('exit_capacity_atomic', UINT64_MAX+1),
    ('side', 'BUY'), ('quote_context_slot', 0), ('costs_known', 1),
    ('price_impact_bps', True), ('price_impact_bps', 1.0), ('price_impact_bps', -1),
    ('anti_rug_reasons', []), ('quote_payload_sha256', 'bad'),
])
def test_order_evidence_requires_native_exact_types(key, value):
    with pytest.raises(ValueError):
        request(**{key:value})


@pytest.mark.parametrize('changes,reason', [
    ({'wallet':_encode(bytes([16])*32)}, 'wallet_cluster_or_rpc_binding_mismatch'),
    ({'cluster':'devnet'}, 'wallet_cluster_or_rpc_binding_mismatch'),
    ({'rpc_endpoint_sha256':'d'*64}, 'wallet_cluster_or_rpc_binding_mismatch'),
    ({'program_id':_encode(bytes([16])*32)}, 'program_not_authorized'),
    ({'quote_received_at_ms':1499}, 'stale_or_future_quote'),
    ({'quote_received_at_ms':2001}, 'stale_or_future_quote'),
    ({'risk_checked_at_ms':999}, 'stale_or_future_health_or_risk'),
    ({'quote_context_slot':101}, 'quote_and_bank_slot_mismatch'),
    ({'identity_verified':False}, 'identity_route_or_anti_rug_unqualified'),
    ({'route_verified':False}, 'identity_route_or_anti_rug_unqualified'),
    ({'anti_rug_reasons':('mint_authority_live',)}, 'identity_route_or_anti_rug_unqualified'),
    ({'costs_known':False}, 'own_costs_unknown'),
    ({'quote_input_atomic':99_999}, 'exact_quote_input_mismatch'),
    ({'minimum_out_atomic':49_499}, 'minimum_output_or_slippage_violation'),
    ({'minimum_out_atomic':50_001}, 'minimum_output_or_slippage_violation'),
    ({'slippage_bps':301}, 'minimum_output_or_slippage_violation'),
    ({'price_impact_bps':501}, 'price_impact_limit'),
    ({'priority_fee_lamports':6000}, 'fee_limit'),
    ({'network_fee_upper_lamports':10_001}, 'fee_limit'),
    ({'compute_units':1_000_001}, 'compute_limit'),
    ({'exit_capacity_atomic':49_999}, 'exact_exit_capacity_unknown_or_insufficient'),
])
def test_each_safety_dimension_is_required(changes, reason):
    result = check(request(**changes))
    assert not result.allowed and reason in result.reasons


@pytest.mark.parametrize('changes,reason', [
    ({'scanner_connected':False}, 'service_disconnected'),
    ({'rpc_connected':False}, 'service_disconnected'),
    ({'websocket_connected':False}, 'service_disconnected'),
    ({'clock_offset_ms':101}, 'clock_skew_limit'),
    ({'clock_offset_ms':-101}, 'clock_skew_limit'),
    ({'rpc_success_at_ms':999}, 'stale_or_future_health_or_risk'),
    ({'websocket_heartbeat_at_ms':1951}, 'heartbeat_after_health_snapshot'),
    ({'observed_at_ms':2001}, 'stale_or_future_health_or_risk'),
    ({'rpc_genesis_hash':_encode(bytes([16])*32)}, 'wallet_cluster_or_rpc_binding_mismatch'),
])
def test_internal_health_must_be_current_and_bound(changes, reason):
    result = check(service=health(**changes))
    assert not result.allowed and reason in result.reasons


@pytest.mark.parametrize('changes,reason', [
    ({'kill_switch':True}, 'persistent_kill_switch'),
    ({'unresolved_orders':1}, 'unreconciled_submission'),
    ({'in_flight_orders':2}, 'in_flight_limit'),
    ({'consecutive_failures':3}, 'consecutive_failure_limit'),
    ({'wallet_balance_lamports':105_999}, 'insufficient_unreserved_cash'),
    ({'reserved_lamports':9_900_000}, 'insufficient_unreserved_cash'),
    ({'day_spent_lamports':3_900_000}, 'daily_spend_limit'),
    ({'capital_at_risk_lamports':1_900_000}, 'capital_limit'),
    ({'realized_daily_loss_lamports':94_000}, 'daily_loss_limit'),
    ({'pending_loss_lamports':94_000}, 'daily_loss_limit'),
])
def test_durable_accounting_and_protection_limits(changes, reason):
    result = check(book=risk(**changes))
    assert not result.allowed and reason in result.reasons


def test_reservations_count_towards_capital_daily_spend_and_cash():
    book = risk(reserved_lamports=1_900_000)
    assert 'capital_limit' in check(book=book).reasons
    book = replace(book, day_spent_lamports=2_000_000)
    assert 'daily_spend_limit' in check(book=book).reasons
    assert 'entry_limit' in check(env=envelope(max_entry_lamports=105_999)).reasons


def test_price_impact_limit_is_owner_bound_separately_from_slippage():
    assert check(request(price_impact_bps=500)).allowed
    assert 'price_impact_limit' in check(request(price_impact_bps=501)).reasons
    assert 'price_impact_limit' in check(request(price_impact_bps=1),
        env=envelope(max_price_impact_bps=0)).reasons
    assert check(request(price_impact_bps=0),env=envelope(max_price_impact_bps=0)).allowed
    changed=envelope(max_price_impact_bps=501)
    assert 'explicit_arm_and_enable_required' in check(env=changed,armed=activation()).reasons


def test_later_risk_bank_preserves_original_quote_clock_and_refuses_older_bank():
    assert check(request(observed_bank_slot=101)).allowed
    assert 'quote_and_bank_slot_mismatch' in check(request(observed_bank_slot=99)).reasons
    # A newer risk check cannot refresh an otherwise stale quote receipt.
    assert 'stale_or_future_quote' in check(request(observed_bank_slot=101,
        quote_received_at_ms=1499)).reasons


def test_position_count_is_reconciled_and_maximum_checked():
    positions = tuple(InventoryPosition(_encode(bytes([20+i])*32),
        _encode(bytes([30+i])*32), 5, 0) for i in range(4))
    assert 'open_position_limit' in check(book=risk(open_positions=4, positions=positions)).reasons
    with pytest.raises(ValueError, match='open_position_inventory_mismatch'):
        risk(open_positions=1)


def test_sell_is_reduce_only_without_reopening_risk_after_daily_loss():
    position = InventoryPosition(MINT, POOL, 50_000, 0)
    book = risk(open_positions=1, positions=(position,),
        realized_daily_loss_lamports=100_000, capital_at_risk_lamports=2_000_001)
    sale = request(side='sell', amount_in_atomic=50_000,
        quote_input_atomic=50_000, quote_output_atomic=110_000,
        minimum_out_atomic=108_900, exit_capacity_atomic=50_000)
    assert check(sale, book=book).allowed
    assert check(sale, book=book).cash_required_lamports == 6_000
    assert 'sell_exceeds_unreserved_inventory' in check(sale).reasons
    assert 'sell_exceeds_unreserved_inventory' in check(sale,
        book=replace(book, positions=(replace(position, reserved_atomic=1),))).reasons
    assert 'persistent_kill_switch' in check(sale, book=replace(book, kill_switch=True)).reasons
    assert 'daily_spend_limit' in check(sale,
        book=replace(book, day_spent_lamports=3_995_000)).reasons


def test_atomic_overflow_does_not_wrap_budget_to_affordable():
    result = check(request(amount_in_atomic=UINT64_MAX,
        quote_input_atomic=UINT64_MAX))
    assert not result.allowed and result.cash_required_lamports is None
    assert 'atomic_sum_overflow' in result.reasons


def test_explicit_receipt_replay_from_different_envelope_cannot_send():
    active = activation()
    assert not check(env=envelope(max_quote_age_ms=501), armed=active).allowed
    bad = replace(active, enabled_at_ms=NOW+1)
    assert not check(armed=bad).allowed


def test_authorization_and_arming_json_roundtrip_preserves_exact_scope():
    env = envelope()
    restored = AuthorizationEnvelope.from_record(json.loads(json.dumps(env.to_record())))
    assert restored == env and restored.digest == env.digest
    active = activation(env)
    assert arming_from_record(json.loads(json.dumps(active.to_record())),
        envelope=restored, now_ms=NOW) == active
    armed = arm(env, now_ms=1500, arm_receipt='arm')
    assert arming_from_record(armed.to_record(), envelope=env, now_ms=NOW) == armed


def test_resume_never_renews_expired_grant_or_accepts_changed_scope():
    env = envelope()
    record = activation(env).to_record()
    with pytest.raises(ValueError, match='authorization_not_current'):
        arming_from_record(record, envelope=env, now_ms=env.expires_at_ms)
    with pytest.raises(ValueError, match='does_not_match_authorization'):
        arming_from_record(record, envelope=replace(env, max_entry_lamports=123_000), now_ms=NOW)
    with pytest.raises(ValueError):
        arming_from_record(dict(record, enabled_at_ms=NOW+1), envelope=env, now_ms=NOW)
    with pytest.raises(ValueError):
        arming_from_record(dict(record, armed_at_ms=True), envelope=env, now_ms=NOW)
    with pytest.raises(ValueError):
        arming_from_record(dict(record, mode='SHADOW'), envelope=env, now_ms=NOW)


def test_authorization_record_exact_schema_and_no_numeric_coercion():
    record = envelope().to_record()
    for mutation in (dict(record, max_capital_lamports='2000000'),
                     dict(record, max_capital_lamports=True),
                     dict(record, unexpected_permission=True),
                     dict(record, allowed_programs=())):
        with pytest.raises(ValueError):
            AuthorizationEnvelope.from_record(mutation)
    bad = ArmingState(Mode.LIVE_ENABLED, envelope().digest,
        envelope().authorization_id, envelope().approved_by, 1500, 'same', 1600, 'same')
    assert not check(armed=bad).allowed
