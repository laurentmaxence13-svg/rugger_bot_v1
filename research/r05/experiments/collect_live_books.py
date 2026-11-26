"""S1-C / S4-B: short prospective snapshot of public order books and DEX quotes.

Read-only public endpoints, no key. Requests of one round are sent concurrently to reduce
non-simultaneity; send/receive times are logged per request. Output: gzip JSON lines under
research/r05/data/live/. Pre-registered duration: 20 minutes, ~5 s period.
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
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

OKX = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "SOL-USDC", "USDC-USDT", "WIF-USDT", "BONK-USDT", "JTO-USDT",
       "BTC-USDT-SWAP", "SOL-USDT-SWAP"]
COINBASE = ["BTC-USD", "ETH-USD", "SOL-USD", "USDT-USD", "WIF-USD", "BONK-USD", "JTO-USD"]
HL = ["BTC", "ETH", "SOL", "WIF", "JUP", "HYPE"]


def requests_for_round(i: int) -> list[dict]:
    reqs = []
    for inst in OKX:
        reqs.append({"venue": "okx", "sym": inst, "method": "GET",
                     "url": "https://www.okx.com/api/v5/market/books", "params": {"instId": inst, "sz": "20"}})
    for p in COINBASE:
        lvl = "2" if (p in ("SOL-USD", "BTC-USD") and i % 12 == 0) else "1"
        reqs.append({"venue": "coinbase", "sym": p, "method": "GET", "level": lvl,
                     "url": f"https://api.exchange.coinbase.com/products/{p}/book", "params": {"level": lvl}})
    reqs.append({"venue": "kraken", "sym": "TICKER", "method": "GET",
                 "url": "https://api.kraken.com/0/public/Ticker",
                 "params": {"pair": "XBTUSD,ETHUSD,SOLUSD,USDTUSD,USDCUSD,WIFUSD,BONKUSD,JTOUSD"}})
    for p in ("SOLUSD", "XBTUSD"):
        reqs.append({"venue": "kraken", "sym": p, "method": "GET",
                     "url": "https://api.kraken.com/0/public/Depth", "params": {"pair": p, "count": "25"}})
    for c in HL:
        reqs.append({"venue": "hyperliquid", "sym": c, "method": "POST",
                     "url": "https://api.hyperliquid.xyz/info", "json": {"type": "l2Book", "coin": c}})
    if i % 4 == 0:
        for sol in (1, 10, 100, 1000):
            reqs.append({"venue": "jupiter", "sym": f"SOL->USDC:{sol}", "method": "GET",
                         "url": "https://lite-api.jup.ag/swap/v1/quote",
                         "params": {"inputMint": SOL, "outputMint": USDC, "amount": str(sol * 10**9),
                                    "slippageBps": "50"}})
        for usd in (100, 1000, 10000, 100000):
            reqs.append({"venue": "jupiter", "sym": f"USDC->SOL:{usd}", "method": "GET",
                         "url": "https://lite-api.jup.ag/swap/v1/quote",
                         "params": {"inputMint": USDC, "outputMint": SOL, "amount": str(usd * 10**6),
                                    "slippageBps": "50"}})
    return reqs


def do(session: requests.Session, rq: dict) -> dict:
    t0 = time.time()
    try:
        if rq["method"] == "POST":
            r = session.post(rq["url"], json=rq["json"], timeout=10, headers=UA)
        else:
            r = session.get(rq["url"], params=rq["params"], timeout=10, headers=UA)
        t1 = time.time()
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") or r.text[:1] in "[{" else r.text
        return {"venue": rq["venue"], "sym": rq["sym"], "t_send": t0, "t_recv": t1, "http": r.status_code,
                "body": body}
    except Exception as e:  # recorded, never hidden
        return {"venue": rq["venue"], "sym": rq["sym"], "t_send": t0, "t_recv": time.time(), "http": -1,
                "error": repr(e)[:300]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--period", type=float, default=5.0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"snap_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl.gz"
    session = requests.Session()
    end = time.time() + a.minutes * 60
    i = 0
    with gzip.open(path, "wt") as f, ThreadPoolExecutor(max_workers=16) as ex:
        while time.time() < end:
            start = time.time()
            res = list(ex.map(lambda rq: do(session, rq), requests_for_round(i)))
            f.write(json.dumps({"round": i, "t_round": start, "results": res}) + "\n")
            f.flush()
            i += 1
            time.sleep(max(0.0, a.period - (time.time() - start)))
    print(json.dumps({"file": str(path), "rounds": i}))


if __name__ == "__main__":
    main()
