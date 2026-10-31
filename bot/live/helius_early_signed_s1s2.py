"""Early confirmed LaunchLab evidence before the WebSocket observation window ends.

Experimental sensor. Public confirmed receipts are cryptographically checked,
but NOT finalized at S1; any later finality claim is separately validated.
Only one producer/consumer pair and ten read-only Helius RPC requests maximum.
Never turns conditional curve estimates into fills, P&L or active authority.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_ws_forward_paper import observe, _hash
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.solana_v1_readonly import verify_v1_base64_receipt
from bot.p3.helius_index_prospective_cohort import _bank
from bot.p3.launchlab import (addresses_from_pool, analyze_snapshot,
                              observed_sell_projection, SnapshotEvidenceError)
from bot.p3.quotes import SOL_MINT
from bot.master_decision import MasterDecisionOrchestrator

MAX_HINTS=4
MAX_RPC=10
S2_DELAY_SECONDS=5
OUTPUT="paper_artifacts/helius_early_signed_s1_s2.json"


def signed_receipt_proof(raw, signature, slot, rpc, *, commitment):
    """Check outer instruction Ed25519 identity without trusting RPC inner logs."""
    if commitment not in ("confirmed","finalized"):
        raise ValueError("unapproved_confirmation_state")
    if (type(raw) is not dict or raw.get("slot")!=slot
            or type(raw.get("meta")) is not dict
            or raw["meta"].get("err") is not None
            or raw.get("transaction",{}).get("signatures",[None])[0]!=signature):
        raise ValueError("receipt_slot_signature_status_unqualified")
    if type(raw.get("version")) is int and raw["version"]==1:
        wire=rpc("getTransaction",[signature,dict(
            encoding="base64",commitment=commitment,
            maxSupportedTransactionVersion=1)])
        proof=verify_v1_base64_receipt(
            wire,expected_signature=signature,expected_slot=slot)
        launches=proof["launched_candidates"]
        if any(c["payer"] not in proof["signer_public_keys"] for c in launches):
            raise ValueError("v1_creation_payer_must_sign")
        return dict(message_sha256=proof["exact_message_sha256"],
            launches=[dict(creator=x["creator"],mint=x["mint"],pool=x["pool"])
                      for x in launches],version=1)
    crypto=verify_compiled_rpc_signatures(raw)
    if crypto.get("cryptographic_signatures_verified") is not True:
        raise ValueError("ed25519_signature_unverified")
    normalized=normalized_compiled_transaction(raw)
    account_rows=normalized["transaction"]["message"]["accountKeys"]
    keys={x["pubkey"] for x in account_rows}
    signers={x["pubkey"] for x in account_rows if x["signer"]}
    all_launches=compiled_launchlab_creations(raw)
    only_outer=compiled_launchlab_creations(
        dict(raw,meta=dict(raw["meta"],innerInstructions=[])))
    def identities(xs):
        return {(x["payer"],x["creator"],x["pool_state"],x["mint"]) for x in xs}
    # Never treat provider inner-instruction claims as signed creators.
    if not identities(all_launches).issubset(identities(only_outer)):
        raise ValueError("inner_unverified_creation_not_eligible")
    for x in only_outer:
        if (x["payer"] not in signers
                or not {x["payer"],x["creator"],x["pool_state"],x["mint"]}.issubset(keys)):
            raise ValueError("outer_creation_signer_or_accounts_unqualified")
    return dict(message_sha256=crypto["exact_message_sha256"],
        launches=[dict(creator=x["creator"],mint=x["mint"],pool=x["pool_state"])
                  for x in only_outer],version=raw.get("version",0))


def inspect_one_hint_early(event,rpc,*,sleep=time.sleep,clock_ms=lambda: time.time_ns()//1000000):
    """Use the observed event, never future prices, to select this read-only probe."""
    if (type(event) is not dict or
            event.get("on_chain_transaction_failed") is not False or
            event.get("untrusted_initialize_log_hint") is not True or
            type(event.get("slot")) is not int or event["slot"]<=0):
        raise ValueError("early_selection_requires_successful_capture_hint")
    from bot.p3.platform_admin_history import _signature
    sig=_signature(event.get("signature"));slot=event["slot"]
    at=clock_ms()
    rec=dict(signature=sig,source_slot=slot,
        event_received_at_ms=event["reception_utc_ns"]//1000000,
        early_probe_started_at_ms=at,receipt_commitment="confirmed",
        source_log_is_only_untrusted_discovery=True,financial_order_submitted=False,
        finality_verified=False,economic_execution_verified=False,
        qualified_master_cycle=False,master_net_pnl_lamports=None,
        reference_net_pnl_lamports=None,master_minus_reference_net_lamports=None)
    if rpc.count>MAX_RPC-5:
        rec["status"]="READ_ONLY_RPC_BUDGET_RESERVED"
        return rec
    try:
        raw=rpc("getTransaction",[sig,dict(
            encoding="json",commitment="confirmed",
            maxSupportedTransactionVersion=1)])
        if raw is None:
            rec["status"]="CONFIRMED_RECEIPT_NOT_YET_AVAILABLE"
            return rec
        proof=signed_receipt_proof(raw,sig,slot,rpc,commitment="confirmed")
    except (ValueError,KeyError,TypeError,IndexError,AttributeError):
        rec["status"]="CONFIRMED_SIGNATURE_OR_CREATION_NOT_QUALIFIED"
        return rec
    rec["confirmed_message_sha256"]=proof["message_sha256"]
    rec["receipt_version"]=proof["version"]
    rec["signed_outer_creations"]=proof["launches"]
    if len(proof["launches"])!=1:
        rec["status"]=("VERIFIED_NON_CREATION" if not proof["launches"]
                        else "AMBIGUOUS_MULTIPLE_SIGNED_CREATIONS")
        return rec
    creator=proof["launches"][0]
    rec.update(creator=creator["creator"],mint=creator["mint"],
        pool=creator["pool"],status="SIGNED_CONFIRMED_PROVISIONAL")
    # A single creator, selected from the already received log, is fixed
    # BEFORE any pool-account or price lookups.
    if rpc.count>MAX_RPC-4:
        rec["root_refusal"]="insufficient_rpc_budget"
        return rec
    try:
        root,accounts=_bank(rpc,[creator["pool"]],slot)
        rec["root_slot"]=root
        rec["creation_to_root_slot_gap"]=root-slot
        if accounts[creator["pool"]] is None:
            rec["root_refusal"]="pool_account_unavailable"
            return rec
        graph=addresses_from_pool(accounts[creator["pool"]],
                                  creator["mint"],creator["pool"])
        if graph["mint_b"]!=SOL_MINT:
            rec["root_refusal"]="non_SOL_quoted_launch"
            return rec
        if len(set(graph.values()))!=7:
            rec["root_refusal"]="duplicate_seven_bank_accounts"
            return rec
        s1slot,s1accounts=_bank(rpc,list(graph.values()),root)
        at=clock_ms()
        rec["s1_slot"]=s1slot;rec["s1_received_ms"]=at
        analysis=analyze_snapshot(s1accounts,context_slot=s1slot,
            expected_mint=creator["mint"],pool_address=creator["pool"],
            input_lamports=1_000_000_000,
            evidence_profile="published_metadata_v1")
        rec["s1_bank_analysis_sha256"]=_hash(analysis)
        rec["s1_blocking_reasons"]=analysis.get("blocking_reasons",[])
        projection=analysis.get("conditional_projection")
        rec["s1_model_buy_output_atomic"]=(projection.get("buy_output_atomic")
             if type(projection) is dict else None)
        # The true Master scorer must reject unknown causal features and
        # cost/execution data; it is not authorized to fill an entry.
        frame=dict(id="early-"+_hash([sig,s1slot,at]),mint=creator["mint"],
            pool=creator["pool"],creator=creator["creator"],
            detected_at_ms=event["reception_utc_ns"]//1000000,
            available_at_ms=at,source_slot=s1slot,
            slot_available_at_ms=at,features=None,
            data_kind="market_observation",bank_state=None)
        decision=MasterDecisionOrchestrator().evaluate(frame,[],
            inventory=None,health=None,capital=None)
        if decision["action"] in ("ENTER","BUY"):
            raise ValueError("unknown_market_features_must_refuse_entry")
        rec["frozen_pre_S2"]=dict(decision_at_ms=at,
            frame_sha256=_hash(frame),
            master_policy_sha256=decision["policy_sha256"],
            master_action=decision["action"],master_reasons=decision["reasons"],
            reference_action="NOT_EVALUABLE_NO_CAUSAL_FEATURES",
            future_S2_consumed=False,financial_order_submitted=False)
        rec["status"]="FROZEN_S1_BEFORE_S2_NO_TRADE"
        print(json.dumps(dict(phase="EARLY_FROZEN_BEFORE_S2",
             creation_slot=slot,s1_slot=s1slot,
             gap_slots=s1slot-slot,financial_order_submitted=False)),flush=True)
        sleep(S2_DELAY_SECONDS)
        if rpc.count>MAX_RPC-2:
            rec["s2_refusal"]="rpc_budget_exhausted"
            return rec
        s2slot,s2accounts=_bank(rpc,list(graph.values()),s1slot+1)
        rec["s2_slot"]=s2slot;rec["s2_received_ms"]=clock_ms()
        if rec["s1_model_buy_output_atomic"] is None:
            rec["s2_refusal"]="no_qualified_S1_buy_projection"
        else:
            a2=analyze_snapshot(s2accounts,context_slot=s2slot,
                expected_mint=creator["mint"],pool_address=creator["pool"],
                input_lamports=1_000_000_000,
                evidence_profile="published_metadata_v1",compute_projection=False)
            facts=a2["facts"];pool=facts["pool"];cfg=facts["config"];p=facts["platform"]
            if pool["status"]!=0 or a2.get("risk_flags"):
                rec["s2_refusal"]="migrated_or_risky_pool"
            else:
                sell=observed_sell_projection(pool,
                    input_token_atomic=int(rec["s1_model_buy_output_atomic"]),
                    fee_rates_ppm=(cfg["trade_fee_rate_ppm"],p["platform_fee_rate_ppm"],
                                  p["creator_fee_rate_ppm"]),
                    quote_vault_lamports=int(facts["quote_vault"]["amount_atomic"]),
                    curve_type=cfg["curve_type"])
                proceeds=int(sell["output_lamports"])
                rec["s2_conditional_proceeds_lamports"]=str(proceeds)
                rec["s1_s2_conditional_markout_lamports"]=str(proceeds-1_000_000_000)
                rec["s2_model_only_not_trade"]=True
    except (ValueError,KeyError,TypeError,IndexError,AttributeError,
            SnapshotEvidenceError) as exc:
        rec["refusal_class"]=type(exc).__name__
        rec.setdefault("root_refusal","early_bank_or_model_unqualified")
    # Finality must be verified separately and its signed message must match.
    # It cannot retroactively change the frozen S1 decision.
    if rec.get("frozen_pre_S2") and rpc.count<=MAX_RPC-2:
        try:
            finalized=rpc("getTransaction",[sig,dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1)])
            if finalized is not None:
                finalproof=signed_receipt_proof(finalized,sig,slot,rpc,
                                               commitment="finalized")
                rec["finality_verified"]=(
                    finalproof["message_sha256"]==proof["message_sha256"]
                    and finalproof["launches"]==proof["launches"])
        except (ValueError,KeyError,TypeError,IndexError,AttributeError):
            rec["finality_refusal"]="separate_finalized_receipt_unqualified"
    return rec


async def bounded_early_capture(*,seconds=45,max_events=100,rpc=None,key=None):
    """Concurrent read-only collector; worker never blocks WebSocket receipts."""
    if rpc is None:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=MAX_RPC)
    if key is None:
        key=os.environ.get("HELIUS_API_KEY")
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("mainnet_genesis_missing")
    queue=asyncio.Queue(maxsize=MAX_HINTS)
    records=[]
    selection=[]
    def enqueue(row):
        if (len(selection)<MAX_HINTS and row.get("untrusted_initialize_log_hint")
                and not row.get("on_chain_transaction_failed")):
            selection.append(dict(signature=row["signature"],slot=row["slot"],
                received_at_ms=row["reception_utc_ns"]//1000000))
            queue.put_nowait(row)
    async def worker():
        while True:
            row=await queue.get()
            if row is None:break
            record=await asyncio.to_thread(inspect_one_hint_early,row,rpc)
            records.append(record)
            if "frozen_pre_S2" in record:
                # First signed creation selected before outcomes. All other
                # queued hints remain denominator records, never claimed absent.
                while not queue.empty():
                    discarded=queue.get_nowait()
                    if discarded is None:break
                    records.append(dict(signature=discarded["signature"],
                        status="NOT_INSPECTED_AFTER_FIRST_S1",financial_order_submitted=False))
                break
    task=asyncio.create_task(worker())
    report=None;events=None
    try:
        report,events=await observe(seconds,max_events,key,
            successful_only=True,on_retained=enqueue)
    finally:
        if not task.done():
            await queue.put(None)
        await task
    return dict(schema="rugger-early-confirmed-signed-S1S2-paper-v1",
        selection_rule="first_four_successful_initialize_log_hints_as_received",
        selected_before_rpc=len(selection),selected=selection,
        attempts=records,forward_log_report=report,
        forward_log_sha256=report["signature_ledger_sha256"],
        source_confirmed_receipt_not_finalized_at_entry=True,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        comparative_edge_lamports=None,qualified_economic_cycles=0,
        financial_order_submitted=False,live_ready_to_arm=False,
        economic_edge_validated=False),events


def main():
    try:
        if os.environ.get("GITHUB_ACTIONS")!="true":
            raise ValueError("GitHub_Actions_readonly_only")
        root=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        report,events=asyncio.run(bounded_early_capture())
        out=root/OUTPUT;out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(dict(report=report,events=events),
                            sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(json.dumps(dict(schema=report["schema"],
            retained=report["forward_log_report"]["events_received_unique"],
            hinted=len(report["selected"]),attempts=len(report["attempts"]),
            signed=sum("signed_outer_creations" in x for x in report["attempts"]),
            frozen=sum("frozen_pre_S2" in x for x in report["attempts"]),
            slots=[dict(creation=x["source_slot"],s1=x.get("s1_slot"),
                        gap=x.get("creation_to_root_slot_gap"),
                        reason=x.get("root_refusal"))
                   for x in report["attempts"] if "signed_outer_creations" in x],
            financial_order_submitted=False,master_net_pnl_lamports=None),
            sort_keys=True))
        return 0
    except Exception as exc:
        # No exception text; it could contain an authenticated provider URL.
        print(json.dumps(dict(status="EARLY_CAPTURE_REFUSED",
            safe_error_class=type(exc).__name__,
            financial_order_submitted=False,live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
