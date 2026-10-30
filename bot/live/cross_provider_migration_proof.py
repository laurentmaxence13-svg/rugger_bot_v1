"""Two independently queried public Solana RPCs for pinned migration evidence.

Confirms equal real signed messages and linked pools from both sources. Does not
authenticate chain consensus or allow financial execution. Exactly 5 reads
per provider, no wallet interaction or sending.
"""
import json
import sys
from bot.live.public_program_observer import SECONDARY_RPC
from bot.live.readonly_plan import PUBLIC_MAINNET_RPC
from bot.live.public_migration_discovery import MigrationReadOnlyRpc
from bot.live.pinned_migration_probe import probe_pinned_migrations

_COMPARE_FIELDS=("signature","slot","mint","launchlab_pool","cpmm_pool",
                 "migration_abi","signed_message_sha256","structural_role_sha256")

def compare_pinned_provider_migrations(primary, secondary):
    if (getattr(primary,"endpoint",None)!=PUBLIC_MAINNET_RPC
            or getattr(secondary,"endpoint",None)!=SECONDARY_RPC):
        raise ValueError("exact_two_approved_independent_RPC_endpoints_required")
    left=probe_pinned_migrations(primary)
    right=probe_pinned_migrations(secondary)
    left_matches={r["signature"]:r for r in left["results"]
                  if r["status"]=="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED"}
    right_matches={r["signature"]:r for r in right["results"]
                   if r["status"]=="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED"}
    if len(left_matches)<2 or set(left_matches)!=set(right_matches):
        raise ValueError("two_migration_proofs_from_both_providers_required")
    for sig in left_matches:
        if any(left_matches[sig][key]!=right_matches[sig][key]
               for key in _COMPARE_FIELDS):
            raise ValueError("cross_provider_signed_migration_evidence_disagreement")
    return dict(schema="rugger-cross-provider-mainnet-migration-v1",
        status="TWO_RPC_PROVIDERS_AGREE_ON_TWO_SIGNED_SOL_MIGRATIONS",
        endpoints=(PUBLIC_MAINNET_RPC,SECONDARY_RPC),
        rpc_calls_used=left["calls_used"]+right["calls_used"],
        verified_migrations=[{key:left_matches[sig][key] for key in _COMPARE_FIELDS}
                             for sig in sorted(left_matches)],
        signed_message_and_role_hashes_agree=True,
        independent_rpc_consensus_verified=False,
        program_source_build_verified=False,
        cpmm_sell_simulation_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        economic_edge_validated=False)

def main():
    try:
        report=compare_pinned_provider_migrations(
            MigrationReadOnlyRpc(endpoint=PUBLIC_MAINNET_RPC),
            MigrationReadOnlyRpc(endpoint=SECONDARY_RPC))
    except Exception as exc:
        report=dict(status="REFUSED",error_type=type(exc).__name__,
                    financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"].startswith("TWO_RPC_PROVIDERS_AGREE") else 2

if __name__=="__main__":
    sys.exit(main())
