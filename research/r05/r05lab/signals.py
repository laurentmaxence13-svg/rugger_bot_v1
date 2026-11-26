"""Pre-registered S2 signal families. Each returns a target position decided at bar close t
from data <= t only (verified by the truncation tests in tests/test_signals.py).

``long_only=True`` clips the position to [0, 1] (spot, long/flat variant).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _clip(pos: pd.Series, long_only: bool) -> pd.Series:
    return pos.clip(lower=0.0) if long_only else pos


def tsmom(close: pd.Series, lookback: int, long_only: bool) -> pd.Series:
    """F1: sign of the past `lookback`-bar return."""
    r = close / close.shift(lookback) - 1.0
    return _clip(np.sign(r).fillna(0.0), long_only)


def donchian(high: pd.Series, low: pd.Series, close: pd.Series, n: int, long_only: bool) -> pd.Series:
    """F2: breakout above the prior n-bar high (below the prior n-bar low for shorts);
    exit when close crosses the prior n/2-bar low (high for shorts)."""
    m = max(2, n // 2)
    hi_n = high.rolling(n).max().shift(1).to_numpy()
    lo_n = low.rolling(n).min().shift(1).to_numpy()
    lo_m = low.rolling(m).min().shift(1).to_numpy()
    hi_m = high.rolling(m).max().shift(1).to_numpy()
    c = close.to_numpy()
    pos = np.zeros(len(c))
    cur = 0.0
    for t in range(len(c)):
        if np.isnan(hi_n[t]):
            pos[t] = 0.0
            continue
        if cur > 0 and c[t] < lo_m[t]:
            cur = 0.0
        elif cur < 0 and c[t] > hi_m[t]:
            cur = 0.0
        if cur == 0.0:
            if c[t] > hi_n[t]:
                cur = 1.0
            elif c[t] < lo_n[t] and not long_only:
                cur = -1.0
        pos[t] = cur
    return pd.Series(pos, index=close.index)


def mean_reversion(close: pd.Series, k: int, long_only: bool, z_entry: float = 2.0,
                   vol_window: int = 720) -> pd.Series:
    """F3: fade a k-bar move larger than z_entry standard deviations; hold k bars."""
    lr = np.log(close).diff()
    sigma = lr.rolling(vol_window, min_periods=vol_window // 2).std()
    z = (np.log(close) - np.log(close.shift(k))) / (sigma * np.sqrt(k))
    zv = z.to_numpy()
    pos = np.zeros(len(zv))
    cur, left = 0.0, 0
    for t in range(len(zv)):
        if left > 0:
            left -= 1
            if left == 0:
                cur = 0.0
        if cur == 0.0 and np.isfinite(zv[t]) and abs(zv[t]) > z_entry:
            cur = -np.sign(zv[t])
            if long_only and cur < 0:
                cur = 0.0
            else:
                left = k
        pos[t] = cur
    return pd.Series(pos, index=close.index)


def flow_imbalance(volume: pd.Series, taker_buy: pd.Series, k: int, long_only: bool,
                   q: float = 0.80, window: int = 720) -> pd.Series:
    """F4: follow the sign of the k-bar taker imbalance when it is in its top (1-q) range
    relative to the previous `window` bars (threshold excludes the current bar)."""
    v = volume.rolling(k).sum()
    b = taker_buy.rolling(k).sum()
    imb = (2.0 * b - v) / v.replace(0.0, np.nan)
    thr = imb.abs().rolling(window, min_periods=window // 2).quantile(q).shift(1)
    pos = np.where(imb.abs() > thr, np.sign(imb), 0.0)
    return _clip(pd.Series(pos, index=volume.index).fillna(0.0), long_only)
