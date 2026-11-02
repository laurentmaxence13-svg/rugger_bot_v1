"""Index-first retrospective SIGNED LaunchLab public-source acquisition.

The Raydium public index is an UNTRUSTED lead, not independent creator proof.
Only an Ed25519-verified OUTER LaunchLab instruction for exactly the claimed
mint/pool/creator can corroborate it. Capturing after index discovery is not
the same as observing a launch at creation time. No PAPER fills, no orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from bot.analyser.artifacts import atomic_write_json
from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.public_sol_forward_paper import PublicReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.p3.helius_index_prospective_cohort import (
    fetch_index, register_prebank_universe, _bank)
from bot.p3.launchlab import addresses_from_pool,analyze_snapshot
from bot.p3.quotes import SOL_MINT

SCHEMA = "rugger-free-public-index-signed-creator-audit-v1"
MAX_POOLS=2
MAX_RECEIPTS_PER_POOL=2
SIGNATURE_PAGE_LIMIT=1000
MAX_RPC_PER_POOL=10
MAX_TOTAL_RPC=20


def _sha(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(",",":"),
                        allow_nan=False).encode("utf-8")).hexdigest()


def inspect_pool(pool, *, rpc, max_receipts=MAX_RECEIPTS_PER_POOL):
    if type(pool) is not dict or not all(type(pool.get(k)) is str and pool[k]
          for k in ("pool","mint","creator_claim")):
        raise ValueError("source_pool_index_claim_required")
    if type(max_receipts) is not int or not 1 <= max_receipts <= 2:
        raise ValueError("fixed_source_receipt_limit_required")
    if rpc("getGenesisHash", []) != MAINNET_GENESIS:
        raise ValueError("wrong_sol_source_genesis")
    page=rpc("getSignaturesForAddress",[pool["pool"],
                {"limit":SIGNATURE_PAGE_LIMIT,"commitment":"finalized"}])
    if type(page) is not list or len(page) > SIGNATURE_PAGE_LIMIT:
        raise ValueError("unbounded_source_pool_signature_page")
    seen=set()
    valid=[]
    for row in page:
        if (type(row) is not dict or type(row.get("signature")) is not str
                or type(row.get("slot")) is not int or row["slot"] <= 0
                or row["signature"] in seen or "err" not in row):
            raise ValueError("malformed_or_duplicate_pool_signatures")
        seen.add(row["signature"])
        if row["err"] is None:
            valid.append(row)
    # Selection fixed from FIRST page before reading any transaction body.
    # The oldest available successful signatures are most likely origin
    # receipts. This is RETROSPECTIVE and can miss a creator outside 1000.
    selected=list(reversed(valid))[:max_receipts]
    result=dict(mint=pool["mint"],pool=pool["pool"],
        claimed_creator=pool["creator_claim"],
        candidate_signature_page_size=len(page),
        page_may_exclude_creation=len(page)==SIGNATURE_PAGE_LIMIT,
        selected_signatures_precommitted=len(selected),
        outer_signed_create_verified=False,
        signed_message_sha256=None,
        signed_creation_signature=None,
        signed_creation_slot=None,
        native_SOL_pool_graph_verified=False,
        contextual_S1_bank_qualified=False,
        S1_blocking_reasons=None,
        candidate_is_retrospective_index_survivor=True,
        price_at_creation_unknown=True,
        genuine_master_paper_buy_sell_verified=False,
        master_net_pnl_lamports=None,
        status="NO_MATCHING_OUTER_SIGNED_CREATE_IN_SAMPLED_PAGE")
    for row in selected:
        raw=rpc("getTransaction",[row["signature"],dict(
            encoding="json",commitment="finalized",
            maxSupportedTransactionVersion=0)])
        if raw is None or type(raw) is not dict or type(raw.get("meta")) is not dict:
            continue
        if (raw.get("slot")!=row["slot"] or raw["meta"].get("err") is not None
                or type(raw.get("transaction")) is not dict
                or type(raw["transaction"].get("signatures")) is not list
                or not raw["transaction"]["signatures"]
                or raw["transaction"]["signatures"][0]!=row["signature"]):
            continue
        # Failing Ed25519 verification cannot be covered by a loose index.
        proof=verify_compiled_rpc_signatures(raw)
        if proof.get("cryptographic_signatures_verified") is not True:
            raise ValueError("source_creator_signature_not_independently_verified")
        outer=dict(raw,meta=dict(raw["meta"],innerInstructions=[]))
        launches=compiled_launchlab_creations(outer)
        if type(launches) is not list:
            raise ValueError("source_outer_creation_parser_refused")
        message=raw["transaction"].get("message")
        if (type(message) is not dict or type(message.get("header")) is not dict
                or type(message.get("accountKeys")) is not list):
            raise ValueError("source_compiled_signer_keys_unavailable")
        signed_count=message["header"].get("numRequiredSignatures")
        if type(signed_count) is not int or not 1<=signed_count<=len(message["accountKeys"]):
            raise ValueError("source_compiled_signer_count_invalid")
        signed_payers=set(message["accountKeys"][:signed_count])
        if not any(type(v) is dict and
            v.get("creator")==pool["creator_claim"] and
            v.get("pool_state")==pool["pool"] and
            v.get("mint")==pool["mint"] and
            v.get("payer") in signed_payers
            for v in launches):
            continue
        result["outer_signed_create_verified"]=True
        result["signed_message_sha256"]=proof["exact_message_sha256"]
        result["signed_creation_signature"]=row["signature"]
        result["signed_creation_slot"]=raw["slot"]
        result["status"]="SIGNED_CREATION_VERIFIED_INDEX_SURVIVOR_NOT_SIGNAL"
        break
    if not result["outer_signed_create_verified"]:
        return result
    # Even matching a signed creation does not establish SOL quote.
    slot,root=_bank(rpc,[pool["pool"]],result["signed_creation_slot"])
    account=root.get(pool["pool"])
    if account is None:
        result["status"]="SIGNED_CREATION_POOL_ACCOUNT_MISSING"
        return result
    graph=addresses_from_pool(account,pool["mint"],pool["pool"])
    if graph.get("mint_b")!=SOL_MINT or len(set(graph.values()))!=7:
        result["status"]="SIGNED_CREATION_NOT_NATIVE_SOL_GRAPH"
        return result
    result["native_SOL_pool_graph_verified"]=True
    # Read all seven public accounts in one context; this is a later bank,
    # NOT state at launch. Missing/partial on-chain identity flags remain.
    s1slot,s1accounts=_bank(rpc,list(graph.values()),slot)
    try:
        analysis=analyze_snapshot(s1accounts,context_slot=s1slot,
            expected_mint=pool["mint"],pool_address=pool["pool"],
            input_lamports=100_000_000,evidence_profile="published_metadata_v1")
        result["contextual_S1_bank_qualified"]=not bool(analysis.get("risk_flags")) and not bool(
            analysis.get("blocking_reasons"))
        result["S1_blocking_reasons"]=analysis.get("blocking_reasons")
        result["S1_risk_flags"]=analysis.get("risk_flags")
        result["S1_observed_slot"]=s1slot
        result["status"]="SIGNED_SOL_CREATION_LATE_BANK_NO_MASTER_FILL"
    except (ValueError,KeyError,TypeError):
        result["status"]="SIGNED_CREATION_LATE_S1_BANK_UNQUALIFIED"
    return result


def run_index_proof_campaign(*,output_dir,fetch_rows=fetch_index,
                             rpc_factory=PublicReadOnlyRpc):
    folder=Path(output_dir)
    if folder.exists() or folder.is_symlink():
        raise ValueError("new_index_source_directory_required")
    folder.mkdir(parents=True,exist_ok=False)
    # Explicitly perform selection BEFORE any account/transaction lookups.
    rows=fetch_rows()
    registration=register_prebank_universe(rows)
    if registration.get("schema")!="rugger-index-first-prospective-cohort-v1":
        raise ValueError("wrong_source_index_registration_schema")
    selected=registration["selected"][:MAX_POOLS]
    receipts=[]
    for item in selected:
        rpc=rpc_factory(None,max_calls=MAX_RPC_PER_POOL)
        receipt=inspect_pool(item,rpc=rpc)
        if type(rpc.count) is not int or not 0<=rpc.count<=MAX_RPC_PER_POOL:
            raise ValueError("unbounded_source_read_budget")
        receipt["public_rpc_calls_used"]=rpc.count
        receipts.append(receipt)
    total=sum(r["public_rpc_calls_used"] for r in receipts)
    if total>MAX_TOTAL_RPC:
        raise ValueError("public_pool_index_call_cap_exceeded")
    summary=dict(schema=SCHEMA,
        source="UNTRUSTED_RAYDIUM_INDEX_PLUS_INDEPENDENT_PUBLIC_SOLANA_RPC",
        index_selection_sha256=_sha(registration),
        captured_at_utc_ms=time.time_ns()//1_000_000,
        precommitted_pool_count=len(selected),
        pools_checked=len(receipts),
        indexed_candidates_without_proven_coverage=True,
        individually_verified_outer_signed_creations=sum(
            r["outer_signed_create_verified"] for r in receipts),
        distinct_native_SOL_verified_creators=len(set(
            r["claimed_creator"] for r in receipts
            if r["native_SOL_pool_graph_verified"])),
        source_receipts=receipts,
        total_public_rpc_calls=total,maximum_allowed_public_rpc_calls=MAX_TOTAL_RPC,
        original_master_enter_qualified=False,
        genuine_master_paper_buy_sell_verified=False,
        independently_executable_quotes_verified=False,
        causal_prospective_creation_arrival_verified=False,
        financial_order_submitted=False,live_trading_enabled=False,
        master_net_pnl_lamports=None)
    atomic_write_json(folder/"index_registration.json",registration,
                      sort_keys=True,allow_nan=False)
    atomic_write_json(folder/"summary.json",summary,sort_keys=True,allow_nan=False)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        print("PUBLIC_INDEX_SOURCE_REFUSED:NETWORK_OPT_IN_REQUIRED")
        return 2
    try:
        result=run_index_proof_campaign(output_dir=args.output_dir)
    except Exception as error:
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
              safe_error_class=type(error).__name__,
              financial_order_submitted=False),sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
