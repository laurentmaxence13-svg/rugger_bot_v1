"""H3d — cross-chain replication of the hedged-LP mechanism (R05_PREREGISTRATION_v3).
Daily edge = DefiLlama fee yield x LP share - RV/8 (hourly Binance realised variance)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from r05lab import stats
from r05lab.data import RESULTS_DIR, Manifest, json_get, load_klines, month_range

TAG = "20261128"
POOLS = [
    ("Ethereum", "uniswap-v2", "USDC-WETH", "702fff16-4bfa-4c1f-8c02-e0ea0f5ecde6", 1.0, "ETH"),
    ("Ethereum", "uniswap-v2", "WETH-USDT", "196aa543-1881-4515-9928-577693d4fa72", 1.0, "ETH"),
    ("Ethereum", "sushiswap", "WETH-USDT", "b1ff3e89-14a0-42a1-b760-716304387201", 0.25 / 0.30, "ETH"),
    ("Ethereum", "pancakeswap-amm", "WETH-USDT", "d77a4965-de74-48d4-afc5-1a73e3ce9d65", 0.17 / 0.25, "ETH"),
    ("Base", "uniswap-v2", "WETH-USDC", "dfe517bb-4beb-45ae-b847-5d4067fc7ef9", 1.0, "ETH"),
    ("BSC", "pancakeswap-amm", "USDT-WBNB", "a3878e88-0c9f-49ef-adbc-da5fe048192d", 0.17 / 0.25, "BNB"),
    ("Polygon", "quickswap-dex", "WMATIC-USDC", "81a51af8-4a0e-409b-9688-264323afc1fe", 0.25 / 0.30, "MATIC"),
    ("Solana", "raydium-amm", "WSOL-USDC", "12edc6f3-4926-4b4f-b97c-38ef6a458574", 0.88, "SOL"),
    ("Solana", "raydium-amm", "WSOL-USDT", "cdd04383-21ea-45d1-94d6-295e58100559", 0.88, "SOL"),
]
A, B = "2023-01-01", "2026-10-31"
SEED = 20261126


def rv_daily(sym: str, m: Manifest) -> pd.Series:
    h = load_klines("spot", sym, "1h", month_range("2023-01", "2026-10"), m)
    lr = np.log(h["close"]).diff()
    return (lr ** 2).groupby(lr.index.floor("D")).sum()


def main():
    mb, mj = Manifest("binance"), Manifest("public_json")
    rv = {"ETH": rv_daily("ETHUSDT", mb), "BNB": rv_daily("BNBUSDT", mb), "SOL": rv_daily("SOLUSDT", mb)}
    mat, pol = rv_daily("MATICUSDT", mb), rv_daily("POLUSDT", mb)
    rv["MATIC"] = pd.concat([mat, pol[pol.index > mat.index.max()]]).sort_index()
    rows = []
    for chain, proj, pair, pid, share, asset in POOLS:
        d = json_get(f"https://yields.llama.fi/chart/{pid}", mj, f"llama_chart_h3d_{pid}_{TAG}.json")["data"]
        df = pd.DataFrame(d)
        df.index = pd.to_datetime(df["timestamp"]).dt.floor("D")
        df = df[~df.index.duplicated(keep="last")]
        idx = df.index.intersection(rv[asset].index)
        idx = idx[(idx >= pd.Timestamp(A, tz="UTC")) & (idx <= pd.Timestamp(B, tz="UTC"))]
        rec = {"chain": chain, "project": proj, "pair": pair, "pool": pid, "lp_share": share, "days": int(len(idx))}
        if len(idx) < 180:
            rec["status"] = "historique < 180 j"
            rows.append(rec)
            continue
        fee_up = df.loc[idx, "apyBase"].astype(float).fillna(0.0) / 100 / 365
        lvr = rv[asset].reindex(idx) / 8
        for lab, f in (("lp_share", fee_up * share), ("upper_bound", fee_up)):
            e = (f - lvr).to_numpy()
            lo, hi, _ = stats.bootstrap_ci(e, np.mean, seed=SEED)
            rec[lab] = {"fee_ann": float(f.mean() * 365), "lvr_ann": float(lvr.mean() * 365),
                        "edge_ann": float(e.mean() * 365), "ci95_ann": [lo * 365, hi * 365],
                        "share_days_pos": float((e > 0).mean())}
        rec.update({"status": "ok", "first": str(idx[0].date()), "tvl_median_musd": float(df.loc[idx, "tvlUsd"].median() / 1e6),
                    "rotation_per_day_median": float((fee_up / (0.003 if proj != "raydium-amm" and proj != "pancakeswap-amm" else 0.0025)).median())})
        rows.append(rec)
    mj.save()
    ok = [r for r in rows if r["status"] == "ok"]
    n_pos = sum(r["lp_share"]["ci95_ann"][0] > 0 for r in ok)
    n_pos_ub = sum(r["upper_bound"]["ci95_ann"][0] > 0 for r in ok)
    verdict = "GENERAL" if n_pos >= 5 else ("SPECIFIQUE" if n_pos <= 2 else "MIXTE")
    res = {"protocol": "R05_PREREGISTRATION_v3 §H3d", "window": [A, B], "evaluated": len(ok),
           "n_ci_positive_lp_share": n_pos, "n_ci_positive_upper_bound": n_pos_ub, "verdict": verdict, "pools": rows}
    (RESULTS_DIR / "H3d_replication.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "pools"}, indent=1))
    for r in rows:
        if r["status"] != "ok":
            print(r["chain"], r["pair"], r["status"], r["days"])
            continue
        x = r["lp_share"]
        print(f"{r['chain']:9s} {r['project']:16s} {r['pair']:12s} {r['first']} {r['days']:4d}j TVL {r['tvl_median_musd']:.2f}M "
              f"frais {x['fee_ann']*100:6.1f}% LVR {x['lvr_ann']*100:5.1f}% avantage {x['edge_ann']*100:6.1f}% "
              f"IC [{x['ci95_ann'][0]*100:6.1f};{x['ci95_ann'][1]*100:6.1f}] borne haute {r['upper_bound']['edge_ann']*100:6.1f}%")


if __name__ == "__main__":
    main()
