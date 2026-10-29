"""A private evidence report for an unsent, pre-registered CPMM preflight.

The complete report can contain PUBLIC wallet addresses and transaction
account snapshots, so it is kept private locally, never pushed automatically.
It contains no signing key or instructions for an outgoing transaction.
"""
import hashlib
import json
import os
from pathlib import Path

from .readonly_plan import readonly_plan_sha256


def make_private_report(plan,result):
    plan_hash=readonly_plan_sha256(plan)
    if type(result) is not dict:
        raise ValueError("explicit_readonly_result_required")
    order=result.get("exact_prepared_order")
    report=dict(
        schema="rugger-private-readonly-mainnet-report-v1",
        plan_sha256=plan_hash,
        status=result.get("status","REFUSED"),
        reason=result.get("reason"),
        trade_sent=False,signer_used=False,
        wallet_armed=False,live_ready_to_arm=False,
        economic_edge_validated=False,
        rpc_source=plan["rpc_endpoint"],
        source_wallet_public_key=plan["wallet"],
        source_mint_public_key=plan["mint"],
        source_original_pool=plan["original_launchlab_pool"],
        source_cpmm_pool=plan["migrated_cpmm_pool"],
        source_migration_signature=plan["migration_signature"],
        supplied_operator_pins=plan["program_pins"],
        actual_read_only_evidence={
            "program_pins":result.get("program_pin_read_only_evidence"),
            "migration":result.get("migration"),
            "historical_signature_proof":result.get("historical_migration_signatures"),
            "bank":result.get("bank"),
            "unsigned_simulation":result.get("simulation"),
        },
        unsigned_order_rebuild_request_json=(
            order.rebuild_request_json if order is not None else None),
        unsigned_message_sha256=result.get("unsigned_message_sha256"),
        limitations=[
            "single pinned RPC is not independent chain consensus",
            "source build unavailable for private LaunchLab code",
            "unsigned simulation is not a confirmed financial execution",
            "no ledger, signer, wallet permissions, or live execution path",
            "no economic edge independently demonstrated",
        ],
    )
    encoded=json.dumps(report,sort_keys=True,separators=(",",":"),
                       allow_nan=False).encode()
    return report,hashlib.sha256(encoded).hexdigest()


def save_private_report(path,report):
    """Create a private 0600 JSON artifact exactly once, with fsync."""
    dst=Path(path)
    if (not dst.parent.is_dir() or dst.is_symlink()
            or dst.parent.is_symlink() or dst.exists()):
        raise ValueError("new_private_report_path_required")
    encoded=json.dumps(report,sort_keys=True,indent=2,
                       allow_nan=False).encode()
    if len(encoded)>10*1024*1024:
        raise ValueError("bounded_report_size_required")
    fd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return hashlib.sha256(encoded).hexdigest()
