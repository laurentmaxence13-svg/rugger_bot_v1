"""Download + verify every Binance public-archive file used by S1, S2 and S4.

All files are checked against the official .CHECKSUM (sha256) and logged in
results/DATA_MANIFEST_binance.json. Missing months (HTTP 404) are logged, not invented.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from r05lab.data import Manifest, fetch_many, month_range

SPOT = {"BTCUSDT": "2018-01", "ETHUSDT": "2018-01", "SOLUSDT": "2020-08"}
PERP = {"BTCUSDT": "2019-09", "ETHUSDT": "2019-11", "SOLUSDT": "2020-09"}
END = "2026-10"
MM_SYMBOLS = ["BTCUSDT", "SOLUSDT", "WIFUSDT"]
SEED = 20261126


def mm_dates() -> list[str]:
    """Pre-registered: 3 dates uniform in [2025-01-01, 2026-10-31], seed 20261126."""
    days = pd.date_range("2025-01-01", "2026-10-31", freq="D")
    rng = np.random.default_rng(SEED)
    pick = np.sort(rng.choice(len(days), size=3, replace=False))
    return [days[i].strftime("%Y-%m-%d") for i in pick]


def main() -> None:
    m = Manifest("binance")
    rels = []
    for s, start in SPOT.items():
        rels += [f"spot/monthly/klines/{s}/1h/{s}-1h-{mo}.zip" for mo in month_range(start, END)]
    for s, start in PERP.items():
        rels += [f"futures/um/monthly/klines/{s}/1h/{s}-1h-{mo}.zip" for mo in month_range(start, END)]
        rels += [f"futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{mo}.zip" for mo in month_range(start, END)]
    dates = mm_dates()
    for s in MM_SYMBOLS:
        rels += [f"spot/daily/aggTrades/{s}/{s}-aggTrades-{d}.zip" for d in dates]
    out = fetch_many(rels, m, workers=8)
    print(json.dumps({"requested": len(rels), "ok": sum(p is not None for p in out),
                      "missing": sum(p is None for p in out), "mm_dates": dates}))


if __name__ == "__main__":
    main()
