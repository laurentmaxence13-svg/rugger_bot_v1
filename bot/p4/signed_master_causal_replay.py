"""Reproduce genuine Master WAIT/NO_TRADE on saved *signed-source* S1 inputs.

No signer, wallet, provider calls, synthetic substitute, or transaction.
The source's original scorer must be reproduced exactly on PRE-S2 inputs.
The PAPER ledger records only frozen decisions, never invents BUY/SELL fills.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bot.master_decision import MasterDecisionOrchestrator
from bot.p4_experiment import decide_prefix
from bot.p4.live_like_paper_ledger import PaperLedger,freeze_decision

SCHEMA="rugger-signed-genuine-master-paper-causal-replay-v1"
SOURCE_SCHEMA="rugger-free-public-signed-cohort-v1"
WINDOW_SCHEMA="rugger-public-solana-forward-signed-paper-v1"
MAX_DOCUMENT_BYTES=1_500_000


def _hash(document):
    return hashlib.sha256(json.dumps(document,sort_keys=True,
                       separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _read(folder,name):
    path=folder/name
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size>MAX_DOCUMENT_BYTES):
        raise ValueError("missing_or_unbounded_frozen_signed_source")
    document=json.loads(path.read_text(encoding="utf-8"))
    if type(document) is not dict:
        raise ValueError("invalid_frozen_signed_source_document")
    return document


def replay_public_signed_cohort(folder):
    folder=Path(folder)
    campaign=_read(folder,"campaign_summary.json")
    if (campaign.get("schema")!=SOURCE_SCHEMA
            or type(campaign.get("window_count")) is not int
            or not 1<=campaign["window_count"]<=4
            or campaign.get("source")!="FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS"
            or campaign.get("financial_order_submitted") is not False
            or campaign.get("live_trading_enabled") is not False
            or campaign.get("master_paper_buys")!=0
            or campaign.get("master_paper_sells")!=0
            or campaign.get("master_net_pnl_lamports") is not None
            or type(campaign.get("windows")) is not list
            or len(campaign["windows"])!=campaign["window_count"]):
        raise ValueError("signed_source_campaign_readiness_not_verified")
    ledger=PaperLedger()
    verified_signatures=set()
    proof_signatures=set()
    frozen=0
    events_total=0
    rpc_total=0
    signed_creators=set()
    graph_creators=set()
    diagnostics=[]
    for i in range(campaign["window_count"]):
        window=folder/f"window_{i:02d}"
        capture=_read(window,"public_log_capture.json")
        verified=_read(window,"finalized_creation_proof.json")
        paired=_read(window,"paired_master_source_shadow.json")
        summary=_read(window,"summary.json")
        row=campaign["windows"][i]
        if (type(row) is not dict or row.get("window")!=i
                or summary.get("schema")!=WINDOW_SCHEMA
                or summary.get("source")!=campaign["source"]
                or row.get("source_summary_sha256")!=_hash(summary)
                or type(summary.get("artifact_sha256")) is not dict):
            raise ValueError("unbound_source_window_and_summary")
        for name,doc in (("public_log_capture",capture),
                         ("finalized_creation_proof",verified),
                         ("paired_master_source_shadow",paired)):
            if summary["artifact_sha256"].get(name)!=_hash(doc):
                raise ValueError("tampered_public_source_artifact")
        report=capture.get("report")
        events=capture.get("events")
        if (type(report) is not dict or type(events) is not list
                or len(events)!=summary.get("log_events")
                or report.get("financial_order_submitted") is not False
                or report.get("events_received_unique")!=len(events)
                or paired.get("financial_order_submitted") is not False
                or paired.get("execution_verified") is not False
                or paired.get("live_ready_to_arm") is not False
                or paired.get("master_net_pnl_lamports") is not None
                or paired.get("reference_net_pnl_lamports") is not None
                or verified.get("financial_order_submitted") is not False
                or verified.get("status")!="CAPTURE_VERIFIED_AND_RPC_INSPECTED"):
            raise ValueError("invalid_public_signed_provenance")
        digest="0"*64
        current_events={}
        for event in events:
            sig=event.get("signature") if type(event) is dict else None
            if type(sig) is not str or not sig or sig in verified_signatures:
                raise ValueError("duplicate_or_invalid_source_signature")
            if (type(event.get("slot")) is not int or event["slot"]<=0
                    or type(event.get("reception_utc_ns")) is not int
                    or event["reception_utc_ns"]<=0):
                raise ValueError("incomplete_original_source_event_clock")
            verified_signatures.add(sig)
            current_events[sig]=event
            digest=_hash(dict(previous=digest,event=event))
        if (digest!=report.get("signature_ledger_sha256")
                or verified.get("source_log_chain_sha256")!=digest
                or paired.get("frozen_source_hash_sha256")!=_hash(
                   dict(log_chain=digest,verified_receipts=verified))):
            raise ValueError("broken_signed_creation_source_chain")
        records=verified.get("records")
        if type(records) is not list or len(records)!=len(events):
            raise ValueError("incomplete_signed_verification_denominator")
        creation_by_signature={}
        seen_verified_records=set()
        for verified_row in records:
            if type(verified_row) is not dict:
                raise ValueError("invalid_signed_receipt_identity")
            signature=verified_row.get("signature")
            event=current_events.get(signature)
            if (event is None or signature in seen_verified_records
                    or verified_row.get("slot")!=event["slot"]
                    or verified_row.get("reception_utc_ns")!=event["reception_utc_ns"]):
                raise ValueError("invalid_signed_receipt_identity")
            seen_verified_records.add(signature)
            if verified_row.get("status")=="SIGNED_OUTER_CREATION_CANDIDATE":
                if (verified_row.get("cryptographic_signature_verified") is not True
                        or type(verified_row.get("launches")) is not list):
                    raise ValueError("unverified_signed_creation_claim")
                creation_by_signature[verified_row["signature"]]=verified_row
        if (len(creation_by_signature)!=
                summary.get("signed_creation_transactions")):
            raise ValueError("signed_creation_transaction_count_drift")
        observations=paired.get("observations")
        selected=paired.get("selected")
        if type(observations) is not list or type(selected) is not list:
            raise ValueError("invalid_paired_source_evidence")
        source_freezes=0
        for selection in selected:
            if type(selection) is not dict or type(selection.get("creator")) is not str:
                raise ValueError("unidentified_signed_source_creator")
            signed_creators.add(selection["creator"])
        for source in observations:
            if type(source) is not dict:
                raise ValueError("invalid_signed_source_observation")
            if type(source.get("graph")) is dict:
                graph_creators.add(source.get("creator"))
            freeze=source.get("frozen_decision_before_S2")
            if freeze is None:
                continue
            if (type(freeze) is not dict
                    or source.get("s1_scorer_inputs_and_outputs_preserved_before_S2") is not True
                    or freeze.get("future_S2_used") is not False
                    or freeze.get("real_order") is not False):
                raise ValueError("missing_original_preoutcome_master_freeze")
            record=creation_by_signature.get(source.get("signature"))
            if record is None or not any(
                    type(launch) is dict
                    and launch.get("creator")==source.get("creator")
                    and launch.get("mint")==source.get("mint")
                    and launch.get("pool")==source.get("pool")
                    for launch in record["launches"]):
                raise ValueError("frozen_master_not_linked_to_signed_creation")
            frame=source.get("s1_preoutcome_frame")
            saved_master=source.get("s1_preoutcome_master_decision")
            saved_reference=source.get("s1_preoutcome_reference_decision")
            if (type(frame) is not dict or type(saved_master) is not dict
                    or type(saved_reference) is not dict
                    or frame.get("features") is not None
                    or frame.get("health") is not None
                    or frame.get("bank_state") is not None
                    or frame.get("mint")!=source.get("mint")
                    or frame.get("creator")!=source.get("creator")
                    or frame.get("pool")!=source.get("pool")
                    or frame.get("source_slot")!=source.get("s1_slot")
                    or frame.get("available_at_ms")!=freeze.get("at_ms")
                    or type(frame.get("detected_at_ms")) is not int
                    or frame["available_at_ms"]<frame["detected_at_ms"]
                    or frame["source_slot"]<source.get("source_slot",0)):
                raise ValueError("noncausal_signed_master_frame")
            if (_hash(frame)!=freeze.get("frame_sha256")
                    or _hash(saved_master)!=freeze.get("master_full_decision_sha256")
                    or _hash(saved_reference)!=freeze.get("reference_full_decision_sha256")):
                raise ValueError("modified_preoutcome_master_or_reference")
            master=MasterDecisionOrchestrator()
            recomputed=master.evaluate(frame,[],inventory=None,health=None,capital=None)
            ref=decide_prefix("early_sniping",frame,[])
            if (recomputed!=saved_master or ref!=saved_reference
                    or master.policy_sha256!=freeze.get("master_policy_sha256")
                    or recomputed.get("action") not in ("WAIT","NO_TRADE")
                    or recomputed.get("action")!=freeze.get("master_action")
                    or ref.get("enter") is not False
                    or freeze.get("reference_action")!="WAIT_FOR_FEATURES"):
                raise ValueError("nonreproducible_or_unqualified_genuine_master_decision")
            frozen_case=freeze_decision(dict(
                id="signed-source-"+source["signature"],
                mint=source["mint"],creator=source["creator"],pool=source["pool"],
                source_slot=frame["source_slot"],
                available_at_ms=frame["available_at_ms"],
                entry_size_lamports=100_000_000,
                decisions=dict(master="WAIT" if recomputed["action"]=="WAIT" else "REJECT",
                               reference="WAIT"),
                signed_creator_verified=True,
                asof_features_verified=False,
                source_quote_clock_verified=False,
                policy_sha256=master.policy_sha256))
            ledger.register(frozen_case)
            source_freezes+=1
            frozen+=1
        if source_freezes!=summary.get("frozen_master_S1_decisions"):
            raise ValueError("incorrect_source_frozen_master_count")
        usage=summary.get("verification_rpc_calls")
        banks=summary.get("bank_rpc_calls")
        if (type(usage) is not int or type(banks) is not int
                or not 0<=usage<=10 or not 0<=banks<=5
                or row.get("rpc_calls")!=usage+banks):
            raise ValueError("unbounded_replay_source_rpc_usage")
        rpc_total+=usage+banks
        events_total+=len(events)
        diagnostics.append(dict(window=i,source_events=len(events),
            signed_creations=len(creation_by_signature),
            frozen_master_replayed=source_freezes,
            master_buy_sell_paper=0))
    book=ledger.snapshot()
    if (book.get("open_inventory_present") is not False
            or any(book["accounts"][arm].get("open_positions")!=0 or
                book["accounts"][arm].get("closed_paper_cycles")!=0
                for arm in ("master","reference"))
            or book.get("frozen_decisions")!=frozen
            or events_total!=campaign.get("observed_unique_events")
            or rpc_total!=campaign.get("total_rpc_calls")
            or len(signed_creators)!=campaign.get("uniquely_selected_signed_creators")
            or len(graph_creators)!=campaign.get("native_SOL_source_creators")):
        raise ValueError("signed_replay_book_or_cohort_count_mismatch")
    return dict(schema=SCHEMA,status="GENUINE_MASTER_CAUSAL_WAIT_REPRODUCED",
        original_master_policy_sha256=MasterDecisionOrchestrator().policy_sha256,
        acquired_events=events_total,
        signed_distinct_creators=len(signed_creators),
        native_SOL_creator_graphs=len(graph_creators),
        genuine_master_S1_decisions_recomputed=frozen,
        master_paper_entries=0,master_paper_exits=0,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        measured_master_edge_lamports=None,
        source_original_Ed25519_proofs_used=True,
        archived_Ed25519_signatures_reverified_from_bytes_here=False,
        independent_executable_quotes_verified=False,
        exact_real_master_buy_sell_paper_cycle_verified=False,
        financial_order_submitted=False,live_trading_enabled=False,
        per_window_diagnostics=diagnostics)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_directory",type=Path)
    args=parser.parse_args(argv)
    try:
        result=replay_public_signed_cohort(args.campaign_directory)
    except Exception as error:
        # Never echo raw provider error text, auth URLs or private payloads.
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
             safe_error_class=type(error).__name__,
             financial_order_submitted=False),sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
