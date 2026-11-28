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
    # Self-sufficient in a fresh clone (data/ is not versioned): fetch the two DefiLlama series
    # when asked to refresh or when the cache is missing.
    from r05lab.data import DATA_DIR
    m = Manifest("prospective")
    for pid, name in (("12edc6f3-4926-4b4f-b97c-38ef6a458574", "raydium_amm_v4_sol_usdc_025"),
                      ("aa70268e-4b52-42bf-a116-608b370f9501", "aave_v3_usdc_eth")):
        cache = f"llama_chart_{name}_{r3.TAG}.json"
        if refresh_llama or not (DATA_DIR / "json" / cache).exists():
            json_get(f"https://yields.llama.fi/chart/{pid}", m, cache, refresh=True)
    m.save()
    f_dl = llama(r3.LLAMA_SOLUSDC)["apyBase"] * r3.LP_SHARE / 100 / 365
    rf = rf_daily()
    out = {}
    years = (idx[-1] - idx[0]).total_seconds() / (365 * 86400)
    # v1.1 (amendment of 2026-11-26, before the window): primary = band rule, fixed 2 USD per transfer
    for name, kw in {"primary_band_0.5_2.0": {"band": (0.5, 2.0)},
                     "band_costs_x2": {"band": (0.5, 2.0), "cost_mult": 2.0},
                     "secondary_daily_transfers": {}}.items():
        sim = r3.simulate_hedged_lp(idx, spot, perp, hi, fund, f_dl, **kw)
        ex = r3.excess_stats(sim["ret"], rf, start, end)
        fixed = 2.0 * (2.0 if "x2" in name else 1.0)
        out[name] = {"window": ex, "components_per_capital": sim["components_per_capital"],
                     "liquidation_hours": sim["liquidation_hours"], "capital_transfers": sim["capital_transfers"],
                     "excess_after_fixed_costs": {str(c): ex["ann_excess"] - sim["capital_transfers"] * fixed / c / years
                                                  for c in (1_100, 10_000)}}
    lr = np.log(spot).diff()
    rv = (lr ** 2).groupby(lr.index.floor("D")).sum()
    fee = f_dl.reindex(rv.index).fillna(0.0)
    out["fee_over_lvr"] = float(fee.sum() / (rv.sum() / 8))
    out["max_consecutive_days_fee_below_lvr_plus_2pct"] = int(
        (fee < rv / 8 + 0.02 / 365).astype(int).groupby((fee >= rv / 8 + 0.02 / 365).cumsum()).sum().max())
    return out


PAPER1B = [  # (label, DefiLlama pool, LP share, hedge asset, fixed cost per LP op, per transfer) — frozen v1.2
    ("raydium_sol_usdt", "cdd04383-21ea-45d1-94d6-295e58100559", 0.88, "SOL", 0.1, 2.0),
    ("base_univ2_weth_usdc_OBSERVATION", "dfe517bb-4beb-45ae-b847-5d4067fc7ef9", 1.0, "ETH", 0.5, 2.0),
    ("ethereum_univ2_usdc_weth_CONTROL", "702fff16-4bfa-4c1f-8c02-e0ea0f5ecde6", 1.0, "ETH", 10.0, 5.0),
]


def paper1b_lp(start: str, end: str) -> dict:
    if pd.Timestamp(start) > pd.Timestamp(end):
        return {"status": "fenêtre PAPER-1b pas encore commencée"}
    mb, mj = Manifest("binance"), Manifest("prospective")
    ms = month_range(pd.Timestamp(start).strftime("%Y-%m"), pd.Timestamp(end).strftime("%Y-%m"))
    idx = pd.date_range(f"{start} 00:00", f"{end} 23:00", freq="h", tz="UTC")
    rf = rf_daily()
    years = (idx[-1] - idx[0]).total_seconds() / (365 * 86400)
    out = {}
    for label, pid, share, asset, lp_op, tr in PAPER1B:
        d = json_get(f"https://yields.llama.fi/chart/{pid}", mj, f"llama_chart_p1b_{pid}_{r3.TAG}.json", refresh=True)["data"]
        dl = pd.DataFrame(d)
        dl.index = pd.to_datetime(dl["timestamp"]).dt.floor("D")
        dl = dl[~dl.index.duplicated(keep="last")]
        fee = dl["apyBase"].astype(float).fillna(0.0) * share / 100 / 365
        sym = f"{asset}USDT"
        sp = load_klines("spot", sym, "1h", ms, mb)["close"].reindex(idx).ffill()
        pk = load_klines("futures/um", sym, "1h", ms, mb)
        pp, hi = pk["close"].reindex(idx).ffill(), pk["high"].reindex(idx).ffill()
        fu = load_funding(sym, ms, mb)["rate"]
        fu = fu.groupby(fu.index.floor("h")).sum().reindex(idx).fillna(0.0)
        sim = r3.simulate_hedged_lp(idx, sp, pp, hi, fu, fee, band=(0.5, 2.0))
        ex = r3.excess_stats(sim["ret"], rf, start, end)
        n_tr = sim["capital_transfers"]
        out[label] = {"window": ex, "transfers": n_tr, "liquidation_hours": sim["liquidation_hours"],
                      "excess_after_fixed_10000": ex["ann_excess"] - ((2 + n_tr) * lp_op + n_tr * tr) / 10_000 / years}
    mj.save()
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
           "PAPER1_lp_hedged": paper1_lp(a.start, a.end, a.refresh_llama),
           "PAPER1B_lp_hedged": paper1b_lp(max(a.start, "2026-11-29"), a.end),
           "PAPER2_f1_OBSERVATION": paper2_f1(a.start, a.end)}
    (RESULTS_DIR / f"PROSPECTIVE_{a.label}_{a.start}_{a.end}.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main()
