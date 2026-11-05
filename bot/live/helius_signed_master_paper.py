"""Bounded real Helius -> signed creator -> two-bank Master PAPER evidence.

One explicit read-only operator action. This joins already existing, tested
WebSocket log collection, finalized ED25519 creation verification, and
source-timed S1 Master/S2 bank observation into one auditable local command.

It does NOT place trades, invent SignalFeatures, simulate executable fills,
guarantee creator coverage, or compute verified Master profitability. RPC
finalization is necessarily checked AFTER receiving websocket notifications.
The S1 decision clock begins only after the verified receipt and S1 bank
have arrived; this is not instantaneous launch sniping.

No private keys, wallet, transaction-sending methods, paid subscriptions or
LIVE controls. Provider API key stays in process memory only.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from bot.analyser.artifacts import atomic_write_json
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_horizon_sampler import observe_horizon
from bot.live.helius_ws_signed_creation_probe import inspect_forward_creations
from bot.p3.signed_creation_forward_bank import signed_creator_asof_paper
from bot.p4.live_like_paper_ledger import PaperLedger,freeze_decision

SCHEMA="rugger-helius-signed-master-paper-integration-v1"
MAX_LOG_EVENTS=100  # stratified over full bounded horizon; raw denominator separately retained
VERIFY_RPC_CAP=10
BANK_RPC_CAP=5


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                allow_nan=False).encode("utf-8")).hexdigest()


def run_pipeline(*,seconds, output_dir, api_key, observer=observe_horizon,
                 verifier=inspect_forward_creations,
                 strategy=signed_creator_asof_paper,
                 rpc_factory=HeliusReadOnlyRpc):
    """One bounded attempt, never reuse/output credentials or overwrite files."""
    if (type(seconds) is not int or not 10<=seconds<=45
            or type(api_key) is not str or api_key=="COLLE_TA_CLE_ICI"
            or re.fullmatch(r"[A-Za-z0-9_-]{16,160}",api_key) is None):
        raise ValueError("bounded_helius_operator_inputs_required")
    folder=Path(output_dir)
    if folder.exists() or folder.is_symlink() or folder.name in ("",".."):
        raise ValueError("fresh_unoccupied_output_directory_required")
    folder.mkdir(parents=True,exist_ok=False)
    def save(name,value):
        path=folder/name
        if path.exists() or path.is_symlink():
            raise ValueError("existing_evidence_refused")
        atomic_write_json(path,value,sort_keys=True,allow_nan=False)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    log_report,events=asyncio.run(observer(seconds,MAX_LOG_EVENTS,api_key,
                                           successful_only=False))
    if (type(log_report) is not dict or type(events) is not list
            or len(events)>MAX_LOG_EVENTS
            or log_report.get("financial_order_submitted") is not False
            or log_report.get("live_ready_to_arm") is not False):
        raise ValueError("invalid_bounded_public_log_capture")
    captured=dict(report=log_report,events=events)
    log_sha=save("signed_log_capture.json",captured)

    # Selection covers the full bounded observation horizon, not the first
    # 100 invocations. The selected source chain is independently checked
    # below; unselected log counts remain explicit in capture metadata.
    # Transaction receipts are fetched strictly *after* capture. No future
    # outcome is ever treated as a feature at notification arrival.
    read_rpc=rpc_factory(api_key,max_calls=VERIFY_RPC_CAP)
    verified=verifier(log_report,events,read_rpc)
    if (type(verified) is not dict
            or verified.get("status")!="CAPTURE_VERIFIED_AND_RPC_INSPECTED"
            or verified.get("financial_order_submitted") is not False
            or verified.get("source_log_chain_sha256")!=log_report.get("signature_ledger_sha256")):
        raise ValueError("invalid_signed_creator_proof")
    verified_sha=save("finalized_creation_proof.json",verified)

    bank_rpc=rpc_factory(api_key,max_calls=BANK_RPC_CAP)
    paired=strategy(captured,verified,bank_rpc)
    if (type(paired) is not dict
            or paired.get("financial_order_submitted") is not False
            or paired.get("live_ready_to_arm") is not False
            or paired.get("execution_verified") is not False
            or paired.get("master_net_pnl_lamports") is not None
            or paired.get("reference_net_pnl_lamports") is not None
            or paired.get("comparative_master_edge_lamports") is not None):
        raise ValueError("unqualified_trading_or_economic_claim")
    pair_sha=save("paired_signed_master_paper.json",paired)
    pool_refusal_counts={}
    for observed in paired.get("observations",[]):
        reason=observed.get("root_refusal") or observed.get("s1_refusal")
        if reason:
            pool_refusal_counts[reason]=pool_refusal_counts.get(reason,0)+1
    eligible_native_sol_count=sum(
        "graph" in row for row in paired.get("observations",[]))
    # Carry the ACTUAL signed S1 Master/ref freezes into the two-arm paper
    # portfolio before any synthetic price may be applied. Neither arm is
    # force-entered: missing causal SignalFeatures and costs remain WAIT.
    paper=PaperLedger()
    for row in sorted(paired.get("observations",[]),
                      key=lambda r:r.get("s1_received_ms",0)):
        freeze=row.get("frozen_decision_before_S2")
        if type(freeze) is not dict:
            continue
        action=freeze.get("master_action")
        if action not in ("WAIT","NO_TRADE"):
            raise ValueError("unexpected_unverified_master_trade_intent")
        item=freeze_decision(dict(
            id="helius-s1-"+row["signature"],
            mint=row["mint"],creator=row["creator"],pool=row["pool"],
            source_slot=freeze["source_slot"],available_at_ms=freeze["at_ms"],
            entry_size_lamports=100_000_000,
            decisions=dict(master="WAIT" if action=="WAIT" else "REJECT",
                           reference="WAIT"),
            signed_creator_verified=True,
            asof_features_verified=False,
            source_quote_clock_verified=False,
            policy_sha256=freeze["master_policy_sha256"]))
        paper.register(item)
    paper_book=paper.snapshot()
    paper_sha=save("paired_paper_portfolio.json",paper_book)
    summary=dict(
        schema=SCHEMA,source="Helius_mainnet_public_finalized_signatures",
        observation_scope="bounded_late_verified_creation_and_two_bank_shadow",
        log_events_retained=len(events),
        crypto_signed_creation_transactions=verified.get(
            "signed_creation_candidate_transactions"),
        signed_creators_claimed=verified.get(
            "distinct_creator_claims_from_signed_transactions"),
        selected_independent_signed_creators=paired.get(
            "signed_creation_candidates_selected"),
        supported_native_SOL_graphs=eligible_native_sol_count,
        source_market_refusal_reason_counts=pool_refusal_counts,
        non_native_SOL_pool_count=pool_refusal_counts.get("non_native_SOL_quote_mint",0),
        economic_qualification_of_non_SOL_quoted_pool_not_attempted=True,
        frozen_S1_decisions=sum(
            "frozen_decision_before_S2" in e
            for e in paired.get("observations",[])),
        actual_signed_policy_frozen_paper_cases=paper_book["frozen_decisions"],
        paper_portfolio_open_positions=sum(
            paper_book["accounts"][arm]["open_positions"]
            for arm in ("master","reference")),
        paper_portfolio_closed_positions=sum(
            paper_book["accounts"][arm]["closed_paper_cycles"]
            for arm in ("master","reference")),
        capture_status=paired.get("status"),
        websocket_delivery_is_not_finalized_entry_signal=True,
        source_creator_verification_after_log_capture=True,
        executable_buy_sell_quotes_verified=False,
        trade_fills_simulated=0,qualified_economic_cycles=0,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        master_minus_reference_net_lamports=None,
        execution_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        exact_profitability_demonstrated=False,
        provider_requests_used_upper_bound=VERIFY_RPC_CAP+BANK_RPC_CAP,
        actual_verification_rpc_calls_used=getattr(read_rpc,"count",None),
        actual_bank_rpc_calls_used=getattr(bank_rpc,"count",None),
        sha256=dict(signed_log_capture=log_sha,
                    finalized_creation_proof=verified_sha,
                    paired_signed_master_paper=pair_sha,
                    paired_paper_portfolio=paper_sha),
        output_dir=str(folder))
    save("summary.json",summary)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true",
                        help="Explicit authorization for bounded Helius public data calls")
    parser.add_argument("--seconds",type=int,default=30)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        parser.error("Explicit --network required; never a real trade")
    try:
        result=run_pipeline(seconds=args.seconds,output_dir=args.output_dir,
                            api_key=os.environ.get("HELIUS_API_KEY"))
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as error:
        # DO NOT print exception strings: they may contain a private API key.
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
            safe_error_class=type(error).__name__,
            no_live_trades=True,no_paid_requests_guarantee=False,
            exact_profitability_demonstrated=False),sort_keys=True))
        return 2


if __name__=="__main__":
    sys.exit(main())
