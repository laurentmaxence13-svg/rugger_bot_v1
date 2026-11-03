"""Unsigned, read-only mainnet simulation receipt for an EXACT prepared order.

This bridge never imports a signer, never calls sendTransaction and never
creates an authorization envelope. It can validate an existing prepared
LaunchLab BUY or SELL on a current public Solana bank. A successful simulation
is NOT proof of executable profit, confirmation, wallet ownership, or
LIVE_READY_TO_ARM.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from bot.live.route import validate_prepared_order
from bot.live.cpmm_exit import PreparedCpmmExit, validate_cpmm_exit
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.p3.certification import PROGRAM


def _integer(value, *, positive=False):
    return type(value) is int and (value > 0 if positive else value >= 0)


def _digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _refused(reason: str, *, side=None, source_slot=None, message_sha256=None):
    return dict(
        schema="rugger-mainnet-unsigned-simulation-v1",
        result="REFUSED",
        reason=reason,
        side=side,
        source_slot=source_slot,
        message_sha256=message_sha256,
        route_executed=False,
        signature_verified=False,
        real_funds_spent=False,
        buy_sell_mainnet_execution_verified=False,
        live_ready_to_arm=False,
        economic_edge_validated=False,
    )


async def check_unsigned_order(
    rpc: Any,
    order: Any,
    *,
    expected_genesis_hash: str,
    expected_endpoint_sha256: str,
    now_ms: int,
    max_bank_age_ms: int = 5000,
    clock_ms=None,
):
    """Simulate one exact, already-prepared legacy order with zero signatures.

    A trusted caller must have obtained the original same-bank accounts and
    built the order with the independently pinned LaunchLab IDL. This function
    revalidates the serialized intent; it cannot approve the source program
    nor a future, post-migration exit.
    """
    if (type(expected_genesis_hash) is not str or not expected_genesis_hash
            or type(expected_endpoint_sha256) is not str
            or len(expected_endpoint_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_endpoint_sha256)
            or not _integer(now_ms, positive=True)
            or not _integer(max_bank_age_ms, positive=True)
            or max_bank_age_ms > 5000
            or (clock_ms is not None and not callable(clock_ms))):
        raise ValueError("explicit_genesis_endpoint_clock_and_freshness_required")
    # Optional deadline rechecks are especially important when the source
    # is acquired within a tight live market window. The original now_ms
    # snapshot cannot prove freshness after one or more slow RPC calls.
    def elapsed_source_refusal(phase, source_available_at_ms, base):
        if clock_ms is None:
            return None
        observed=clock_ms()
        if (type(observed) is not int
                or not 0 <= observed-source_available_at_ms <= max_bank_age_ms):
            return _refused("stale_or_future_source_bank_after_"+phase,**base)
        return None

    # Validate the *complete* transaction against its own original retained
    # request. Never let a caller provide a fake validation success flag.
    if type(order) is PreparedCpmmExit:
        order = validate_cpmm_exit(order)
        route_program = CPMM_PROGRAM
    else:
        order = validate_prepared_order(order)
        route_program = PROGRAM
    prepared = order.transaction
    if prepared.required_signers != (order.user,):
        return _refused("unexpected_signer_requirement", side=order.side,
                        source_slot=order.source_slot)
    message_sha256 = _digest_bytes(prepared.message)
    base = dict(side=order.side, source_slot=order.source_slot,
                message_sha256=message_sha256)
    if (not _integer(order.source_slot, positive=True)
            or not _integer(order.source_available_at_ms)
            or not 0 <= now_ms - order.source_available_at_ms <= max_bank_age_ms):
        return _refused("stale_or_future_source_bank", **base)
    if getattr(rpc, "endpoint_sha256", None) != expected_endpoint_sha256:
        return _refused("RPC_endpoint_not_pinned", **base)
    if await rpc.genesis_hash() != expected_genesis_hash:
        return _refused("unexpected_cluster_genesis", **base)
    timed_out=elapsed_source_refusal("genesis",order.source_available_at_ms,base)
    if timed_out is not None:
        return timed_out
    height = await rpc.get_block_height()
    if (not _integer(height, positive=True)
            or height > prepared.last_valid_block_height):
        return _refused("blockhash_expired_before_simulation", **base)
    timed_out=elapsed_source_refusal("block_height",order.source_available_at_ms,base)
    if timed_out is not None:
        return timed_out
    serialized = prepared.unsigned_transaction()
    if type(serialized) is not bytes or not 65 <= len(serialized) <= 1232:
        return _refused("unsigned_wire_size_invalid", **base)
    # This is the ONLY transaction RPC in this method. The signed message is
    # never constructed, the wallet is never accessed, and no submission
    # endpoint is called.
    simulation = await rpc.simulate_transaction(
        serialized, sig_verify=False, min_context_slot=order.source_slot)
    timed_out=elapsed_source_refusal("simulation",order.source_available_at_ms,base)
    if timed_out is not None:
        return timed_out
    if (type(simulation) is not dict or "err" not in simulation
            or not _integer(simulation.get("context_slot"), positive=True)
            or simulation["context_slot"] < order.source_slot):
        return _refused("missing_or_noncausal_simulation_receipt", **base)
    # Retain the bounded canonical parsed simulation evidence for private
    # replay. This is NOT the raw HTTP JSON-RPC envelope.
    try:
        simulation_json=json.dumps(simulation,sort_keys=True,
            separators=(",",":"),allow_nan=False).encode()
    except (TypeError,ValueError,OverflowError):
        return _refused("noncanonical_simulation_response", **base)
    if len(simulation_json)>4*1024*1024:
        return _refused("simulation_response_exceeds_evidence_limit", **base)
    simulation_evidence=dict(
        parsed_RPC_simulation_result=simulation,
        parsed_RPC_simulation_sha256=hashlib.sha256(simulation_json).hexdigest(),
        original_HTTP_RPC_envelope_retained=False)
    try:
        registered_request = json.loads(order.rebuild_request_json)
        maximum_compute = registered_request["compute_unit_limit"]
    except (ValueError, KeyError, TypeError):
        return _refused("missing_original_compute_limit", **base)
    units = simulation.get("unitsConsumed")
    if not _integer(maximum_compute, positive=True) or maximum_compute > 1400000:
        return _refused("original_compute_limit_invalid", **base)
    if simulation["err"] is not None:
        return {**_refused("simulation_returned_error", **base),
                **simulation_evidence,
                "simulation_slot": simulation["context_slot"],
                "simulation_error_class": type(simulation["err"]).__name__}
    if not _integer(units) or units > maximum_compute:
        return {**_refused("simulation_compute_units_unqualified", **base),
                **simulation_evidence}
    # A success may be stale by the time it arrives. This is a simulation
    # receipt, not permission to sign a transaction at a later instant.
    return dict(
        schema="rugger-mainnet-unsigned-simulation-v1",
        result="SIMULATION_SUCCEEDED_UNSENT",
        reason=None,
        side=order.side,
        program_id=route_program,
        source_slot=order.source_slot,
        simulation_slot=simulation["context_slot"],
        message_sha256=message_sha256,
        unsigned_transaction_sha256=_digest_bytes(serialized),
        simulation_units=units,
        **simulation_evidence,
        registered_compute_limit=maximum_compute,
        source_available_at_ms=order.source_available_at_ms,
        request_at_ms=now_ms,
        source_clock_type="RPC_context_slot_and_local_receipt_not_provider_quote_clock",
        signatures_are_all_zero=True,
        sig_verify=False,
        replace_recent_blockhash=False,
        route_executed=False,
        signature_verified=False,
        real_funds_spent=False,
        buy_sell_mainnet_execution_verified=False,
        migration_provenance_verified=False,
        live_ready_to_arm=False,
        economic_edge_validated=False,
        caveat="Unsigned simulation is not a fill or permission to spend; current source, program and costs must be revalidated.",
    )
