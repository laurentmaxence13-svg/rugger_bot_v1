"""Vectorised position backtester with explicit timing and costs.

Convention (tested): ``pos[t]`` is decided at the close of bar t using data <= t and is held
over bar t+1. Net return of bar t+1:

    net[t+1] = pos[t] * ret[t+1] - |pos[t] - pos[t-1]| * cost_per_side - pos[t] * funding[t+1]

``funding[t+1]`` is the sum of perp funding rates settled during bar t+1 (a long pays a
positive rate). ``cost_per_side`` is a fraction (10 bp = 0.0010).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def bar_returns(close: pd.Series) -> pd.Series:
    return close.pct_change()


def run(pos: pd.Series, ret: pd.Series, cost_per_side: float,
        funding: pd.Series | None = None) -> pd.DataFrame:
    pos = pos.reindex(ret.index).fillna(0.0).astype(float)
    held = pos.shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs()).shift(1).fillna(0.0)
    gross = held * ret.fillna(0.0)
    cost = turnover * cost_per_side
    fund = held * funding.reindex(ret.index).fillna(0.0) if funding is not None else 0.0 * gross
    net = gross - cost - fund
    return pd.DataFrame({"pos": held, "gross": gross, "cost": cost, "funding": fund, "net": net,
                         "turnover": turnover})


def to_daily(bt: pd.DataFrame) -> pd.Series:
    """Compound intraday net returns into UTC calendar days."""
    return (1.0 + bt["net"]).groupby(bt.index.floor("D")).prod() - 1.0


def trades(bt: pd.DataFrame) -> pd.DataFrame:
    """Segments of constant non-zero held position; net return compounded per segment."""
    p = bt["pos"].to_numpy()
    net = bt["net"].to_numpy()
    out = []
    i, n = 0, len(p)
    while i < n:
        if p[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < n and p[j + 1] == p[i]:
            j += 1
        # exit cost is charged on the bar after the segment
        exit_cost = bt["cost"].iloc[j + 1] if j + 1 < n and p[j + 1] == 0 else 0.0
        r = np.prod(1.0 + net[i:j + 1]) * (1.0 - exit_cost) - 1.0
        out.append({"start": bt.index[i], "end": bt.index[j], "side": float(np.sign(p[i])),
                    "bars": j - i + 1, "net": float(r)})
        i = j + 1
    return pd.DataFrame(out)


def split(series: pd.Series | pd.DataFrame, periods: dict[str, tuple[str, str]]) -> dict:
    return {k: series.loc[a:b] for k, (a, b) in periods.items()}
