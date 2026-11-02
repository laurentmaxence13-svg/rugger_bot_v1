"""Signed-creation -> two-clock public LaunchLab bank and paired PAPER refusal.

A finalized receipt checked AFTER websocket capture qualifies public identity,
NOT a tradable signal at creation. Actual decision clocks begin only after S1
bank retrieval. Two frozen research decisions precede S2; missing feature,
health and quote data remain unknown. Only read-only Helius RPC methods.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from bot.master_decision import MasterDecisionOrchestrator
from bot.p4.native_asof_signal_bridge import native_asof_bank,verified_full_asof_features
from bot.p3.signed_s1_master_bank_bridge import signed_s1_master_bank
from bot.p4_experiment import decide_prefix
from bot.p3.helius_index_prospective_cohort import _bank, _hash
from bot.p3.launchlab import (SnapshotEvidenceError, addresses_from_pool,
                              analyze_snapshot, observed_sell_projection)
from bot.p3.quotes import SOL_MINT
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS
from tools.master_prospective_gate import _capture_checks

MAX_CANDIDATES = 3
MAX_WAIT_SECONDS = 15
PAPER_BUY_LAMPORTS = 1_000_000_000
OUTPUT = "paper_artifacts/paper_signed_creations_asof_banks.json"


def _select(capture, verified):
    """Select only outer-SIGNED unique verified creators BEFORE reading any bank."""
    _capture_checks(capture, verified)
    if verified.get("status") != "CAPTURE_VERIFIED_AND_RPC_INSPECTED":
        raise ValueError("finalized_signed_creation_verification_required")
    captured = {e["signature"]: e for e in capture["events"]}
    accepted = []
    denominator = []
    creators, mints, pools = set(), set(), set()
    for index, record in enumerate(verified["records"]):
        if type(record) is not dict or record.get("signature") not in captured:
            raise ValueError("verified_record_not_in_capture")
        event = captured[record["signature"]]
        if (record.get("slot") != event["slot"] or
                record.get("reception_utc_ns") != event["reception_utc_ns"]):
            raise ValueError("verified_receipt_event_identity_mismatch")
        if record.get("status") != "SIGNED_OUTER_CREATION_CANDIDATE":
            denominator.append(dict(index=index,signature=record["signature"],
                                    reason="no_outer_signed_creation_evidence"))
            continue
        if record.get("cryptographic_signature_verified") is not True:
            raise ValueError("signed_creation_without_cryptographic_proof")
        launches = record.get("launches")
        if type(launches) is not list or not launches:
            raise ValueError("missing_signed_launch_identity")
        for launch in launches:
            if type(launch) is not dict:
                raise ValueError("invalid_signed_launch")
            creator, mint, pool = (launch.get("creator"), launch.get("mint"),
                                   launch.get("pool"))
            from bot.p3.quotes import _mint
            for address in (creator, mint, pool):
                _mint(address)
            reason = "selected"
            if creator in creators or mint in mints or pool in pools:
                reason = "duplicate_creator_mint_or_pool"
            elif len(accepted) >= MAX_CANDIDATES:
                reason = "beyond_fixed_three_creator_limit"
            if reason == "selected":
                accepted.append(dict(signature=record["signature"],source_slot=event["slot"],
                    detected_utc_ns=event["reception_utc_ns"],creator=creator,mint=mint,
                    pool=pool,cryptographic_creation=True))
                creators.add(creator);mints.add(mint);pools.add(pool)
            denominator.append(dict(index=index,signature=record["signature"],mint=mint,
                                    pool=pool,creator=creator,reason=reason))
    return accepted, denominator


def signed_creator_asof_paper(capture, verified, rpc, *,
                              sleep=time.sleep, clock_ms=lambda: time.time_ns()//1_000_000,
                              delay_seconds=12,include_readonly_quotes=False):
    """Capture S1 + frozen actual shadow decisions, THEN S2 (no trade calls).

    Missing or moved pools are preserved as refusals. Native SDK quotes are
    conditional, not executable provider quotes; there is no settled book.
    """
    if (type(delay_seconds) is not int or not 1<=delay_seconds<=MAX_WAIT_SECONDS
            or not callable(rpc) or not callable(sleep) or not callable(clock_ms)
            or type(include_readonly_quotes) is not bool):
        raise ValueError("bounded_readonly_prospective_inputs_required")
    candidates, denominator = _select(capture, verified)
    report = dict(schema="rugger-signed-creator-asof-paired-paper-v1",
        frozen_source_hash_sha256=_hash(dict(
            log_chain=capture["report"]["signature_ledger_sha256"],
            verified_receipts=verified)),
        selected=candidates,denominator=denominator,
        selected_before_first_bank=True,observations=[],
        signed_creation_candidates_selected=len(candidates),
        independent_creators_with_complete_economic_cycles=0,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        comparative_master_edge_lamports=None,qualified_market_cycles=0,
        financial_order_submitted=False,execution_verified=False,
        promotion_allowed=False,live_ready_to_arm=False)
    if not candidates:
        report["status"]="NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE"
        return report
    if rpc("getGenesisHash",[]) != MAINNET_GENESIS:
        raise ValueError("incorrect_mainnet_genesis")
    root_floor=max(c["source_slot"] for c in candidates)
    root_slot, root_accounts = _bank(rpc,[c["pool"] for c in candidates],root_floor)
    supported = []
    for c in candidates:
        row=dict(c,root_slot=root_slot,
                 creation_to_root_slot_gap=root_slot-c["source_slot"])
        account=root_accounts.get(c["pool"])
        try:
            if account is None:
                row["root_refusal"]="pool_account_not_available"
                raise ValueError("absent_root")
            graph=addresses_from_pool(account,c["mint"],c["pool"])
            if graph["mint_b"]!=SOL_MINT:
                row["root_refusal"]="non_native_SOL_quote_mint"
                raise ValueError("not_SOL_quoted")
            if len(set(graph.values()))!=7:
                row["root_refusal"]="duplicate_required_seven_account_graph"
                raise ValueError("duplicate_accounts")
            row["graph"]=graph;supported.append(row)
        except SnapshotEvidenceError as error:
            code=str(error)
            allowed=frozenset(("pool_owner_or_executable_invalid",
                "pool_encoding_invalid", "pool_unsupported_layout_length",
                "pool_base_mint_mismatch", "invalid_public_address"))
            row["root_refusal"]=code if code in allowed else "unqualified_root_pool_layout"
            row["refusal"]="invalid_root_account_or_non_SOL_pool"
        except (ValueError,KeyError,TypeError):
            row.setdefault("root_refusal","root_pool_graph_refused")
            row["refusal"]="invalid_root_account_or_non_SOL_pool"
        report["observations"].append(row)
    keys=list(dict.fromkeys(key for row in supported for key in row["graph"].values()))
    if not keys:
        report["status"]="NO_VALID_POOL_ACCOUNT_GRAPHS"
        return report
    s1slot,s1accounts=_bank(rpc,keys,root_slot)
    core=MasterDecisionOrchestrator()
    for row in report["observations"]:
        graph=row.get("graph")
        if graph is None:continue
        s1at=clock_ms()
        row["s1_slot"]=s1slot;row["s1_received_ms"]=s1at
        a=None  # Never reuse a previous creator's source analysis on a failed row.
        # Preserve the EXACT 7 public account responses before subsequent S2
        # reads. An analysis hash without the underlying bytes is not
        # independently reproducible and cannot establish Master readiness.
        # No secret, wallet or mutable RPC client object is serialized.
        raw_bank=dict(source_signature=row["signature"],
            creation_slot=row["source_slot"],context_slot=s1slot,
            received_at_ms=s1at,graph=deepcopy(graph),
            accounts={addr:deepcopy(s1accounts.get(addr)) for addr in graph.values()})
        row["s1_raw_bank"]=raw_bank
        row["s1_raw_bank_sha256"]=_hash(raw_bank)
        row["s1_bank_preserved_before_S2"]=True
        try:
            a=analyze_snapshot(
                {address:s1accounts[address] for address in graph.values()},
                context_slot=s1slot,expected_mint=row["mint"],pool_address=row["pool"],
                input_lamports=PAPER_BUY_LAMPORTS,evidence_profile="published_metadata_v1")
            row["s1_analysis_hash_sha256"]=_hash(a)
            row["s1_blocking_reasons"]=a.get("blocking_reasons")
            try:
                row["native_sol_asof_signal"]=native_asof_bank(
                    analysis=a,mint=row["mint"],creator=row["creator"],
                    pool=row["pool"],source_slot=s1slot,available_at_ms=s1at)
                row["native_sol_signal_status"]="SOURCE_NATIVE_SOL_PRICE_OBSERVED"
            except (ValueError,KeyError,TypeError):
                row["native_sol_asof_signal"]=None
                row["native_sol_signal_status"]="NATIVE_SOL_CURVE_SIGNAL_UNQUALIFIED"
            projection=a.get("conditional_projection")
            row["s1_buy_model"]=deepcopy(projection) if type(projection) is dict else None
        except (SnapshotEvidenceError,ValueError,KeyError,TypeError):
            row["s1_refusal"]="unsupported_or_invalid_seven_account_bank"
            row["s1_buy_model"]=None
            row["native_sol_asof_signal"]=None
            row["native_sol_signal_status"]="SOURCE_BANK_NOT_QUALIFIED"
        # Source-bank facts have ALREADY been captured and audited as of S1.
        # Retain exactly verified accounts/reserves/fees instead of forcing
        # Master.bank_state=None on every genuinely signed pool. Unsafe or
        # incompletely certified banks remain UNKNOWN, never paper-tradable.
        bank_state,bank_refusal=signed_s1_master_bank(
            analysis=a,mint=row["mint"],pool=row["pool"],
            creator=row["creator"],signature=row["signature"],
            source_slot=s1slot,received_at_ms=s1at,
            raw_bank_sha256=row["s1_raw_bank_sha256"],
            signed_creation_verified=row.get("cryptographic_creation") is True)
        row["s1_source_bank_bridge_status"]=(
            "SIGNED_CERTIFIED_S1_BANK_RETAINED_FOR_MASTER" if bank_state is not None
            else bank_refusal)
        # Compute an explicit, audited feature completeness receipt using
        # only the evidence available at S1. Do not invent USD oracle, creator
        # history, signed swap tape, or historical source prices.
        native=row.get("native_sol_asof_signal")
        if native is not None:
            feature_audit=verified_full_asof_features(
                native=native,
                creation=dict(mint=row["mint"],pool=row["pool"],
                    creator=row["creator"],cryptographic_creation=True,
                    verified_at_ms=s1at,
                    detected_at_ms=row["detected_utc_ns"]//1_000_000),
                sol_usd=None,creator_history=None,
                verified_transactions=None,market_price_history=None,
                decision_at_ms=s1at)
            if feature_audit["status"]!="INSUFFICIENT_CAUSAL_FEATURE_EVIDENCE":
                raise ValueError("unexpected_complete_asof_features_without_sources")
            row["asof_feature_evidence_audit"]=feature_audit
        else:
            row["asof_feature_evidence_audit"]=dict(
                status="UNQUALIFIED_NATIVE_S1_BANK",
                missing=["native_SOL_bank_not_qualified"],
                features=None,eligible_for_actual_master_entry=False)
        # No features/operational health/source clocked quote. Evaluate BOTH
        # real scorers on the SAME source clock before S2. Never substitute a
        # fictitious reference BUY or a fixed research-probe entry.
        frame=dict(id="signed-s1-"+_hash([row["signature"],s1slot,s1at]),
            mint=row["mint"],creator=row["creator"],pool=row["pool"],
            detected_at_ms=row["detected_utc_ns"]//1_000_000,
            available_at_ms=s1at,source_slot=s1slot,
            slot_available_at_ms=s1at,data_kind="market_observation",
            features=None,features_available_at_ms=None,health=None,
            independent_buyers=None,bank_state=bank_state,
            unknowns=["causal_USD_features","source_quote_clock","independent_buyers",
                      "own_network_costs","execution_health","creator_independence"])
        master=core.evaluate(frame,[],inventory=None,health=None,capital=None)
        reference=decide_prefix("early_sniping",frame,[])
        if master["action"] in ("ENTER","BUY") or reference["enter"] is not False:
            raise ValueError("unknown_asof_features_must_not_trigger_either_entry")
        # A hash-only freeze cannot be independently REPLAYED: it omits the
        # original as-of inputs and exact scorer outputs. Preserve all three
        # before reading any S2 account, without changing policy admission.
        # This is public-source research, not a wallet, quote, fill or order.
        row["s1_preoutcome_frame"]=deepcopy(frame)
        row["s1_preoutcome_master_decision"]=deepcopy(master)
        row["s1_preoutcome_reference_decision"]=deepcopy(reference)
        row["s1_scorer_inputs_and_outputs_preserved_before_S2"]=True
        row["frozen_decision_before_S2"]=dict(at_ms=s1at,source_slot=s1slot,
            frame_sha256=_hash(frame),master_policy_sha256=core.policy_sha256,
            reference_action="WAIT_FOR_FEATURES",
            reference_reason="actual_reference_scorer_has_no_asof_features",
            reference_full_decision_sha256=_hash(reference),
            source_feature_audit_sha256=_hash(row["asof_feature_evidence_audit"]),
            source_feature_missing=list(row["asof_feature_evidence_audit"]["missing"]),
            master_action=master["action"],master_reasons=master["reasons"],
            master_full_decision_sha256=_hash(master),
            paired_comparison_is_not_trade_backtest=True,
            future_S2_used=False,real_order=False)
        if include_readonly_quotes:
            # Explicitly OPTIONAL: research-only exact-lot free GET quote
            # after the REAL Master's WAIT has been frozen, before S2 reads.
            # It cannot retroactively change the original Master decision,
            # cannot grant source-produced quote clocks, and never buys.
            from bot.p3.real_signed_sol_exactlot_quote_probe import (
                _quote, _checked_receipt, BUY_LOT_LAMPORTS)
            row["s1_independent_quote_state"]="REFUSED_OR_NOT_AVAILABLE"
            try:
                quoted=_checked_receipt("BUY",BUY_LOT_LAMPORTS,
                    _quote("BUY",BUY_LOT_LAMPORTS,
                           mint=row["mint"],pool=row["pool"]),
                    mint=row["mint"],pool=row["pool"])
                if (quoted["received_at_utc_ms"]<s1at
                        or quoted["provider_source_slot"] is not None
                        or quoted["provider_produced_at_ms"] is not None):
                    raise ValueError("postdecision_local_quote_clock_unqualified")
                row["s1_independent_research_buy_quote"]=quoted
                row["s1_independent_quote_state"]="AFTER_MASTER_WAIT_BEFORE_S2_INDICATIVE"
            except Exception as error:
                row["s1_independent_quote_refusal_class"]=type(error).__name__
                # Do not leak provider response/URL or invent a price.
                row["s1_independent_quote_state"]="QUOTE_UNAVAILABLE_NOT_EXECUTABLE"
    report["freeze_completed_before_S2"]=True
    report["status"]="S1_DECISIONS_FROZEN_BEFORE_S2"
    # Print only public receipt identifying data; subsequent I/O cannot
    # retroactively alter decision clocks. No wallet keys or auth URLs.
    print(json.dumps(dict(phase="FROZEN_BEFORE_S2",
        selected=len(candidates),frozen=sum("frozen_decision_before_S2" in x
        for x in report["observations"]),cash_traded_lamports=0)),flush=True)
    sleep(delay_seconds)
    s2slot,s2accounts=_bank(rpc,keys,s1slot+1)
    for row in report["observations"]:
        if row.get("graph") is None:continue
        row["s2_slot"]=s2slot;row["s2_received_ms"]=clock_ms()
        if include_readonly_quotes and row.get("s1_independent_research_buy_quote") is not None:
            from bot.p3.real_signed_sol_exactlot_quote_probe import _quote,_checked_receipt
            buy_quote=row["s1_independent_research_buy_quote"]
            row["s2_independent_quote_state"]="REFUSED_OR_NOT_AVAILABLE"
            try:
                exact_qty=int(buy_quote["output_atomic"])
                quoted=_checked_receipt("SELL",exact_qty,
                    _quote("SELL",exact_qty,mint=row["mint"],pool=row["pool"]),
                    mint=row["mint"],pool=row["pool"])
                if (quoted["received_at_utc_ms"]<row["s2_received_ms"]
                        or quoted["received_at_utc_ms"]<=buy_quote["received_at_utc_ms"]
                        or quoted["provider_source_slot"] is not None
                        or quoted["provider_produced_at_ms"] is not None):
                    raise ValueError("post_S2_quote_clock_unqualified")
                row["s2_independent_research_sell_quote"]=quoted
                row["s2_independent_quote_state"]="AFTER_S2_INDICATIVE"
                row["research_only_quote_delta_before_extra_costs_lamports"]=str(
                    int(quoted["output_atomic"])-int(buy_quote["input_atomic"]))
                row["source_produced_quote_clocks_verified"]=False
                row["research_quote_is_not_owned_Master_position"]=True
                row["research_quote_pair_is_not_an_actual_Master_PAPER_cycle"]=True
            except Exception as error:
                row["s2_independent_quote_refusal_class"]=type(error).__name__
                row["s2_independent_quote_state"]="QUOTE_UNAVAILABLE_NOT_EXECUTABLE"
        if row.get("s1_buy_model") is None:
            row["s2_refusal"]="no_qualified_preexisting_s1_buy_projection"
            continue
        try:
            a=analyze_snapshot(
                {addr:s2accounts[addr] for addr in row["graph"].values()},
                context_slot=s2slot,expected_mint=row["mint"],
                pool_address=row["pool"],input_lamports=PAPER_BUY_LAMPORTS,
                evidence_profile="published_metadata_v1",compute_projection=False)
            facts=a["facts"];pool=facts["pool"];cfg=facts["config"];platform=facts["platform"]
            if pool["status"]!=0 or a.get("risk_flags") or a.get("blocking_reasons"):
                raise ValueError("unsupported_or_migrated_followup_pool")
            qty=int(row["s1_buy_model"]["buy_output_atomic"])
            model=observed_sell_projection(pool,input_token_atomic=qty,
                fee_rates_ppm=(cfg["trade_fee_rate_ppm"],
                    platform["platform_fee_rate_ppm"],platform["creator_fee_rate_ppm"]),
                quote_vault_lamports=int(facts["quote_vault"]["amount_atomic"]),
                curve_type=cfg["curve_type"])
            proceeds=int(model["output_lamports"])
            row["s2_same_exact_qty_conditional_sell_lamports"]=str(proceeds)
            row["s1_to_s2_conditional_curve_markout_lamports"]=str(proceeds-PAPER_BUY_LAMPORTS)
            row["s2_analysis_sha256"]=_hash(a)
            row["own_costs_known"]=False;row["provider_executable_quote_observed"]=False
            row["market_economic_cycle_qualified"]=False
        except (SnapshotEvidenceError,ValueError,TypeError,KeyError,OverflowError):
            row["s2_refusal"]="missing_or_unsupported_conditional_exact_lot_exit"
    report["status"]="TWO_CLOCK_MODEL_CAPTURE_COMPLETE_NOT_PROFITABILITY"
    report["s2_follows_frozen_S1"]=s2slot>s1slot
    report["helius_readonly_rpc_calls_used"]=getattr(rpc,"count",None)
    return report


def main():
    try:
        if os.environ.get("GITHUB_ACTIONS")!="true":
            raise ValueError("github_actions_source_required")
        root=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        first=root/"paper_artifacts/paper_helius_log_stream.json"
        second=root/"paper_artifacts/paper_helius_verified_creations.json"
        if (first.is_symlink() or second.is_symlink() or
                first.stat().st_size>300000 or second.stat().st_size>300000):
            raise ValueError("public_capture_inputs_invalid")
        raw=json.loads(first.read_text(encoding="utf-8"))
        verified=json.loads(second.read_text(encoding="utf-8"))
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=5)
        report=signed_creator_asof_paper(raw,verified,rpc)
        out=root/OUTPUT
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(json.dumps(dict(status=report["status"],
            selected=report["signed_creation_candidates_selected"],
            asof_frozen_decisions=sum("frozen_decision_before_S2" in x
                for x in report["observations"]),
            qualified_cycles=0,master_net_pnl_lamports=None,
            financial_order_submitted=False),sort_keys=True))
        return 0
    except Exception as error:
        # No URLs, RPC errors or private client content in diagnostics.
        trace=error.__traceback__
        last_site=None
        while trace is not None:
            last_site=dict(function=trace.tb_frame.f_code.co_name,
                           line=trace.tb_lineno,
                           module=trace.tb_frame.f_globals.get("__name__","unknown"))
            trace=trace.tb_next
        print(json.dumps(dict(status="REFUSED",
            safe_error_class=type(error).__name__,safe_last_site=last_site,
            financial_order_submitted=False,live_ready_to_arm=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())
