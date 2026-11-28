"""D-1 daily collector (R05_PREREGISTRATION_v3): direct measurement of LP fee accrual.

Each run: one public Raydium API snapshot of reserves and LP supply for the frozen pool list
(prospective/POOLS_D1.json); sqrt(x*y)/LP grows only through fees on a constant-product pool.
Weekly (or when the last fetch is older than 6 days): last 14 daily closes and volumes from
GeckoTerminal for the same pools (its free history only covers 180 days).
Outputs are small committed files under research/r05/prospective/. No key, read-only.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1] / "prospective"
UA = {"User-Agent": "r05-research/0.1 (public market data, paper only)"}


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def get(url: str, params: dict, tries: int = 4) -> dict:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30, headers=UA)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = repr(e)[:200]
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url} failed: {last}")


def snapshot(pools: list[dict]) -> dict:
    ids = [p["address"] for p in pools]
    rows, failed = [], []
    for k in range(0, len(ids), 20):
        batch = ids[k:k + 20]
        t0 = time.time()
        try:
            d = get("https://api-v3.raydium.io/pools/info/ids", {"ids": ",".join(batch)})
        except RuntimeError as e:
            failed += batch
            continue
        for x in d.get("data") or []:
            if not x:
                continue
            a, b, lp = x.get("mintAmountA"), x.get("mintAmountB"), x.get("lpAmount")
            rows.append({"id": x["id"], "pair": f"{x['mintA']['symbol']}-{x['mintB']['symbol']}",
                         "mintAmountA": a, "mintAmountB": b, "lpAmount": lp,
                         "sqrtk_per_lp": math.sqrt(a * b) / lp if a and b and lp else None,
                         "price": x.get("price"), "tvl": x.get("tvl"), "feeRate": x.get("feeRate"),
                         "day_volume": x["day"]["volume"], "week_volume": x["week"]["volume"],
                         "t_recv": time.time(), "t_send": t0})
    got = {r["id"] for r in rows}
    failed += [i for i in ids if i not in got and i not in failed]
    return {"utc": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "n_ok": len(rows), "n_failed": len(failed),
            "failed": failed, "pools": rows}


def gt_due(path: Path) -> bool:
    if not path.exists():
        return True
    last = None
    with path.open() as f:
        for row in csv.DictReader(f):
            last = row["fetched_utc"]
    if last is None:
        return True
    age = utcnow() - dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return age.days >= 6


def gt_fetch(pools: list[dict], path: Path) -> int:
    new = path.exists()
    fetched = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if not new:
            w.writerow(["fetched_utc", "pool", "day_utc", "open", "high", "low", "close", "volume"])
        for p in pools:
            try:
                d = get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{p['address']}/ohlcv/day",
                        {"aggregate": "1", "limit": "14", "currency": "token"})
                for r in d["data"]["attributes"]["ohlcv_list"]:
                    day = dt.datetime.fromtimestamp(r[0], dt.timezone.utc).strftime("%Y-%m-%d")
                    w.writerow([fetched, p["address"], day] + r[1:6])
                    n += 1
            except (RuntimeError, KeyError, TypeError):
                w.writerow([fetched, p["address"], "ERROR", "", "", "", "", ""])
            time.sleep(2.2)
    return n


def main() -> int:
    pools = json.loads((ROOT / "POOLS_D1.json").read_text())["pools"]
    snap = snapshot(pools)
    now = utcnow()
    out = ROOT / "pool_state" / now.strftime("%Y") / f"state_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(snap, separators=(",", ":"), sort_keys=True).encode()
    out.write_bytes(body)
    gt_rows = gt_fetch(pools, ROOT / "gt_daily.csv") if gt_due(ROOT / "gt_daily.csv") else 0
    man = ROOT / "MANIFEST.csv"
    first = not man.exists()
    with man.open("a", newline="") as f:
        w = csv.writer(f)
        if first:
            w.writerow(["utc", "file", "sha256", "n_ok", "n_failed", "gt_rows_added"])
        w.writerow([snap["utc"], str(out.relative_to(ROOT)), hashlib.sha256(body).hexdigest(),
                    snap["n_ok"], snap["n_failed"], gt_rows])
    print(json.dumps({"file": str(out.relative_to(ROOT)), "n_ok": snap["n_ok"], "n_failed": snap["n_failed"],
                      "gt_rows_added": gt_rows}))
    return 0 if snap["n_ok"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
