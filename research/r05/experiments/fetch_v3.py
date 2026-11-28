"""Data for pre-registration v3: daily klines of the 18-coin replication universe (H2b) and
hourly klines for the cross-chain LP replication (H3d). Official CHECKSUM verified; 404 logged."""
from __future__ import annotations

import json

from r05lab.data import Manifest, fetch_many, month_range

H2B = ["XRP", "LTC", "BCH", "ADA", "DOT", "LINK", "BNB", "XLM", "DOGE", "UNI", "AAVE", "EOS", "TRX", "XTZ",
       "ATOM", "VET", "THETA", "FIL"]
H3D_HOURLY = ["BNBUSDT", "MATICUSDT", "POLUSDT", "ETHUSDT", "SOLUSDT"]


def main():
    m = Manifest("binance")
    rels = []
    for c in H2B:
        s = f"{c}USDT"
        rels += [f"spot/monthly/klines/{s}/1d/{s}-1d-{mo}.zip" for mo in month_range("2017-08", "2026-10")]
    for s in H3D_HOURLY:
        rels += [f"spot/monthly/klines/{s}/1h/{s}-1h-{mo}.zip" for mo in month_range("2023-01", "2026-10")]
    out = fetch_many(rels, m, workers=8)
    print(json.dumps({"requested": len(rels), "ok": sum(p is not None for p in out), "missing": sum(p is None for p in out)}))


if __name__ == "__main__":
    main()
