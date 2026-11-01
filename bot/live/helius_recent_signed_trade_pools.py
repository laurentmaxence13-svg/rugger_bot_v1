"""Bounded Helius signed *recent-trade* LaunchLab/SOL pool discovery.

Sampling the first active-pool program page yielded static/dormant pools.
This discovery instead follows recent FINALIZED LaunchLab program signatures,
validates exact transaction Ed25519 messages, and accepts only OUTER signed
LaunchLab buy/sell instructions with IDL-pinned account indices and SOL quote.

Candidates are registered before any S1 market/account lookup. This proves
a previously signed recent program trade, NOT token creator identity, S1
executable entry/exit price, real filled PAPER inventory or profitability.
Inner routed calls and Solana v1 receipts are explicitly censored here;
there is no silent parsed-metadata promotion. No wallet or sending ability.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_launchlab_cohort_probe import RAW_OPTS
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.certification import PROGRAM,_encode
from bot.p3.platform_admin_history import _b58_bytes,_signature
from bot.p3.quotes import SOL_MINT

PAGE=20
RECEIPT_LIMIT=8
MAX_SELECTED=3
MAX_AGE_SECONDS=600
IDL_TRADE_DISCRIMINATORS={
    bytes([250,234,13,123,213,156,19,236]):"BUY_EXACT_IN",
    bytes([24,211,116,40,105,3,153,56]):"BUY_EXACT_OUT",
    bytes([149,39,222,155,211,124,152,26]):"SELL_EXACT_IN",
    bytes([95,200,71,34,8,9,11,166]):"SELL_EXACT_OUT"}


def digest(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,
                separators=(",",":"),allow_nan=False).encode()).hexdigest()


def pinned_signed_launchlab_swaps(tx):
    """Require same verified signed outer message, no provider parsed hints."""
    if (type(tx) is not dict or type(tx.get("meta")) is not dict
            or tx["meta"].get("err") is not None):
        raise ValueError("successful_finalized_compiled_transaction_required")
    proof=verify_compiled_rpc_signatures(tx)
    if proof.get("cryptographic_signatures_verified") is not True:
        raise ValueError("launchlab_recent_trade_signature_unverified")
    normalized=normalized_compiled_transaction(tx)
    keys=normalized["transaction"]["message"]["accountKeys"]
    outer=normalized["transaction"]["message"]["instructions"]
    if type(outer) is not list:
        raise ValueError("compiled_outer_instructions_required")
    candidates=[]
    for ix in outer:
        if type(ix) is not dict:
            continue
        pi=ix.get("programIdIndex")
        ids=ix.get("accounts")
        wire=ix.get("data")
        if (type(pi) is not int or not 0<=pi<len(keys)
                or keys[pi]["pubkey"]!=PROGRAM):
            continue
        if type(ids) is not list or len(ids)<15 or type(wire) is not str:
            continue
        if any(type(i) is not int or not 0<=i<len(keys) for i in ids):
            raise ValueError("signed_trade_account_index_out_of_bounds")
        raw=_b58_bytes(wire)
        if _encode(raw)!=wire:
            raise ValueError("signed_trade_instruction_noncanonical")
        kind=IDL_TRADE_DISCRIMINATORS.get(raw[:8])
        if kind is None:
            continue
        payer,pool,base,quote=(keys[ids[i]] for i in (0,4,9,10))
        if (payer["signer"] is not True or pool["writable"] is not True or
                quote["pubkey"]!=SOL_MINT or base["pubkey"]==SOL_MINT or
                base["pubkey"]==pool["pubkey"]):
            continue
        candidates.append(dict(pool=pool["pubkey"],mint=base["pubkey"],
            signed_trader_payer=payer["pubkey"],side=kind,
            source_slot=tx["slot"],
            exact_message_sha256=proof["exact_message_sha256"],
            original_creation_signer_verified=False,
            direct_outer_idl_trade_instruction=True))
    return candidates


def discover_recent_signed_sol_trade_pools(rpc,*,clock_ms=None):
    """Exact 10-call ceiling: genesis(1), signatures(1), eight receipts."""
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("mainnet_genesis_read_only_required")
    now=int(time.time_ns()//1_000_000 if clock_ms is None else clock_ms)
    if now<=0:
        raise ValueError("valid_source_observation_clock_required")
    listed=rpc("getSignaturesForAddress",[PROGRAM,dict(
        limit=PAGE,commitment="finalized")])
    if (type(listed) is not list or len(listed)>PAGE
            or any(type(x) is not dict for x in listed)):
        raise ValueError("bounded_program_signature_page_required")
    records=[];seen=set();selected=[];seen_pools=set();seen_mints=set()
    for i,meta in enumerate(listed):
        sig=_signature(meta.get("signature"))
        slot=meta.get("slot")
        observed_time=meta.get("blockTime")
        if sig in seen or type(slot) is not int or slot<=0:
            raise ValueError("invalid_duplicate_program_signature_page")
        seen.add(sig)
        age=(now-observed_time*1000 if type(observed_time) is int else None)
        row=dict(ordinal=i,signature=sig,slot=slot,
            listed_block_time_sec=observed_time,
            source_age_ms=age,
            eligibility_reason=None,trade_pool=None,
            financial_order_submitted=False)
        if meta.get("err") is not None:
            row["eligibility_reason"]="FAILED_SIGNED_PROGRAM_TRANSACTION"
        elif age is None or age<0 or age>MAX_AGE_SECONDS*1000:
            row["eligibility_reason"]="UNVERIFIED_OR_STALE_PROGRAM_TRANSACTION_CLOCK"
        elif i>=RECEIPT_LIMIT:
            row["eligibility_reason"]="NOT_INSPECTED_RPC_BUDGET"
        else:
            receipt=rpc("getTransaction",[sig,RAW_OPTS])
            if (type(receipt) is not dict or receipt.get("slot")!=slot or
                    type(receipt.get("transaction")) is not dict or
                    receipt["transaction"].get("signatures",[None])[0]!=sig or
                    receipt.get("version") not in ("legacy",0,None)):
                row["eligibility_reason"]="FINALIZED_RECEIPT_VERSION_OR_IDENTITY_UNQUALIFIED"
            else:
                try:
                    swaps=pinned_signed_launchlab_swaps(receipt)
                    row["signed_outer_launchlab_SOL_trades"]=len(swaps)
                    row["eligibility_reason"]=(
                        "SIGNED_SOL_LAUNCHLAB_TRADE" if swaps else
                        "VERIFIED_OTHER_PROGRAM_INSTRUCTION")
                    for swap in swaps:
                        if (len(selected)<MAX_SELECTED and
                                swap["pool"] not in seen_pools and
                                swap["mint"] not in seen_mints):
                            selected.append(dict(swap,signature=sig,
                                observed_before_market_S1=True,
                                source_age_ms=age))
                            seen_pools.add(swap["pool"]);seen_mints.add(swap["mint"])
                            row["trade_pool"]=swap["pool"]
                except (ValueError,TypeError,IndexError,KeyError):
                    row["eligibility_reason"]="SIGNED_RECEIPT_OR_INSTRUCTION_REFUSED"
        records.append(row)
    report=dict(schema="rugger-signed-recent-sol-launchlab-trades-v1",
        source_program=PROGRAM,source_commitment="finalized",
        root_selection_at_ms=now,source_signature_count=len(listed),
        receipt_lookup_budget=RECEIPT_LIMIT,
        receipt_lookup_attempts=sum(
            x["eligibility_reason"] in (
                "SIGNED_SOL_LAUNCHLAB_TRADE",
                "VERIFIED_OTHER_PROGRAM_INSTRUCTION",
                "SIGNED_RECEIPT_OR_INSTRUCTION_REFUSED",
                "FINALIZED_RECEIPT_VERSION_OR_IDENTITY_UNQUALIFIED")
            for x in records),
        selected_recent_pool_count=len(selected),
        selected_signed_recent_trade_pools=selected,
        original_signature_page_records=records,
        source_signature_denominator_sha256=digest(listed),
        only_outer_signed_trade_accounts_accepted=True,
        v1_and_inner_routed_trades_not_verified=True,
        source_creator_not_authenticated_by_trader=True,
        live_pool_status_not_yet_queried=True,
        S1_S2_account_banks_not_yet_observed=True,
        recent_trade_selection_no_future_exit_used=True,
        actual_master_decision=None,actual_PAPER_fills=0,
        full_roundtrip_proof=False,master_net_pnl_lamports=None,
        financial_order_submitted=False,live_ready_to_arm=False)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.network:p.error("Explicit read-only --network required")
    if args.output.exists() or args.output.is_symlink():
        p.error("new immutable output required")
    try:
        rpc=HeliusReadOnlyRpc.from_environment(
            max_calls=10,allow_launch_discovery=True)
        doc=discover_recent_signed_sol_trade_pools(rpc)
        doc["RPC_calls_used"]=rpc.count
        args.output.parent.mkdir(parents=True,exist_ok=True)
        atomic_write_json(args.output,doc,sort_keys=True,allow_nan=False)
        print(json.dumps(dict(status="SIGNED_RECENT_TRADE_DISCOVERY_FINISHED",
            signed_recent_SOL_pools=doc["selected_recent_pool_count"],
            inspected_receipts=doc["receipt_lookup_attempts"],
            RPC_calls=rpc.count,financial_order_submitted=False,
            exact_master_profitability=None),sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="SOURCE_REFUSED",
            error_class=type(exc).__name__,
            financial_order_submitted=False),sort_keys=True))
        return 2


if __name__=="__main__":
    sys.exit(main())
