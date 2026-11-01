"""Post-hoc cryptographic audit of three legacy-only Initialize hints.

These signatures came from immutable public window 02 of GitHub run 41257191511.
They were NOT scoped to LaunchLab by the real-time log parser. This is an
independent finalized receipt falsification check, not an as-of entry decision.
Only read-only RPC (<=7 calls), no wallet or transaction submission.
"""
import json
import os
from pathlib import Path
import sys

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_early_signed_s1s2 import signed_receipt_proof
from bot.live.readonly_plan import MAINNET_GENESIS

SOURCE_RUN=41257191511
SOURCE_WINDOW=2
SOURCE_SHA256="06bf6c1ffa675f2a5156e775f780d47c7d04fbb016f515480519ac6c5ec17cdf"
LEGACY_ONLY=[
    ("5wu2aNya3uv82VBsFVxpMpaqE94ywJVK7rL9ahxPczzDQJMUKJsKdp1QJpRfgbnzg1CHULSRzPs7n21temcQvm8c",463891978),
    ("2ieT4635qSBoNNNTinzjG7xPY8MQ8QnVpBTVfyAGsD7NNekXregttmTGQxTurBoCvmBKzFhF3HrMcuJJRimBFREY",463892024),
    ("3VovZiJdzHvCt6z7CypSbqpujq8NEw41YhkVQUVL7kHvh1UzU9SuUjzrcLwcutCcSLAfLtxoychTozJqUVdbu3iw",463892069),
]


def inspect_legacy_hints(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("mainnet_readonly_required")
    rows=[]
    for signature,slot in LEGACY_ONLY:
        row=dict(signature=signature,source_slot=slot,
            selection_reason="archived_legacy_initialize_prefix_without_launchlab_scoped_hint",
            status="UNVERIFIED",signed_outer_creations=None,
            master_net_pnl_lamports=None,financial_order_submitted=False)
        try:
            raw=rpc("getTransaction",[signature,dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1)])
            if raw is None:
                row["status"]="FINALIZED_RECEIPT_UNAVAILABLE"
            else:
                proof=signed_receipt_proof(raw,signature,slot,rpc,commitment="finalized")
                row["exact_message_sha256"]=proof["message_sha256"]
                row["signed_outer_creations"]=proof["launches"]
                row["status"]=("VERIFIED_SIGNED_OUTER_CREATION"
                               if proof["launches"] else "VERIFIED_NON_CREATION")
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as exc:
            row["status"]="RECEIPT_OR_CRYPTO_REFUSED"
            row["safe_error_class"]=type(exc).__name__
        rows.append(row)
    creator_ids={launch.get("creator") for row in rows
                 for launch in (row.get("signed_outer_creations") or [])
                 if type(launch) is dict and type(launch.get("creator")) is str}
    signed=sum(len(r.get("signed_outer_creations") or []) for r in rows)
    complete=all(r["status"] in ("VERIFIED_NON_CREATION","VERIFIED_SIGNED_OUTER_CREATION")
                 for r in rows)
    return dict(schema="rugger-legacy-unscoped-hint-crypto-audit-v1",
        source_run_id=SOURCE_RUN,source_window=SOURCE_WINDOW,
        public_source_window_sha256=SOURCE_SHA256,
        original_untrusted_legacy_prefix_count=len(LEGACY_ONLY),
        original_scoped_launchlab_hint_count=0,
        retrospective_finalized_verification_only=True,
        rows=rows,verified_signed_creations=signed,
        unique_creator_claims=len(creator_ids),
        fully_verified=complete,
        verdict=("SCOPED_HINT_FILTER_REQUIRES_REVIEW"
                 if signed else "NO_SIGNED_CREATION_AMONG_LEGACY_HINTS"
                 if complete else "INCONCLUSIVE_FINALIZED_EVIDENCE"),
        economic_cycles_qualified=0,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        financial_order_submitted=False,live_ready_to_arm=False)


def main():
    if (os.environ.get("GITHUB_ACTIONS")!="true" or
        not os.environ.get("GITHUB_WORKSPACE") or not os.environ.get("HELIUS_API_KEY")):
        print(json.dumps(dict(status="CRYPTO_HINT_AUDIT_REFUSED",
            financial_order_submitted=False)))
        return 2
    try:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=10)
        report=inspect_legacy_hints(rpc)
        root=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        if not (root/"bot/live/helius_early_signed_s1s2.py").is_file():
            raise ValueError("repository_root_required")
        directory=root/"paper_artifacts"
        if directory.is_symlink():
            raise ValueError("artifact_symlink_refused")
        directory.mkdir(mode=0o700,exist_ok=True)
        out=directory/f"legacy_hint_crypto_{os.environ['GITHUB_RUN_ID']}.json"
        with out.open("x",encoding="utf-8") as stream:
            stream.write(json.dumps(report,sort_keys=True,allow_nan=False)+"\n")
        print(json.dumps(dict(status=report["verdict"],
            checked=len(report["rows"]),verified=report["fully_verified"],
            signed_creations=report["verified_signed_creations"],
            unique_creators=report["unique_creator_claims"],
            financial_order_submitted=False)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="CRYPTO_HINT_AUDIT_REFUSED",
            safe_error_class=type(exc).__name__,
            financial_order_submitted=False,live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
