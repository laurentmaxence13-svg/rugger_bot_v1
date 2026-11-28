"""H3d-net (R05_PREREGISTRATION_v3 addendum v3.1): full hedged-LP simulation, PAPER-1 v1.1 rules,
on the 9 H3d pools, with chain-specific fixed costs (hypotheses)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from experiments.h3d_replication import POOLS, TAG
from experiments.r3_lp_refutation import excess_stats, simulate_hedged_lp
from experiments.s1_carry import rf_daily
from r05lab.data import DATA_DIR, RESULTS_DIR, Manifest, fetch_many, load_funding, load_klines, month_range

END = "2026-10-31"
FIXED = {"Ethereum": (10.0, 5.0), "Base": (0.5, 2.0), "BSC": (0.5, 2.0), "Polygon": (0.5, 2.0), "Solana": (0.1, 2.0)}
CAPITALS = (10_000, 1_100)
MS = month_range("2023-01", "2026-10")


def series(asset: str, m: Manifest):
    if asset == "MATIC":
        parts = [(s, load_klines("spot", f"{s}USDT", "1h", MS, m), load_klines("futures/um", f"{s}USDT", "1h", MS, m),
                  load_funding(f"{s}USDT", MS, m)["rate"]) for s in ("MATIC", "POL")]
        cut_s = parts[0][1].index.max()
        cut_p = parts[0][2].index.max()
        spot = pd.concat([parts[0][1], parts[1][1][parts[1][1].index > cut_s]])
        perp = pd.concat([parts[0][2], parts[1][2][parts[1][2].index > cut_p]])
        fund = pd.concat([parts[0][3], parts[1][3][parts[1][3].index > parts[0][3].index.max()]])
        return spot, perp, fund
    s = f"{asset}USDT"
    return (load_klines("spot", s, "1h", MS, m), load_klines("futures/um", s, "1h", MS, m),
            load_funding(s, MS, m)["rate"])


def main():
    m = Manifest("binance")
    rels = []
    for s in ("BNBUSDT", "MATICUSDT", "POLUSDT"):
        rels += [f"futures/um/monthly/klines/{s}/1h/{s}-1h-{mo}.zip" for mo in MS]
        rels += [f"futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{mo}.zip" for mo in MS]
    fetch_many(rels, m)
    rf = rf_daily()
    rows = []
    for chain, proj, pair, pid, share, asset in POOLS:
        d = json.loads((DATA_DIR / "json" / f"llama_chart_h3d_{pid}_{TAG}.json").read_text())["data"]
        dl = pd.DataFrame(d)
        dl.index = pd.to_datetime(dl["timestamp"]).dt.floor("D")
        dl = dl[~dl.index.duplicated(keep="last")]
        fee = dl["apyBase"].astype(float).fillna(0.0) * share / 100 / 365
        start = max(pd.Timestamp("2023-01-02", tz="UTC"), fee.index[0])
        spot, perp, fund = series(asset, m)
        idx = pd.date_range(start.tz_convert("UTC").tz_localize(None), f"{END} 23:00", freq="h", tz="UTC")
        sp = spot["close"].reindex(idx).ffill().bfill()
        pp = perp["close"].reindex(idx).ffill().bfill()
        hi = perp["high"].reindex(idx).fillna(pp)
        fu = fund.groupby(fund.index.floor("h")).sum().reindex(idx).fillna(0.0)
        a0 = str(idx[0].date())
        rec = {"chain": chain, "project": proj, "pair": pair, "start": a0}
        for lab, cm in (("base", 1.0), ("costs_x2", 2.0)):
            sim = simulate_hedged_lp(idx, sp, pp, hi, fu, fee, band=(0.5, 2.0), cost_mult=cm)
            ex = excess_stats(sim["ret"], rf, a0, END)
            years = (idx[-1] - idx[0]).total_seconds() / (365 * 86400)
            lp_op, tr = FIXED[chain]
            n_ops, n_tr = 2 + sim["capital_transfers"], sim["capital_transfers"]
            rec[lab] = {"excess_before_fixed": ex["ann_excess"], "ci_monthly": ex["monthly_excess_ci95"],
                        "max_dd": ex["max_dd"], "rf": ex["rf_ann"], "transfers": n_tr, "liq_hours": sim["liquidation_hours"],
                        "components": sim["components_per_capital"]}
            for cap in CAPITALS:
                fixed_ann = (n_ops * lp_op + n_tr * tr) * cm / cap / years
                rec[lab][f"excess_net_{cap}"] = ex["ann_excess"] - fixed_ann
                rec[lab][f"ci_low_net_{cap}"] = ex["monthly_excess_ci95"][0] * 12 - fixed_ann
        b = rec["base"]
        rec["candidate"] = bool(b["excess_net_10000"] > 0 and b["ci_low_net_10000"] > 0
                                and rec["costs_x2"]["excess_net_10000"] > 0)
        rows.append(rec)
    res = {"protocol": "R05_PREREGISTRATION_v3 addendum v3.1 (H3d-net)", "fixed_costs_hypothesis_usd": FIXED,
           "pools": rows, "candidates": [f"{r['chain']} {r['project']} {r['pair']}" for r in rows if r["candidate"]]}
    (RESULTS_DIR / "H3d_net.json").write_text(json.dumps(res, indent=1, default=str))
    for r in rows:
        b = r["base"]
        print(f"{r['chain']:9s} {r['project']:16s} {r['pair']:12s} depuis {r['start']} excès {b['excess_before_fixed']*100:6.1f}% "
              f"net10k {b['excess_net_10000']*100:6.1f}% (IC bas {b['ci_low_net_10000']*100:6.1f}%) net1.1k {b['excess_net_1100']*100:6.1f}% "
              f"x2 {r['costs_x2']['excess_net_10000']*100:6.1f}% DD {b['max_dd']*100:4.1f}% transf {b['transfers']} liq {b['liq_hours']} "
              f"-> {'CANDIDAT' if r['candidate'] else '-'}")
    print(res["candidates"])


if __name__ == "__main__":
    main()
