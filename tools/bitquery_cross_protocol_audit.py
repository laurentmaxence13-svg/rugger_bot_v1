#!/usr/bin/env python3
"""Offline DEXTrades cross-protocol overlap audit; NO trade or migration claim."""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

PROGRAMS = {
    "raydium_launchpad": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    "raydium_cp_swap": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
}
WSOL = "So11111111111111111111111111111111111111112"
REQUIRED = ("event_id", "block_time_utc", "block_slot", "signature", "protocol",
            "program_address", "market_address", "buy_mint", "sell_mint", "wsol_trade")


def audit(rows, source_sha256=None):
    sides = {p: defaultdict(list) for p in PROGRAMS}
    by_sig, seen = defaultdict(list), set()
    counts = Counter()
    data = list(rows)
    for e in data:
        if any(not e.get(k) for k in REQUIRED):
            raise ValueError("Missing required DEXTrades field")
        p = e["protocol"]
        if p not in PROGRAMS or e["program_address"] != PROGRAMS[p]:
            raise ValueError("Mismatched Raydium program")
        if e["event_id"] in seen:
            raise ValueError("Duplicate event identifier")
        seen.add(e["event_id"])
        try:
            slot = int(e["block_slot"])
            t = datetime.fromisoformat(e["block_time_utc"].replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid time or slot") from exc
        if slot < 1 or t.tzinfo is None:
            raise ValueError("Invalid time or slot")
        b, s = e["buy_mint"], e["sell_mint"]
        has_wsol = (b == WSOL) != (s == WSOL)
        if str(e["wsol_trade"]).lower() != str(has_wsol).lower():
            raise ValueError("Invalid WSOL classification")
        if has_wsol and e.get("token_mint") != (s if b == WSOL else b):
            raise ValueError("Wrong token-side mint")
        counts[p] += 1
        by_sig[e["signature"]].append(e)
        for mint in {b, s}:
            sides[p][mint].append(e)

    shared = sorted((set(sides["raydium_launchpad"]) & set(sides["raydium_cp_swap"])) - {WSOL})
    wsol_by_p = {
        p: {e["token_mint"] for e in data
            if e["protocol"] == p and str(e["wsol_trade"]).lower() == "true"}
        for p in PROGRAMS
    }
    routed = []
    for sig, entries in sorted(by_sig.items()):
        a = {mint for e in entries if e["protocol"] == "raydium_launchpad"
             for mint in (e["buy_mint"], e["sell_mint"])}
        b = {mint for e in entries if e["protocol"] == "raydium_cp_swap"
             for mint in (e["buy_mint"], e["sell_mint"])}
        if not a or not b:
            continue
        routed.append({
            "signature": sig,
            "slots": sorted({int(e["block_slot"]) for e in entries}),
            "rows": len(entries),
            "common_leg_mints_excluding_wsol": sorted((a & b) - {WSOL}),
            "classification": "MULTI_PROTOCOL_TRANSACTION_NOT_GRADUATION"
        })
    leads = []
    for mint in shared:
        appearances = []
        for p in PROGRAMS:
            evs = sides[p][mint]
            appearances.append({
                "protocol": p, "swaps": len(evs),
                "pools": len({e["market_address"] for e in evs}),
                "first_slot": min(int(e["block_slot"]) for e in evs),
                "last_slot": max(int(e["block_slot"]) for e in evs),
                "swaps_with_wsol": sum(str(e["wsol_trade"]).lower() == "true" for e in evs)
            })
        leads.append({
            "mint": mint, "appearances": appearances,
            "cross_program_signatures": sorted(
                r["signature"] for r in routed if mint in r["common_leg_mints_excluding_wsol"]),
            "migration_verified": False
        })
    return {
        "schema": "rugger-bitquery-cross-protocol-audit-v1",
        "source_sha256": source_sha256,
        "rows": len(data), "protocol_rows": dict(counts),
        "distinct_signatures": len(by_sig),
        "distinct_mints_launchlab_both_legs": len(sides["raydium_launchpad"]),
        "distinct_mints_cpmm_both_legs": len(sides["raydium_cp_swap"]),
        "shared_mints_excluding_wsol": len(shared),
        "shared_mints_wsol_direct_only": len(wsol_by_p["raydium_launchpad"] & wsol_by_p["raydium_cp_swap"]),
        "cross_protocol_same_signature_count": len(routed),
        "shared_mint_leads": leads,
        "same_signature_routes": routed,
        "verified_migrations": 0,
        "verified_creators": 0,
        "net_pnl_sol": None,
        "master_minus_baseline_pnl_sol": None,
        "economic_gate": "NO_GO_CREATION_MIGRATION_EXIT_EVIDENCE_MISSING",
        "caveat": "Shared mint or same transaction across programs proves neither token graduation nor executable entry/exit. No execution fees or creator identity."
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("normalized_swaps_csv", type=Path)
    ap.add_argument("--output", type=Path, default=Path("validation/bitquery_dextrades/cross_protocol_audit.json"))
    args = ap.parse_args()
    raw = args.normalized_swaps_csv.read_bytes()
    with args.normalized_swaps_csv.open(newline="", encoding="utf-8-sig") as f:
        report = audit(csv.DictReader(f), hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("ROWS:", report["rows"], "BRIDGE LEADS:", report["shared_mints_excluding_wsol"],
          "MULTIPROGRAM TX:", report["cross_protocol_same_signature_count"],
          "GATE:", report["economic_gate"])


if __name__ == "__main__":
    main()
