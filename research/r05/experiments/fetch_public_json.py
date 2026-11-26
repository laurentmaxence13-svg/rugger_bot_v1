"""Fetch public JSON series for S1-B (Hyperliquid funding + daily candles) and S1-A/S3-B
(DefiLlama pool histories). Raw bodies cached; sha256 recorded in results manifests."""
from __future__ import annotations

import json
import time

from r05lab.data import Manifest, json_get

HL = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "SOL"]
LLAMA_POOLS = {
    "aave_v3_usdc_eth": "aa70268e-4b52-42bf-a116-608b370f9501",
    "raydium_amm_v4_sol_usdc_025": "12edc6f3-4926-4b4f-b97c-38ef6a458574",
    "raydium_clmm_sol_usdc_004": "709f121d-d3b4-44da-b3d0-47bc16f5400b",
    "orca_whirlpool_sol_usdc_top": "a5c85bc8-eb41-45c0-a520-d18d7529c0d8",
}
TAG = "20261126"


def hl_funding(coin: str, m: Manifest) -> list[dict]:
    out, start, page = [], 1_640_995_200_000, 0  # 2022-01-01
    end = 1_793_577_600_000  # 2026-11-01 00:00Z (end of TEST window)
    while True:
        rows = json_get(HL, m, f"hl_funding_{coin}_{TAG}_p{page:04d}.json", method="POST",
                        payload={"type": "fundingHistory", "coin": coin, "startTime": start, "endTime": end})
        if not rows:
            break
        out += rows
        last = max(r["time"] for r in rows)
        if len(rows) < 500 or last >= end:
            break
        start, page = last + 1, page + 1
        time.sleep(0.3)
    return out


def main() -> None:
    m = Manifest("public_json")
    summary = {}
    for c in COINS:
        rows = hl_funding(c, m)
        summary[f"hl_funding_{c}"] = [len(rows), min(r["time"] for r in rows), max(r["time"] for r in rows)]
        candles = json_get(HL, m, f"hl_candles_1d_{c}_{TAG}.json", method="POST",
                           payload={"type": "candleSnapshot", "req": {"coin": c, "interval": "1d",
                                    "startTime": 1_640_995_200_000, "endTime": 1_793_577_600_000}})
        summary[f"hl_candles_{c}"] = [len(candles), candles[0]["t"] if candles else None]
        m.save()
    for name, pid in LLAMA_POOLS.items():
        d = json_get(f"https://yields.llama.fi/chart/{pid}", m, f"llama_chart_{name}_{TAG}.json")
        rows = d["data"]
        summary[name] = [len(rows), rows[0]["timestamp"], rows[-1]["timestamp"]]
    m.save()
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
