"""Bounded finalized Ed25519 replay of previously archived Helius creations.

Archive hashes prove internal consistency, not provenance by themselves.
Only independently fetched finalized signed outer instructions can upgrade a
creator claim to a cryptographically authenticated public key. Replay is
HISTORICAL: it never retroactively authenticates the as-of trading signal.
"""
import argparse
import json
from pathlib import Path

from bot.p3.prospective_campaign_funnel import funnel
from bot.live.helius_early_signed_s1s2 import signed_receipt_proof
from bot.live.readonly_plan import MAINNET_GENESIS

SCHEMA="rugger-finalized-campaign-ed25519-replay-v1"
MAX_REPLAY=3


def _digest(value):
    return (type(value) is str and len(value)==64
            and all(c in "0123456789abcdef" for c in value))


def replay_finalized_campaign(summary,windows,rpc,*,max_replay=3,
                              proof=signed_receipt_proof):
    """Read-only <=1+2*max_replay RPC calls, with explicit missing denominator."""
    if (not callable(rpc) or not callable(proof) or type(max_replay) is not int
            or not 1<=max_replay<=MAX_REPLAY):
        raise ValueError("bounded_readonly_replay_required")
    source=funnel(summary,windows)
    candidates={}
    seen_pool={}
    for window in windows:
        events={e["signature"]:e for e in window["events"]}
        for attempt in window["report"]["attempts"]:
            launches=attempt.get("signed_outer_creations")
            if not launches:
                continue
            sig=attempt["signature"]
            if type(launches) is not list or len(launches)!=1:
                raise ValueError("ambiguous_outer_creation_claim")
            launch=launches[0]
            if type(launch) is not dict:
                raise ValueError("signed_creation_identity_missing")
            creator=launch.get("creator");mint=launch.get("mint");pool=launch.get("pool")
            if not all(type(x) is str and x for x in (creator,mint,pool)):
                raise ValueError("complete_public_creation_identity_required")
            slot=attempt.get("source_slot")
            event_slot=events[sig].get("slot")
            if type(slot) is not int or slot<=0 or event_slot!=slot:
                raise ValueError("signed_creation_source_slot_not_bound_to_capture")
            message_hash=attempt.get("confirmed_message_sha256")
            if not _digest(message_hash):
                raise ValueError("preoutcome_message_sha256_required")
            identity=(creator,mint,pool,slot,message_hash)
            if sig in candidates and candidates[sig]!=identity:
                raise ValueError("contradictory_signed_creation_claim_across_windows")
            candidates[sig]=identity
            if (mint,pool) in seen_pool and seen_pool[(mint,pool)]!=creator:
                raise ValueError("contradictory_creator_for_same_signed_pool")
            seen_pool[(mint,pool)]=creator
    # Before querying any later finalized outcomes, fix the sample by
    # source observation order, not by price, finality, or later survivorship.
    ordered=list(candidates.items())
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("explicit_mainnet_required")
    records=[]
    for index,(sig,identity) in enumerate(ordered):
        creator,mint,pool,slot,confirmed_hash=identity
        row=dict(signature=sig,creator=creator,mint=mint,pool=pool,
            source_slot=slot,source_confirmed_message_sha256=confirmed_hash,
            independently_verified_finalized_message_sha256=None,
            status="NOT_REPLAYED_BUDGET" if index>=max_replay else "UNVERIFIED",
            source_capture_asof_authentication=False,
            financial_order_submitted=False)
        if index>=max_replay:
            records.append(row)
            continue
        try:
            raw=rpc("getTransaction",[sig,dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1)])
            if raw is None:
                row["status"]="FINALIZED_RECEIPT_UNAVAILABLE"
            else:
                final=proof(raw,sig,slot,rpc,commitment="finalized")
                row["independently_verified_finalized_message_sha256"]=final["message_sha256"]
                signed=final["launches"]
                if final["message_sha256"]!=confirmed_hash:
                    row["status"]="CONFIRMED_FINALIZED_MESSAGE_MISMATCH"
                elif len(signed)!=1:
                    row["status"]="FINALIZED_OUTER_CREATION_AMBIGUOUS_OR_ABSENT"
                elif signed[0] != dict(creator=creator,mint=mint,pool=pool):
                    row["status"]="FINALIZED_CREATOR_MINT_POOL_MISMATCH"
                else:
                    row["status"]="EXACT_FINALIZED_ED25519_CREATION_VERIFIED"
        except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
            row["status"]="FINALIZED_RECEIPT_OR_CRYPTO_REFUSED"
            row["safe_error_class"]=type(exc).__name__
        records.append(row)
    verified={r["creator"] for r in records
              if r["status"]=="EXACT_FINALIZED_ED25519_CREATION_VERIFIED"}
    return dict(schema=SCHEMA,
        source_campaign_sha256=source["campaign_sha256"],
        source_total_observed_event_signatures=source["unique_event_signatures"],
        source_uninspected_event_signatures=source["uninspected_unique_event_signatures"],
        signed_creation_claim_signatures=len(candidates),
        source_claimed_creator_ids=len({x[0] for x in candidates.values()}),
        bounded_replay_attempts=min(len(candidates),max_replay),
        not_replayed_due_to_budget=max(0,len(candidates)-max_replay),
        independently_verified_finalized_creator_ids=len(verified),
        independently_verified_creator_public_keys=sorted(verified),
        records=records,
        cryptographic_replay_does_not_prove_historical_decision_availability=True,
        eligible_for_future_registered_holdout=False,
        independent_economic_actor_identity_verified=False,
        exact_lot_executable_buy_sell_cycles=0,
        net_master_reference_advantage_lamports=None,
        market_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)


def main(argv=None):
    import os
    from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args(argv)
    if (args.summary.resolve()==args.output.resolve() or args.output.exists()
            or args.output.is_symlink()):
        p.error("immutable_distinct_source_and_new_output_required")
    if (os.environ.get("GITHUB_ACTIONS")!="true" or
            not os.environ.get("HELIUS_API_KEY")):
        print(json.dumps(dict(status="REPLAY_REFUSED",financial_order_submitted=False)))
        return 2
    prefix=args.summary.name.removesuffix("_summary.json")
    if prefix==args.summary.name:
        p.error("campaign_summary_filename_required")
    summary=json.loads(args.summary.read_text(encoding="utf8"))
    windows=[json.loads((args.summary.parent/f"{prefix}_window_{i:02d}.json").read_text(encoding="utf8"))
             for i in range(1,summary["windows_requested"]+1)]
    try:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=1+2*MAX_REPLAY)
        report=replay_finalized_campaign(summary,windows,rpc)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x",encoding="utf8") as f:
            json.dump(report,f,sort_keys=True,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(dict(status="HISTORICAL_ED25519_REPLAY",
            claimed=report["signed_creation_claim_signatures"],
            verified=report["independently_verified_finalized_creator_ids"],
            not_replayed=report["not_replayed_due_to_budget"],
            qualified_cycles=0,financial_order_submitted=False)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="REPLAY_REFUSED",
            safe_error_class=type(exc).__name__,
            financial_order_submitted=False,live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
