"""R3.6 (post hoc robustness, descriptive): PAPER-1 hedged on Hyperliquid instead of Binance.

Daily simulation (exact for daily rebalancing: a CPMM LP value depends only on the current price,
the hedge P&L is linear between rebalances). LP valued at the Binance SOLUSDT daily close; hedge
on the Hyperliquid SOL perp daily close with real hourly HL funding summed per day; liquidation
check on the HL daily high. A Binance-hedged daily run is the control for the discretisation.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from experiments.r3_lp_refutation import END, LLAMA_SOLUSDC, LP_SHARE, START, excess_stats, simulate_hedged_lp
from experiments.s1_carry import hl_series, rf_daily
from experiments.s3_lp import llama
from r05lab.data import RESULTS_DIR, Manifest, load_funding, load_klines, month_range


def main():
    m = Manifest("binance")
    ms = month_range("2025-01", "2026-10")
    days = pd.date_range(START, END, freq="D", tz="UTC")
    spot = load_klines("spot", "SOLUSDT", "1h", ms, m)["close"].resample("1D").last().reindex(days).ffill()
    bp = load_klines("futures/um", "SOLUSDT", "1h", ms, m)
    b_close = bp["close"].resample("1D").last().reindex(days).ffill()
    b_hi = bp["high"].resample("1D").max().reindex(days).ffill()
    bf = load_funding("SOLUSDT", ms, m)["rate"]
    b_fund = bf.groupby(bf.index.floor("D")).sum().reindex(days).fillna(0.0)
    hl_d, _, hl_close = hl_series("SOL")
    import json as _j
    from r05lab.data import DATA_DIR
    c = _j.loads((DATA_DIR / "json" / "hl_candles_1d_SOL_20261126.json").read_text())
    hl_hi = pd.Series({pd.Timestamp(r["t"], unit="ms", tz="UTC").floor("D"): float(r["h"]) for r in c}).sort_index()
    h_close = hl_close.reindex(days).ffill()
    h_hi = hl_hi.reindex(days).ffill()
    h_fund = hl_d.reindex(days).fillna(0.0)
    f = llama(LLAMA_SOLUSDC)["apyBase"] * LP_SHARE / 100 / 365
    f_step = (1 + f) ** 24 - 1  # simulate_hedged_lp spreads a daily yield over 24 steps; here 1 step = 1 day
    rf = rf_daily()
    out = {"note": "post hoc, descriptif ; non éliminatoire", "window": [START, END]}
    for venue, pc, ph, fu in (("binance_daily_control", b_close, b_hi, b_fund), ("hyperliquid", h_close, h_hi, h_fund)):
        sim = simulate_hedged_lp(days, spot, pc, ph, fu, f_step, rebal_h=1, band=(0.5, 2.0))
        ex = excess_stats(sim["ret"], rf, START, END)
        out[venue] = {"ann_excess": ex["ann_excess"], "ci_monthly": ex["monthly_excess_ci95"], "max_dd": ex["max_dd"],
                      "liquidation_days": sim["liquidation_hours"], "transfers": sim["capital_transfers"],
                      "funding_per_capital": sim["components_per_capital"]["funding"],
                      "hedge_price_per_capital": sim["components_per_capital"]["hedge_price"],
                      "funding_ann_rate_mean": float(fu.mean() * 365)}
    basis = (h_close / spot - 1).dropna()
    out["hl_perp_vs_binance_spot_basis_bp"] = {"mean": float(basis.mean() * 1e4), "std": float(basis.std() * 1e4),
                                                "min": float(basis.min() * 1e4), "max": float(basis.max() * 1e4)}
    (RESULTS_DIR / "R3_hedge_venue.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
