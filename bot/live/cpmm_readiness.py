"""Bounded unsigned CPMM exit preflight, retaining all distinct trust boundaries.

Runs code-identity pins for LaunchLab and CPMM, verifies a historical
migration, fetches a current CPMM bank and simulates its exact unsent SELL.
No signer, submission, ledger mutation, or auto-arming path exists here.

A successful output means only that supplied program pins matched claims
from one pinned RPC and an unsigned transaction simulated on a later bank.
Historical signature cryptography and independent RPC consensus are NOT
verified. It is never a financial execution authorization.
"""
import hashlib
import json

from bot.p3.certification import PROGRAM
from .cpmm_swap import CPMM_PROGRAM
from .program_pin import attest_program_pin
from .migration_rpc_receipt import read_finalized_migration
from .cpmm_bank import prepare_cpmm_sell_from_rpc
from .unsigned_preflight import check_unsigned_order


async def preflight_migrated_sell(
    rpc, *, program_pins, original_launchlab_pool,
    migrated_cpmm_pool, migration_signature, mint, wallet, decision_id,
    expected_endpoint_sha256, expected_genesis_hash, min_context_slot,
    clock_ms, amount_in, slippage_bps, max_slippage_bps,
    max_price_impact_bps, compute_unit_limit=200000,
    priority_fee_micro_lamports=0, max_priority_fee_lamports=0,
    max_bank_age_ms=5000,
):
    """Read-only end-to-end qualification; at most 17 RPC requests.

    Five read phases: dual on-chain code pins, structural finalized migration,
    joint-bank CPMM account graph, and unsigned exact wire simulation.
    The block's timestamp is obtained from the bank's own slot by getBlockTime.
    Caller retains any raw receipt returned and documents transport budget.
    """
    if (type(program_pins) is not dict or
            set(program_pins)!={PROGRAM,CPMM_PROGRAM} or
            any(type(v) is not dict for v in program_pins.values())
            or type(min_context_slot) is not int or min_context_slot<=0
            or not callable(clock_ms)):
        raise ValueError("two_explicit_program_pins_and_source_slot_required")
    envelope=dict(schema="rugger-cpmm-unsigned-preflight-v1",
        status="REFUSED", live_ready_to_arm=False,
        live_execution_authorized=False,
        financial_order_submitted=False,
        independent_RPC_consensus_verified=False,
        historical_signature_cryptographically_verified=False,
        economic_edge_validated=False)
    pin_results={}
    for program_id in (PROGRAM,CPMM_PROGRAM):
        expected=dict(program_pins[program_id])
        if "program_id" in expected and expected["program_id"]!=program_id:
            raise ValueError("program_pin_identity_mismatch")
        expected.update(program_id=program_id,
            expected_endpoint_sha256=expected_endpoint_sha256,
            expected_genesis_hash=expected_genesis_hash,
            min_context_slot=min_context_slot)
        pin=await attest_program_pin(rpc,**expected)
        if pin["result"]!="PIN_MATCHED_READ_ONLY":
            return dict(envelope,reason="onchain_program_pin_not_matched")
        pin_results[program_id]=pin
    migration=await read_finalized_migration(
        rpc,signature=migration_signature,mint=mint,
        launchlab_pool=original_launchlab_pool,cpmm_pool=migrated_cpmm_pool,
        expected_endpoint_sha256=expected_endpoint_sha256,
        expected_genesis_hash=expected_genesis_hash,
        observed_at_slot=min_context_slot)
    if migration["status"]!="FINALIZED_RPC_STRUCTURAL_MATCH":
        return dict(envelope,reason="migration_not_qualified",
            migration=migration,program_pins_matched=True)
    min_bank=max(min_context_slot,migration["migration_slot"]+1,
                 pin_results[PROGRAM]["joint_bank_slot"],
                 pin_results[CPMM_PROGRAM]["joint_bank_slot"])
    bank=await prepare_cpmm_sell_from_rpc(
        rpc,pool_address=migrated_cpmm_pool,mint=mint,
        wallet=wallet,decision_id=decision_id,min_context_slot=min_bank,
        clock_ms=clock_ms,expected_genesis_hash=expected_genesis_hash,
        expected_endpoint_sha256=expected_endpoint_sha256,
        amount_in=amount_in,slippage_bps=slippage_bps,
        max_slippage_bps=max_slippage_bps,
        max_price_impact_bps=max_price_impact_bps,
        compute_unit_limit=compute_unit_limit,
        priority_fee_micro_lamports=priority_fee_micro_lamports,
        max_priority_fee_lamports=max_priority_fee_lamports,
        max_bank_age_ms=max_bank_age_ms)
    order=bank["order"]
    if (order.pool!=migrated_cpmm_pool or order.mint!=mint
            or order.user!=wallet or order.input_amount!=amount_in
            or bank["source_bank_slot"]<min_bank):
        raise ValueError("cpmm_route_differs_from_migration_or_wallet")
    now=clock_ms()
    if type(now) is not int or now<bank["decision_at_ms"]:
        raise ValueError("simulation_clock_invalid")
    simulated=await check_unsigned_order(
        rpc,order,expected_genesis_hash=expected_genesis_hash,
        expected_endpoint_sha256=expected_endpoint_sha256,
        now_ms=now,max_bank_age_ms=max_bank_age_ms)
    base=dict(envelope,
        migrated_cpmm_pool=migrated_cpmm_pool,
        original_launchlab_pool=original_launchlab_pool,
        mint=mint,simulation=simulated,
        program_pins_matched=True,
        operator_pin_approval_independently_established=False,
        program_pin_read_only_evidence={
            program_id:dict(programdata_sha256=pin["programdata_sha256"],
                            elf_sha256=pin["elf_sha256"],
                            last_upgrade_slot=pin["deployment_slot"],
                            joint_bank_slot=pin["joint_bank_slot"])
            for program_id,pin in pin_results.items()},
        migration=migration,
        bank=dict((k,v) for k,v in bank.items() if k!="order"),
        unsigned_message_sha256=hashlib.sha256(
            order.transaction.message).hexdigest(),
        exact_prepared_order=order,
        exact_order_rebuild_request_sha256=hashlib.sha256(
            order.rebuild_request_json.encode()).hexdigest(),
        receipt_persisted_by_this_function=False,
        program_upgrade_rechecked_after_simulation=False,
        source_transport_independently_authenticated=False)
    if simulated["result"]!="SIMULATION_SUCCEEDED_UNSENT":
        return dict(base,status="REFUSED",reason="unsigned_simulation_failed")
    return dict(base,status="UNSIGNED_CPMM_ROUTE_SIMULATED",
                reason=None,
                actual_mainnet_execution_confirmed=False,
                migration_provenance_sufficient_for_live_execution=False)
