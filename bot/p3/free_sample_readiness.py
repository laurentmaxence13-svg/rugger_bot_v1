"""Fail-closed source-data readiness audit for real (not synthetic) P3/P4 data.

An integrity check or a historically observed trade is not a verified
profitability test. At best complete data allows the real Master and baseline
policies to be replayed. Actual out-of-sample statistical advantage then
needs a SEPARATE evaluation with the same transaction accounting.

Never emits a YES to live trading, never touches a wallet, never sends RPC.
"""
import json
from pathlib import Path

SOL_MINT = "So11111111111111111111111111111111111111112"
REQUIRED_HOLDOUT_CREATORS = 50


def evaluate_data_source_readiness(snapshot):
    if type(snapshot) is not dict or snapshot.get("schema") != "rugger-free-Parquet-prepurchase-readiness-v1":
        raise ValueError("versioned_free_sample_evidence_required")
    def true(k):
        return snapshot.get(k) is True
    creators = snapshot.get("distinct_creator_claims")
    if type(creators) is not int or creators < 0:
        raise ValueError("sample_creator_count_invalid")
    source_count = snapshot.get("manifest_files_sha256_verified")
    if type(source_count) is not int or source_count < 0:
        raise ValueError("sample_provenance_missing")
    matched = snapshot.get("wsol_instruction_event_matched")
    if type(matched) is not dict or any(type(matched.get(k)) is not int
                                       or matched[k] < 0 for k in ("buy", "sell")):
        raise ValueError("wsol_instruction_event_counts_required")
    pairs = snapshot.get("historical_pairs_wsol")
    if type(pairs) is not int or pairs < 0:
        raise ValueError("historical_wsol_pairs_malformed")
    # A pair by itself is insufficient: it is not a known exact lot, fill
    # receipt, complete wallet book or an observed policy decision.
    checks = {
        "wsol_buy_and_sell_events_present": matched["buy"] > 0 and matched["sell"] > 0,
        "wsol_historical_pair_candidates_present": pairs > 0,
        "all_creation_denominators_complete": true("full_creation_denominator_verified"),
        "full_wallet_history_verified": true("complete_wallet_history_verified"),
        "post_graduation_CPmm_tape_available": true("after_migration_CPMM_swaps_present"),
        "all_fees_and_failed_exits_reconciled": true("all_fees_reconciled"),
        "both_engine_decisions_observed_asof": true("at_decision_master_reference_observed"),
        "creator_disjoint_holdout_50_receipts": true("creator_disjoint_holdout_50_verified"),
        "data_source_not_biased_short_independent_samples":
            snapshot.get("source_trades_are_independent_short_per_table_samples") is False,
        "real_transaction_master_advantage_not_inferred_from_source_only":
            True,
    }
    ready = all(checks.values())
    return {
        "schema": "rugger-real-market-source-readiness-v1",
        "result": ("DATA_READY_FOR_PROSPECTIVE_REPLAY_ONLY" if ready
                   else "NO_GO_DATA_INSUFFICIENT"),
        "source_integrity_verified_files": source_count,
        "creator_claims_in_free_sample": creators,
        "holdout_minimum_distinct_creators": REQUIRED_HOLDOUT_CREATORS,
        "raw_sampled_wsol_event_matches": dict(matched),
        "raw_sampled_wsol_historical_pairs": pairs,
        "checks": checks,
        "eligible_P4_strategy_economic_cycles": 0,
        "economic_edge_validated": False,
        "realized_profitability_validated": False,
        "LIVE_READY_TO_ARM": False,
        "financial_order_submitted": False,
        "note": "Passing data-source eligibility never establishes positive Master PnL.",
    }


def main():
    p = (Path(__file__).resolve().parents[2] /
         "validation/live_readonly/FREE_PARQUET_P3P4_GATE_2026-10-30.json")
    report = evaluate_data_source_readiness(json.loads(p.read_text(encoding="utf-8")))
    print(json.dumps(report, sort_keys=True))
    return 0 if report["result"] == "NO_GO_DATA_INSUFFICIENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
