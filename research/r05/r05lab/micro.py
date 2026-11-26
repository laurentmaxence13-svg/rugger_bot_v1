"""Market-making markouts from public trade prints (Binance aggTrades).

Quote proxy: best bid = last price printed by a seller-initiated trade, best ask = last price
printed by a buyer-initiated trade (forward-filled). Two fill models for a small passive quote:

* optimistic ("head of queue"): every aggressive trade on our side fills us at its price;
* pessimistic ("back of queue"): we rest at the previous best level and are filled only when
  an aggressive trade prints *through* that level.

Markout(h) for a maker buy at price p: (mid(t+h) - p) / p ; for a maker sell: (p - mid(t+h)) / p.
These are upper bounds on MM economics: no latency, no cancel race, no inventory limits.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

AGG_COLS = ["agg_id", "price", "qty", "first_id", "last_id", "time", "is_buyer_maker", "best_match"]


def read_aggtrades_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0])
    header = 0 if raw[:1].isalpha() else None
    df = pd.read_csv(io.BytesIO(raw), header=header, names=None if header == 0 else AGG_COLS,
                     usecols=[1, 2, 5, 6])
    df.columns = ["price", "qty", "time", "is_buyer_maker"]
    t = df["time"].astype("int64").to_numpy()
    df["t_ms"] = np.where(t > 10**14, t // 1000, t)
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(str).str.lower().isin(["true", "1"])
    return df[["t_ms", "price", "qty", "is_buyer_maker"]]


def _ffill(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    idx = np.where(mask, np.arange(len(values)), -1)
    np.maximum.accumulate(idx, out=idx)
    out = np.where(idx >= 0, values[np.maximum(idx, 0)], np.nan)
    return out


def quote_proxy(price: np.ndarray, sell_aggr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bid = _ffill(price, sell_aggr)
    ask = _ffill(price, ~sell_aggr)
    mid = np.where(np.isfinite(bid) & np.isfinite(ask) & (ask >= bid), 0.5 * (bid + ask), price)
    return bid, ask, mid


def markouts(df: pd.DataFrame, horizons_s=(1, 10, 60, 300), min_notional: float = 0.0) -> dict:
    t = df["t_ms"].to_numpy()
    p = df["price"].to_numpy(float)
    notional = p * df["qty"].to_numpy(float)
    sell = df["is_buyer_maker"].to_numpy(bool)  # buyer is maker => seller aggressed (hit the bid)
    bid, ask, mid = quote_proxy(p, sell)
    prev_bid = np.concatenate([[np.nan], bid[:-1]])
    prev_ask = np.concatenate([[np.nan], ask[:-1]])
    prev_mid = np.concatenate([[np.nan], mid[:-1]])
    big = notional >= min_notional
    res = {"n_trades": int(len(p)), "hours": float((t[-1] - t[0]) / 3.6e6)}
    hs = 0.5 * (prev_ask - prev_bid) / prev_mid
    ok = np.isfinite(hs) & (hs >= 0)
    res["half_spread_bps_median"] = float(np.median(hs[ok]) * 1e4)
    res["half_spread_bps_mean"] = float(np.mean(hs[ok]) * 1e4)
    # optimistic fills
    opt_buy = sell & big
    opt_sell = (~sell) & big
    # pessimistic: trade-through of the previous best level
    pes_buy = sell & big & np.isfinite(prev_bid) & (p < prev_bid)
    pes_sell = (~sell) & big & np.isfinite(prev_ask) & (p > prev_ask)
    for h in horizons_s:
        j = np.searchsorted(t, t + h * 1000, side="right") - 1
        fut = mid[j]
        valid = (t + h * 1000) <= t[-1]
        mo_opt = np.concatenate([((fut - p) / p)[opt_buy & valid], ((p - fut) / p)[opt_sell & valid]])
        mo_pes = np.concatenate([((fut - prev_bid) / prev_bid)[pes_buy & valid],
                                 ((prev_ask - fut) / prev_ask)[pes_sell & valid]])
        res[f"h{h}s"] = {
            "opt_n": int(len(mo_opt)), "opt_mean_bps": float(np.mean(mo_opt) * 1e4),
            "opt_se_bps": float(np.std(mo_opt, ddof=1) / np.sqrt(len(mo_opt)) * 1e4),
            "pes_n": int(len(mo_pes)), "pes_mean_bps": float(np.mean(mo_pes) * 1e4) if len(mo_pes) else float("nan"),
            "pes_se_bps": float(np.std(mo_pes, ddof=1) / np.sqrt(len(mo_pes)) * 1e4) if len(mo_pes) > 1 else float("nan"),
        }
    return res
