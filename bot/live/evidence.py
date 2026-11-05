"""Concrete, fail-closed admission evidence from RPC and scanner supervision.

Construction performs no I/O and grants no financial authority. Invocation uses
only the injected RPC's bounded, authorized transport. Deployment hashes, clock
measurements and anti-rug decisions are supplied through trusted operational
boundaries; none is inferred, defaulted, or approved from the observation itself.
"""
import base64
from dataclasses import dataclass
import hashlib
import inspect
import json
import re
import struct
import time

from bot.live.route import validate_prepared_order
from bot.live.cpmm_exit import PreparedCpmmExit,validate_cpmm_exit
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.safety import AdmissionRequest, AuthorizationEnvelope, HealthEvidence
from bot.p3.certification import PROGRAM, _decode, find_program_address
from bot.p3 import launchlab
from bot.scanner.supervision import ScannerHealth


UPGRADEABLE_LOADER = 'BPFLoaderUpgradeab1e11111111111111111111111'
PROGRAMDATA_METADATA_BYTES = 45


def _uint(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        raise ValueError('evidence_exact_unsigned_integer_required')
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('evidence_sha256_required')


def _text(value):
    if (type(value) is not str or not 1 <= len(value) <= 512
            or value.strip() != value or not value.strip() or not value.isprintable()):
        raise ValueError('evidence_source_reference_required')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class DeploymentPin:
    """Trusted program/ABI fingerprint input, never auto-approved by fresh RPC.

    The operator supplies a configured deployed-byte fingerprint and official
    ABI review receipt before enabling execution. LaunchLab source is private:
    this is not a claim of source compilation or code audit. This object
    authenticates no reviewer;
    acceptance of that source receipt remains a trusted configuration boundary.
    Matching the observed hash certifies bytes at that bank, not absence of bugs
    or the impossibility of a later upgrade.
    """
    program_id: str
    programdata_address: str
    elf_sha256: str
    deployment_slot: int
    upgrade_authority: str | None
    approved_at_ms: int
    approved_by: str
    source_reference: str
    source_sha256: str

    def __post_init__(self):
        if self.program_id not in (PROGRAM,CPMM_PROGRAM):
            raise ValueError('only_pinned_LaunchLab_or_CPMM_program_supported')
        _decode(self.programdata_address)
        expected = find_program_address((_decode(self.program_id),), UPGRADEABLE_LOADER)[0]
        if self.programdata_address != expected:
            raise ValueError('noncanonical_programdata_address')
        _hash(self.elf_sha256); _hash(self.source_sha256)
        _uint(self.deployment_slot, positive=True); _uint(self.approved_at_ms, positive=True)
        if self.upgrade_authority is not None:
            _decode(self.upgrade_authority)
        _text(self.approved_by); _text(self.source_reference)


@dataclass(frozen=True)
class ClockOffsetEvidence:
    offset_ms: int
    observed_at_ms: int
    source_id: str
    evidence_sha256: str

    def __post_init__(self):
        if type(self.offset_ms) is not int or abs(self.offset_ms) >= 2**64:
            raise ValueError('measured_clock_offset_required')
        _uint(self.observed_at_ms, positive=True)
        _text(self.source_id); _hash(self.evidence_sha256)


@dataclass(frozen=True)
class AntiRugEvidence:
    decision_id: str
    mint: str
    pool: str
    source_account_digest: str
    checked_at_ms: int
    reasons: tuple
    evidence_sha256: str

    def __post_init__(self):
        _text(self.decision_id); _decode(self.mint); _decode(self.pool)
        _hash(self.source_account_digest); _hash(self.evidence_sha256)
        _uint(self.checked_at_ms, positive=True)
        if (type(self.reasons) is not tuple
                or any(type(r) is not str or not r or len(r) > 256 for r in self.reasons)):
            raise ValueError('explicit_retained_anti_rug_reasons_required')


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


def _account_bytes(account, *, executable):
    if (type(account) is not dict or account.get('owner') != UPGRADEABLE_LOADER
            or account.get('executable') is not executable):
        raise ValueError('deployed_program_owner_or_execution_flag_invalid')
    encoding = account.get('data')
    if (type(encoding) is not list or len(encoding) != 2 or encoding[1] != 'base64'
            or type(encoding[0]) is not str or len(encoding[0]) > 4*1024*1024):
        raise ValueError('deployed_program_raw_base64_required')
    try:
        return base64.b64decode(encoding[0], validate=True)
    except (ValueError, TypeError):
        raise ValueError('deployed_program_raw_base64_invalid') from None


def verify_deployment(program_account, programdata_account, pin, *, observed_slot, now_ms):
    if type(pin) is not DeploymentPin:
        raise ValueError('independently_approved_deployment_pin_required')
    _uint(observed_slot, positive=True); _uint(now_ms, positive=True)
    if pin.approved_at_ms > now_ms or pin.deployment_slot > observed_slot:
        raise ValueError('deployment_approval_or_slot_not_yet_available')
    program = _account_bytes(program_account, executable=True)
    if (len(program) != 36 or struct.unpack_from('<I', program)[0] != 2
            or program[4:] != _decode(pin.programdata_address)):
        raise ValueError('program_to_programdata_binding_invalid')
    data = _account_bytes(programdata_account, executable=False)
    if len(data) < PROGRAMDATA_METADATA_BYTES+64 or struct.unpack_from('<I', data)[0] != 3:
        raise ValueError('programdata_layout_invalid')
    deployment_slot = struct.unpack_from('<Q', data, 4)[0]
    option = data[12]
    if option not in (0, 1):
        raise ValueError('programdata_authority_option_invalid')
    from bot.p3.certification import _encode
    authority = _encode(data[13:45]) if option else None
    if deployment_slot != pin.deployment_slot or authority != pin.upgrade_authority:
        raise ValueError('deployment_slot_or_upgrade_authority_changed')
    elf = data[PROGRAMDATA_METADATA_BYTES:]
    if not elf.startswith(b'\x7fELF') or hashlib.sha256(elf).hexdigest() != pin.elf_sha256:
        raise ValueError('deployed_ELF_differs_from_independently_approved_code')
    return dict(program_id=pin.program_id, programdata_address=pin.programdata_address,
        deployment_slot=deployment_slot, elf_sha256=pin.elf_sha256,
        source_sha256=pin.source_sha256, source_reference=pin.source_reference,
        observed_slot=observed_slot, scope='current_bank_code_bytes_and_authority_only',
        source_build_match='UNAVAILABLE_UNPUBLISHED' if pin.program_id==PROGRAM else 'NOT_ATTESTED',
        source_code_audit_performed=False)


class FreshAdmissionEvidence:
    """Reusable concrete evidence_provider for ExecutionEngine.

    Three read-only calls per assessment: one grouped account bank, genesis,
    and 165-byte rent exemption. There are no retries/fallbacks or market loops.
    The engine separately checks actual message fees, cash, lifetime and ledger.
    Every original account must be byte-for-byte unchanged; a changed market
    requires explicit re-preparation, never silent message mutation/re-signing.
    No successful call refreshes a quote timestamp or scanner heartbeat.
    """
    def __init__(self, *, rpc, envelope, scanner_health, deployment_pin,
                 anti_rug_provider, clock_offset_provider, clock_ms=None,journal=None,
                 deployment_pins=None):
        if type(envelope) is not AuthorizationEnvelope:
            raise ValueError('explicit_owner_authorization_envelope_required')
        if type(scanner_health) is not ScannerHealth:
            raise ValueError('actual_scanner_supervision_required')
        if deployment_pin is not None and type(deployment_pin) is not DeploymentPin:
            raise ValueError('typed_deployment_pin_required')
        if deployment_pins is not None and (type(deployment_pins) is not dict
                or not deployment_pins or any(k not in (PROGRAM,CPMM_PROGRAM)
                    or type(p) is not DeploymentPin or p.program_id!=k
                    for k,p in deployment_pins.items())):
            raise ValueError('typed_execution_program_pin_mapping_required')
        if not callable(anti_rug_provider) or not callable(clock_offset_provider):
            raise ValueError('explicit_decision_and_clock_evidence_providers_required')
        self.rpc, self.envelope, self.scanner_health = rpc, envelope, scanner_health
        self.deployment_pin = deployment_pin
        self.deployment_pins=dict(deployment_pins) if deployment_pins is not None else None
        self.anti_rug_provider, self.clock_offset_provider = anti_rug_provider, clock_offset_provider
        self.clock_ms = clock_ms or (lambda: time.time_ns()//1_000_000)
        self.last_assessment = None
        self._operational_context = None
        self.journal=journal

    def _migration_binding(self,order,now):
        if type(order) is not PreparedCpmmExit:return None
        if self.journal is None:
            raise ValueError('CPMM_fresh_evidence_requires_durable_migration_journal')
        binding=self.journal.migration_binding(order.mint,order.pool,
            at_ms=now,source_slot=order.source_slot,wallet=order.user,
            endpoint_sha256=self.rpc.endpoint_sha256,
            genesis_hash=self.envelope.genesis_hash)
        if (type(binding) is not dict or binding.get('mint')!=order.mint
                or binding.get('cpmm_pool')!=order.pool
                or binding.get('wallet')!=order.user
                or binding.get('endpoint_sha256')!=self.rpc.endpoint_sha256
                or binding.get('genesis_hash')!=self.envelope.genesis_hash):
            raise ValueError('CPMM_durable_migration_binding_unavailable_or_mismatched')
        _decode(binding.get('inventory_pool'));_hash(binding.get('binding_sha256'))
        if binding['inventory_pool'] in (order.pool,order.mint):
            raise ValueError('CPMM_inventory_pool_must_be_distinct_original_position')
        return binding

    def _program_pin(self,order):
        program=CPMM_PROGRAM if type(order) is PreparedCpmmExit else PROGRAM
        return (self.deployment_pins.get(program) if self.deployment_pins is not None
                else self.deployment_pin)

    def assert_operational_now(self):
        """Synchronous final gate; no await/I/O or refreshed heartbeat.

        The engine/transport invokes this immediately before submission to
        catch a scanner/RPC/WS failure while earlier chain checks were awaited.
        Existing clock evidence and financial scope must still be current.
        """
        context = self._operational_context
        if context is None:
            raise ValueError('no_successful_current_evidence_assessment')
        now = _uint(self.clock_ms(), positive=True)
        env, order, anti = self.envelope, context['order'], context['anti']
        if (env.digest != context['authorization_digest']
                or self._program_pin(order) != context['deployment_pin']
                or self.rpc.endpoint_sha256 != env.rpc_endpoint_sha256
                or not env.issued_at_ms <= now < env.expires_at_ms
                or not 0 <= now-order.source_available_at_ms <= min(5000, env.max_quote_age_ms)
                or not 0 <= now-anti.checked_at_ms <= env.max_health_age_ms):
            raise ValueError('operational_scope_or_evidence_no_longer_current')
        if self._migration_binding(order,now)!=context['migration_binding']:
            raise ValueError('migration_binding_changed_before_submission')
        return self._health(now=now, genesis=context['genesis'], clock=context['clock'])

    def _health(self, *, now, genesis, clock):
        health = self.scanner_health
        if (not health.services_fresh(max_age_ms=self.envelope.max_health_age_ms)
                or not health.permits_entries()):
            raise ValueError('scanner_services_not_operational_and_fresh')
        observed = health.operational_observations()
        required_states = dict(scanner='ready', rpc='healthy', websocket='subscribed')
        for role, state in required_states.items():
            item = observed.get(role, {})
            at = item.get('observed_at_ms')
            if (item.get('state') != state or type(at) is not int
                    or not 0 <= now-at <= self.envelope.max_health_age_ms):
                raise ValueError('scanner_service_observation_stale_or_missing')
        if (type(clock) is not ClockOffsetEvidence
                or not 0 <= now-clock.observed_at_ms <= self.envelope.max_health_age_ms
                or abs(clock.offset_ms) > self.envelope.max_clock_skew_ms):
            raise ValueError('measured_current_clock_offset_unknown_or_unacceptable')
        return HealthEvidence(observed_at_ms=now,
            scanner_heartbeat_at_ms=observed['scanner']['observed_at_ms'],
            rpc_success_at_ms=observed['rpc']['observed_at_ms'],
            websocket_heartbeat_at_ms=observed['websocket']['observed_at_ms'],
            scanner_connected=True, rpc_connected=True, websocket_connected=True,
            rpc_genesis_hash=genesis, rpc_endpoint_sha256=self.rpc.endpoint_sha256,
            clock_offset_ms=clock.offset_ms)

    async def __call__(self, decision_id, order):
        self.last_assessment = None
        self._operational_context = None
        cpmm=type(order) is PreparedCpmmExit
        order = validate_cpmm_exit(order) if cpmm else validate_prepared_order(order)
        program=CPMM_PROGRAM if cpmm else PROGRAM
        original = json.loads(order.rebuild_request_json)
        now = _uint(self.clock_ms(), positive=True)
        env = self.envelope
        pin=self._program_pin(order)
        if type(pin) is not DeploymentPin:
            raise ValueError('independently_approved_deployment_pin_required')
        if pin.program_id!=program:
            raise ValueError('deployment_pin_does_not_match_execution_program')
        if (decision_id != original['decision_id'] or order.user != env.wallet
                or self.rpc.endpoint_sha256 != env.rpc_endpoint_sha256
                or program not in env.allowed_programs
                or not env.issued_at_ms <= now < env.expires_at_ms):
            raise ValueError('exact_current_authorization_and_endpoint_binding_required')
        if not 0 <= now-order.source_available_at_ms <= min(5000, env.max_quote_age_ms):
            raise ValueError('original_quote_stale_or_future_no_retiming_allowed')
        binding=self._migration_binding(order,now)
        clock = await _resolve(self.clock_offset_provider())
        # Check existing supervision before issuing even a read-only request.
        now = _uint(self.clock_ms(), positive=True)
        self._health(now=now, genesis=env.genesis_hash, clock=clock)
        anti = await _resolve(self.anti_rug_provider(decision_id, order))
        now = _uint(self.clock_ms(), positive=True)
        if (type(anti) is not AntiRugEvidence or anti.decision_id != decision_id
                or anti.mint != order.mint or anti.pool != order.pool
                or anti.source_account_digest != order.source_account_digest
                or anti.checked_at_ms < order.source_available_at_ms
                or not 0 <= now-anti.checked_at_ms <= env.max_health_age_ms):
            raise ValueError('current_source_bound_anti_rug_decision_required')
        if anti.reasons:
            raise ValueError('anti_rug_decision_refused')
        if (not env.issued_at_ms <= now < env.expires_at_ms
                or not 0 <= now-order.source_available_at_ms <= min(5000, env.max_quote_age_ms)):
            raise ValueError('evidence_expired_before_RPC_revalidation')
        addresses = sorted(set(original['accounts']) | {program, pin.programdata_address})
        if len(addresses) > 100:
            raise ValueError('evidence_grouped_bank_exceeds_bound')
        response = await self.rpc.get_multiple_accounts(addresses, min_context_slot=order.source_slot)
        slot = response.get('context', {}).get('slot') if type(response) is dict else None
        values = response.get('value') if type(response) is dict else None
        if (type(slot) is not int or slot < order.source_slot
                or type(values) is not list or len(values) != len(addresses)):
            raise ValueError('fresh_grouped_bank_missing_or_before_quote_slot')
        fresh = dict(zip(addresses, values, strict=True))
        for address, before in original['accounts'].items():
            if _canonical(fresh[address]) != _canonical(before):
                raise ValueError('prepared_raw_account_changed_explicit_reprepare_required')
        deployment = verify_deployment(fresh[program], fresh[pin.programdata_address], pin,
            observed_slot=slot, now_ms=_uint(self.clock_ms(), positive=True))
        genesis = await self.rpc.genesis_hash()
        if genesis != env.genesis_hash:
            raise ValueError('fresh_RPC_genesis_differs_from_authorized_cluster')
        rent = await self.rpc.rent_exemption(165)
        if (type(rent) is not int or rent != original['rent_exempt_lamports']
                or (not cpmm and rent != original['base_ata_rent_lamports'])):
            raise ValueError('current_classic_account_rent_differs_from_prepared_budget')
        now = _uint(self.clock_ms(), positive=True)
        health = self._health(now=now, genesis=genesis, clock=clock)
        if (not env.issued_at_ms <= now < env.expires_at_ms
                or not 0 <= now-order.source_available_at_ms <= min(5000, env.max_quote_age_ms)
                or not 0 <= now-anti.checked_at_ms <= env.max_health_age_ms):
            raise ValueError('evidence_expired_during_RPC_revalidation')
        if self._migration_binding(order,now)!=binding:
            raise ValueError('migration_binding_changed_during_RPC_revalidation')
        # Qualify full exact sale against the OBSERVED bank, without inserting
        # our hypothetical BUY. Refusal of an empty bank is only this strict
        # admission policy, not proof that a post-buy sale would be impossible.
        quantity = order.expected_output if order.side == 'BUY' else order.input_amount
        if cpmm:
            # Rebuild uses only this same-bank subset, validates net reserves,
            # creator/LP fees, inventory, authorities and exact sell quantity.
            # Deployment account bytes are not silently added to route inputs.
            from .cpmm_exit import build_cpmm_exit
            current=dict(original,accounts={a:fresh[a] for a in original['accounts']})
            revalidated=build_cpmm_exit(**current)
            if revalidated!=order:raise ValueError('CPMM_current_route_differs_from_prepared_intent')
        else:
            self._qualify_launchlab_exit(fresh,order,slot,quantity)
        priority = (original['compute_unit_limit']*original['priority_fee_micro_lamports']+999999)//1_000_000
        request = AdmissionRequest(decision_id=decision_id, side=order.side.lower(),
            wallet=order.user, cluster=env.cluster, genesis_hash=genesis,
            rpc_endpoint_sha256=self.rpc.endpoint_sha256, program_id=program,
            mint=order.mint, pool=order.pool,
            position_pool=binding['inventory_pool'] if binding else None,
            quote_source_id='pinned_local_CPMM_on_retained_RPC_bank' if cpmm else 'pinned_local_curve_on_retained_RPC_bank',
            quote_payload_sha256=order.source_account_digest,
            route_message_sha256=hashlib.sha256(order.transaction.message).hexdigest(),
            quote_received_at_ms=order.source_available_at_ms, risk_checked_at_ms=now,
            quote_context_slot=order.source_slot, observed_bank_slot=slot,
            amount_in_atomic=order.input_amount, quote_input_atomic=order.input_amount,
            quote_output_atomic=order.expected_output, minimum_out_atomic=order.minimum_out,
            network_fee_upper_lamports=order.network_fee_upper_lamports,
            priority_fee_lamports=priority, compute_units=original['compute_unit_limit'],
            slippage_bps=original['slippage_bps'], price_impact_bps=order.price_impact_bps,
            rent_deposit_upper_lamports=order.rent_deposit_lamports,
            exit_capacity_atomic=quantity, identity_verified=True, route_verified=True,
            costs_known=True, anti_rug_reasons=anti.reasons)
        self.last_assessment = dict(decision_id=decision_id,
            request_source_bank_slot=slot, quote_context_slot=order.source_slot,
            quote_received_at_ms=order.source_available_at_ms,
            original_quote_not_retimed=True, deployment=deployment,
            execution_program=program,position_pool=request.position_pool,
            migration_binding_sha256=binding['binding_sha256'] if binding else None,
            anti_rug_evidence_sha256=anti.evidence_sha256,
            clock_evidence_sha256=clock.evidence_sha256,
            source_account_digest=order.source_account_digest,
            strict_observed_full_exit_quantity=str(quantity),
            exit_scope='conditional_projection_on_current_observed_bank_not_a_fill',
            network_fee_scope='engine_must_independently_recheck_current_message_fee',
            realized_market_execution=False)
        self._operational_context = dict(order=order, anti=anti, clock=clock,
            genesis=genesis, authorization_digest=env.digest, deployment_pin=pin,
            migration_binding=binding)
        self.assert_operational_now()
        return request, health

    @staticmethod
    def _qualify_launchlab_exit(fresh,order,slot,quantity):
        analysis = launchlab.analyze_snapshot(fresh, context_slot=slot,
            expected_mint=order.mint, pool_address=order.pool,
            input_lamports=order.input_amount if order.side == 'BUY' else 1,
            evidence_profile='published_metadata_v1', compute_projection=False)
        facts = analysis['facts']
        pool = dict(facts['pool'])
        for key in ('status', 'virtual_a', 'virtual_b', 'real_a', 'real_b',
                    'protocol_fee_accrued', 'platform_fee_accrued'):
            pool[key] = int(pool[key])
        launchlab.observed_sell_projection(pool, input_token_atomic=quantity,
            fee_rates_ppm=(int(facts['config']['trade_fee_rate_ppm']),
                int(facts['platform']['platform_fee_rate_ppm']),
                int(facts['platform']['creator_fee_rate_ppm'])),
            quote_vault_lamports=int(facts['quote_vault']['amount_atomic']),
            curve_type=int(facts['config']['curve_type']), share_fee_rate_ppm=0)
