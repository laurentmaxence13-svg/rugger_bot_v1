"""Fail-closed, side-effect-free admission for an explicitly authorized live run.

Nothing here discovers credentials, arms from environment variables or assumes
that a Master decision is permission to spend. The caller must retain the owner
authorization receipt and two separate operator actions in its durable journal.
This module validates their exact binding, then rechecks limits before submission.
RPC simulation, transaction semantics and signer verification remain mandatory
independent checks performed by the execution engine.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re

from bot.p3.certification import _decode


UINT64_MAX = 2**64 - 1


class Mode(str, Enum):
    RESEARCH = 'RESEARCH'
    SHADOW = 'SHADOW'
    LIVE_PREPARED = 'LIVE_PREPARED'
    LIVE_ARMED = 'LIVE_ARMED'
    LIVE_ENABLED = 'LIVE_ENABLED'


def _uint(value, label, *, positive=False, maximum=UINT64_MAX):
    if type(value) is not int or not (1 if positive else 0) <= value <= maximum:
        raise ValueError('invalid_' + label)
    return value


def _text(value, label):
    if (type(value) is not str or not 1 <= len(value) <= 256
            or value.strip() != value or not value.isprintable()):
        raise ValueError('invalid_' + label)
    return value


def _hash(value, label):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('invalid_' + label)
    return value


def _pubkey(value, label):
    try:
        _decode(value)
    except (ValueError, TypeError):
        raise ValueError('invalid_' + label) from None
    return value


def _bool(value, label):
    if type(value) is not bool:
        raise ValueError('invalid_' + label)


def _sum(*values):
    result = sum(values)
    if result > UINT64_MAX:
        raise ValueError('atomic_sum_overflow')
    return result


@dataclass(frozen=True)
class AuthorizationEnvelope:
    """Explicit financial scope supplied only after an owner authorization.

    No capital or permission field has a default. Receipt identifiers are audit
    references, not an authentication protocol; accepting a receipt from the
    owner is an operator boundary and must not be exposed to strategy input.
    Daily spend includes principal committed plus fees/deposits, never P&L netting.
    """
    authorization_id: str
    approved_by: str
    cluster: str
    genesis_hash: str
    wallet: str
    rpc_endpoint_sha256: str
    allowed_programs: tuple
    issued_at_ms: int
    expires_at_ms: int
    max_capital_lamports: int
    max_entry_lamports: int
    max_daily_spend_lamports: int
    max_daily_loss_lamports: int
    max_open_positions: int
    max_in_flight_orders: int
    max_slippage_bps: int
    max_price_impact_bps: int
    max_network_fee_lamports: int
    max_priority_fee_lamports: int
    max_compute_units: int
    max_quote_age_ms: int
    max_health_age_ms: int
    max_clock_skew_ms: int
    max_consecutive_failures: int

    def __post_init__(self):
        for key in ('authorization_id', 'approved_by'):
            _text(getattr(self, key), key)
        if self.cluster not in ('mainnet-beta', 'devnet', 'testnet'):
            raise ValueError('invalid_cluster')
        _pubkey(self.genesis_hash, 'genesis_hash')
        _pubkey(self.wallet, 'wallet')
        _hash(self.rpc_endpoint_sha256, 'rpc_endpoint_sha256')
        if (type(self.allowed_programs) is not tuple or not self.allowed_programs
                or any(type(p) is not str for p in self.allowed_programs)
                or len(set(self.allowed_programs)) != len(self.allowed_programs)):
            raise ValueError('invalid_allowed_programs')
        for program in self.allowed_programs:
            _pubkey(program, 'allowed_program')
        zero_ok = {'max_slippage_bps', 'max_price_impact_bps', 'max_priority_fee_lamports', 'max_clock_skew_ms'}
        for name in self.__dataclass_fields__:
            if name.startswith('max_') or name.endswith('_at_ms'):
                _uint(getattr(self, name), name, positive=name not in zero_ok)
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError('authorization_expiry_not_after_issue')
        if self.max_entry_lamports > self.max_capital_lamports:
            raise ValueError('entry_limit_exceeds_capital')
        if self.max_slippage_bps > 9999:
            raise ValueError('slippage_must_preserve_positive_minimum')
        if self.max_price_impact_bps > 9999:
            raise ValueError('price_impact_scope_exceeds_transaction_limit')
        if self.max_priority_fee_lamports > self.max_network_fee_lamports:
            raise ValueError('priority_fee_exceeds_total_fee_limit')
        if self.max_compute_units > 1_400_000:
            raise ValueError('compute_limit_exceeds_solana_transaction_limit')

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    def to_record(self):
        """Public authorization scope only; no key material or RPC credentials."""
        record = asdict(self)
        record['allowed_programs'] = list(self.allowed_programs)
        return record

    @classmethod
    def from_record(cls, record):
        if (type(record) is not dict or set(record) != set(cls.__dataclass_fields__)
                or type(record.get('allowed_programs')) is not list):
            raise ValueError('exact_authorization_record_required')
        return cls(**dict(record, allowed_programs=tuple(record['allowed_programs'])))


@dataclass(frozen=True)
class ArmingState:
    mode: Mode
    authorization_digest: str
    authorization_id: str
    approved_by: str
    armed_at_ms: int
    arm_receipt: str
    enabled_at_ms: int | None = None
    enable_receipt: str | None = None

    def to_record(self):
        record = asdict(self)
        record['mode'] = self.mode.value
        return record


def _authorization_time(envelope, now_ms):
    if type(envelope) is not AuthorizationEnvelope:
        raise ValueError('owner_authorization_required')
    _uint(now_ms, 'now_ms', positive=True)
    if not envelope.issued_at_ms <= now_ms < envelope.expires_at_ms:
        raise ValueError('authorization_not_current')


def arm(envelope, *, now_ms, arm_receipt):
    """First explicit operator action; this result still cannot send an order."""
    _authorization_time(envelope, now_ms)
    _text(arm_receipt, 'arm_receipt')
    return ArmingState(Mode.LIVE_ARMED, envelope.digest,
        envelope.authorization_id, envelope.approved_by, now_ms, arm_receipt)


def enable(envelope, arming, *, now_ms, enable_receipt):
    """Second, distinct operator action bound to precisely the same envelope."""
    _authorization_time(envelope, now_ms)
    _text(enable_receipt, 'enable_receipt')
    if (type(arming) is not ArmingState or arming.mode is not Mode.LIVE_ARMED
            or arming.authorization_digest != envelope.digest
            or arming.authorization_id != envelope.authorization_id
            or arming.approved_by != envelope.approved_by
            or type(arming.armed_at_ms) is not int
            or not envelope.issued_at_ms <= arming.armed_at_ms <= now_ms
            or arming.enable_receipt is not None or arming.enabled_at_ms is not None):
        raise ValueError('matching_explicit_arm_required')
    _text(arming.arm_receipt, 'arm_receipt')
    if enable_receipt == arming.arm_receipt:
        raise ValueError('distinct_enable_action_required')
    return ArmingState(Mode.LIVE_ENABLED, envelope.digest,
        envelope.authorization_id, envelope.approved_by, arming.armed_at_ms,
        arming.arm_receipt, now_ms, enable_receipt)


def arming_from_record(record, *, envelope, now_ms):
    """Restore retained operator actions without widening or renewing scope.

    The execution journal must authenticate its own hash chain before passing
    records here. Merely possessing an untrusted JSON record is not authority.
    Expired grants remain expired after a restart.
    """
    _authorization_time(envelope, now_ms)
    if type(record) is not dict or set(record) != set(ArmingState.__dataclass_fields__):
        raise ValueError('exact_arming_record_required')
    if record.get('mode') not in (Mode.LIVE_ARMED.value, Mode.LIVE_ENABLED.value):
        raise ValueError('explicit_retained_arming_actions_required')
    expected = arm(envelope, now_ms=record['armed_at_ms'],
                   arm_receipt=record['arm_receipt'])
    if record['mode'] == Mode.LIVE_ENABLED.value:
        expected = enable(envelope, expected, now_ms=record['enabled_at_ms'],
                          enable_receipt=record['enable_receipt'])
    if (expected.to_record() != record or expected.armed_at_ms > now_ms
            or expected.enabled_at_ms is not None and expected.enabled_at_ms > now_ms):
        raise ValueError('retained_arming_does_not_match_authorization')
    return expected


@dataclass(frozen=True)
class InventoryPosition:
    mint: str
    pool: str
    quantity_atomic: int
    reserved_atomic: int

    def __post_init__(self):
        _pubkey(self.mint, 'position_mint')
        _pubkey(self.pool, 'position_pool')
        _uint(self.quantity_atomic, 'position_quantity')
        _uint(self.reserved_atomic, 'position_reserved')
        if self.reserved_atomic > self.quantity_atomic:
            raise ValueError('position_reservation_exceeds_inventory')


@dataclass(frozen=True)
class RiskSnapshot:
    observed_at_ms: int
    wallet_balance_lamports: int
    reserved_lamports: int
    capital_at_risk_lamports: int
    day_spent_lamports: int
    realized_daily_loss_lamports: int
    pending_loss_lamports: int
    open_positions: int
    in_flight_orders: int
    consecutive_failures: int
    unresolved_orders: int
    kill_switch: bool
    positions: tuple

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            if name not in ('kill_switch', 'positions'):
                _uint(getattr(self, name), name)
        _bool(self.kill_switch, 'kill_switch')
        if (type(self.positions) is not tuple
                or any(type(p) is not InventoryPosition for p in self.positions)
                or len({(p.mint, p.pool) for p in self.positions}) != len(self.positions)):
            raise ValueError('invalid_position_inventory')
        if self.open_positions != sum(p.quantity_atomic > 0 for p in self.positions):
            raise ValueError('open_position_inventory_mismatch')
        if self.reserved_lamports > self.wallet_balance_lamports:
            raise ValueError('wallet_reservation_exceeds_balance')


@dataclass(frozen=True)
class HealthEvidence:
    observed_at_ms: int
    scanner_heartbeat_at_ms: int
    rpc_success_at_ms: int
    websocket_heartbeat_at_ms: int
    scanner_connected: bool
    rpc_connected: bool
    websocket_connected: bool
    rpc_genesis_hash: str
    rpc_endpoint_sha256: str
    clock_offset_ms: int

    def __post_init__(self):
        for key in ('observed_at_ms', 'scanner_heartbeat_at_ms', 'rpc_success_at_ms',
                    'websocket_heartbeat_at_ms'):
            _uint(getattr(self, key), key)
        for key in ('scanner_connected', 'rpc_connected', 'websocket_connected'):
            _bool(getattr(self, key), key)
        _pubkey(self.rpc_genesis_hash, 'rpc_genesis_hash')
        _hash(self.rpc_endpoint_sha256, 'rpc_endpoint_sha256')
        if type(self.clock_offset_ms) is not int or abs(self.clock_offset_ms) > UINT64_MAX:
            raise ValueError('invalid_clock_offset_ms')


_NOTIONAL = ('amount_in_atomic', 'quote_input_atomic', 'quote_output_atomic',
             'minimum_out_atomic')


@dataclass(frozen=True)
class AdmissionRequest:
    decision_id: str
    side: str
    wallet: str
    cluster: str
    genesis_hash: str
    rpc_endpoint_sha256: str
    program_id: str
    mint: str
    pool: str
    quote_source_id: str
    quote_payload_sha256: str
    route_message_sha256: str
    quote_received_at_ms: int
    risk_checked_at_ms: int
    quote_context_slot: int
    observed_bank_slot: int
    amount_in_atomic: int
    quote_input_atomic: int
    quote_output_atomic: int
    minimum_out_atomic: int
    network_fee_upper_lamports: int
    priority_fee_lamports: int
    compute_units: int
    slippage_bps: int
    price_impact_bps: int
    rent_deposit_upper_lamports: int
    exit_capacity_atomic: int
    identity_verified: bool
    route_verified: bool
    costs_known: bool
    anti_rug_reasons: tuple
    position_pool: str | None = None

    def __post_init__(self):
        for key in ('decision_id', 'quote_source_id'):
            _text(getattr(self, key), key)
        if self.side not in ('buy', 'sell', 'cleanup'):
            raise ValueError('invalid_side')
        if self.cluster not in ('mainnet-beta', 'devnet', 'testnet'):
            raise ValueError('invalid_cluster')
        for key in ('wallet', 'genesis_hash', 'program_id', 'mint', 'pool'):
            _pubkey(getattr(self, key), key)
        if self.position_pool is not None:
            _pubkey(self.position_pool,'position_pool')
            from .cpmm_swap import CPMM_PROGRAM
            if (self.side!='sell' or self.program_id!=CPMM_PROGRAM
                    or self.position_pool in (self.pool,self.mint)):
                raise ValueError('migrated_inventory_identity_requires_distinct_CPMM_sell')
        if self.pool == self.mint:
            raise ValueError('pool_mint_alias')
        for key in ('rpc_endpoint_sha256', 'quote_payload_sha256', 'route_message_sha256'):
            _hash(getattr(self, key), key)
        for key in self.__dataclass_fields__:
            if key.endswith(('_ms', '_slot', '_atomic', '_lamports')) or key in ('compute_units', 'slippage_bps', 'price_impact_bps'):
                _uint(getattr(self, key), key,
                      positive=key in ('amount_in_atomic', 'quote_input_atomic',
                          'quote_output_atomic', 'minimum_out_atomic', 'compute_units',
                          'quote_context_slot', 'observed_bank_slot',
                          'network_fee_upper_lamports')
                      and not (self.side == 'cleanup' and key in _NOTIONAL))
        # A base-account cleanup is not a trade: it swaps nothing, so every
        # notional/slippage field must be exactly zero rather than merely small.
        if self.side == 'cleanup' and any(getattr(self, key) != 0 for key in _NOTIONAL + (
                'slippage_bps', 'price_impact_bps', 'rent_deposit_upper_lamports',
                'exit_capacity_atomic')):
            raise ValueError('cleanup_carries_no_notional')
        for key in ('identity_verified', 'route_verified', 'costs_known'):
            _bool(getattr(self, key), key)
        if (type(self.anti_rug_reasons) is not tuple
                or any(type(x) is not str or not x for x in self.anti_rug_reasons)):
            raise ValueError('invalid_anti_rug_reasons')

    @property
    def cash_required_lamports(self):
        return _sum(self.amount_in_atomic if self.side == 'buy' else 0,
                    self.network_fee_upper_lamports, self.rent_deposit_upper_lamports)


@dataclass(frozen=True)
class AdmissionResult:
    allowed: bool
    reasons: tuple
    authorization_digest: str | None
    cash_required_lamports: int | None


def evaluate_admission(request, *, envelope, arming, health, risk, now_ms,
                       require_enabled=True):
    """Recheck every send using fresh service and durable ledger observations.

    ``require_enabled=False`` permits a *prepared* admission assessment only;
    callers must never use that assessment as permission to sign or submit.
    Loss/capital/entry limits refuse new buys. A bounded, inventory-backed sell
    may still reduce an existing position after the loss limit, but does not
    bypass kill-switch, unresolved submissions, fee, cash or daily spend limits.
    A base-account cleanup is not a trade: notional, slippage and
    inventory-for-sell are inapplicable (all zero); every other check applies.
    """
    reasons = []
    if (type(request) is not AdmissionRequest or type(health) is not HealthEvidence
            or type(risk) is not RiskSnapshot or type(require_enabled) is not bool):
        return AdmissionResult(False, ('typed_bound_evidence_required',), None, None)
    try:
        _authorization_time(envelope, now_ms)
    except ValueError as error:
        return AdmissionResult(False, (str(error),), None, None)
    digest = envelope.digest
    if require_enabled:
        if (type(arming) is not ArmingState or arming.mode is not Mode.LIVE_ENABLED
                or arming.authorization_digest != digest
                or arming.authorization_id != envelope.authorization_id
                or arming.approved_by != envelope.approved_by
                or type(arming.armed_at_ms) is not int
                or type(arming.enabled_at_ms) is not int
                or not envelope.issued_at_ms <= arming.armed_at_ms <= arming.enabled_at_ms <= now_ms
                or type(arming.arm_receipt) is not str or not arming.arm_receipt
                or type(arming.enable_receipt) is not str or not arming.enable_receipt
                or arming.arm_receipt == arming.enable_receipt):
            reasons.append('explicit_arm_and_enable_required')
    if risk.kill_switch:
        reasons.append('persistent_kill_switch')
    if risk.unresolved_orders:
        reasons.append('unreconciled_submission')
    if risk.in_flight_orders >= envelope.max_in_flight_orders:
        reasons.append('in_flight_limit')
    if risk.consecutive_failures >= envelope.max_consecutive_failures:
        reasons.append('consecutive_failure_limit')
    if (request.wallet != envelope.wallet or request.cluster != envelope.cluster
            or request.genesis_hash != envelope.genesis_hash
            or request.rpc_endpoint_sha256 != envelope.rpc_endpoint_sha256
            or health.rpc_genesis_hash != envelope.genesis_hash
            or health.rpc_endpoint_sha256 != envelope.rpc_endpoint_sha256):
        reasons.append('wallet_cluster_or_rpc_binding_mismatch')
    if request.program_id not in envelope.allowed_programs:
        reasons.append('program_not_authorized')
    clocks = (health.observed_at_ms, health.scanner_heartbeat_at_ms,
              health.rpc_success_at_ms, health.websocket_heartbeat_at_ms,
              risk.observed_at_ms, request.risk_checked_at_ms)
    if any(not 0 <= now_ms - value <= envelope.max_health_age_ms for value in clocks):
        reasons.append('stale_or_future_health_or_risk')
    if any(value > health.observed_at_ms for value in clocks[1:4]):
        reasons.append('heartbeat_after_health_snapshot')
    if not (health.scanner_connected and health.rpc_connected and health.websocket_connected):
        reasons.append('service_disconnected')
    if abs(health.clock_offset_ms) > envelope.max_clock_skew_ms:
        reasons.append('clock_skew_limit')
    if not 0 <= now_ms - request.quote_received_at_ms <= envelope.max_quote_age_ms:
        reasons.append('stale_or_future_quote')
    # The quote retains its original source slot/receipt clock. Pre-submission
    # risk revalidation may observe a *later* bank; it must never backdate the
    # quote or accept a bank older than the bank used to prepare the route.
    if request.observed_bank_slot < request.quote_context_slot:
        reasons.append('quote_and_bank_slot_mismatch')
    if not request.identity_verified or not request.route_verified or request.anti_rug_reasons:
        reasons.append('identity_route_or_anti_rug_unqualified')
    if not request.costs_known:
        reasons.append('own_costs_unknown')
    if request.amount_in_atomic != request.quote_input_atomic:
        reasons.append('exact_quote_input_mismatch')
    # Inapplicable to a cleanup: no swap, so no minimum output to protect.
    if request.side != 'cleanup' and (request.slippage_bps > envelope.max_slippage_bps
            or request.slippage_bps > 9999
            or request.minimum_out_atomic > request.quote_output_atomic
            or request.minimum_out_atomic < max(1, request.quote_output_atomic * (10000-request.slippage_bps)//10000)):
        reasons.append('minimum_output_or_slippage_violation')
    if request.price_impact_bps > envelope.max_price_impact_bps:
        reasons.append('price_impact_limit')
    if (request.network_fee_upper_lamports > envelope.max_network_fee_lamports
            or request.priority_fee_lamports > envelope.max_priority_fee_lamports
            or request.priority_fee_lamports > request.network_fee_upper_lamports):
        reasons.append('fee_limit')
    if request.compute_units > min(1_400_000, envelope.max_compute_units):
        reasons.append('compute_limit')
    required_exit = request.quote_output_atomic if request.side == 'buy' else request.amount_in_atomic
    if request.exit_capacity_atomic < required_exit:
        reasons.append('exact_exit_capacity_unknown_or_insufficient')
    try:
        cash = request.cash_required_lamports
        if _sum(risk.reserved_lamports, cash) > risk.wallet_balance_lamports:
            reasons.append('insufficient_unreserved_cash')
        if _sum(risk.day_spent_lamports, risk.reserved_lamports, cash) > envelope.max_daily_spend_lamports:
            reasons.append('daily_spend_limit')
        if request.side == 'buy':
            if cash > envelope.max_entry_lamports:
                reasons.append('entry_limit')
            if _sum(risk.capital_at_risk_lamports, risk.reserved_lamports, cash) > envelope.max_capital_lamports:
                reasons.append('capital_limit')
            if risk.open_positions >= envelope.max_open_positions:
                reasons.append('open_position_limit')
            if _sum(risk.realized_daily_loss_lamports, risk.pending_loss_lamports,
                    request.network_fee_upper_lamports) >= envelope.max_daily_loss_lamports:
                reasons.append('daily_loss_limit')
        elif request.side == 'sell':
            position = next((p for p in risk.positions
                             if p.mint == request.mint and p.pool ==
                             (request.position_pool or request.pool)), None)
            if position is None or request.amount_in_atomic > position.quantity_atomic-position.reserved_atomic:
                reasons.append('sell_exceeds_unreserved_inventory')
    except ValueError:
        cash = None
        reasons.append('atomic_sum_overflow')
    return AdmissionResult(not reasons, tuple(reasons), digest, cash)
