"""Performance and inference statistics (numpy + stdlib only)."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

N01 = NormalDist()
EULER_GAMMA = 0.5772156649015329


def sharpe(r: np.ndarray, ppy: float = 365.0) -> float:
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if len(r) < 2 or np.std(r, ddof=1) == 0:
        return float("nan")
    return float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(ppy))


def ann_return(r: np.ndarray, ppy: float = 365.0) -> float:
    """Geometric annualised return of simple periodic returns."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return float("nan")
    w = np.prod(1.0 + r)
    if w <= 0:
        return -1.0
    return float(w ** (ppy / len(r)) - 1.0)


def ann_vol(r: np.ndarray, ppy: float = 365.0) -> float:
    r = np.asarray(r, float)
    return float(np.std(r[np.isfinite(r)], ddof=1) * math.sqrt(ppy))


def max_drawdown(r: np.ndarray) -> float:
    """Max peak-to-trough loss of compounded wealth, as a positive fraction."""
    r = np.asarray(r, float)
    w = np.cumprod(1.0 + np.nan_to_num(r))
    peak = np.maximum.accumulate(np.concatenate([[1.0], w]))[1:]
    return float(np.max(1.0 - w / peak)) if len(w) else float("nan")


def cvar(r: np.ndarray, alpha: float = 0.05) -> float:
    """Expected loss in the worst alpha tail (returned as a negative return)."""
    r = np.sort(np.asarray(r, float)[np.isfinite(r)])
    k = max(1, int(math.floor(alpha * len(r))))
    return float(np.mean(r[:k]))


def moments(r: np.ndarray) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    m = r.mean()
    s = r.std(ddof=0)
    if s == 0:
        return 0.0, 3.0
    z = (r - m) / s
    return float(np.mean(z ** 3)), float(np.mean(z ** 4))


def psr(r: np.ndarray, sr_star: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio (Bailey & López de Prado 2012).

    sr_star is per-period (not annualised). Returns P[true SR > sr_star].
    """
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = moments(r)
    den = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr ** 2
    if den <= 0:
        return float("nan")
    return float(N01.cdf((sr - sr_star) * math.sqrt(n - 1) / math.sqrt(den)))


def expected_max_sr(trial_srs_per_period: np.ndarray, n_trials: int) -> float:
    """E[max SR] under the null for n_trials independent trials (per period)."""
    v = float(np.var(np.asarray(trial_srs_per_period, float), ddof=1)) if len(trial_srs_per_period) > 1 else 0.0
    if n_trials < 2 or v <= 0:
        return 0.0
    a = (1 - EULER_GAMMA) * N01.inv_cdf(1 - 1.0 / n_trials)
    b = EULER_GAMMA * N01.inv_cdf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(v) * (a + b)


def expected_max_sr_null(n_obs: int, n_trials: int) -> float:
    """E[max SR] (per period) of n_trials independent null strategies observed n_obs periods:
    under SR = 0 the estimator variance is ~ 1/(n_obs - 1), whatever the kurtosis."""
    if n_trials < 2 or n_obs < 3:
        return 0.0
    a = (1 - EULER_GAMMA) * N01.inv_cdf(1 - 1.0 / n_trials)
    b = EULER_GAMMA * N01.inv_cdf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(1.0 / (n_obs - 1)) * (a + b)


def dsr_null(r: np.ndarray, n_trials: int) -> float:
    """DSR with the analytic null variance (robust to cost-dominated trials)."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    return psr(r, expected_max_sr_null(len(r), n_trials))


def dsr(r: np.ndarray, trial_srs_per_period: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio: PSR against the expected max SR of n_trials null trials."""
    return psr(r, expected_max_sr(trial_srs_per_period, n_trials))


def stationary_bootstrap_idx(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis & Romano (1994) stationary bootstrap indices."""
    p = 1.0 / mean_block
    jumps = rng.random(n) < p
    jumps[0] = True
    starts = rng.integers(0, n, size=n)
    t = np.arange(n)
    block_first_t = np.flatnonzero(jumps)          # time index where each block starts
    block_id = np.cumsum(jumps) - 1
    offset = t - block_first_t[block_id]
    return (starts[block_first_t][block_id] + offset) % n


def bootstrap_ci(r: np.ndarray, fn, n_boot: int = 2000, mean_block: float = 20.0,
                 seed: int = 20261126, level: float = 0.95) -> tuple[float, float, np.ndarray]:
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        vals[b] = fn(r[stationary_bootstrap_idx(len(r), mean_block, rng)])
    lo, hi = np.nanquantile(vals, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi), vals


def alpha_beta(y: np.ndarray, x: np.ndarray, ppy: float = 365.0) -> dict:
    """OLS y = a + b x ; returns annualised alpha, beta and naive t-stat of alpha."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    m = np.isfinite(y) & np.isfinite(x)
    y, x = y[m], x[m]
    X = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    s2 = resid @ resid / (len(y) - 2)
    cov = s2 * np.linalg.inv(X.T @ X)
    return {"alpha_ann": float(coef[0] * ppy), "beta": float(coef[1]),
            "t_alpha": float(coef[0] / math.sqrt(cov[0, 0]))}


def holm(pvals: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj.tolist()


def summarize(r: np.ndarray, ppy: float = 365.0) -> dict:
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    g3, g4 = moments(r) if len(r) > 2 else (float("nan"), float("nan"))
    return {
        "n": int(len(r)),
        "ann_return": ann_return(r, ppy),
        "ann_vol": ann_vol(r, ppy) if len(r) > 1 else float("nan"),
        "sharpe": sharpe(r, ppy),
        "max_dd": max_drawdown(r),
        "cvar95": cvar(r) if len(r) else float("nan"),
        "skew": g3,
        "kurt": g4,
        "psr0": psr(r) if len(r) > 2 else float("nan"),
    }
