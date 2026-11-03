"""Independent finalized Ed25519 check of two P3 public Raydium index creators.

Sources are pinned P3 capture journal from Actions 41259451370, rows 40/43
and 50/53. Provider-parsed creation is NOT necessarily in an outer signed ix.
Historical proof cannot retroactively certify real-time decision availability.
"""
import json
import os
from pathlib import Path
import sys

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_early_signed_s1s2 import signed_receipt_proof
from bot.live.readonly_plan import MAINNET_GENESIS

SOURCE_RUN=41259451370
RECORDS=(
    dict(signature="2qMuBHkbWPy41ThgSrsTm3kHk7G2r86nDQmxMtgp4FkiSQAKcxg5n8Nn7krcAwrqEsHfDgTjQpt35LNyjCFT7iQ1",
         slot=463900146,mint="9qSvf5uzaUCRvucCmTgLJcicFZXP5dJZN23ZxpYTqG5Q",
         creator="GDLcuuJCRab8Tako3STjH6GbX9j12QNtoDjRGE19EuMn",
         pool="BUvP1ZpDYPwNM87quDHaJQqyv3wCdcMPThHXb5WHj78W"),
    dict(signature="81CFUF2dGb9Vqz2TUKnuUu2ZMVBGaoub7Dq86SWPU9WYnGfj4gNSUi9XLCqCV6nwkhNyrUkHJBfJnSpETG34VTv",
         slot=463900114,mint="7Cc78JVbBvzHJvbQcSw1vojQtng7zSSyJSHNbYBHgt2t",
         creator="Ed1qtbw7KUGtrNsdYNPYX7X8c8pH7RoP1TKzUZgFaDi7",
         pool="84M9vKc2V5C4GHHJFp1rXq7uk7TbLotxSTxUQPUfTW4e"),
)


def inspect_pinned_index_signatures(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("explicit_mainnet_required")
    records=[]
    for source in RECORDS:
        entry=dict(source,status="UNVERIFIED",
            verified_exact_message_sha256=None,signed_outer_creations=None,
            source_provenance="p3_public_index_creation_claim_not_signed_evidence",
            historical_asof_market_admissibility=False,
            paper_master_action=None,financial_order_submitted=False)
        try:
            raw=rpc("getTransaction",[source["signature"],dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1)])
            if raw is None:
                entry["status"]="FINALIZED_RECEIPT_UNAVAILABLE"
            else:
                proof=signed_receipt_proof(raw,source["signature"],source["slot"],rpc,
                    commitment="finalized")
                entry["verified_exact_message_sha256"]=proof["message_sha256"]
                signed=proof["launches"]
                entry["signed_outer_creations"]=signed
                if len(signed)!=1:
                    entry["status"]=("SIGNED_OUTER_CREATION_ABSENT"
                        if not signed else "AMBIGUOUS_SIGNED_OUTER_CREATIONS")
                elif ((signed[0].get("mint"),signed[0].get("pool"),signed[0].get("creator"))
                      != (source["mint"],source["pool"],source["creator"])):
                    entry["status"]="INDEX_AND_SIGNED_CREATION_MISMATCH"
                else:
                    entry["status"]="EXACT_OUTER_SIGNED_CREATION_VERIFIED"
        except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
            entry["status"]="RECEIPT_OR_CRYPTO_REFUSED"
            entry["safe_error_class"]=type(exc).__name__
        records.append(entry)
    count=sum(x["status"]=="EXACT_OUTER_SIGNED_CREATION_VERIFIED" for x in records)
    return dict(schema="rugger-pinned-index-creators-finalized-proof-v1",
        source_actions_run=SOURCE_RUN,source_claim_count=len(RECORDS),
        records=records,exact_outer_signed_creators_verified=count,
        fully_receipt_classified=all(
            x["status"] not in ("UNVERIFIED","FINALIZED_RECEIPT_UNAVAILABLE","RECEIPT_OR_CRYPTO_REFUSED")
            for x in records),
        asof_market_entry_proven=False,
        source_quote_time_and_slot_missing=True,
        full_position_quotes_from_separate_p3_journal=True,
        qualified_economic_cycles=0,master_net_pnl_lamports=None,
        reference_net_pnl_lamports=None,master_vs_reference_edge_lamports=None,
        financial_order_submitted=False,live_ready_to_arm=False)


def main():
    if (os.environ.get("GITHUB_ACTIONS")!="true" or
        not os.environ.get("GITHUB_WORKSPACE") or not os.environ.get("HELIUS_API_KEY")):
        print(json.dumps(dict(status="PINNED_CREATOR_PROOF_REFUSED",
            financial_order_submitted=False)))
        return 2
    try:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=5)
        report=inspect_pinned_index_signatures(rpc)
        root=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        if not (root/"bot/p3/bitquery_creation_intake.py").is_file():
            raise ValueError("required_research_root_missing")
        dest=root/"paper_artifacts"
        if dest.is_symlink():
            raise ValueError("artifact_symlink_refused")
        dest.mkdir(exist_ok=True)
        out=dest/f"pinned_index_signed_proof_{os.environ['GITHUB_RUN_ID']}.json"
        with out.open("x",encoding="utf8") as stream:
            json.dump(report,stream,sort_keys=True,allow_nan=False)
            stream.write("\n")
        print(json.dumps(dict(status="PINNED_CREATOR_PROOF_AUDIT",
            signed_outer_creators_verified=report["exact_outer_signed_creators_verified"],
            fully_receipt_classified=report["fully_receipt_classified"],
            qualified_economic_cycles=0,financial_order_submitted=False)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="PINNED_CREATOR_PROOF_REFUSED",
            safe_error_class=type(exc).__name__,
            financial_order_submitted=False,live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
