"""Offline audit for Bitquery token-side exports. No wallet, network or trading."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

VALID = {"raydium_launchpad", "raydium_cp_swap"}

def audit(payload, source_sha256=None):
    rows = (payload.get("Solana") or {}).get("DEXTradeByTokens")
    if not isinstance(rows, list):
        raise ValueError("Expected Solana.DEXTradeByTokens array")
    signatures = defaultdict(list)
    mints, stamps = set(), set()
    protocols = Counter()
    malformed, exact_repeated, price_mismatch = 0, 0, 0
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            malformed += 1
            continue
        tx, trade, block = row.get("Transaction") or {}, row.get("Trade") or {}, row.get("Block") or {}
        sig = tx.get("Signature")
        protocol = (trade.get("Dex") or {}).get("ProtocolName")
        mint = (trade.get("Currency") or {}).get("MintAddress")
        stamp = block.get("Time")
        if not all(isinstance(x, str) and x for x in (sig, protocol, mint, stamp)) or protocol not in VALID:
            malformed += 1
            continue
        signatures[sig].append(row)
        mints.add(mint)
        stamps.add(stamp)
        protocols[protocol] += 1
        raw = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if raw in seen:
            exact_repeated += 1
        seen.add(raw)
        try:
            amount = Decimal(str(trade["Amount"]))
            price = Decimal(str(trade["PriceInUSD"]))
            usd = Decimal(str(trade["AmountInUSD"]))
            if amount * price > 0 and abs(usd / (amount * price) - 1) > Decimal("0.05"):
                price_mismatch += 1
        except (KeyError, InvalidOperation, TypeError, ArithmeticError):
            pass
    distribution = Counter(len(v) for v in signatures.values())
    return {
        "schema": "rugger-bitquery-token-audit-v1",
        "source_cube": "Solana.DEXTradeByTokens",
        "source_sha256": source_sha256,
        "rows_received": len(rows),
        "valid_rows": sum(protocols.values()),
        "malformed_rows": malformed,
        "protocol_rows": dict(protocols),
        "distinct_signatures": len(signatures),
        "signature_row_distribution": {str(k): v for k, v in sorted(distribution.items())},
        "signatures_with_more_than_two_rows": sum(n for k, n in distribution.items() if k > 2),
        "rows_in_signatures_with_more_than_two_rows": sum(k * n for k, n in distribution.items() if k > 2),
        "distinct_token_mints": len(mints),
        "first_observed_utc": min(stamps) if stamps else None,
        "last_observed_utc": max(stamps) if stamps else None,
        "exact_repeated_rows_not_removed": exact_repeated,
        "amount_usd_price_discrepancy_gt_5pct": price_mismatch,
        "canonical_swaps_proven": 0,
        "qualified_entry_exit_cycles": 0,
        "verified_creators": 0,
        "realized_pnl_sol": None,
        "master_vs_baseline_edge_sol": None,
        "economic_validation": "NO_GO_INSUFFICIENT_EXECUTION_DATA",
        "reason": "Token-side rows lack swap index/pool, full buy-sell legs, fees, creator cohort, graduation and complete exits; signatures alone do not identify swaps."
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path, default=Path("research/bitquery/sample_audit.json"))
    args = p.parse_args()
    raw = args.input.read_bytes()
    report = audit(json.loads(raw), hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"{report['rows_received']} rows, {report['distinct_signatures']} signatures. {report['economic_validation']}")

if __name__ == "__main__":
    main()
