"""Pure offline helpers for the RUGGER 03 v2 candidate protocol. No network, DB or secrets."""
import gzip, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
KNOWN_KINDS = frozenset({"candidate_decision", "transaction", "request", "quote_attempt", "checkpoint",
                         "pool_snapshot", "gap", "launch", "discovery", "fx"})
CYCLE_KINDS = frozenset({"cycle", "paper_cycle", "fill"})
MIGRATION_HINTS = ("migrat", "cpmm")


def load_bundles(base=None):
    base = pathlib.Path(base) if base else ROOT / "evidence" / "p3"
    out = {}
    for f in sorted(base.glob("*/events.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            out[f.parent.name] = [json.loads(l) for l in fh if l.strip()]
    return out


def flat(bundles):
    return [r for rs in bundles.values() for r in rs]


def dedup_by_mint(records, kind=None):
    """Analysis unit = mint. Returns {mint: [records]}; records without mint are skipped."""
    d = {}
    for r in records:
        if kind and r.get("kind") != kind:
            continue
        if r.get("mint"):
            d.setdefault(r["mint"], []).append(r)
    return d


def cross_bundle_duplicate_signatures(bundles, kind="transaction"):
    seen = {}
    for name, rs in bundles.items():
        for r in rs:
            if r.get("kind") == kind and r.get("signature"):
                seen.setdefault(r["signature"], set()).add(name)
    return {s: b for s, b in seen.items() if len(b) > 1}


def causal_view(records, t_ms):
    """Only records whose available_at_ms <= t_ms AND with a known source_time_ms (strict mode)."""
    return [r for r in records
            if r.get("available_at_ms") is not None and r["available_at_ms"] <= t_ms
            and r.get("source_time_ms") is not None]


def unknown_source_time(records):
    return [r for r in records if r.get("source_time_ms") is None]


def net_pnl_lamports(buy_in, sell_out, fees):
    """Integer lamports only. fees: dict of components; any None => cost unknown => None."""
    if any(v is None for v in fees.values()):
        return None
    for v in (buy_in, sell_out, *fees.values()):
        if not isinstance(v, int) or isinstance(v, bool):
            raise TypeError("lamports must be int")
    return sell_out - buy_in - sum(fees.values())
