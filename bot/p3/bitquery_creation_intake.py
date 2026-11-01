"""Read-only Bitquery -> independently signed LaunchLab creation evidence.

A Bitquery Instruction row is a DISCOVERY CLAIM, not proof that an instruction
was in the outer Ed25519-signed message and not a real-time Master signal.
Only finalized exact receipts can qualify the identity; no historical S1 tape
is reconstructed from a current RPC snapshot. No network except the caller's
explicitly allowlisted Helius public RPC client.
"""
from datetime import datetime, timezone
import hashlib
import json

from bot.p3.certification import PROGRAM
from bot.p3.platform_admin_history import _signature
from bot.p3.quotes import _mint
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.helius_early_signed_s1s2 import signed_receipt_proof

METHODS=frozenset(("initialize_v2","initialize_with_token_2022",
                   "initialize_with_token2022"))
MAX_ROWS=200
MAX_VERIFY=4


def _digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,
        allow_nan=False,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()


def _utc(value):
    if type(value) is not str:
        raise ValueError("bitquery_block_time_missing")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise ValueError("bitquery_block_time_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:
        raise ValueError("bitquery_block_time_must_be_utc")
    return parsed.isoformat()


def parse_bitquery_creation_response(payload):
    """No invented source clocks, fee payer, quote mint, signer or S1 tape."""
    if type(payload) is not dict:
        raise ValueError("bitquery_response_must_be_object")
    if payload.get("errors"):
        raise ValueError("bitquery_graphql_errors_present")
    data=payload.get("data")
    if type(data) is not dict or type(data.get("Solana")) is not dict:
        raise ValueError("bitquery_sol_create_response_missing")
    rows=data["Solana"].get("Instructions")
    if type(rows) is not list or len(rows)>MAX_ROWS:
        raise ValueError("bitquery_bounded_instructions_required")
    claims=[]
    seen={}
    discarded=0
    for index,row in enumerate(rows):
        if type(row) is not dict:
            raise ValueError("bitquery_instruction_row_invalid")
        block=row.get("Block");tx=row.get("Transaction");ix=row.get("Instruction")
        if not all(type(x) is dict for x in (block,tx,ix)):
            raise ValueError("bitquery_block_tx_instruction_incomplete")
        program=ix.get("Program")
        if type(program) is not dict:
            raise ValueError("bitquery_program_missing")
        # Rows returned by Bitquery's Method filter must still be checked here.
        if program.get("Address")!=PROGRAM or program.get("Method") not in METHODS:
            discarded+=1
            continue
        sig=_signature(tx.get("Signature"))
        slot=block.get("Slot")
        if type(slot) is not int or slot<=0:
            raise ValueError("bitquery_slot_invalid")
        t=_utc(block.get("Time"))
        accounts=ix.get("Accounts")
        if type(accounts) is not list or len(accounts)<7 or len(accounts)>255:
            raise ValueError("bitquery_initialization_accounts_incomplete")
        addrs=[]
        for account in accounts:
            if type(account) is not dict:
                raise ValueError("bitquery_account_row_invalid")
            addrs.append(_mint(account.get("Address")))
        idx=ix.get("Index")
        # Index may be absent in some public responses; retain this unknown.
        if idx is not None and (type(idx) is not int or idx<0):
            raise ValueError("bitquery_instruction_index_invalid")
        identity=dict(signature=sig,source_slot=slot,block_time_utc=t,
            instruction_index=idx,reported_method=program["Method"],
            reported_payer=addrs[0],reported_creator=addrs[1],
            reported_pool=addrs[5],reported_mint=addrs[6],
            reported_quote_mint=None,
            provider_reported_signer=tx.get("Signer") if type(tx.get("Signer")) is str else None,
            provider_available_at_ms=None,
            is_cryptographically_verified=False,
            asof_master_decision_possible=False,
            economic_cycle_qualified=False,
            financial_order_submitted=False)
        if sig in seen:
            old=seen[sig]
            if {k:v for k,v in old.items() if k not in ("instruction_index","reported_method")} != {
               k:v for k,v in identity.items() if k not in ("instruction_index","reported_method")}:
                raise ValueError("conflicting_creation_claim_same_signature")
            discarded+=1
            continue
        seen[sig]=identity
        claims.append(identity)
    claims.sort(key=lambda x:(x["source_slot"],x["signature"]))
    return dict(schema="rugger-bitquery-creation-discovery-v1",
        source="bitquery_instructions_graphql",
        source_response_sha256=_digest(payload),
        rows_returned=len(rows),rows_discarded_or_duplicated=discarded,
        candidates=len(claims),claims=claims,
        source_block_time_not_source_availability=True,
        source_universe_completeness_verified=False,
        historical_causal_S1_evidence_present=False,
        signed_creations_verified=0,
        master_net_pnl_lamports=None,
        reference_net_pnl_lamports=None,
        financial_order_submitted=False,
        live_ready_to_arm=False)


def verify_bitquery_candidates(report,rpc,*,selection_limit=MAX_VERIFY):
    """Never infer a signed creator from Bitquery's provider-reported fields."""
    if (type(report) is not dict or
        report.get("schema")!="rugger-bitquery-creation-discovery-v1"
        or report.get("financial_order_submitted") is not False
        or report.get("live_ready_to_arm") is not False
        or type(report.get("claims")) is not list
        or type(selection_limit) is not int or not 1<=selection_limit<=MAX_VERIFY
        or not callable(rpc)):
        raise ValueError("immutable_readonly_candidate_intake_required")
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("mainnet_genesis_required")
    # Select a fixed prefix *before* looking up any receipts.
    selections=report["claims"][:selection_limit]
    records=[]
    for item in selections:
        if item.get("is_cryptographically_verified") is not False:
            raise ValueError("discovery_claim_cannot_be_self_verified")
        signature=item["signature"];slot=item["source_slot"]
        record=dict(signature=signature,slot=slot,
            reported_mint=item["reported_mint"],reported_pool=item["reported_pool"],
            reported_creator=item["reported_creator"],
            status="UNVERIFIED",exact_message_sha256=None,
            confirmed_signed_creations=[],
            quote_mint=None,
            historical_entry_clock_available=False,
            signed_creator_from_exact_receipt=False,
            financial_order_submitted=False)
        try:
            raw=rpc("getTransaction",[signature,dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1)])
            if raw is None:
                record["status"]="FINALIZED_RECEIPT_UNAVAILABLE"
            else:
                proof=signed_receipt_proof(raw,signature,slot,rpc,commitment="finalized")
                record["exact_message_sha256"]=proof["message_sha256"]
                signed=proof["launches"]
                if not signed:
                    record["status"]="VERIFIED_NON_CREATION"
                elif len(signed)!=1:
                    record["status"]="AMBIGUOUS_SIGNED_CREATION_COUNT"
                elif (signed[0]["mint"],signed[0]["pool"],signed[0]["creator"]) != (
                      item["reported_mint"],item["reported_pool"],item["reported_creator"]):
                    record["status"]="BITQUERY_SIGNED_IDENTITY_DISAGREEMENT"
                else:
                    record["confirmed_signed_creations"]=signed
                    record["status"]="SIGNED_CREATION_IDENTITY_VERIFIED"
                    record["signed_creator_from_exact_receipt"]=True
        except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
            record["status"]="CRYPTO_OR_RECEIPT_REFUSED"
            record["safe_error_class"]=type(exc).__name__
        records.append(record)
    return dict(schema="rugger-bitquery-helius-identity-reconciliation-v1",
        source_discovery_sha256=_digest(report),
        selection="first_four_earliest_exported_creation_hints_before_RPC_lookup",
        source_rows=len(report["claims"]),selected_count=len(selections),
        records=records,
        verified_signed_creations=sum(r["status"]=="SIGNED_CREATION_IDENTITY_VERIFIED" for r in records),
        independent_creator_ids=len({r["confirmed_signed_creations"][0]["creator"] for r in records
             if r["status"]=="SIGNED_CREATION_IDENTITY_VERIFIED"}),
        asof_entry_quotes_available=False,executed_trades=0,
        qualified_economic_cycles=0,master_net_pnl_lamports=None,
        reference_net_pnl_lamports=None,financial_order_submitted=False,
        live_ready_to_arm=False)


def main(argv=None):
    """Convert one Bitquery export to immutable discovery plus optional proof."""
    import argparse
    import os
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--verify-signed-receipts",action="store_true")
    parser.add_argument("--verified-output",type=Path)
    args=parser.parse_args(argv)
    if args.input.resolve()==args.output.resolve():
        parser.error("input_and_output_must_differ")
    if args.verify_signed_receipts and (
        args.verified_output is None or not os.environ.get("HELIUS_API_KEY")):
        parser.error("signed_proof_requires_output_and_existing_helius_secret")
    if args.verified_output and (
        args.verified_output.resolve() in (args.input.resolve(),args.output.resolve())):
        parser.error("proof_output_must_be_distinct")
    if args.input.stat().st_size>3_000_000:
        parser.error("bitquery_export_exceeded_bounded_input")
    payload=json.loads(args.input.read_text(encoding="utf-8"))
    report=parse_bitquery_creation_response(payload)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8") as out:
        out.write(json.dumps(report,sort_keys=True,allow_nan=False)+"\n")
    if args.verify_signed_receipts:
        from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=10)
        proof=verify_bitquery_candidates(report,rpc)
        args.verified_output.parent.mkdir(parents=True,exist_ok=True)
        with args.verified_output.open("x",encoding="utf-8") as out:
            out.write(json.dumps(proof,sort_keys=True,allow_nan=False)+"\n")
        print(json.dumps(dict(status="SIGNED_IDENTITY_RECONCILED",
            discovered=report["candidates"],cryptographically_verified=proof["verified_signed_creations"],
            asof_entry_quotes_available=False,
            master_net_pnl_lamports=None,financial_order_submitted=False)))
    else:
        print(json.dumps(dict(status="BITQUERY_HINTS_ONLY_NOT_SIGNED",
            discovered=report["candidates"],cryptographically_verified=0,
            asof_entry_quotes_available=False,
            master_net_pnl_lamports=None,financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
