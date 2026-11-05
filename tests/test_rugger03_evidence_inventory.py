"""RUGGER 03: offline, read-only inventory of committed P3 evidence.

No network, no DB, no secrets. Pins what the archived evidence does and does not
prove, so a claim of profitability cannot pass without real BUY/SELL cycles.
"""
import collections
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "p3"


def records():
    for path in sorted(EVIDENCE.glob("*/events.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                yield path.parent.name, json.loads(line)


def count(kind, field=None):
    out = collections.Counter()
    for _, r in records():
        if r["kind"] == kind:
            out[(r["outcome"], r["reason"]) if field is None else r[field]] += 1
    return out


def test_archived_inventory_is_stable():
    kinds = collections.Counter(r["kind"] for _, r in records())
    assert sum(kinds.values()) == 397
    assert kinds["candidate_decision"] == 214
    assert kinds["launch"] == 3
    assert kinds["quote_attempt"] == 26


def test_only_three_observed_launch_creations_and_no_independent_creator_cohort():
    assert count("launch") == {("observed", None): 3}
    mints = {r["mint"] for _, r in records() if r["kind"] == "launch"}
    assert len(mints) <= 3 < 50  # target: >= 50 verified independent creators


def test_candidate_decisions_are_scope_filters_not_master_wait_reasons():
    reasons = count("candidate_decision")
    assert reasons[("rejected_from_capture_sample", "outside_native_SOL_scope")] == 129
    assert reasons[("rejected_from_capture_sample", "outside_preregistered_sample")] == 67
    assert not any("master" in str(k).lower() for k in reasons)


def test_no_sell_quote_or_complete_buy_sell_cycle_exists():
    quotes = count("quote_attempt")
    assert quotes[("quoted", None)] == 7
    assert quotes[("unavailable", "unsupported_or_unverified_state")] == 16
    sells = [(run, r) for run, r in records() if r["kind"] == "quote_attempt"
             and r["outcome"] == "quoted" and '"sell"' in json.dumps(r["payload"])]
    # one LaunchLab sell quote (launchlab_001) + one USDC transport probe; both
    # explicitly non-executable quotes, not fills.
    assert sorted(run for run, _ in sells) == ["launchlab_001", "pr19_access_smoke"]
    assert all(r["payload"]["executable_confirmed"] is False for _, r in sells)
    cycles = [r for _, r in records() if r["kind"] in ("cycle", "paper_cycle", "fill")]
    assert cycles == []  # 0 of the >= 20 required cycles


def test_no_master_strategy_engine_in_active_source():
    hits = []
    for p in (ROOT / "bot").rglob("*.py"):
        if "bot/bot/" in p.as_posix():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "MasterEngine" in text or "master_engine" in text or "strategy_mode='master'" in text:
            hits.append(p.name)
    assert hits == []  # MASTER vs reference comparison is not implemented here
