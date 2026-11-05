"""Concrete RPC/scanner evidence contracts, with isolated raw-account fixtures.

No network, real wallet, code approval, signature or blockchain transaction is
performed. The synthetic ELF tests hash/layout binding, not executable validity.
"""
import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace
import struct

import pytest

from bot.live.evidence import (
    AntiRugEvidence, ClockOffsetEvidence, DeploymentPin, FreshAdmissionEvidence,
    UPGRADEABLE_LOADER, verify_deployment,
)
from bot.live.route import build_launchlab_order
from bot.live.safety import AuthorizationEnvelope, AdmissionRequest, HealthEvidence
from bot.p3.certification import PROGRAM, _decode, _encode, find_program_address
from bot.scanner.supervision import ScannerHealth
from test_live_wire_route import route_request


GENESIS = _encode(bytes([12])*32)
ENDPOINT = 'a'*64


def _raw_account(data, *, executable):
    return dict(data=[base64.b64encode(data).decode(), 'base64'],
                owner=UPGRADEABLE_LOADER, executable=executable, lamports=1_000_000)


def deployment_fixture():
    programdata = find_program_address((_decode(PROGRAM),), UPGRADEABLE_LOADER)[0]
    authority = _encode(bytes([81])*32)
    elf = b'\x7fELF'+bytes(60)
    pin = DeploymentPin(PROGRAM, programdata, hashlib.sha256(elf).hexdigest(),
        100, authority, 900, 'ISOLATED-reviewer', 'ISOLATED-code-review-receipt', 'b'*64)
    program = _raw_account(struct.pack('<I', 2)+_decode(programdata), executable=True)
    data = _raw_account(struct.pack('<IQB', 3, 100, 1)+_decode(authority)+elf, executable=False)
    return pin, program, data


def authorized_envelope(wallet):
    return AuthorizationEnvelope(authorization_id='ISOLATED-owner-receipt',
        approved_by='ISOLATED-owner', cluster='mainnet-beta', genesis_hash=GENESIS,
        wallet=wallet, rpc_endpoint_sha256=ENDPOINT, allowed_programs=(PROGRAM,),
        issued_at_ms=900, expires_at_ms=10000, max_capital_lamports=1_000_000_000,
        max_entry_lamports=200_000_000, max_daily_spend_lamports=2_000_000_000,
        max_daily_loss_lamports=100_000_000, max_open_positions=4, max_in_flight_orders=3,
        max_slippage_bps=200, max_price_impact_bps=2000,
        max_network_fee_lamports=10000, max_priority_fee_lamports=1000,
        max_compute_units=200000, max_quote_age_ms=5000, max_health_age_ms=1000,
        max_clock_skew_ms=100, max_consecutive_failures=3)


class FixtureRpc:
    endpoint_sha256 = ENDPOINT

    def __init__(self, bank):
        self.bank = bank
        self.slot = 1300
        self.calls = []
        self.genesis = GENESIS
        self.rent = 2_039_280

    async def get_multiple_accounts(self, addresses, *, min_context_slot):
        self.calls.append(('getMultipleAccounts', tuple(addresses), min_context_slot))
        return dict(context=dict(slot=self.slot), value=[deepcopy(self.bank[a]) for a in addresses])

    async def genesis_hash(self):
        self.calls.append(('getGenesisHash',))
        return self.genesis

    async def rent_exemption(self, size):
        self.calls.append(('getMinimumBalanceForRentExemption', size))
        assert size == 165
        return self.rent


def exercise(assertion, *, side='BUY'):
    async def scenario():
        parameters = route_request(side)
        order = build_launchlab_order(**parameters)
        pin, program, data = deployment_fixture()
        bank = deepcopy(parameters['accounts'])
        bank[PROGRAM], bank[pin.programdata_address] = program, data
        rpc = FixtureRpc(bank)
        now = [1100]
        health = ScannerHealth(require_observations=True,
            clock_ms=lambda: now[0], monotonic_ms=lambda: now[0])
        task = health.start_task(asyncio.Event().wait(), 'ISOLATED-scanner-task')
        health.observe_rpc(True)
        health.observe_websocket('subscribed')
        anti = AntiRugEvidence(parameters['decision_id'], order.mint, order.pool,
            order.source_account_digest, 1100, (), 'c'*64)
        clock = ClockOffsetEvidence(0, 1100, 'ISOLATED-measured-clock', 'd'*64)
        value = SimpleNamespace(parameters=parameters, order=order, pin=pin, bank=bank,
            rpc=rpc, now=now, health=health, task=task, anti=anti, clock=clock)
        value.provider = FreshAdmissionEvidence(rpc=rpc,
            envelope=authorized_envelope(order.user), scanner_health=health,
            deployment_pin=pin, anti_rug_provider=lambda *_: value.anti,
            clock_offset_provider=lambda: value.clock, clock_ms=lambda: now[0])
        try:
            return await assertion(value)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return asyncio.run(scenario())


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_real_provider_contract_uses_raw_group_bank_deployment_and_actual_supervision(side):
    async def check(value):
        order = value.order
        request, health = await value.provider(value.parameters['decision_id'], order)
        assert type(request) is AdmissionRequest and type(health) is HealthEvidence
        assert request.quote_context_slot == order.source_slot
        assert request.observed_bank_slot == 1300 > order.source_slot
        assert request.quote_received_at_ms == 1000  # NEVER re-stamped at 1100.
        assert request.risk_checked_at_ms == 1100
        assert health.scanner_heartbeat_at_ms == 1100
        assert health.rpc_success_at_ms == 1100
        assert request.identity_verified and request.route_verified and request.costs_known
        assert request.exit_capacity_atomic == (order.expected_output if side == 'BUY' else order.input_amount)
        assert request.price_impact_bps == order.price_impact_bps
        assert [x[0] for x in value.rpc.calls] == [
            'getMultipleAccounts', 'getGenesisHash', 'getMinimumBalanceForRentExemption']
        assert value.rpc.calls[0][-1] == order.source_slot
        assert len(value.rpc.calls[0][1]) == 12
        assert value.provider.last_assessment['realized_market_execution'] is False
    exercise(check, side=side)


def test_provider_keeps_existing_heartbeat_clocks_instead_of_retiming_them():
    async def check(value):
        value.now[0] = 1200
        value.clock = replace(value.clock, observed_at_ms=1200)
        value.anti = replace(value.anti, checked_at_ms=1200)
        _, health = await value.provider(value.parameters['decision_id'], value.order)
        assert health.observed_at_ms == 1200
        assert (health.scanner_heartbeat_at_ms, health.rpc_success_at_ms,
                health.websocket_heartbeat_at_ms) == (1100, 1100, 1100)
    exercise(check)


@pytest.mark.parametrize('role', ['pool', 'mint', 'wallet', 'base_ATA', 'WSOL'])
def test_any_changed_market_or_user_account_requires_explicit_reprepare(role):
    async def check(value):
        order = value.order
        address = {'pool': order.pool, 'mint': order.mint, 'wallet': order.user,
                   'base_ATA': order.base_token_account, 'WSOL': order.quote_token_account}[role]
        if value.bank[address] is None:
            value.bank[address] = dict(lamports=1)
        else:
            value.bank[address]['lamports'] += 1
        with pytest.raises(ValueError, match='raw_account_changed'):
            await value.provider(value.parameters['decision_id'], order)
        assert len(value.rpc.calls) == 1
        assert value.provider.last_assessment is None
    exercise(check)


def test_json_numeric_type_change_is_not_treated_as_equal_atomic_balance():
    async def check(value):
        value.bank[value.order.user]['lamports'] = float(value.bank[value.order.user]['lamports'])
        with pytest.raises(ValueError, match='raw_account_changed'):
            await value.provider(value.parameters['decision_id'], value.order)
    exercise(check)


def test_missing_independently_approved_code_pin_stops_before_RPC():
    async def check(value):
        value.provider.deployment_pin = None
        with pytest.raises(ValueError, match='approved_deployment_pin'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.rpc.calls == []
    exercise(check)


@pytest.mark.parametrize('mutation,reason', [
    ('program_owner', 'owner_or_execution'), ('program_executable', 'owner_or_execution'),
    ('programdata_owner', 'owner_or_execution'), ('programdata_executable', 'owner_or_execution'),
    ('program_link', 'programdata_binding'), ('ELF', 'approved_code'),
    ('deployment_slot', 'slot_or_upgrade_authority'), ('authority', 'slot_or_upgrade_authority'),
])
def test_deployment_tampering_or_upgrade_never_auto_approves_observed_hash(mutation, reason):
    async def check(value):
        program = value.bank[PROGRAM]
        data = value.bank[value.pin.programdata_address]
        if mutation.endswith('_owner'):
            (program if mutation.startswith('program_') else data)['owner'] = value.order.user
        elif mutation.endswith('_executable'):
            (program if mutation.startswith('program_') else data)['executable'] ^= True
        else:
            target = program if mutation == 'program_link' else data
            raw = bytearray(base64.b64decode(target['data'][0]))
            index = {'program_link': 4, 'ELF': 60, 'deployment_slot': 4, 'authority': 13}[mutation]
            raw[index] ^= 1
            target['data'][0] = base64.b64encode(raw).decode()
        with pytest.raises(ValueError, match=reason):
            await value.provider(value.parameters['decision_id'], value.order)
        assert len(value.rpc.calls) == 1
    exercise(check)


@pytest.mark.parametrize('failure', ['rpc_disconnected', 'websocket_disconnected', 'failed_scanner', 'stale_services'])
def test_actual_supervision_refuses_unavailable_or_stale_services_before_RPC(failure):
    async def check(value):
        if failure == 'rpc_disconnected':
            value.health.observe_rpc(False)
        elif failure == 'websocket_disconnected':
            value.health.observe_websocket('disconnected')
        elif failure == 'failed_scanner':
            value.health.fail('ISOLATED-failure')
        else:
            value.now[0] += 1001
            value.clock = replace(value.clock, observed_at_ms=value.now[0])
        with pytest.raises(ValueError, match='scanner_services'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.rpc.calls == []
    exercise(check)


@pytest.mark.parametrize('clock', [None, 0, True, '0'])
def test_unknown_or_unproven_clock_offset_never_defaults_to_zero(clock):
    async def check(value):
        value.clock = clock
        with pytest.raises(ValueError, match='clock_offset_unknown'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.rpc.calls == []
    exercise(check)


@pytest.mark.parametrize('field,replacement', [
    ('offset_ms', 101), ('observed_at_ms', 1101), ('observed_at_ms', 99),
])
def test_measured_clock_skew_or_staleness_is_rejected(field, replacement):
    async def check(value):
        value.clock = replace(value.clock, **{field: replacement})
        with pytest.raises(ValueError, match='clock_offset_unknown'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.rpc.calls == []
    exercise(check)


@pytest.mark.parametrize('field,replacement', [
    ('source_account_digest', 'e'*64), ('decision_id', 'different-decision'),
    ('checked_at_ms', 999), ('checked_at_ms', 1101), ('reasons', ('creator_risk',)),
])
def test_anti_rug_evidence_must_be_causal_source_bound_and_admissible(field, replacement):
    async def check(value):
        value.anti = replace(value.anti, **{field: replacement})
        with pytest.raises(ValueError, match='anti_rug'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.rpc.calls == []
    exercise(check)


@pytest.mark.parametrize('failure,reason,expected_calls', [
    ('bank_slot', 'before_quote_slot', 1), ('genesis', 'genesis_differs', 2),
    ('rent', 'rent_differs', 3), ('endpoint', 'endpoint_binding', 0),
])
def test_real_RPC_binding_slot_cluster_rent_and_endpoint_are_rechecked(failure, reason, expected_calls):
    async def check(value):
        if failure == 'bank_slot': value.rpc.slot = value.order.source_slot-1
        elif failure == 'genesis': value.rpc.genesis = _encode(bytes([21])*32)
        elif failure == 'rent': value.rpc.rent += 1
        elif failure == 'endpoint': value.rpc.endpoint_sha256 = 'e'*64
        with pytest.raises(ValueError, match=reason):
            await value.provider(value.parameters['decision_id'], value.order)
        assert len(value.rpc.calls) == expected_calls
    exercise(check)


def test_stale_original_quote_is_not_revived_by_fresh_RPC_or_clock_evidence():
    async def check(value):
        value.now[0] = 6001
        value.clock = replace(value.clock, observed_at_ms=value.now[0])
        with pytest.raises(ValueError, match='original_quote_stale'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.rpc.calls == []
    exercise(check)


def test_later_assessment_failure_clears_previous_success_receipt():
    async def check(value):
        await value.provider(value.parameters['decision_id'], value.order)
        assert value.provider.last_assessment is not None
        value.bank[value.order.pool]['lamports'] += 1
        with pytest.raises(ValueError, match='raw_account_changed'):
            await value.provider(value.parameters['decision_id'], value.order)
        assert value.provider.last_assessment is None
    exercise(check)


def test_trusted_deployment_pin_requires_canonical_address_and_source_receipt():
    pin, program, data = deployment_fixture()
    assert verify_deployment(program, data, pin, observed_slot=1300, now_ms=1100)['elf_sha256'] == pin.elf_sha256
    for change in (dict(programdata_address=_encode(bytes([91])*32)),
                   dict(elf_sha256=''), dict(source_sha256=''), dict(source_reference=''),
                   dict(source_reference=' '), dict(approved_by=' ')):
        with pytest.raises(ValueError):
            replace(pin, **change)
    with pytest.raises(ValueError, match='not_yet_available'):
        verify_deployment(program, data, replace(pin, approved_at_ms=1101), observed_slot=1300, now_ms=1100)


def test_immutable_programdata_layout_does_not_assume_authority_bytes_exist():
    pin, program, data = deployment_fixture()
    raw = bytearray(base64.b64decode(data['data'][0]))
    raw[12] = 0
    # ProgramData executable byte offset remains 45 even for Option::None.
    data['data'][0] = base64.b64encode(raw).decode()
    result = verify_deployment(program, data, replace(pin, upgrade_authority=None), observed_slot=1300, now_ms=1100)
    assert result['deployment_slot'] == 100


@pytest.mark.parametrize('failure', ['websocket', 'rpc', 'task', 'clock', 'envelope', 'pin'])
def test_synchronous_final_gate_observes_failures_after_successful_async_assessment(failure):
    async def check(value):
        await value.provider(value.parameters['decision_id'], value.order)
        calls = len(value.rpc.calls)
        assert value.provider.assert_operational_now().scanner_connected
        if failure == 'websocket':
            value.health.observe_websocket('disconnected')
        elif failure == 'rpc':
            value.health.observe_rpc(False)
        elif failure == 'task':
            value.task.cancel()
        elif failure == 'clock':
            # New service callbacks do not refresh the independent clock proof.
            value.now[0] += 1001
            value.health.observe_rpc(True)
            value.health.observe_websocket('subscribed')
        elif failure == 'envelope':
            value.provider.envelope = replace(value.provider.envelope, max_entry_lamports=199_000_000)
        else:
            value.provider.deployment_pin = None
        with pytest.raises(ValueError):
            value.provider.assert_operational_now()
        assert len(value.rpc.calls) == calls  # Final gate issues no traffic.
    exercise(check)


def test_synchronous_final_gate_cannot_be_used_before_successful_assessment():
    async def check(value):
        with pytest.raises(ValueError, match='no_successful_current'):
            value.provider.assert_operational_now()
        assert value.rpc.calls == []
    exercise(check)
