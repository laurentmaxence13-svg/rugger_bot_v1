"""Unit tests for the R05 core (no network)."""
from __future__ import annotations

import io
import math
import zipfile

import numpy as np
import pandas as pd
import pytest

from r05lab import backtest, lp, micro, signals, stats
from r05lab.data import _to_utc, read_klines_zip, read_funding_zip


# ---------------------------------------------------------------- backtest timing & costs
def _idx(n, freq="D"):
    return pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")


def test_position_earns_next_bar_return_only():
    idx = _idx(5)
    ret = pd.Series([0.0, 0.10, -0.20, 0.05, 0.0], index=idx)
    pos = pd.Series([0, 1, 0, 0, 0], index=idx, dtype=float)  # decided at close of bar 1
    bt = backtest.run(pos, ret, cost_per_side=0.0)
    # held over bar 2 only -> earns -0.20, never the +0.10 of the decision bar
    assert bt["net"].tolist() == pytest.approx([0, 0, -0.20, 0, 0])


def test_round_trip_costs_two_sides():
    idx = _idx(6)
    ret = pd.Series(0.0, index=idx)
    pos = pd.Series([0, 1, 1, 0, 0, 0], index=idx, dtype=float)
    bt = backtest.run(pos, ret, cost_per_side=0.001)
    assert bt["cost"].sum() == pytest.approx(0.002)
    flip = pd.Series([0, 1, -1, 0, 0, 0], index=idx, dtype=float)
    assert backtest.run(flip, ret, 0.001)["cost"].sum() == pytest.approx(0.004)


def test_long_pays_positive_funding():
    idx = _idx(4)
    ret = pd.Series(0.0, index=idx)
    fund = pd.Series([0.0, 0.0, 0.0001, 0.0001], index=idx)
    bt = backtest.run(pd.Series([1, 1, 1, 1.0], index=idx), ret, 0.0, funding=fund)
    assert bt["net"].sum() == pytest.approx(-0.0002)
    bt_s = backtest.run(pd.Series([-1, -1, -1, -1.0], index=idx), ret, 0.0, funding=fund)
    assert bt_s["net"].sum() == pytest.approx(0.0002)


def test_trades_and_daily_compounding():
    idx = _idx(48, "h")
    ret = pd.Series(0.01, index=idx)
    pos = pd.Series(0.0, index=idx)
    pos.iloc[2:5] = 1.0
    bt = backtest.run(pos, ret, 0.0)
    tr = backtest.trades(bt)
    assert len(tr) == 1 and tr["bars"].iloc[0] == 3
    assert tr["net"].iloc[0] == pytest.approx(1.01 ** 3 - 1)
    d = backtest.to_daily(bt)
    assert len(d) == 2 and d.iloc[0] == pytest.approx(1.01 ** 3 - 1)


# ---------------------------------------------------------------- no look-ahead in signals
@pytest.fixture(scope="module")
def market():
    rng = np.random.default_rng(1)
    n = 3000
    idx = _idx(n, "h")
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    vol = pd.Series(rng.uniform(10, 20, n), index=idx)
    tb = vol * rng.uniform(0.3, 0.7, n)
    return close, high, low, vol, tb


@pytest.mark.parametrize("long_only", [True, False])
def test_signals_are_causal(market, long_only):
    close, high, low, vol, tb = market
    cut = 2200
    fns = {
        "tsmom": lambda c, h, l, v, b: signals.tsmom(c, 90, long_only),
        "donchian": lambda c, h, l, v, b: signals.donchian(h, l, c, 55, long_only),
        "mr": lambda c, h, l, v, b: signals.mean_reversion(c, 12, long_only),
        "flow": lambda c, h, l, v, b: signals.flow_imbalance(v, b, 4, long_only),
    }
    for name, f in fns.items():
        full = f(close, high, low, vol, tb)
        trunc = f(close.iloc[:cut], high.iloc[:cut], low.iloc[:cut], vol.iloc[:cut], tb.iloc[:cut])
        assert np.allclose(full.iloc[:cut].to_numpy(), trunc.to_numpy(), equal_nan=True), name
        if long_only:
            assert (full >= 0).all(), name


def test_signal_cannot_see_future_shock(market):
    """A +50% jump at bar k must not change any position decided before k."""
    close, high, low, vol, tb = market
    k = 2500
    c2 = close.copy()
    c2.iloc[k:] *= 1.5
    for f in (lambda c: signals.tsmom(c, 30, False), lambda c: signals.mean_reversion(c, 4, False)):
        assert np.allclose(f(close).iloc[:k], f(c2).iloc[:k])


# ---------------------------------------------------------------- statistics
def test_sharpe_drawdown_cvar():
    r = np.array([0.01, -0.02, 0.03, -0.01])
    assert stats.sharpe(r, 1) == pytest.approx(r.mean() / r.std(ddof=1))
    assert stats.max_drawdown(np.array([0.10, -0.50, 0.20])) == pytest.approx(0.5)
    assert stats.cvar(np.arange(-10, 10) / 100.0, 0.10) == pytest.approx(-0.095)


def test_psr_and_dsr_behave():
    rng = np.random.default_rng(0)
    good = rng.normal(0.002, 0.01, 1000)
    null = rng.normal(0.0, 0.01, 1000)
    assert stats.psr(good) > 0.99
    assert 0.0 < stats.psr(null) < 1.0
    trials = rng.normal(0, 0.03, 50)
    assert stats.dsr(good, trials, 50) < stats.psr(good)


def test_holm_known_values():
    assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_stationary_bootstrap_blocks():
    rng = np.random.default_rng(3)
    idx = stats.stationary_bootstrap_idx(1000, 20.0, rng)
    assert idx.min() >= 0 and idx.max() < 1000
    cont = np.mean(np.diff(idx) % 1000 == 1)
    assert 0.9 < cont < 0.99  # ~1 - 1/20 consecutive


def test_alpha_beta_recovers_coefficients():
    rng = np.random.default_rng(4)
    x = rng.normal(0, 0.02, 5000)
    y = 0.001 + 0.5 * x + rng.normal(0, 0.001, 5000)
    ab = stats.alpha_beta(y, x, ppy=1)
    assert ab["beta"] == pytest.approx(0.5, abs=0.01)
    assert ab["alpha_ann"] == pytest.approx(0.001, abs=1e-4)


# ---------------------------------------------------------------- LP
def test_cpmm_identities():
    assert lp.cpmm_lp_over_hodl(1.0) == pytest.approx(1.0)
    assert lp.cpmm_lp_over_hodl(4.0) == pytest.approx(0.8)
    assert lp.breakeven_rotation(0.04, 0.0021) == pytest.approx(0.0016 / 0.0168)


def test_lvr_matches_discrete_rebalancing_simulation():
    """CPMM value minus the self-financing delta-rebalanced portfolio drifts at sigma^2/8."""
    rng = np.random.default_rng(7)
    sigma, steps, paths, T = 0.05, 2000, 4000, 1.0
    dt = T / steps
    z = rng.normal(0, 1, (paths, steps))
    logp = np.cumsum(-0.5 * sigma**2 * dt + sigma * math.sqrt(dt) * z, axis=1)
    P = np.exp(np.concatenate([np.zeros((paths, 1)), logp], axis=1))
    # CPMM with k=1: x = 1/sqrt(P) risky units, value V = 2 sqrt(P)
    V = 2 * np.sqrt(P)
    x = 1 / np.sqrt(P)
    rebal_pnl = np.sum(x[:, :-1] * np.diff(P, axis=1), axis=1)  # hold LP's risky amount each step
    lvr = (V[:, 0] + rebal_pnl) - V[:, -1]
    expected = np.mean(np.sum((sigma**2 / 8) * V[:, :-1] * dt, axis=1))
    assert np.mean(lvr) == pytest.approx(expected, rel=0.08)


# ---------------------------------------------------------------- microstructure
def test_markouts_adverse_selection_sign():
    # price trends up 1 bp per trade; sells hit our bid then price rises (good for buys),
    # buys lift our ask then price rises (bad for sells).
    n = 2000
    t = np.arange(n) * 500
    p = 100 * (1 + 1e-4 * np.arange(n))
    sell = np.arange(n) % 2 == 0
    df = pd.DataFrame({"t_ms": t, "price": p, "qty": 1.0, "is_buyer_maker": sell})
    m = micro.markouts(df, horizons_s=(10,))
    assert m["n_trades"] == n
    assert abs(m["h10s"]["opt_mean_bps"]) < 1.0  # buys win ~ what sells lose


def test_quote_proxy_ffill():
    p = np.array([10.0, 10.2, 10.1, 10.3])
    sell = np.array([True, False, True, False])
    bid, ask, mid = micro.quote_proxy(p, sell)
    assert bid.tolist()[2] == 10.1 and ask.tolist()[3] == 10.3
    assert mid[3] == pytest.approx((10.1 + 10.3) / 2)


# ---------------------------------------------------------------- data parsing
def _zip(name, text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def test_timestamp_units_ms_and_us():
    ms = pd.Series([1704067200000])
    us = pd.Series([1735689600000000])
    assert str(_to_utc(ms)[0]) == "2024-01-01 00:00:00+00:00"
    assert str(_to_utc(us)[0]) == "2025-01-01 00:00:00+00:00"


def test_read_klines_with_and_without_header(tmp_path):
    row = "1704067200000,1,2,0.5,1.5,10,1704070799999,15,5,6,9,0\n"
    hdr = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,"
           "taker_buy_volume,taker_buy_quote_volume,ignore\n")
    for i, txt in enumerate([row, hdr + row]):
        p = tmp_path / f"k{i}.zip"
        p.write_bytes(_zip("k.csv", txt))
        df = read_klines_zip(p)
        assert df["close"].iloc[0] == 1.5 and df["taker_buy_base"].iloc[0] == 6


def test_read_funding(tmp_path):
    p = tmp_path / "f.zip"
    p.write_bytes(_zip("f.csv", "calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.0001\n"))
    df = read_funding_zip(p)
    assert df["rate"].iloc[0] == 0.0001


def test_dsr_null_threshold_grows_with_trials():
    assert stats.expected_max_sr_null(1000, 1) == 0.0
    a, b = stats.expected_max_sr_null(1000, 10), stats.expected_max_sr_null(1000, 100)
    assert 0 < a < b
    rng = np.random.default_rng(5)
    r = rng.normal(0.003, 0.01, 1000)
    assert stats.dsr_null(r, 100) < stats.dsr_null(r, 2) <= stats.psr(r)
