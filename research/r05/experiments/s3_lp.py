"""S3 — liquidity provision: LP fees vs loss-versus-rebalancing (R05_PREREGISTRATION_v1 §4).

S3-A: cross-section of the top-60 Raydium pools by TVL (public API v3), daily volatility of the
pool price (GeckoTerminal daily OHLCV, price in quote token, last 30 complete days).
S3-B: daily history of SOL-USDC pools (DefiLlama apyBase = fee yield) against the realised
variance of SOLUSDT (Binance 1 h, CHECKSUM-verified): LVR_d = RV_d / 8 for a full-range CPMM.
"""
from __future__ import annotations

import json
import math
import time

import numpy as np
import pandas as pd

from r05lab import lp, stats
from r05lab.data import DATA_DIR, RESULTS_DIR, Manifest, json_get, load_klines, month_range

TAG = "20261126"
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
STABLES = {"USDC", "USDT", "USD1", "PYUSD", "USDS", "USDG", "FDUSD", "USDe", "USDH", "UXD", "EURC"}
SEED = 20261126


def lp_share(pool: dict) -> float:
    if pool["programId"] == AMM_V4:
        return 0.22 / 0.25  # 0.25 % fee, 0.03 % to RAY buyback
    cfg = pool.get("config") or {}
    taken = (cfg.get("protocolFeeRate", 0) + cfg.get("fundFeeRate", 0) + cfg.get("creatorFeeRate", 0)) / 1e6
    return 1.0 - taken


def kind(pool: dict) -> str:
    if pool["type"] == "Concentrated":
        return "CLMM"
    return "AMMv4" if pool["programId"] == AMM_V4 else ("CPMM" if pool["programId"] == CPMM else "Standard-autre")


def fetch_universe(m: Manifest) -> list[dict]:
    pools = []
    for page in (1, 2):
        d = json_get("https://api-v3.raydium.io/pools/info/list", m, f"raydium_list_tvl_p{page}_{TAG}.json",
                     params={"poolType": "all", "poolSortField": "liquidity", "sortType": "desc",
                             "pageSize": "100", "page": str(page)})
        pools += d["data"]["data"]
    pools = [p for p in pools if (p.get("tvl") or 0) >= 50_000]
    return pools[:60]


def sigma_daily(pool_id: str, m: Manifest) -> tuple[float, int]:
    d = json_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_id}/ohlcv/day", m,
                 f"gt_ohlcv_day_{pool_id}_{TAG}.json", params={"aggregate": "1", "limit": "40", "currency": "token"})
    rows = sorted(d["data"]["attributes"]["ohlcv_list"], key=lambda r: r[0])
    today = pd.Timestamp(TAG, tz="UTC").timestamp()
    closes = np.array([r[4] for r in rows if r[0] < today], float)[-31:]
    closes = closes[closes > 0]
    if len(closes) < 21:
        return float("nan"), int(len(closes))
    lr = np.diff(np.log(closes))
    return float(np.std(lr, ddof=1)), int(len(lr))


def run_a() -> dict:
    m = Manifest("raydium_gecko")
    pools = fetch_universe(m)
    rows = []
    for p in pools:
        cached = (DATA_DIR / "json" / f"gt_ohlcv_day_{p['id']}_{TAG}.json").exists()
        try:
            sig, n = sigma_daily(p["id"], m)
        except RuntimeError as e:
            sig, n = float("nan"), 0
        if not cached:
            time.sleep(2.2)  # GeckoTerminal public limit ~30 req/min
        share = lp_share(p)
        tvl = float(p["tvl"])
        vol7 = float(p["week"]["volume"]) / 7.0
        rot = vol7 / tvl
        f_d = rot * float(p["feeRate"]) * share
        a, b = p["mintA"]["symbol"], p["mintB"]["symbol"]
        rec = {"id": p["id"], "pair": f"{a}-{b}", "kind": kind(p), "fee_rate": float(p["feeRate"]), "lp_share": share,
               "tvl": tvl, "vol_7d_per_day": vol7, "rotation_per_day": rot, "fee_yield_day": f_d,
               "api_feeApr_week": float(p["week"].get("feeApr") or 0) / 100.0,
               "sigma_day": sig, "sigma_obs": n, "stable_pair": a in STABLES and b in STABLES,
               "lvr_day": lp.lvr_rate_cpmm(sig) if np.isfinite(sig) else float("nan"),
               "edge_day": f_d - lp.lvr_rate_cpmm(sig) if np.isfinite(sig) else float("nan"),
               "cf_star": (f_d / lp.lvr_rate_cpmm(sig)) if np.isfinite(sig) and sig > 0 else float("nan"),
               "breakeven_rotation": lp.breakeven_rotation(sig, float(p["feeRate"]) * share) if np.isfinite(sig) else float("nan")}
        rows.append(rec)
    m.save()
    df = pd.DataFrame(rows)
    out = {"n_pools": int(len(df)), "by_kind": {}, "pools": rows}
    for k, g in df.groupby("kind"):
        e = g["edge_day"].dropna().to_numpy()
        out["by_kind"][k] = {"n": int(len(g)), "n_sigma": int(len(e)),
                             "median_edge_ann": float(np.median(e) * 365) if len(e) else float("nan"),
                             "share_edge_pos": float(np.mean(e > 0)) if len(e) else float("nan"),
                             "median_fee_yield_ann": float(g["fee_yield_day"].median() * 365),
                             "median_lvr_ann": float(g["lvr_day"].median() * 365),
                             "median_cf_star": float(g["cf_star"].median())}
    std = df[df["kind"].isin(["AMMv4", "CPMM", "Standard-autre"]) & df["edge_day"].notna()]
    e = std["edge_day"].to_numpy()
    rng = np.random.default_rng(SEED)
    meds = [np.median(rng.choice(e, len(e), replace=True)) for _ in range(5000)] if len(e) else [np.nan]
    out["H3a"] = {"n": int(len(e)), "median_edge_day": float(np.median(e)) if len(e) else float("nan"),
                  "median_ci95_day": [float(np.quantile(meds, 0.025)), float(np.quantile(meds, 0.975))],
                  "share_positive": float(np.mean(e > 0)) if len(e) else float("nan")}
    nonstable = std[~std["stable_pair"]]["edge_day"].to_numpy()
    out["H3a"]["median_edge_day_excl_stable_pairs"] = float(np.median(nonstable)) if len(nonstable) else float("nan")
    out["H3a"]["verdict"] = ("H3a SOUTENUE" if out["H3a"]["median_ci95_day"][0] > 0 else
                             "H3a REJETEE" if out["H3a"]["median_ci95_day"][1] < 0 else "H3a NON CONCLUANTE")
    return out


def llama(name: str) -> pd.DataFrame:
    d = json.loads((DATA_DIR / "json" / f"llama_chart_{name}_{TAG}.json").read_text())["data"]
    df = pd.DataFrame(d)
    df.index = pd.to_datetime(df["timestamp"]).dt.floor("D")
    df = df[~df.index.duplicated(keep="last")]
    return df[["tvlUsd", "apyBase"]].astype(float)


def run_b() -> dict:
    m = Manifest("binance")
    h = load_klines("spot", "SOLUSDT", "1h", month_range("2023-01", "2026-10"), m)
    lr = np.log(h["close"]).diff()
    rv = (lr ** 2).groupby(lr.index.floor("D")).sum()
    close = h["close"].resample("1D").last()
    out = {}
    # R05-D5: DefiLlama apyBase counts the full trade fee. Cross-check against GeckoTerminal volume
    # (39 days, corr 1.00, ratio 0.88 = 0.22/0.25) -> scale to the LP share. CLMM shares: 0.84 (config).
    lp_scale = {"raydium_amm_v4_sol_usdc_025": 0.22 / 0.25, "raydium_clmm_sol_usdc_004": 0.84,
                "orca_whirlpool_sol_usdc_top": float("nan")}
    for name, label, rigorous in [("raydium_amm_v4_sol_usdc_025", "Raydium AMM v4 SOL-USDC 0,25 % (plage complète)", True),
                                  ("orca_whirlpool_sol_usdc_top", "Orca Whirlpool SOL-USDC (concentré)", False),
                                  ("raydium_clmm_sol_usdc_004", "Raydium CLMM SOL-USDC 0,04 % (concentré)", False)]:
        df = llama(name)
        idx = df.index.intersection(rv.index)
        idx = idx[(idx >= pd.Timestamp("2023-01-01", tz="UTC")) & (idx <= pd.Timestamp("2026-10-31", tz="UTC"))]
        scale = lp_scale[name] if np.isfinite(lp_scale[name]) else 1.0
        f = (df.loc[idx, "apyBase"] * scale / 100.0 / 365.0).fillna(0.0)
        lvr = rv.reindex(idx) / 8.0
        edge = f - lvr
        lo, hi, _ = stats.bootstrap_ci(edge.to_numpy(), np.mean, seed=SEED)
        sim = (lp.simulate_cpmm_vs_hodl(close.reindex(idx).ffill().to_numpy(), f.to_numpy()) if rigorous
               else {"lp_minus_hodl": float("nan"), "note": "non calculable : rendement de pool concentré"})
        out[name] = {"label": label, "rigorous_full_range": rigorous, "lp_share_scale_applied": lp_scale[name], "first_day": str(idx[0].date()),
                     "last_day": str(idx[-1].date()), "days": int(len(idx)),
                     "fee_yield_ann": float(f.mean() * 365), "lvr_fullrange_ann": float(lvr.mean() * 365),
                     "edge_ann": float(edge.mean() * 365), "edge_ci95_ann": [lo * 365, hi * 365],
                     "share_days_edge_pos": float((edge > 0).mean()),
                     "edge_median_ann": float(edge.median() * 365),
                     "edge_trimmed5_ann": float(edge.clip(edge.quantile(0.05), edge.quantile(0.95)).mean() * 365),
                     "fee_yield_median_ann": float(f.median() * 365),
                     "breakeven_concentration_factor": float(f.mean() / lvr.mean()), "tvl_median_usd": float(df.loc[idx, "tvlUsd"].median()),
                     "unhedged_vs_hodl": sim}
    r = out["raydium_amm_v4_sol_usdc_025"]
    out["H3b"] = {"pool": r["label"], "coverage": f"{r['first_day']} -> {r['last_day']} (pré-enregistré : 2023-01 -> 2026-10 ; historique DefiLlama disponible seulement depuis cette date)",
                  "verdict": "H3b SOUTENUE" if r["edge_ci95_ann"][0] > 0 else ("H3b REJETEE" if r["edge_ci95_ann"][1] < 0 else "H3b NON CONCLUANTE")}
    return out


def pct(x, nd=1):
    return "n/d" if x is None or not np.isfinite(x) else f"{x * 100:.{nd}f} %"


def write_md(res):
    A, B = res["S3A"], res["S3B"]
    L = ["# S3 — Fourniture de liquidité : frais vs LVR", "",
         "Protocole : `docs/R05_PREREGISTRATION_v1.md` §4. Avantage couvert = frais LP − LVR (plage complète, σ²/8).",
         "Une stratégie LP n'est jamais jugée rentable sur ses seuls frais.", "",
         "## S3-A — coupe transversale (top 60 pools Raydium par TVL, instantané du 2026-11-26)", "",
         "| Type | Pools | avec σ | Frais LP médians (ann.) | LVR plage complète médiane (ann.) | Avantage médian (ann.) | Part avantage > 0 | CF* médian |",
         "|---|---|---|---|---|---|---|---|"]
    for k, v in A["by_kind"].items():
        conc = k == "CLMM"
        L.append(f"| {k} | {v['n']} | {v['n_sigma']} | {pct(v['median_fee_yield_ann'])} | {pct(v['median_lvr_ann'])} | "
                 f"{'non évaluable' if conc else pct(v['median_edge_ann'])} | {'—' if conc else pct(v['share_edge_pos'], 0)} | "
                 f"{v['median_cf_star']:.1f} |")
    h = A["H3a"]
    L += ["", f"**H3a (pools non concentrés)** : n = {h['n']}, avantage médian {pct(h['median_edge_day'] * 365)} /an "
          f"[IC 95 % {pct(h['median_ci95_day'][0] * 365)} ; {pct(h['median_ci95_day'][1] * 365)}], "
          f"hors paires stables {pct(h['median_edge_day_excl_stable_pairs'] * 365)} ; part > 0 : {pct(h['share_positive'], 0)} → **{h['verdict']}**.", "",
          "Pools CLMM : l'avantage n'est pas calculable sans la liquidité active. On publie **CF\\*** = frais/TVL ÷ LVR plage "
          "complète : les LP d'un pool concentré ne couvrent la LVR que si leur liquidité est en moyenne moins de CF\\* fois plus "
          "concentrée qu'une plage complète. Indicateur, pas preuve.", "",
          "| Paire | Type | Frais | TVL (k$) | Rotation /j | Frais LP /an | σ /j | LVR plage complète /an | Avantage /an (CLMM : CF\\*) | Rotation de point mort /j |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for p in sorted(A["pools"], key=lambda x: -x["tvl"]):
        L.append(f"| {p['pair']} | {p['kind']} | {p['fee_rate'] * 100:.2f} % | {p['tvl'] / 1e3:,.0f} | {pct(p['rotation_per_day'])} | "
                 f"{pct(p['fee_yield_day'] * 365)} | {pct(p['sigma_day'])} | {pct(p['lvr_day'] * 365)} | "
                 f"{('CF* ' + format(p['cf_star'], '.1f')) if p['kind'] == 'CLMM' and np.isfinite(p['cf_star']) else ('n/d' if p['kind'] == 'CLMM' else pct(p['edge_day'] * 365))} | "
                 f"{pct(p['breakeven_rotation'])} |")
    L += ["", "## S3-B — historique SOL-USDC (DefiLlama × variance réalisée Binance)", "",
          "| Pool | Période | Jours | Frais LP ann. (moy. / méd.) | LVR plage complète ann. | Avantage ann. moyen [IC 95 %] | Avantage médian / tronqué 5 % | Jours > 0 | CF* | LP non couvert − détention |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in B.items():
        if k == "H3b":
            continue
        ci = v["edge_ci95_ann"]
        L.append(f"| {v['label']}{'' if v['rigorous_full_range'] else ' — indicatif'} | {v['first_day']} → {v['last_day']} | {v['days']} | "
                 f"{pct(v['fee_yield_ann'])} / {pct(v['fee_yield_median_ann'])} | {pct(v['lvr_fullrange_ann'])} | "
                 f"{(pct(v['edge_ann']) + ' [' + pct(ci[0]) + ' ; ' + pct(ci[1]) + ']') if v['rigorous_full_range'] else 'non évaluable'} | "
                 f"{(pct(v['edge_median_ann']) + ' / ' + pct(v['edge_trimmed5_ann'])) if v['rigorous_full_range'] else '—'} | "
                 f"{pct(v['share_days_edge_pos'], 0) if v['rigorous_full_range'] else '—'} | {v['breakeven_concentration_factor']:.1f} | "
                 f"{pct(v['unhedged_vs_hodl']['lp_minus_hodl'])} |")
    L += ["", f"**H3b** ({B['H3b']['pool']}) : **{B['H3b']['verdict']}**. Couverture : {B['H3b']['coverage']}.",
          "", "Correction R05-D5 appliquée : l'APY de base DefiLlama compte la totalité des frais de transaction ; "
          "recoupé avec les volumes GeckoTerminal du même pool (39 jours, corrélation 1,00, rapport 0,88 = 0,22/0,25), "
          "il est ramené à la part LP (AMM v4 × 0,88 ; CLMM × 0,84 ; Orca non corrigé, part inconnue)."]
    (RESULTS_DIR / "S3_lp.md").write_text("\n".join(L) + "\n")


def main():
    res = {"protocol": "R05_PREREGISTRATION_v1 §4", "S3B": run_b(), "S3A": run_a()}
    (RESULTS_DIR / "S3_lp.json").write_text(json.dumps(res, indent=1, default=str))
    write_md(res)
    print(json.dumps({"H3a": res["S3A"]["H3a"], "H3b": res["S3B"]["H3b"]["verdict"]}, indent=1))


if __name__ == "__main__":
    main()
