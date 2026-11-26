"""Frozen evaluator for the prospective PAPER protocols (docs/R05_PAPER_PROTOCOLS_v1.md).

Applies the frozen rules to any window [start, end] using only public data available
afterwards (Binance archive with checksums, DefiLlama, Aave rate). No live process is needed:
the evaluation is run on the reading dates by a session or by the owner.

    python -m experiments.prospective_eval --start 2026-11-27 --end 2027-02-28

A run on a past window is a plumbing check, never evidence.
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd

from experiments import r3_lp_refutation as r3
from experiments.s1_carry import rf_daily
from experiments.s3_lp import llama
from r05lab import backtest, signals, stats
from r05lab.data import RESULTS_DIR, Manifest, json_get, load_funding, load_klines, month_range

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
F1_COST = 0.0012


def months(start: str, end: str) -> list[str]:
    a = (pd.Timestamp(start) - pd.DateOffset(days=40)).strftime("%Y-%m")
    return month_range(a, pd.Timestamp(end).strftime("%Y-%m"))


def paper1_lp(start: str, end: str, refresh_llama: bool) -> dict:
    mb = Manifest("binance")
    ms = month_range(pd.Timestamp(start).strftime("%Y-%m"), pd.Timestamp(end).strftime("%Y-%m"))
    sp = load_klines("spot", "SOLUSDT", "1h", ms, mb)
    pp = load_klines("futures/um", "SOLUSDT", "1h", ms, mb)
    fu = load_funding("SOLUSDT", ms, mb)["rate"]
    idx = pd.date_range(f"{start} 00:00", f"{end} 23:00", freq="h", tz="UTC")
    spot, perp = sp["close"].reindex(idx).ffill(), pp["close"].reindex(idx).ffill()
    hi = pp["high"].reindex(idx).fillna(perp)
    fund = fu.groupby(fu.index.floor("h")).sum().reindex(idx).fillna(0.0)
    if refresh_llama:
        m = Manifest("prospective")
        json_get("https://yields.llama.fi/chart/12edc6f3-4926-4b4f-b97c-38ef6a458574", m,
                 f"llama_chart_raydium_amm_v4_sol_usdc_025_{r3.TAG}.json", refresh=True)
        m.save()
    f_dl = llama(r3.LLAMA_SOLUSDC)["apyBase"] * r3.LP_SHARE / 100 / 365
    rf = rf_daily()
    out = {}
    for name, kw in {"primary_24h": {}, "costs_x2": {"cost_mult": 2.0}}.items():
        sim = r3.simulate_hedged_lp(idx, spot, perp, hi, fund, f_dl, **kw)
        out[name] = {"window": r3.excess_stats(sim["ret"], rf, start, end),
                     "components_per_capital": sim["components_per_capital"],
                     "liquidation_hours": sim["liquidation_hours"]}
    lr = np.log(spot).diff()
    rv = (lr ** 2).groupby(lr.index.floor("D")).sum()
    fee = f_dl.reindex(rv.index).fillna(0.0)
    out["fee_over_lvr"] = float(fee.sum() / (rv.sum() / 8))
    out["max_consecutive_days_fee_below_lvr_plus_2pct"] = int(
        (fee < rv / 8 + 0.02 / 365).astype(int).groupby((fee >= rv / 8 + 0.02 / 365).cumsum()).sum().max())
    return out


def paper2_f1(start: str, end: str) -> dict:
    mb = Manifest("binance")
    nets, bh = {}, {}
    for s in SYMS:
        h = load_klines("spot", s, "1h", months(start, end), mb)
        d = h["close"].resample("1D").last()
        sig = signals.tsmom(d, 30, True)
        stamp = sig.index + pd.Timedelta(hours=24)  # execution at the close of the 00:00Z bar
        hp = pd.Series(sig.to_numpy(), index=stamp).reindex(h.index).ffill().fillna(0.0)
        bt = backtest.run(hp, h["close"].pct_change(), F1_COST)
        nets[s] = backtest.to_daily(bt).loc[start:end]
        bh[s] = d.pct_change().loc[start:end]
    p = pd.DataFrame(nets).mean(axis=1)
    b = pd.DataFrame(bh).mean(axis=1)
    return {"f1": stats.summarize(p.to_numpy()), "f1_total_return": float(np.prod(1 + p) - 1),
            "bh": stats.summarize(b.dropna().to_numpy()), "bh_total_return": float(np.prod(1 + b.dropna()) - 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--refresh-llama", action="store_true")
    ap.add_argument("--label", default="reading")
    a = ap.parse_args()
    res = {"window": [a.start, a.end], "label": a.label,
           "PAPER1_lp_hedged": paper1_lp(a.start, a.end, a.refresh_llama), "PAPER2_f1": paper2_f1(a.start, a.end)}
    (RESULTS_DIR / f"PROSPECTIVE_{a.label}_{a.start}_{a.end}.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main()
