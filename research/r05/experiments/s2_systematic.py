"""S2-A — systematic trading on BTC / ETH / SOL, as pre-registered (R05_PREREGISTRATION_v1 §2).

Offline once experiments.fetch_binance has run. Deterministic (seed 20261126).
Outputs results/S2_systematic.json and results/S2_systematic.md.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from r05lab import backtest, signals, stats
from r05lab.data import RESULTS_DIR, Manifest, load_funding, load_klines, month_range

SYMS = {"BTCUSDT": "2018-01", "ETHUSDT": "2018-01", "SOLUSDT": "2020-08"}
END = "2026-10"
PERIODS = {"DESIGN": ("2018-01-01", "2022-12-31"), "VALID": ("2023-01-01", "2024-12-31"),
           "TEST": ("2025-01-01", "2026-10-31")}
OOS = ("2023-01-01", "2026-10-31")
LS_START = "2020-01-01"  # perp funding archive starts 2020-01 (see manifest)
COST = {"spot": 0.0010 + 0.0002, "perp": 0.0005 + 0.0002}
GRID = {"F1": [30, 90, 180], "F2": [20, 55, 100], "F3": [4, 12, 24], "F4": [1, 4, 24]}
N_TRIALS = 24
SEED = 20261126


def load_all():
    m = Manifest("binance")
    hourly, funding = {}, {}
    for s, start in SYMS.items():
        h = load_klines("spot", s, "1h", month_range(start, END), m)
        hourly[s] = h.loc[:"2026-10-31 23:00"]
        f = load_funding(s, month_range("2020-01", END), m)
        funding[s] = f["rate"]
    return hourly, funding


def quality(h: pd.DataFrame) -> dict:
    full = pd.date_range(h.index[0], h.index[-1], freq="h")
    missing = full.difference(h.index)
    return {"first": str(h.index[0]), "last": str(h.index[-1]), "bars": int(len(h)),
            "missing_hours": int(len(missing)), "dup": int(h.index.duplicated().sum()),
            "nonpositive_close": int((h["close"] <= 0).sum()), "zero_volume_bars": int((h["volume"] == 0).sum()),
            "max_abs_hourly_ret": float(h["close"].pct_change().abs().max())}


def to_daily_bars(h: pd.DataFrame) -> pd.DataFrame:
    d = h.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                              "volume": "sum", "taker_buy_base": "sum"})
    n = h["close"].resample("1D").count()
    return d[n >= 20]


def funding_per_bar(rate: pd.Series, index: pd.DatetimeIndex, freq: str) -> pd.Series:
    return rate.groupby(rate.index.floor(freq)).sum().reindex(index).fillna(0.0)


def position(fam: str, p: int, bars: pd.DataFrame, long_only: bool) -> pd.Series:
    if fam == "F1":
        return signals.tsmom(bars["close"], p, long_only)
    if fam == "F2":
        return signals.donchian(bars["high"], bars["low"], bars["close"], p, long_only)
    if fam == "F3":
        return signals.mean_reversion(bars["close"], p, long_only)
    if fam == "F4":
        return signals.flow_imbalance(bars["volume"], bars["taker_buy_base"], p, long_only)
    raise ValueError(fam)


def run_config(fam, p, variant, hourly, daily, funding, cost_mult=1.0):
    """Returns per-asset bar-level backtests and the daily portfolio net return."""
    long_only = variant == "spot"
    freq = "D" if fam in ("F1", "F2") else "h"
    per_asset, daily_net, daily_gross_ex = {}, {}, {}
    for s in SYMS:
        bars = daily[s] if freq == "D" else hourly[s]
        if not long_only:
            bars = bars.loc[LS_START:]
        ret = bars["close"].pct_change()
        pos = position(fam, p, bars, long_only)
        fund = None if long_only else funding_per_bar(funding[s], bars.index, freq)
        bt = backtest.run(pos, ret, COST[variant] * cost_mult, fund)
        per_asset[s] = bt
        daily_net[s] = backtest.to_daily(bt)
    port = pd.DataFrame(daily_net).mean(axis=1, skipna=True)  # equal weight over available assets
    return per_asset, port


def bh_portfolio(daily):
    r = pd.DataFrame({s: d["close"].pct_change() for s, d in daily.items()})
    return r.mean(axis=1, skipna=True)


def seg(x: pd.Series, a: str, b: str) -> np.ndarray:
    return x.loc[a:b].dropna().to_numpy()


def breakeven_cost(per_asset: dict, a: str, b: str) -> float:
    """Cost per side (bp) at which aggregate net P&L over [a, b] is zero (linear approx)."""
    g = sum(bt.loc[a:b, "gross"].sum() - bt.loc[a:b, "funding"].sum() for bt in per_asset.values())
    t = sum(bt.loc[a:b, "turnover"].sum() for bt in per_asset.values())
    return float(g / t * 1e4) if t > 0 else float("nan")


def trade_stats(per_asset: dict, a: str, b: str) -> dict:
    tr = pd.concat([backtest.trades(bt.loc[a:b]) for bt in per_asset.values()], ignore_index=True)
    if tr.empty:
        return {"n_trades": 0}
    return {"n_trades": int(len(tr)), "mean_net_per_trade": float(tr["net"].mean()),
            "median_net_per_trade": float(tr["net"].median()), "hit_rate": float((tr["net"] > 0).mean()),
            "mean_bars": float(tr["bars"].mean())}


def exposure(per_asset: dict, a: str, b: str) -> float:
    return float(np.mean([bt.loc[a:b, "pos"].abs().mean() for bt in per_asset.values()]))


def regime_table(port: pd.Series, bh: pd.Series, btc_daily: pd.DataFrame) -> dict:
    """Descriptive (ex post labels): BTC 30d realised vol vs full-sample median; 180d trend."""
    r = btc_daily["close"].pct_change()
    vol = r.rolling(30).std() * math.sqrt(365)
    trend = btc_daily["close"] / btc_daily["close"].shift(180) - 1
    lab = pd.DataFrame({"hi_vol": vol > vol.median(), "up": trend > 0}).reindex(port.index)
    bh = bh.reindex(port.index)
    out = {}
    for name, mask in {"vol_haute": lab["hi_vol"] == True, "vol_basse": lab["hi_vol"] == False,
                       "tendance_hausse": lab["up"] == True, "tendance_baisse": lab["up"] == False}.items():
        out[name] = {"strat_sharpe": stats.sharpe(port[mask].dropna().to_numpy()),
                     "strat_ann_ret": stats.ann_return(port[mask].dropna().to_numpy()),
                     "bh_sharpe": stats.sharpe(bh[mask].dropna().to_numpy()), "days": int(mask.sum())}
    return out


def main():
    hourly, funding = load_all()
    daily = {s: to_daily_bars(h) for s, h in hourly.items()}
    bh = bh_portfolio(daily)
    out = {"protocol": "R05_PREREGISTRATION_v1 §2", "periods": PERIODS, "costs_per_side": COST,
           "quality": {s: quality(h) for s, h in hourly.items()},
           "funding_coverage": {s: [str(f.index[0]), str(f.index[-1]), int(len(f))] for s, f in funding.items()},
           "buy_and_hold": {k: stats.summarize(seg(bh, *v)) for k, v in PERIODS.items()},
           "configs": {}, "selected": {}}
    out["buy_and_hold"]["OOS"] = stats.summarize(seg(bh, *OOS))
    ports = {}
    # ---- all trials (24 configs): every one is logged and counts in N
    for fam, grid in GRID.items():
        for variant in ("spot", "perp"):
            for p in grid:
                per_asset, port = run_config(fam, p, variant, hourly, daily, funding)
                key = f"{fam}_{p}_{variant}"
                ports[key] = (per_asset, port)
                out["configs"][key] = {k: stats.summarize(seg(port, *v)) for k, v in PERIODS.items()}
                out["configs"][key]["OOS"] = stats.summarize(seg(port, *OOS))
    # per-period SR of all trials on OOS (for DSR)
    oos_srs = np.array([np.mean(seg(port, *OOS)) / np.std(seg(port, *OOS), ddof=1) for _, port in ports.values()])
    # ---- selection on DESIGN only, then frozen evaluation
    for fam, grid in GRID.items():
        for variant in ("spot", "perp"):
            design_sr = {p: out["configs"][f"{fam}_{p}_{variant}"]["DESIGN"]["sharpe"] for p in grid}
            best = max(design_sr, key=lambda p: (-np.inf if np.isnan(design_sr[p]) else design_sr[p]))
            key = f"{fam}_{best}_{variant}"
            per_asset, port = ports[key]
            oos = seg(port, *OOS)
            lo, hi, _ = stats.bootstrap_ci(oos, lambda x: stats.sharpe(x), seed=SEED)
            _, port2 = run_config(fam, best, variant, hourly, daily, funding, cost_mult=2.0)
            _, port3 = run_config(fam, best, variant, hourly, daily, funding, cost_mult=3.0)
            joined = pd.concat([port, bh], axis=1, keys=["s", "b"], sort=True).loc[OOS[0]:OOS[1]].dropna()
            ab = stats.alpha_beta(joined["s"].to_numpy(), joined["b"].to_numpy())
            rng_seed = SEED
            alphas = []
            rng = np.random.default_rng(rng_seed)
            y, x = joined["s"].to_numpy(), joined["b"].to_numpy()
            for _ in range(1000):
                ii = stats.stationary_bootstrap_idx(len(y), 20.0, rng)
                alphas.append(stats.alpha_beta(y[ii], x[ii])["alpha_ann"])
            a_lo = float(np.quantile(alphas, 0.05))
            gross_cfg = run_config(fam, best, variant, hourly, daily, funding, cost_mult=0.0)[1]
            rec = {
                "selected_param": best, "design_sharpes": design_sr,
                "VALID": stats.summarize(seg(port, *PERIODS["VALID"])),
                "TEST": stats.summarize(seg(port, *PERIODS["TEST"])),
                "OOS": stats.summarize(oos),
                "OOS_gross_sharpe": stats.sharpe(seg(gross_cfg, *OOS)),
                "OOS_sharpe_ci95": [lo, hi],
                "OOS_psr0": stats.psr(oos),
                "OOS_dsr_crosssec": stats.dsr(oos, oos_srs, N_TRIALS),
                "OOS_dsr": stats.dsr_null(oos, N_TRIALS),
                "OOS_sr_star_ann_null": stats.expected_max_sr_null(len(oos), N_TRIALS) * math.sqrt(365),
                "OOS_sharpe_cost_x2": stats.sharpe(seg(port2, *OOS)),
                "OOS_sharpe_cost_x3": stats.sharpe(seg(port3, *OOS)),
                "OOS_breakeven_cost_bp_per_side": breakeven_cost(per_asset, *OOS),
                "OOS_alpha_vs_bh": ab, "OOS_alpha_ci90_low": a_lo,
                "OOS_trades": trade_stats(per_asset, *OOS),
                "OOS_exposure": exposure(per_asset, *OOS),
                "regimes_full_sample": regime_table(port, bh, daily["BTCUSDT"]),
            }
            c1 = rec["VALID"]["sharpe"] > 0.5 and rec["TEST"]["sharpe"] > 0
            c2 = rec["OOS_psr0"] >= 0.95 and rec["OOS_dsr"] >= 0.90
            rec["C2_under_crosssec_dsr"] = rec["OOS_psr0"] >= 0.95 and rec["OOS_dsr_crosssec"] >= 0.90
            c3 = rec["OOS_sharpe_cost_x2"] > 0
            c4 = ab["alpha_ann"] > 0 and a_lo > 0
            rec["criteria"] = {"C1_valid_gt_0.5_and_test_gt_0": c1, "C2_psr_dsr": c2, "C3_cost_x2": c3,
                               "C4_alpha": c4}
            if variant == "spot":
                rec["verdict"] = ("REJETEE" if not (c1 and c3) else "CANDIDATE_PAPER" if (c2 and c4)
                                  else "NON_CONCLUANTE")
            else:
                rec["verdict"] = "SECONDAIRE (" + ("REJETEE" if not (c1 and c3) else "CANDIDATE_PAPER"
                                                   if (c2 and c4) else "NON_CONCLUANTE") + ")"
            out["selected"][f"{fam}_{variant}"] = rec
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "S2_systematic.json").write_text(json.dumps(out, indent=1, default=str))
    write_md(out)
    print(json.dumps({k: (v["selected_param"], v["verdict"], round(v["OOS"]["sharpe"], 2),
                          round(v["OOS_gross_sharpe"], 2)) for k, v in out["selected"].items()}, indent=1))


def f(x, pct=False, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/d"
    return f"{x * 100:.1f} %" if pct else f"{x:.{nd}f}"


def write_md(out):
    L = ["# S2-A — Trading systématique BTC/ETH/SOL : résultats", "",
         "Protocole : `docs/R05_PREREGISTRATION_v1.md` §2. Données : archive publique Binance spot 1 h, "
         "CHECKSUM vérifiés (`DATA_MANIFEST_binance.json`). Portefeuille équipondéré, rendements journaliers.", "",
         "## Qualité des données", "", "| Actif | Début | Fin | Barres | Heures manquantes | Doublons | Var. horaire max |",
         "|---|---|---|---|---|---|---|"]
    for s, q in out["quality"].items():
        L.append(f"| {s} | {q['first'][:10]} | {q['last'][:16]} | {q['bars']} | {q['missing_hours']} | {q['dup']} | {f(q['max_abs_hourly_ret'], True)} |")
    L += ["", "## Détention passive (référence)", "", "| Période | Rend. annualisé | Vol | Sharpe | DD max |", "|---|---|---|---|---|"]
    for k, v in out["buy_and_hold"].items():
        L.append(f"| {k} | {f(v['ann_return'], True)} | {f(v['ann_vol'], True)} | {f(v['sharpe'])} | {f(v['max_dd'], True)} |")
    L += ["", "## Configurations retenues sur CONCEPTION puis évaluées hors échantillon", "",
          "| Famille / variante | Param. | Sharpe VALID | Sharpe TEST | Sharpe OOS net [IC 95 %] | Sharpe OOS brut | PSR | DSR (nul analytique / inter-essais) | ×2 coûts | Point mort (pb/côté) | Alpha ann. (borne 5 %) | Trades | Verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in out["selected"].items():
        ci = r["OOS_sharpe_ci95"]
        L.append(f"| {k} | {r['selected_param']} | {f(r['VALID']['sharpe'])} | {f(r['TEST']['sharpe'])} | "
                 f"{f(r['OOS']['sharpe'])} [{f(ci[0])} ; {f(ci[1])}] | {f(r['OOS_gross_sharpe'])} | {f(r['OOS_psr0'])} | "
                 f"{f(r['OOS_dsr'])} / {f(r['OOS_dsr_crosssec'])} | {f(r['OOS_sharpe_cost_x2'])} | {f(r['OOS_breakeven_cost_bp_per_side'], nd=1)} | "
                 f"{f(r['OOS_alpha_vs_bh']['alpha_ann'], True)} ({f(r['OOS_alpha_ci90_low'], True)}) | "
                 f"{r['OOS_trades'].get('n_trades', 0)} | **{r['verdict']}** |")
    L += ["", "## Toutes les configurations (24 essais, tous comptés dans N)", "",
          "| Config | Sharpe DESIGN | Sharpe VALID | Sharpe TEST | Rend. ann. OOS | DD max OOS |", "|---|---|---|---|---|---|"]
    for k, v in out["configs"].items():
        L.append(f"| {k} | {f(v['DESIGN']['sharpe'])} | {f(v['VALID']['sharpe'])} | {f(v['TEST']['sharpe'])} | "
                 f"{f(v['OOS']['ann_return'], True)} | {f(v['OOS']['max_dd'], True)} |")
    L += ["", "## Régimes (descriptif, étiquettes ex post, échantillon complet)", "",
          "| Config retenue | Sharpe vol haute | Sharpe vol basse | Sharpe tendance + | Sharpe tendance − | Passif vol haute / basse |",
          "|---|---|---|---|---|---|"]
    for k, r in out["selected"].items():
        g = r["regimes_full_sample"]
        L.append(f"| {k} | {f(g['vol_haute']['strat_sharpe'])} | {f(g['vol_basse']['strat_sharpe'])} | "
                 f"{f(g['tendance_hausse']['strat_sharpe'])} | {f(g['tendance_baisse']['strat_sharpe'])} | "
                 f"{f(g['vol_haute']['bh_sharpe'])} / {f(g['vol_basse']['bh_sharpe'])} |")
    (RESULTS_DIR / "S2_systematic.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
