"""Verify pre-registered public LaunchLab migration signatures against mainnet.

Only getGenesisHash and finalized getTransaction are allowed. Candidate signatures
come from public Solscan account pages, NOT from a user wallet or claimed market
opportunity. A positive response proves a signed structural transaction under
one RPC provider only; it never grants LIVE permission or verifies profitability.
"""
import json
import sys

from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.public_migration_discovery import (
    MigrationReadOnlyRpc, candidate_role_mapping)
from bot.live.migration_evidence import validate_migrate_to_cpswap_transaction
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.p3.platform_admin_history import _signature

# Solscan Raydium treasury and migration-signer account listings; independent
# web metadata, not proof. Each signature MUST pass finalized RPC and Ed25519.
CANDIDATES = (
    "4dVjRdwd6UGTuCyJviznUKeF6m7qiezaAg7mQY7uTvp8FABVBrnWLaJ1ssaq7yjXGRxA7xKVJv8Ldegpwm5HMqX",
    "25efs9qYjtUNmJDQkfFTFCffhaqYXhtx9u6coHWVmB7efH7E3xi7Swix9whtCjJpQhWB5n5A4KYFeHwzKFj44Bhk",
    "28TDLoj9kUZQ5ADCo2JN4nidFKsB2LBBHRuW5EP4VSPxi5TYCa1htXYNNLxm6Es7r8aLGyLeW9awtuMJ9Y71TitX",
    "3zphmsVirhesYZdiq1PXpFRiKAHiW5dhUKkLEdiaMxZUKU67trTE2wJMDEg5stXfbX3tR1HJHtg7DB7ECsPueMie",
)

def probe_pinned_migrations(rpc, candidates=CANDIDATES):
    if not callable(rpc) or type(candidates) not in (tuple,list) or not 1<=len(candidates)<=4:
        raise ValueError("bounded_readonly_candidate_set_required")
    for sig in candidates:
        _signature(sig)
    if len(set(candidates))!=len(candidates):
        raise ValueError("duplicate_public_migration_signatures")
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("wrong_mainnet_genesis")
    reports=[]
    for sig in candidates:
        raw=rpc("getTransaction",[sig,dict(
            encoding="json",commitment="finalized",maxSupportedTransactionVersion=0)])
        if raw is None:
            reports.append(dict(signature=sig,status="HISTORICAL_TRANSACTION_NOT_RETURNED"))
            continue
        if type(raw) is not dict or type(raw.get("slot")) is not int:
            reports.append(dict(signature=sig,status="MALFORMED_RPC_TRANSACTION"))
            continue
        if type(raw.get("meta")) is not dict or raw["meta"].get("err") is not None:
            reports.append(dict(signature=sig,status="RPC_TRANSACTION_FAILED_OR_INCOMPLETE"))
            continue
        try:
            role=candidate_role_mapping(raw)
        except (ValueError,KeyError,TypeError,IndexError):
            reports.append(dict(signature=sig,status="UNRECOGNIZED_RAW_TRANSACTION"))
            continue
        if role is None:
            reports.append(dict(signature=sig,slot=raw["slot"],
                                status="NOT_SUPPORTED_SOL_MIGRATION"))
            continue
        structural=validate_migrate_to_cpswap_transaction(
            raw,signature=sig,mint=role["mint"],
            launchlab_pool=role["original_pool"],
            cpmm_pool=role["cpmm_pool"],observed_at_slot=raw["slot"])
        if structural["status"]!="STRUCTURAL_MIGRATION_RECEIPT":
            reports.append(dict(signature=sig,slot=raw["slot"],
                status="MIGRATION_STRUCTURAL_GRAPH_REJECTED",
                reason=structural["reason"]))
            continue
        try:
            signed=verify_compiled_rpc_signatures(raw)
        except (ValueError,TypeError,KeyError):
            reports.append(dict(signature=sig,slot=raw["slot"],
                                status="ED25519_EXACT_MESSAGE_REJECTED"))
            continue
        reports.append(dict(signature=sig,slot=raw["slot"],
            status="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED",
            migration_abi=structural["migration_abi"],
            mint=role["mint"],launchlab_pool=role["original_pool"],
            cpmm_pool=role["cpmm_pool"],
            signed_message_sha256=signed["exact_message_sha256"],
            structural_role_sha256=structural["normalized_role_sha256"]))
    matches=sum(r["status"]=="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED"
                for r in reports)
    return dict(schema="rugger-pinned-public-migrations-v1",
        status="MATCH_FOUND" if matches else "NO_CRYPTOGRAPHIC_MATCH",
        candidate_count=len(candidates),matches=matches,
        calls_used=getattr(rpc,"count",None),results=reports,
        source_RPC_claim_finalized=True,
        independent_RPC_consensus_verified=False,
        actual_sell_simulated=False,financial_order_submitted=False,
        economic_edge_validated=False,live_ready_to_arm=False)

def main():
    try:
        report=probe_pinned_migrations(MigrationReadOnlyRpc())
    except Exception as exc:
        report=dict(status="REFUSED",error_type=type(exc).__name__,
            financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="MATCH_FOUND" else 2

if __name__=="__main__":
    sys.exit(main())
