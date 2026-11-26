"""S1-A cash-and-carry (long spot / short perp, Binance) and S1-B cross-venue funding spread
(Hyperliquid vs Binance), as pre-registered (R05_PREREGISTRATION_v1 §3).

Precisions fixed before running (logged in REGISTRE): criteria evaluated on the
equal-weight BTC/ETH/SOL portfolio (as in S2), per-asset results descriptive; H selected on
DESIGN by net Sharpe (rf unavailable before 2023-02); S1-B capital uses leverage 2 per leg.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from r05lab import backtest, stats
from r05lab.data import DATA_DIR, RESULTS_DIR, Manifest, load_funding, load_klines, month_range

SYMS = {"BTCUSDT": ("2018-01", "2020-01"), "ETHUSDT": ("2018-01", "2020-01"), "SOLUSDT": ("2020-08", "2020-09")}
HL_COIN = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"}
END = "2026-10"
A_PERIODS = {"DESIGN": ("2020-01-01", "2022-12-31"), "VALID": ("2023-01-01", "2024-12-31"),
             "TEST": ("2025-01-01", "2026-10-31")}
B_PERIODS = {"DESIGN": ("2023-05-13", "2024-06-30"), "VALID": ("2024-07-01", "2025-06-30"),
             "TEST": ("2025-07-01", "2026-10-31")}
LEV_A = 3.0
CAP_A = 1.0 + 1.0 / LEV_A
COST_A = (0.0010 + 0.0002) + (0.0005 + 0.0002)  # spot leg + perp leg, per side of the pair
LEV_B = 2.0
CAP_B = 2.0 / LEV_B
COST_B = (0.00045 + 0.0002) + (0.0005 + 0.0002)
H_A = [0.05, 0.10, 0.20]
H_B = [0.10, 0.20, 0.40]
MMR = 0.005
SEED = 20261126
TAG = "20261126"


def daily_close(h: pd.DataFrame) -> pd.Series:
    c = h["close"].resample("1D").last()
    n = h["close"].resample("1D").count()
    return c[n >= 20]


def rf_daily() -> pd.Series:
    d = json.loads((DATA_DIR / "json" / f"llama_chart_aave_v3_usdc_eth_{TAG}.json").read_text())["data"]
    s = pd.Series({pd.Timestamp(r["timestamp"]).floor("D"): (r.get("apyBase") or 0.0) / 100.0 for r in d})
    s = s[~s.index.duplicated()].sort_index()
    return s


def load():
    m = Manifest("binance")
    spot, perp, fund, perp_hi = {}, {}, {}, {}
    for s, (s0, p0) in SYMS.items():
        h = load_klines("spot", s, "1h", month_range(s0, END), m).loc[:"2026-10-31 23:00"]
        ph = load_klines("futures/um", s, "1h", month_range(p0, END), m).loc[:"2026-10-31 23:00"]
        spot[s] = daily_close(h)
        perp[s] = daily_close(ph)
        perp_hi[s] = ph["high"].resample("1D").max()
        f = load_funding(s, month_range("2020-01", END), m)["rate"]
        fund[s] = f.groupby(f.index.floor("D")).sum()
    return spot, perp, fund, perp_hi


def hl_series(coin: str):
    rows = []
    for p in sorted((DATA_DIR / "json").glob(f"hl_funding_{coin}_{TAG}_p*.json")):
        rows += json.loads(p.read_text())
    f = pd.Series({pd.Timestamp(r["time"], unit="ms", tz="UTC"): float(r["fundingRate"]) for r in rows})
    f = f[~f.index.duplicated()].sort_index()
    c = json.loads((DATA_DIR / "json" / f"hl_candles_1d_{coin}_{TAG}.json").read_text())
    close = pd.Series({pd.Timestamp(r["t"], unit="ms", tz="UTC").floor("D"): float(r["c"]) for r in c}).sort_index()
    return f.groupby(f.index.floor("D")).sum(), f, close


def period_stats(net: pd.Series, pos: pd.Series, rf: pd.Series, a: str, b: str) -> dict:
    x = net.loc[a:b].dropna()
    p = pos.reindex(x.index).fillna(0.0)
    rfx = rf.reindex(x.index).ffill().bfill() / 365.0 if len(rf) else pd.Series(0.0, index=x.index)
    exc = x - rfx
    exc = exc.dropna()
    mex = (1 + exc).groupby(exc.index.tz_localize(None).to_period("M")).prod() - 1
    lo, hi, _ = stats.bootstrap_ci(mex.to_numpy(), np.mean, mean_block=3.0, seed=SEED) if len(mex) > 6 else (np.nan, np.nan, None)
    s = stats.summarize(x.to_numpy())
    s.update({"ann_excess_over_rf": float(exc.mean() * 365), "rf_ann_mean": float(rfx.mean() * 365),
              "rf_coverage": float(rf.reindex(x.index).notna().mean()) if len(rf) else 0.0,
              "monthly_excess_mean": float(mex.mean()), "monthly_excess_ci95": [lo, hi], "months": int(len(mex)),
              "time_invested": float((p != 0).mean()), "entries": int(((p != 0) & (p.shift(1).fillna(0) == 0)).sum())})
    return s


def carry_a(spot, perp, fund, s):
    idx = perp[s].index.intersection(spot[s].index)
    rs = spot[s].reindex(idx).pct_change()
    rp = perp[s].reindex(idx).pct_change()
    f = fund[s].reindex(idx).fillna(0.0)
    pnl = (rs - rp + f).fillna(0.0)  # per unit notional, short perp receives positive funding
    return pnl, f, idx


def liquidation_days(perp_close, perp_hi, lev, a=None, b=None) -> int:
    prev = perp_close.shift(1)
    rise = perp_hi.reindex(perp_close.index) / prev - 1.0
    if a:
        rise = rise.loc[a:b]
    return int((rise > 1.0 / lev - MMR).sum())


def run_a(spot, perp, fund, perp_hi, rf):
    out = {"assets": {}, "portfolio": {}}
    nets = {k: {} for k in ["C0"] + [f"C1_H{h}" for h in H_A]}
    poss = {k: {} for k in nets}
    for s in SYMS:
        pnl, f, idx = carry_a(spot, perp, fund, s)
        ret_cap = pnl / CAP_A
        a = {"funding_ann_by_period": {}, "basis_daily_change_std_bp": float((spot[s].reindex(idx).pct_change()
             - perp[s].reindex(idx).pct_change()).std() * 1e4),
             "basis_level_bp": {"mean": float(((perp[s].reindex(idx) / spot[s].reindex(idx)) - 1).mean() * 1e4),
                                "min": float(((perp[s].reindex(idx) / spot[s].reindex(idx)) - 1).min() * 1e4),
                                "max": float(((perp[s].reindex(idx) / spot[s].reindex(idx)) - 1).max() * 1e4)},
             "neg_funding_day_share": float((f < 0).mean()),
             "worst_30d_funding": float(f.rolling(30).sum().min()),
             "liquidation_days_no_intraday_rebal": {str(L): liquidation_days(perp[s], perp_hi[s], L) for L in (2, 3, 5)},
             "liquidation_days_OOS": {str(L): liquidation_days(perp[s], perp_hi[s], L, "2023-01-01", "2026-10-31") for L in (2, 3, 5)}}
        for k, (p0, p1) in A_PERIODS.items():
            a["funding_ann_by_period"][k] = float(f.loc[p0:p1].mean() * 365)
        trail = f.rolling(7).mean() * 365
        cfgs = {"C0": pd.Series(1.0, index=idx)}
        for h in H_A:
            cfgs[f"C1_H{h}"] = (trail > h).astype(float)
        for k, pos in cfgs.items():
            bt = backtest.run(pos, ret_cap, COST_A / CAP_A)
            nets[k][s] = bt["net"]
            poss[k][s] = bt["pos"]
        out["assets"][s] = a
    port = {k: pd.DataFrame(v).mean(axis=1) for k, v in nets.items()}
    ppos = {k: pd.DataFrame(v).mean(axis=1) for k, v in poss.items()}
    for k in port:
        out["portfolio"][k] = {p: period_stats(port[k], ppos[k], rf, *rg) for p, rg in A_PERIODS.items()}
        out["portfolio"][k]["OOS"] = period_stats(port[k], ppos[k], rf, "2023-01-01", "2026-10-31")
    # selection of H on DESIGN by net Sharpe, then criteria
    best = max(H_A, key=lambda h: out["portfolio"][f"C1_H{h}"]["DESIGN"]["sharpe"])
    out["selected_C1"] = f"C1_H{best}"
    for k in ("C0", f"C1_H{best}"):
        out[f"verdict_{k}"] = criteria_a(k, nets, poss, spot, perp, fund, rf, best)
    return out


def criteria_a(k, nets, poss, spot, perp, fund, rf, best):
    # cost x2 rerun
    nets2 = {}
    for s in SYMS:
        pnl, f, idx = carry_a(spot, perp, fund, s)
        pos = pd.Series(1.0, index=idx) if k == "C0" else ((f.rolling(7).mean() * 365) > best).astype(float)
        nets2[s] = backtest.run(pos, pnl / CAP_A, 2 * COST_A / CAP_A)["net"]
    p1 = pd.DataFrame(nets[k]).mean(axis=1)
    p2 = pd.DataFrame(nets2).mean(axis=1)
    pp = pd.DataFrame(poss[k]).mean(axis=1)
    o1 = period_stats(p1, pp, rf, "2023-01-01", "2026-10-31")
    o2 = period_stats(p2, pp, rf, "2023-01-01", "2026-10-31")
    c = {"excess_gt_0": o1["ann_excess_over_rf"] > 0, "ci_low_gt_0": (o1["monthly_excess_ci95"][0] or -1) > 0,
         "cost_x2_excess_gt_0": o2["ann_excess_over_rf"] > 0, "dd_lt_10pct": o1["max_dd"] < 0.10}
    verdict = "CANDIDATE_PAPER" if all(c.values()) else ("REJETEE" if not c["excess_gt_0"] else "NON_CONCLUANTE")
    return {"criteria": c, "verdict": verdict, "OOS": o1, "OOS_cost_x2": o2,
            "note": "liquidation criterion assessed per asset in assets[*].liquidation_days_OOS"}


def run_b(perp, fund, rf):
    out = {"assets": {}, "portfolio": {}}
    nets = {f"H{h}": {} for h in H_B}
    poss = {f"H{h}": {} for h in H_B}
    nets2 = {f"H{h}": {} for h in H_B}
    for s, coin in HL_COIN.items():
        hl_d, hl_raw, hl_close = hl_series(coin)
        idx = hl_d.index.intersection(fund[s].index).intersection(perp[s].index).intersection(hl_close.index)
        idx = idx[idx >= pd.Timestamp("2023-05-13", tz="UTC")]
        spread = (hl_d.reindex(idx) - fund[s].reindex(idx)).fillna(0.0)
        basis = (perp[s].reindex(idx).pct_change() - hl_close.reindex(idx).pct_change()).fillna(0.0)
        pnl_long_spread = spread + basis  # short HL perp / long Binance perp
        trail = spread.rolling(3).mean() * 365
        a = {"hl_funding_ann": float(hl_d.reindex(idx).mean() * 365), "bn_funding_ann": float(fund[s].reindex(idx).mean() * 365),
             "spread_ann_mean": float(spread.mean() * 365), "spread_ann_std_daily": float(spread.std() * 365),
             "abs_trailing_spread_gt_10pct_share": float((trail.abs() > 0.10).mean()),
             "cross_venue_daily_basis_std_bp": float(basis.std() * 1e4),
             "first_day": str(idx[0].date()), "days": int(len(idx))}
        for h in H_B:
            pos = pd.Series(np.where(trail > h, 1.0, np.where(trail < -h, -1.0, 0.0)), index=idx)
            bt = backtest.run(pos, pnl_long_spread / CAP_B, COST_B / CAP_B)
            nets[f"H{h}"][s] = bt["net"]
            poss[f"H{h}"][s] = bt["pos"]
            nets2[f"H{h}"][s] = backtest.run(pos, pnl_long_spread / CAP_B, 2 * COST_B / CAP_B)["net"]
        out["assets"][s] = a
    for k in nets:
        port = pd.DataFrame(nets[k]).mean(axis=1)
        pp = pd.DataFrame(poss[k]).mean(axis=1)
        out["portfolio"][k] = {p: period_stats(port, pp, rf, *rg) for p, rg in B_PERIODS.items()}
        out["portfolio"][k]["OOS"] = period_stats(port, pp, rf, "2024-07-01", "2026-10-31")
        out["portfolio"][k]["OOS_cost_x2"] = period_stats(pd.DataFrame(nets2[k]).mean(axis=1), pp, rf, "2024-07-01", "2026-10-31")
    best = max(H_B, key=lambda h: out["portfolio"][f"H{h}"]["DESIGN"]["sharpe"])
    o = out["portfolio"][f"H{best}"]
    c = {"excess_gt_0": o["OOS"]["ann_excess_over_rf"] > 0, "ci_low_gt_0": (o["OOS"]["monthly_excess_ci95"][0] or -1) > 0,
         "cost_x2_excess_gt_0": o["OOS_cost_x2"]["ann_excess_over_rf"] > 0, "dd_lt_10pct": o["OOS"]["max_dd"] < 0.10}
    out["selected"] = f"H{best}"
    out["verdict"] = {"criteria": c, "verdict": "CANDIDATE_PAPER" if all(c.values()) else
                      ("REJETEE" if not c["excess_gt_0"] else "NON_CONCLUANTE"),
                      "unmeasured": "transferts de marge inter-plateformes, risque de contrepartie Hyperliquid"}
    return out


def pct(x):
    return "n/d" if x is None or not np.isfinite(x) else f"{x * 100:.1f} %"


def write_md(res):
    A, B = res["S1A"], res["S1B"]
    L = ["# S1 — Carry et funding : résultats", "",
         "Protocole : `docs/R05_PREREGISTRATION_v1.md` §3. Données : archive Binance (CHECKSUM vérifiés), "
         "API publique Hyperliquid, DefiLlama (Aave v3 USDC, taux de référence). Rendements sur **capital** "
         f"(S1-A : 1 + 1/{LEV_A:g} = {CAP_A:.3f} par unité de notionnel ; S1-B : {CAP_B:.2f}).", "",
         "## S1-A — funding moyen annualisé par période (Binance USDⓈ-M)", "",
         "| Actif | DESIGN | VALID | TEST | Jours funding < 0 | Pire funding 30 j | Basis moyen (pb) [min ; max] | Jours de liquidation OOS (L=2/3/5) |",
         "|---|---|---|---|---|---|---|---|"]
    for s, a in A["assets"].items():
        fp = a["funding_ann_by_period"]
        b = a["basis_level_bp"]
        lq = a["liquidation_days_OOS"]
        L.append(f"| {s} | {pct(fp['DESIGN'])} | {pct(fp['VALID'])} | {pct(fp['TEST'])} | {pct(a['neg_funding_day_share'])} | "
                 f"{pct(a['worst_30d_funding'])} | {b['mean']:.1f} [{b['min']:.0f} ; {b['max']:.0f}] | {lq['2']}/{lq['3']}/{lq['5']} |")
    L += ["", "## S1-A — portefeuille équipondéré, net de frais, sur capital", "",
          "| Config | Période | Rend. ann. | Vol | Sharpe | DD max | Taux réf. moyen | Excès ann. sur réf. | IC 95 % excès mensuel | Temps investi |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in A["portfolio"].items():
        for p in ("DESIGN", "VALID", "TEST", "OOS"):
            x = v[p]
            ci = x["monthly_excess_ci95"]
            L.append(f"| {k} | {p} | {pct(x['ann_return'])} | {pct(x['ann_vol'])} | {x['sharpe']:.2f} | {pct(x['max_dd'])} | "
                     f"{pct(x['rf_ann_mean'])} | {pct(x['ann_excess_over_rf'])} | [{pct(ci[0])} ; {pct(ci[1])}] | {pct(x['time_invested'])} |")
    L += ["", f"Sélection C1 sur DESIGN : **{A['selected_C1']}**.", ""]
    for k in ("C0", A["selected_C1"]):
        v = A[f"verdict_{k}"]
        L.append(f"- **{k}** : {v['verdict']} — critères {v['criteria']} ; excès OOS ×2 coûts {pct(v['OOS_cost_x2']['ann_excess_over_rf'])}.")
    L += ["", "## S1-B — écart de funding Hyperliquid − Binance", "",
          "| Actif | Depuis | Funding HL ann. | Funding Binance ann. | Écart moyen ann. | Part du temps \\|écart 3 j\\| > 10 % | σ basis inter-plateformes (pb/j) |",
          "|---|---|---|---|---|---|---|"]
    for s, a in B["assets"].items():
        L.append(f"| {s} | {a['first_day']} | {pct(a['hl_funding_ann'])} | {pct(a['bn_funding_ann'])} | {pct(a['spread_ann_mean'])} | "
                 f"{pct(a['abs_trailing_spread_gt_10pct_share'])} | {a['cross_venue_daily_basis_std_bp']:.1f} |")
    L += ["", "| Seuil H | Période | Rend. ann. | Sharpe | DD max | Excès ann. | IC 95 % excès mensuel | Temps investi | Entrées |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, v in B["portfolio"].items():
        for p in ("DESIGN", "VALID", "TEST", "OOS", "OOS_cost_x2"):
            x = v[p]
            ci = x["monthly_excess_ci95"]
            L.append(f"| {k} | {p} | {pct(x['ann_return'])} | {x['sharpe']:.2f} | {pct(x['max_dd'])} | {pct(x['ann_excess_over_rf'])} | "
                     f"[{pct(ci[0])} ; {pct(ci[1])}] | {pct(x['time_invested'])} | {x['entries']} |")
    L += ["", f"Sélection sur DESIGN : **{B['selected']}** → **{B['verdict']['verdict']}** — {B['verdict']['criteria']}.",
          f"Non mesuré : {B['verdict']['unmeasured']}."]
    (RESULTS_DIR / "S1_carry.md").write_text("\n".join(L) + "\n")


def main():
    spot, perp, fund, perp_hi = load()
    rf = rf_daily()
    res = {"protocol": "R05_PREREGISTRATION_v1 §3", "rf_source": "DefiLlama aave-v3 USDC Ethereum apyBase, from "
           + str(rf.index[0].date()), "S1A": run_a(spot, perp, fund, perp_hi, rf), "S1B": run_b(perp, fund, rf)}
    (RESULTS_DIR / "S1_carry.json").write_text(json.dumps(res, indent=1, default=str))
    write_md(res)
    print(json.dumps({"S1A_C0": res["S1A"]["verdict_C0"]["verdict"], "S1A_sel": res["S1A"]["selected_C1"],
                      "S1A_C1": res["S1A"][f"verdict_{res['S1A']['selected_C1']}"]["verdict"],
                      "S1B": [res["S1B"]["selected"], res["S1B"]["verdict"]["verdict"]]}))


if __name__ == "__main__":
    main()
