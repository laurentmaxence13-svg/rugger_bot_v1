"""Liquidity-provision economics.

References: Milionis, Moallemi, Roughgarden, Zhang (2022) "Automated Market Making and
Loss-Versus-Rebalancing"; standard constant-product identities.
"""
from __future__ import annotations

import math

import numpy as np


def cpmm_lp_over_hodl(k: float) -> float:
    """Value of a 50/50 constant-product LP position / value of holding the initial tokens,
    when the price ratio moves by factor k (fees excluded). Impermanent loss = 1 - this."""
    return 2.0 * math.sqrt(k) / (1.0 + k)


def lvr_rate_cpmm(sigma: float) -> float:
    """Instantaneous LVR per unit of pool value for a full-range CPMM under GBM:
    sigma^2 / 8 per unit of time in which sigma is expressed."""
    return sigma * sigma / 8.0


def breakeven_rotation(sigma: float, lp_fee: float) -> float:
    """Daily volume / TVL at which LP fees equal LVR (full range CPMM).
    fees/V = rotation * lp_fee ; LVR/V = sigma^2/8  =>  rotation* = sigma^2 / (8 lp_fee)."""
    return sigma * sigma / (8.0 * lp_fee)


def hedged_edge(fee_yield: float, sigma: float) -> float:
    """Fee yield minus LVR, same time unit (e.g. per day)."""
    return fee_yield - lvr_rate_cpmm(sigma)


def simulate_cpmm_vs_hodl(prices: np.ndarray, fee_yield_per_step: np.ndarray) -> dict:
    """Unhedged full-range LP on a price path vs holding the initial 50/50 basket.
    Fees are reinvested pro rata (approximation: fee yield applied to current LP value)."""
    p0 = prices[0]
    lp_rel = np.array([cpmm_lp_over_hodl(p / p0) for p in prices])  # ex-fee LP/HODL
    hodl = 0.5 + 0.5 * prices / p0                                  # HODL value, start = 1
    fee_growth = np.cumprod(1.0 + np.concatenate([[0.0], fee_yield_per_step[1:]]))
    lp = lp_rel * hodl * fee_growth
    return {"lp_final": float(lp[-1]), "hodl_final": float(hodl[-1]),
            "lp_minus_hodl": float(lp[-1] - hodl[-1]), "il_ex_fee": float(1.0 - lp_rel[-1])}
