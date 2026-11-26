"""R4.1 — market-making markouts on Hyperliquid small caps (R05_PREREGISTRATION_v2 §R4).

Quotes: best bid/ask of the last l2Book snapshot (exchange timestamp) before each trade.
Optimistic fill: every trade on our side fills our resting quote at that best price.
Pessimistic fill: only trades printing strictly through that price (level swept).
Markout(h) vs the mid of the first snapshot at or after t+h. Net = markout - 1.5 bp maker fee.
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from r05lab.data import DATA_DIR, RESULTS_DIR

MAKER_BPS = 1.5
HORIZONS = (10, 60)


def load(path):
    books, trades = {}, {}
    lines = []
    with gzip.open(path, "rt") as fh:
        try:
            for line in fh:
                lines.append(line)
        except EOFError:
            pass
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            break
        for r in d["results"]:
            if r["http"] != 200 or not r.get("body"):
                continue
            c = r["coin"]
            if r["kind"] == "l2Book":
                b = r["body"]
                if b["levels"][0] and b["levels"][1]:
                    books.setdefault(c, []).append((b["time"], float(b["levels"][0][0]["px"]), float(b["levels"][1][0]["px"])))
            else:
                for t in r["body"]:
                    trades.setdefault(c, {})[t["tid"]] = (t["time"], float(t["px"]), float(t["sz"]), t["side"])
    return books, trades


def analyse(book_rows, trade_map):
    bk = pd.DataFrame(book_rows, columns=["t", "bid", "ask"]).drop_duplicates("t").sort_values("t")
    bk["mid"] = 0.5 * (bk["bid"] + bk["ask"])
    tr = pd.DataFrame(list(trade_map.values()), columns=["t", "px", "sz", "side"]).sort_values("t")
    tr = tr[(tr["t"] >= bk["t"].iloc[0]) & (tr["t"] <= bk["t"].iloc[-1])]
    bt, bb, ba, bm = (bk[c].to_numpy() for c in ("t", "bid", "ask", "mid"))
    i = np.searchsorted(bt, tr["t"].to_numpy(), side="right") - 1
    ok = i >= 0
    tr, i = tr[ok], i[ok]
    b, a, m0 = bb[i], ba[i], bm[i]
    px = tr["px"].to_numpy()
    buy_aggr = np.where(px >= a, True, np.where(px <= b, False, px >= m0))
    out = {"snapshots": int(len(bk)), "trades": int(len(tr)), "minutes": float((bt[-1] - bt[0]) / 60000),
           "half_spread_bps_median": float(np.median((ba - bb) / bm / 2 * 1e4))}
    for h in HORIZONS:
        j = np.searchsorted(bt, tr["t"].to_numpy() + h * 1000, side="left")
        valid = j < len(bt)
        mh = np.where(valid, bm[np.minimum(j, len(bt) - 1)], np.nan)
        mo_ask = (a - mh) / a * 1e4      # we sold at the ask
        mo_bid = (mh - b) / b * 1e4      # we bought at the bid
        opt = np.concatenate([mo_ask[buy_aggr & valid], mo_bid[~buy_aggr & valid]])
        pes = np.concatenate([mo_ask[buy_aggr & valid & (px > a)], mo_bid[~buy_aggr & valid & (px < b)]])
        for name, x in (("opt", opt), ("pes", pes)):
            n = len(x)
            out[f"h{h}s_{name}"] = {"n": int(n), "mean_bps": float(np.mean(x)) if n else float("nan"),
                                    "se_bps": float(np.std(x, ddof=1) / np.sqrt(n)) if n > 1 else float("nan"),
                                    "net_mean_bps": float(np.mean(x) - MAKER_BPS) if n else float("nan")}
    p = out["h10s_pes"]
    out["reopen"] = bool(p["n"] >= 200 and (p["net_mean_bps"] - 2 * p["se_bps"]) > 0)
    return out


def main():
    f = sorted((DATA_DIR / "live").glob("hl_*.jsonl.gz"))[-1]
    books, trades = load(f)
    res = {"protocol": "R05_PREREGISTRATION_v2 §R4.1", "file": f.name, "maker_fee_bps": MAKER_BPS,
           "coins": {c: analyse(books[c], trades.get(c, {})) for c in books}}
    res["verdict"] = "REOUVERTURE" if any(v["reopen"] for v in res["coins"].values()) else "REJET CONFIRME"
    (RESULTS_DIR / "R4_hl_markouts.json").write_text(json.dumps(res, indent=1))
    for c, v in res["coins"].items():
        print(c, v["trades"], round(v["half_spread_bps_median"], 2),
              {k: (v[k]["n"], round(v[k]["mean_bps"], 2), round(v[k]["se_bps"], 2)) for k in v if k[:1] == "h" and k[1:2].isdigit()})
    print(res["verdict"])


if __name__ == "__main__":
    main()
