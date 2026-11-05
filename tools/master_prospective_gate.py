#!/usr/bin/env python3
"""Read-only prospective Helius -> Master/reference evidence gate.

Inputs are immutable public-research artifacts. This tool cannot trade,
activate a strategy, infer a fill from a swap or quote, or certify a P&L.
When no comparison exists it explicitly records missing paired decisions.
"""
import argparse
import hashlib
import json
from pathlib import Path

WS_SCHEMA = "rugger-helius-program-log-forward-paper-v1"
CREATION_SCHEMA = "rugger-mainnet-forward-captured-creation-check-v1"
COMPARISON_SCHEMA = "rugger-master-reference-comparison-v1"
SCENARIOS = {(1, 0), (2, 0), (1, 250), (2, 250)}
MIN_HOLDOUT_CREATORS = 50


def _sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _capture_checks(capture, verification):
    if capture is None:
        return {"logs": 0, "signed_creation_candidates": 0,
                "status": "NO_CAPTURE", "reason": "websocket_capture_missing"}
    if type(capture) is not dict or type(capture.get("report")) is not dict or type(capture.get("events")) is not list:
        raise ValueError("capture_structure_invalid")
    report, events = capture["report"], capture["events"]
    if report.get("schema") != WS_SCHEMA or report.get("financial_order_submitted") is not False:
        raise ValueError("invalid_capture_provenance")
    if type(report.get("events_received_unique")) is not int or report["events_received_unique"] != len(events) or len(events) > 200:
        raise ValueError("invalid_capture_count")
    digest = "0" * 64
    seen = set()
    for event in events:
        if type(event) is not dict or type(event.get("signature")) is not str or event["signature"] in seen:
            raise ValueError("duplicated_or_unidentified_capture_event")
        seen.add(event["signature"])
        digest = _sha({"previous": digest, "event": event})
    if digest != report.get("signature_ledger_sha256"):
        raise ValueError("capture_hash_chain_mismatch")
    if verification is None:
        return {"logs": len(events), "signed_creation_candidates": 0,
                "status": "NO_VERIFICATION", "reason": "finalized_receipts_missing"}
    if type(verification) is not dict or verification.get("schema") != CREATION_SCHEMA:
        raise ValueError("creation_verification_schema_invalid")
    if (verification.get("source_log_chain_sha256") != digest or
            verification.get("first_phase_captured_logs") != len(events) or
            verification.get("financial_order_submitted") is not False):
        raise ValueError("capture_and_creation_verification_not_linked")
    if verification.get("status") != "CAPTURE_VERIFIED_AND_RPC_INSPECTED":
        return {"logs": len(events), "signed_creation_candidates": 0,
                "status": "VERIFICATION_REFUSED", "reason": "read_only_rpc_verification_refused"}
    signed = verification.get("signed_creation_candidate_transactions")
    claims = verification.get("distinct_creator_claims_from_signed_transactions")
    records = verification.get("records")
    if (type(signed) is not int or type(claims) is not int
            or not 0 <= signed <= len(events) or not 0 <= claims <= 4 * max(signed, 1)
            or type(records) is not list or len(records) != len(events)
            or sum(r.get("status") == "SIGNED_OUTER_CREATION_CANDIDATE" for r in records) != signed):
        raise ValueError("inconsistent_signed_creation_counters")
    return {"logs": len(events), "signed_creation_candidates": signed,
            "signed_creator_claims": claims, "status": "CAPTURE_CHECKED",
            "reason": "later_finalized_receipts_do_not_prove_asof_tradable_quotes"}


def _comparison_checks(comparison):
    if comparison is None:
        return {"status": "NO_PAIRED_DECISIONS", "holdout_creators": 0,
                "scenarios": {}, "eligible_trades": 0,
                "reason": "missing_asof_master_reference_frames_and_full_size_exit_quotes"}
    if type(comparison) is not dict or comparison.get("schema") != COMPARISON_SCHEMA:
        raise ValueError("paired_comparison_schema_invalid")
    if (comparison.get("data_kind") != "market_observation" or
            comparison.get("same_observation_tape") is not True or
            comparison.get("same_financial_implementation") is not True or
            comparison.get("active_policy_changed") is not False or
            comparison.get("promotion_allowed") is not False or
            comparison.get("execution_verified") is not False):
        raise ValueError("comparison_must_be_real_observation_and_read_only")
    if type(comparison.get("pairs")) is not list or type(comparison.get("assignments")) is not dict:
        raise ValueError("incomplete_paired_comparison")
    holdout = {mint for mint, split in comparison["assignments"].items()
               if split == "validation"}
    out = {}
    counted = set()
    for pair in comparison["pairs"]:
        if type(pair) is not dict:
            raise ValueError("invalid_pair")
        fee, delay, split = (pair.get("fee_multiplier"), pair.get("decision_delay_ms"),
                             pair.get("split"))
        if (fee, delay) not in SCENARIOS or split not in ("development", "validation"):
            raise ValueError("unregistered_scenario")
        key = (fee, delay, split)
        if key in counted:
            raise ValueError("duplicated_scenario")
        counted.add(key)
        if split != "validation":
            continue
        entries = pair.get("opportunities")
        if type(entries) is not list:
            raise ValueError("opportunities_missing")
        seen = set()
        known = []
        unresolved = 0
        for row in entries:
            mint = row.get("mint")
            if mint not in holdout or mint in seen:
                raise ValueError("holdout_id_mismatch_or_duplicate")
            seen.add(mint)
            delta = row.get("conditional_delta_lamports")
            if delta is None:
                unresolved += 1
                continue
            if type(delta) is not str or not delta.lstrip("-").isdigit():
                raise ValueError("invalid_atomic_pnl")
            known.append(int(delta))
        out[f"{fee}x_{delay}ms"] = {
            "observed_holdout_opportunities": len(entries),
            "conditional_complete_pairs": len(known),
            "unknown_or_open_pairs": unresolved,
            "all_holdout_opportunities_represented": seen == holdout,
            "conditional_delta_lamports": (str(sum(known))
                if unresolved == 0 and seen == holdout else None),
            "actual_fill_proven": False,
        }
    if counted != {(a, b, c) for a, b in SCENARIOS for c in ("development", "validation")}:
        raise ValueError("four_stress_scenarios_and_two_splits_required")
    return {"status": "PAIRED_CONDITIONAL_REPLAY_ONLY",
            "holdout_creators": len(holdout), "scenarios": out,
            "eligible_trades": sum(v["conditional_complete_pairs"] for v in out.values()),
            "reason": "counterfactual_quotes_do_not_certify_executed_fills"}


def build_gate(capture=None, verification=None, comparison=None):
    c = _capture_checks(capture, verification)
    p = _comparison_checks(comparison)
    return {
        "schema": "rugger-prospective-master-evidence-progress-v1",
        "capture": c, "comparison": p,
        "minimum_independent_holdout_creators": MIN_HOLDOUT_CREATORS,
        "actual_master_minus_reference_net_pnl_sol": None,
        "observed_filled_entry_exit_cycles": 0,
        "market_profitability_verified": False,
        "economic_edge_validated": False,
        "live_ready_to_arm": False,
        "financial_order_submitted": False,
        "status": "NO_GO_UNTIL_INDEPENDENT_ASOF_EXECUTION_EVIDENCE",
        "missing": [
            "verified_new_launch_denominator_with_creator_nonoverlap",
            "frozen_master_reference_decisions_before_outcomes",
            "exact_lot_buy_and_later_sell_quotes_with_source_clocks",
            "all_costs_failed_exits_and_open_positions",
            "independent_holdout_and_creator_clustered_inference",
        ],
    }


def _read(path):
    if path is None or not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 16_777_216:
        raise ValueError("untrusted_artifact_path")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--verified", type=Path)
    parser.add_argument("--comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink() or args.output.suffix != ".json":
        parser.error("new_json_output_path_required")
    report = build_gate(_read(args.capture), _read(args.verified), _read(args.comparison))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"],
                      "capture": report["capture"]["status"],
                      "paired": report["comparison"]["status"],
                      "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
