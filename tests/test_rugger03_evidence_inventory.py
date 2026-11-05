"""RUGGER 01 (issues #163, #172): offline, read-only, non-vacuous inventory of committed P3 evidence.

Portability (issue #172): the inventory is pinned to FIVE named proof bundles, never a glob
of evidence/p3/*, because the number of bundles differs between main (5) and
integration/consolidation-20261103 (17). Provenance: the five bundles were introduced by the
RUGGER 03 audit (issue #152; commit b0c403b is the parent of PR #166) and are byte-identical
(same git tree SHAs) on main and on the integration branch. Extra bundles are ignored on purpose.
Total: 10 tests (8 real-evidence + 2 SYNTHETIC controls); earlier "11" was a miscount (audit #167).

No network, no DB, no secrets. Reinforces the RUGGER 03 inventory per audit #160:
real schema kinds only, raw records vs unique entities, exact transaction count,
and positive controls (clearly SYNTHETIC, in-memory, never mixed with real data)
proving each detector can actually fail.
"""
import collections
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "p3"
PROOF_BUNDLES = (
    "creation_diagnostic", "launchlab_001", "launchlab_002", "pr19_access_smoke", "version_diagnostic",
)

# Kinds that really exist in the committed schema (audit #160).
REAL_KINDS = {
    "candidate_decision", "transaction", "request", "quote_attempt", "checkpoint",
    "pool_snapshot", "gap", "launch", "discovery", "fx",
}


def records():
    for name in PROOF_BUNDLES:  # fixed list: a missing bundle must fail loudly, not shrink the sample
        path = EVIDENCE / name / "events.jsonl.gz"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                yield path.parent.name, json.loads(line)


def count(kind):
    return collections.Counter((r["outcome"], r["reason"]) for _, r in records() if r["kind"] == kind)


# ---- detectors (pure functions over (run, record) pairs, so they can be controlled) ----
def unknown_kinds(recs):
    return {r["kind"] for _, r in recs} - REAL_KINDS


def complete_cycles(recs):
    """A cycle needs, for one mint, an executable-confirmed buy AND sell quote."""
    sides = collections.defaultdict(set)
    for _, r in recs:
        p = r.get("payload") or {}
        if r["kind"] == "quote_attempt" and r["outcome"] == "quoted" \
                and p.get("executable_confirmed") is True and r.get("mint"):
            sides[r["mint"]].add(p.get("quote_side"))
    return [m for m, s in sides.items() if {"buy", "sell"} <= s]


def migration_records(recs):
    return [r for _, r in recs
            if any("migrat" in str(r.get(k) or "").lower() for k in ("kind", "outcome", "reason"))]


def unique_signatures(recs):
    return {r["signature"] for _, r in recs if r["kind"] == "transaction" and r["signature"]}


def unique_mints(recs, kind):
    return {r["mint"] for _, r in recs if r["kind"] == kind and r["mint"]}


# ---- real-evidence tests ----
def test_raw_events_are_distinct_from_unique_entities():
    recs = list(records())
    assert len(recs) == 397  # raw records, NOT unique entities
    decisions = [r for _, r in recs if r["kind"] == "candidate_decision"]
    assert sum(r["mint"] is None for r in decisions) == 3  # 3 decisions carry no mint
    # 135 real mints (audit #160 counted 136 by including the null mint)
    assert len(unique_mints(recs, "candidate_decision")) == 135 < 214
    all_sigs = {r["signature"] for _, r in recs if r["signature"]}
    assert len(all_sigs) == 79  # transactions + launches + decisions share signatures
    assert len({r["record_hash"] for _, r in recs}) == 397  # no fully duplicated record


def test_transaction_count_is_81_records_79_unique_signatures():
    recs = list(records())
    tx = [r for _, r in recs if r["kind"] == "transaction"]
    per_bundle = collections.Counter(run for run, r in recs if r["kind"] == "transaction")
    assert per_bundle == {"launchlab_001": 40, "launchlab_002": 33, "pr19_access_smoke": 5,
                          "version_diagnostic": 2, "creation_diagnostic": 1}
    assert len(tx) == 81  # not 80 (report #152 was off by one)
    assert all(r["signature"] for r in tx)
    assert len(unique_signatures(recs)) == 79  # 2 signatures recur across bundles
    bundles = collections.defaultdict(set)
    for run, r in recs:
        if r["kind"] == "transaction":
            bundles[r["signature"]].add(run)
    assert sum(len(v) > 1 for v in bundles.values()) == 2


def test_inventory_uses_only_real_schema_kinds():
    recs = list(records())
    assert unknown_kinds(recs) == set()
    kinds = collections.Counter(r["kind"] for _, r in recs)
    assert kinds == {"candidate_decision": 214, "transaction": 81, "request": 39,
                     "quote_attempt": 26, "checkpoint": 14, "pool_snapshot": 12,
                     "gap": 5, "launch": 3, "discovery": 2, "fx": 1}


def test_only_three_observed_launch_creations_and_no_independent_creator_cohort():
    recs = list(records())
    assert count("launch") == {("observed", None): 3}
    assert len(unique_mints(recs, "launch")) == 3 < 50  # target: >= 50 verified independent creators


def test_candidate_decisions_are_scope_filters_not_master_wait_reasons():
    reasons = count("candidate_decision")
    assert reasons[("rejected_from_capture_sample", "outside_native_SOL_scope")] == 129
    assert reasons[("rejected_from_capture_sample", "outside_preregistered_sample")] == 67
    assert not any("master" in str(k).lower() for k in reasons)


def test_zero_cycles_is_measured_on_real_quote_schema_not_absent_kinds():
    recs = list(records())
    quotes = [r for _, r in recs if r["kind"] == "quote_attempt"]
    assert collections.Counter((r["payload"].get("quote_side"), r["outcome"]) for r in quotes) == {
        ("buy", "quoted"): 5, ("sell", "quoted"): 2,
        ("buy", "unavailable"): 8, ("sell", "unavailable"): 11}
    assert count("quote_attempt")[("unavailable", "unsupported_or_unverified_state")] == 16
    quoted = [r for r in quotes if r["outcome"] == "quoted"]
    assert len(quoted) == 7 and all(r["payload"]["executable_confirmed"] is False for r in quoted)
    assert all(r["payload"]["fee_details"]["network_fee_lamports"] is None for r in quoted)
    assert complete_cycles(recs) == []  # 0 of the >= 20 required cycles


def test_no_migration_event_in_real_evidence():
    # LaunchLab config fields such as migrate_type/migrate_fee are not migration events.
    assert migration_records(list(records())) == []


def test_no_master_strategy_engine_in_active_source():
    hits = []
    for p in (ROOT / "bot").rglob("*.py"):
        if "bot/bot/" in p.as_posix():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "MasterEngine" in text or "master_engine" in text or "strategy_mode='master'" in text:
            hits.append(p.name)
    assert hits == []  # MASTER vs reference comparison is not implemented here


# ---- SYNTHETIC positive controls (in-memory only; prove the detectors can fail) ----
def _synthetic_quote(mint, side, confirmed):
    return ("SYNTHETIC", {"kind": "quote_attempt", "outcome": "quoted", "reason": None, "mint": mint,
                          "payload": {"quote_side": side, "executable_confirmed": confirmed}})


def test_synthetic_control_cycle_detector_can_fail():
    cycle = [_synthetic_quote("MINT_S", "buy", True), _synthetic_quote("MINT_S", "sell", True)]
    assert complete_cycles(cycle) == ["MINT_S"]
    not_executable = [_synthetic_quote("MINT_S", "buy", False), _synthetic_quote("MINT_S", "sell", False)]
    assert complete_cycles(not_executable) == []
    one_sided = [_synthetic_quote("MINT_S", "buy", True)]
    assert complete_cycles(one_sided) == []


def test_synthetic_control_migration_unknown_kind_and_dedup_detectors_can_fail():
    mig = [("SYNTHETIC", {"kind": "pool_snapshot", "outcome": "observed", "reason": "migration_to_cpmm"})]
    assert len(migration_records(mig)) == 1
    assert unknown_kinds([("SYNTHETIC", {"kind": "paper_cycle"})]) == {"paper_cycle"}
    dup = [("A", {"kind": "transaction", "signature": "S1"}), ("B", {"kind": "transaction", "signature": "S1"})]
    assert len(unique_signatures(dup)) == 1 != len(dup)
