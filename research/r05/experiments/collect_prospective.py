"""Prospective collectors for the refutation battery (R05_PREREGISTRATION_v2):

* ``raydium``: R3.1b — every 60 s, reserves and LP supply of the Raydium AMM v4 SOL-USDC pool
  (public API v3). sqrt(x*y)/LP supply only grows through fees.
* ``hl``: R4.1 — every 5 s, Hyperliquid l2Book + recentTrades for WIF, JUP, POPCAT, kPEPE.
  Trader addresses present in the public feed are dropped (not needed).
Read-only public endpoints, no key. Output: research/r05/data/live/.
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parents[1] / "data" / "live"
UA = {"User-Agent": "r05-research/0.1 (public market data, paper only)"}
POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
HL_COINS = ["WIF", "JUP", "POPCAT", "kPEPE"]
HL = "https://api.hyperliquid.xyz/info"


def raydium_round(s: requests.Session) -> dict:
    t0 = time.time()
    r = s.get("https://api-v3.raydium.io/pools/info/ids", params={"ids": POOL}, timeout=15, headers=UA)
    rec = {"t_send": t0, "t_recv": time.time(), "http": r.status_code}
    if r.status_code == 200:
        x = r.json()["data"][0]
        rec.update({k: x.get(k) for k in ("mintAmountA", "mintAmountB", "lpAmount", "lpPrice", "tvl", "price")})
        rec["day_volume"] = x["day"]["volume"]
    return rec


def hl_round(s: requests.Session, ex: ThreadPoolExecutor) -> list[dict]:
    def one(kind: str, coin: str) -> dict:
        t0 = time.time()
        try:
            r = s.post(HL, json={"type": kind, "coin": coin}, timeout=10, headers=UA)
            body = r.json() if r.status_code == 200 else None
            if kind == "recentTrades" and body:
                body = [{k: v for k, v in tr.items() if k != "users"} for tr in body]
            return {"kind": kind, "coin": coin, "t_send": t0, "t_recv": time.time(), "http": r.status_code, "body": body}
        except Exception as e:
            return {"kind": kind, "coin": coin, "t_send": t0, "t_recv": time.time(), "http": -1, "error": repr(e)[:200]}
    jobs = [("l2Book", c) for c in HL_COINS] + [("recentTrades", c) for c in HL_COINS]
    return list(ex.map(lambda j: one(*j), jobs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["raydium", "hl"])
    ap.add_argument("--minutes", type=float, required=True)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    period = 60.0 if a.which == "raydium" else 5.0
    path = OUT / f"{a.which}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl.gz"
    s = requests.Session()
    end = time.time() + a.minutes * 60
    n = 0
    with gzip.open(path, "wt") as f, ThreadPoolExecutor(max_workers=8) as ex:
        while time.time() < end:
            start = time.time()
            rec = raydium_round(s) if a.which == "raydium" else {"t_round": start, "results": hl_round(s, ex)}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            n += 1
            time.sleep(max(0.0, period - (time.time() - start)))
    print(json.dumps({"file": str(path), "rounds": n}))


if __name__ == "__main__":
    main()
