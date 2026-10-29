"""Pre-registered, strictly read-only mainnet CPMM preflight plan.

Plans must be explicitly completed with public addresses and externally
approved program bytecode pins. No private key, password, token or RPC API
secret is allowed. A syntactically valid plan does NOT authorize financial
execution, certify source authenticity or endorse market participation.
"""
from copy import deepcopy
import hashlib
import json
import re

from bot.p3.certification import _decode, PROGRAM
from bot.p3.platform_admin_history import _signature
from .cpmm_swap import CPMM_PROGRAM

PUBLIC_MAINNET_RPC="https://api.mainnet.solana.com"
MAINNET_GENESIS="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
_SHA=re.compile("[0-9a-f]{64}\\Z")


def _hash(value):
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError("explicit_program_hash_required")


def _integer(value,*,minval=0,maxval=2**63-1):
    if type(value) is not int or not minval<=value<=maxval:
        raise ValueError("bounded_exact_plan_integer_required")


def validate_readonly_plan(plan):
    if type(plan) is not dict:
        raise ValueError("explicit_JSON_readonly_plan_required")
    required={
        "schema","rpc_endpoint","expected_genesis_hash","send_allowed",
        "signature_allowed","financial_execution_allowed",
        "operator_confirmed_readonly","program_pins",
        "original_launchlab_pool","migrated_cpmm_pool",
        "migration_signature","mint","wallet","decision_id",
        "min_context_slot","amount_in","slippage_bps","max_slippage_bps",
        "max_price_impact_bps","compute_unit_limit",
        "priority_fee_micro_lamports","max_priority_fee_lamports",
        "max_bank_age_ms","max_rpc_requests","max_transport_elapsed_seconds",
    }
    if set(plan)!=required:
        raise ValueError("readonly_plan_exact_fields_required")
    if (plan["schema"]!="rugger-cpmm-readonly-mainnet-plan-v1"
            or plan["rpc_endpoint"]!=PUBLIC_MAINNET_RPC
            or plan["expected_genesis_hash"]!=MAINNET_GENESIS
            or plan["send_allowed"] is not False
            or plan["signature_allowed"] is not False
            or plan["financial_execution_allowed"] is not False
            or plan["operator_confirmed_readonly"] is not True):
        raise ValueError("readonly_only_public_mainnet_with_explicit_consent_required")
    for k in ("original_launchlab_pool","migrated_cpmm_pool","mint","wallet"):
        if type(plan[k]) is not str:
            raise ValueError("public_address_string_required")
        _decode(plan[k])
    _signature(plan["migration_signature"])
    if (type(plan["decision_id"]) is not str or
            not 1<=len(plan["decision_id"])<=128):
        raise ValueError("bounded_decision_id_required")
    for key in ("min_context_slot","amount_in","compute_unit_limit",
                "max_bank_age_ms","max_rpc_requests",
                "max_transport_elapsed_seconds"):
        _integer(plan[key],minval=1)
    for key in ("slippage_bps","max_slippage_bps","max_price_impact_bps",
                "priority_fee_micro_lamports","max_priority_fee_lamports"):
        _integer(plan[key])
    if (not 0<=plan["slippage_bps"]<=plan["max_slippage_bps"]<10000
            or not 0<=plan["max_price_impact_bps"]<10000
            or plan["compute_unit_limit"]>1_400_000
            or plan["max_bank_age_ms"]>5000
            or plan["max_rpc_requests"]!=17
            or plan["max_transport_elapsed_seconds"]>60):
        raise ValueError("strict_single_pass_RPC_budget_and_limits_required")
    pins=plan["program_pins"]
    if type(pins) is not dict or set(pins)!={PROGRAM,CPMM_PROGRAM}:
        raise ValueError("both_exact_program_pins_required")
    for program,values in pins.items():
        if (type(values) is not dict or set(values)!={
                "expected_deployment_slot","expected_programdata_sha256",
                "expected_elf_sha256","expected_upgrade_authority"}):
            raise ValueError("all_operator_program_pins_required")
        _integer(values["expected_deployment_slot"],minval=1)
        _hash(values["expected_programdata_sha256"])
        _hash(values["expected_elf_sha256"])
        if values["expected_upgrade_authority"] is not None:
            _decode(values["expected_upgrade_authority"])
    # Operator-supplied bytecode hashes are never silently read/approved
    # from the same RPC being tested.
    return deepcopy(plan)


def readonly_plan_sha256(plan):
    canonical=json.dumps(validate_readonly_plan(plan),
        sort_keys=True,separators=(",",":"),allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
