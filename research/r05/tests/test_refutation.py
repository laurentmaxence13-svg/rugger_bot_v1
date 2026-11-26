"""Unit tests for the refutation battery code (no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from experiments.r2_r1_refutation import placebo_positions, runs
from experiments.r3_lp_refutation import COSTS, simulate_hedged_lp


def _market(prices, funding=0.0):
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="h", tz="UTC")
    p = pd.Series(prices, index=idx, dtype=float)
    return idx, p, p.copy(), p.copy(), pd.Series(funding, index=idx)


def test_placebo_preserves_exposure_and_trades():
    rng = np.random.default_rng(0)
    held = np.array([0, 0, 1, 1, 1, 0, 1, 0, 0, 0, 1, 1], float)
    for _ in range(50):
        h = placebo_positions(held, rng)
        assert len(h) == len(held) and h.sum() == held.sum()
        assert len(runs(h)) == len(runs(held)) and h[0] == held[0]


def test_hedged_lp_flat_price_no_fee_loses_only_costs():
    idx, s, p, hi, f = _market(np.full(72, 100.0))
    sim = simulate_hedged_lp(idx, s, p, hi, f, pd.Series(0.0, index=idx.floor("D").unique()))
    c = sim["components_per_capital"]
    assert c["lp_price"] == pytest.approx(0.0) and c["hedge_price"] == pytest.approx(0.0)
    K = 1 + 1 / 6
    expected = (0.5 * COSTS["swap"] * 2 + 0.5 / 100 * 100 * COSTS["perp"] * 2) / K
    assert sim["final_wealth_per_capital"] == pytest.approx(1 - expected, rel=1e-6)


def test_hedged_lp_collects_fees_at_flat_price():
    idx, s, p, hi, f = _market(np.full(48, 100.0))
    days = idx.floor("D").unique()
    sim = simulate_hedged_lp(idx, s, p, hi, f, pd.Series(0.001, index=days), cost_mult=0.0)
    # 48 hourly closes = 47 accrual intervals at 0.1 %/day on the LP value (1/K of capital)
    expected = ((1.001 ** (1 / 24)) ** 47 - 1) / (1 + 1 / 6)
    assert sim["final_wealth_per_capital"] - 1 == pytest.approx(expected, rel=0.01)


def test_hedged_lp_pays_lvr_on_oscillating_price():
    prices = np.tile([100.0, 110.0], 60)
    idx, s, p, hi, f = _market(prices)
    sim = simulate_hedged_lp(idx, s, p, hi, f, pd.Series(0.0, index=idx.floor("D").unique()), cost_mult=0.0)
    c = sim["components_per_capital"]
    assert c["lp_price"] + c["hedge_price"] < 0  # short gamma: hedged LP loses on round trips


def test_short_hedge_receives_positive_funding():
    idx, s, p, hi, f = _market(np.full(48, 100.0), funding=0.0001)
    sim = simulate_hedged_lp(idx, s, p, hi, f, pd.Series(0.0, index=idx.floor("D").unique()), cost_mult=0.0)
    assert sim["components_per_capital"]["funding"] > 0


def test_hl_markouts_detect_adverse_selection():
    from experiments.r4_hl_markouts import analyse
    # mid rises 1 bp every 5 s; buyers lift the ask -> our sells lose, sellers hit the bid -> our buys win
    books, trades = [], {}
    for k in range(200):
        t = k * 5000
        mid = 100.0 * (1 + 1e-4 * k)
        books.append((t, mid - 0.01, mid + 0.01))
        if k < 190:
            trades[2 * k] = (t + 1000, mid + 0.02, 1.0, "B")   # through the ask
    res = analyse(books, trades)
    assert res["h10s_pes"]["n"] > 100
    assert res["h10s_pes"]["mean_bps"] < 0  # selling into a rising market
    assert res["reopen"] is False
