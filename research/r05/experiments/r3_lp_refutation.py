"""R3 refutation battery for hedged full-range LP (R05_PREREGISTRATION_v2 §R3)."""
from __future__ import annotations

import gzip
import json
import math
import sys
import time

import numpy as np
import pandas as pd

from experiments.s1_carry import rf_daily
from experiments.s3_lp import llama
from r05lab import stats
from r05lab.data import DATA_DIR, RESULTS_DIR, Manifest, json_get, load_funding, load_klines, month_range

TAG = "20261126"
POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
LLAMA_SOLUSDC = "raydium_amm_v4_sol_usdc_025"
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
LP_SHARE = 0.22 / 0.25
START, END = "2025-01-24", "2026-10-31"
RECENT = ("2025-12-01", "2026-10-31")
LEV = 3.0
COSTS = {"swap": 0.0003, "transfer": 0.0002, "perp": 0.0005 + 0.0002}
MMR = 0.005
SEED = 20261126


# ----------------------------------------------------------------------------- data
def gt_daily(pool: str, m: Manifest, limit: int = 1000) -> pd.DataFrame:
    d = json_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/day", m,
                 f"gt_ohlcv_day1000_{pool}_{TAG}.json", params={"aggregate": "1", "limit": str(limit), "currency": "token"})
    rows = d["data"]["attributes"]["ohlcv_list"]
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"])
    df.index = pd.to_datetime(df["t"], unit="s", utc=True)
    df = df.sort_index()
    df = df[df.index < pd.Timestamp(TAG, tz="UTC")]
    return df


def gt_daily_usd_volume(pool: str, m: Manifest) -> pd.Series:
    d = json_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/day", m,
                 f"gt_ohlcv_day1000usd_{pool}_{TAG}.json", params={"aggregate": "1", "limit": "1000", "currency": "usd"})
    rows = d["data"]["attributes"]["ohlcv_list"]
    s = pd.Series({pd.Timestamp(r[0], unit="s", tz="UTC"): float(r[5]) for r in rows}).sort_index()
    return s[s.index < pd.Timestamp(TAG, tz="UTC")]


# ----------------------------------------------------------------------------- R3.1
def r31(m: Manifest) -> tuple[dict, pd.Series]:
    vol = gt_daily_usd_volume(POOL, m)
    dl = llama(LLAMA_SOLUSDC)
    idx = vol.index.intersection(dl.index)
    idx = idx[(idx >= pd.Timestamp(START, tz="UTC")) & (idx <= pd.Timestamp(END, tz="UTC"))]
    f_gt = vol.reindex(idx) * 0.0022 / dl.loc[idx, "tvlUsd"]
    f_dl = dl.loc[idx, "apyBase"] * LP_SHARE / 100 / 365
    ratio = float(f_gt.sum() / f_dl.sum())
    out = {"gt_first_day": str(vol.index[0].date()), "common_days": int(len(idx)),
           "first_common": str(idx[0].date()), "last_common": str(idx[-1].date()),
           "fees_gt_over_dl_ratio": ratio, "corr_daily": float(np.corrcoef(f_gt, f_dl)[0, 1]),
           "mean_abs_rel_diff_daily": float((f_gt / f_dl - 1).abs().median()),
           "verdict": "PASSE" if ratio >= 0.5 else "ELIMINE"}
    return out, f_gt


# ----------------------------------------------------------------------------- R3.2
def load_market():
    mb = Manifest("binance")
    sp = load_klines("spot", "SOLUSDT", "1h", month_range("2025-01", "2026-10"), mb)
    pp = load_klines("futures/um", "SOLUSDT", "1h", month_range("2025-01", "2026-10"), mb)
    fu = load_funding("SOLUSDT", month_range("2025-01", "2026-10"), mb)["rate"]
    idx = pd.date_range(f"{START} 00:00", f"{END} 23:00", freq="h", tz="UTC")
    spot = sp["close"].reindex(idx).ffill()
    perp = pp["close"].reindex(idx).ffill()
    perp_hi = pp["high"].reindex(idx).fillna(perp)
    fund = fu.groupby(fu.index.floor("h")).sum().reindex(idx).fillna(0.0)
    return idx, spot, perp, perp_hi, fund


def simulate_hedged_lp(idx, spot, perp, perp_hi, fund, fee_daily: pd.Series, rebal_h: int = 24,
                       cost_mult: float = 1.0, fee_mult: float = 1.0) -> dict:
    c_swap, c_tr, c_perp = (COSTS["swap"] * cost_mult, COSTS["transfer"] * cost_mult, COSTS["perp"] * cost_mult)
    f = fee_daily.reindex(idx.floor("D")).fillna(0.0).to_numpy() * fee_mult
    g = (1.0 + f) ** (1.0 / 24.0) - 1.0
    S, Pp, Hi, F = spot.to_numpy(), perp.to_numpy(), perp_hi.to_numpy(), fund.to_numpy()
    K = 1.0 + 1.0 / (2 * LEV)
    V = 1.0
    margin = K - V
    cost_acc = V / 2 * c_swap
    margin -= V / 2 * c_swap
    h = V / (2 * S[0])
    cost_acc += h * Pp[0] * c_perp
    margin -= h * Pp[0] * c_perp
    W = np.empty(len(idx))
    comp = {"fees": 0.0, "lp_price": 0.0, "hedge_price": 0.0, "funding": 0.0, "costs": cost_acc}
    liq = 0
    for t in range(len(idx)):
        if t > 0:
            v_before = V
            V = V * math.sqrt(S[t] / S[t - 1])
            comp["lp_price"] += V - v_before
            fee = V * g[t]
            V += fee
            comp["fees"] += fee
            worst = margin - h * (Hi[t] - Pp[t - 1])
            if worst < MMR * h * Hi[t]:
                liq += 1
            hp = -h * (Pp[t] - Pp[t - 1])
            margin += hp
            comp["hedge_price"] += hp
            fd = h * Pp[t] * F[t]  # short receives positive funding
            margin += fd
            comp["funding"] += fd
            if t % rebal_h == 0:
                Wt = V + margin
                v_target = Wt / K
                dv = v_target - V
                c = abs(dv) * (c_swap / 2 + c_tr)
                V = v_target
                margin = Wt - V - c
                h_new = V / (2 * S[t])
                c += abs(h_new - h) * Pp[t] * c_perp
                margin -= abs(h_new - h) * Pp[t] * c_perp
                h = h_new
                comp["costs"] += c
        W[t] = V + margin
    exit_c = V / 2 * c_swap + h * Pp[-1] * c_perp
    W[-1] -= exit_c
    comp["costs"] += exit_c
    w = pd.Series(W, index=idx)
    daily = w.resample("1D").last()
    ret = daily.pct_change().fillna(daily.iloc[0] / K - 1.0)
    return {"ret": ret, "components_per_capital": {k: v / K for k, v in comp.items()}, "liquidation_hours": liq,
            "final_wealth_per_capital": float(W[-1] / K)}


def excess_stats(ret: pd.Series, rf: pd.Series, a: str, b: str) -> dict:
    x = ret.loc[a:b]
    rfx = rf.reindex(x.index).ffill().bfill() / 365.0
    exc = (x - rfx).dropna()
    mex = (1 + exc).groupby(exc.index.tz_localize(None).to_period("M")).prod() - 1
    lo, hi, _ = stats.bootstrap_ci(mex.to_numpy(), np.mean, mean_block=3.0, seed=SEED)
    s = stats.summarize(x.to_numpy())
    s.update({"ann_excess": float(exc.mean() * 365), "rf_ann": float(rfx.mean() * 365),
              "monthly_excess_mean": float(mex.mean()), "monthly_excess_ci95": [lo, hi], "months": int(len(mex))})
    return s


def r32(f_gt: pd.Series) -> dict:
    idx, spot, perp, perp_hi, fund = load_market()
    rf = rf_daily()
    dl = llama(LLAMA_SOLUSDC)
    f_dl = dl["apyBase"] * LP_SHARE / 100 / 365
    runs = {}
    for name, kw in {"primary_24h": {}, "rebal_4h": {"rebal_h": 4}, "rebal_1h": {"rebal_h": 1},
                     "costs_x2": {"cost_mult": 2.0}, "fees_x0.5": {"fee_mult": 0.5}}.items():
        sim = simulate_hedged_lp(idx, spot, perp, perp_hi, fund, f_dl, **kw)
        runs[name] = {"full": excess_stats(sim["ret"], rf, START, END),
                      "recent_half": excess_stats(sim["ret"], rf, *RECENT),
                      "components_per_capital": sim["components_per_capital"],
                      "liquidation_hours": sim["liquidation_hours"], "final_wealth": sim["final_wealth_per_capital"]}
    # alternative fee source on its own coverage
    a0 = str(f_gt.index[0].date())
    sim = simulate_hedged_lp(idx, spot, perp, perp_hi, fund, f_gt)
    sim_dl_same = simulate_hedged_lp(idx, spot, perp, perp_hi, fund, f_dl.where(f_dl.index >= f_gt.index[0], 0.0))
    runs["fee_source_gt"] = {"coverage_start": a0, "window": excess_stats(sim["ret"], rf, a0, END),
                             "same_window_dl": excess_stats(sim_dl_same["ret"], rf, a0, END)}
    p = runs["primary_24h"]
    crit = {"a_excess_gt0_ci_gt0": p["full"]["ann_excess"] > 0 and p["full"]["monthly_excess_ci95"][0] > 0,
            "b_costs_x2_excess_gt0": runs["costs_x2"]["full"]["ann_excess"] > 0,
            "c_gt_fee_source_excess_gt0": runs["fee_source_gt"]["window"]["ann_excess"] > 0,
            "d_recent_half_excess_gt0": p["recent_half"]["ann_excess"] > 0,
            "e_maxdd_lt_15pct": p["full"]["max_dd"] < 0.15}
    return {"runs": runs, "criteria": crit, "verdict": "SURVIT" if all(crit.values()) else "ELIMINE"}


# ----------------------------------------------------------------------------- R3.3
def r33(m: Manifest) -> dict:
    pools = json.loads((DATA_DIR / "json" / f"defillama_pools_{TAG}.json").read_text())["data"]
    uni = [p for p in pools if p["chain"] == "Solana" and p["project"] == "raydium-amm"
           and (p.get("poolMeta") or "") == "Standard - 0.25%" and p["tvlUsd"] >= 250_000]
    rows = []
    for p in sorted(uni, key=lambda x: -x["tvlUsd"]):
        mints = p.get("underlyingTokens") or []
        rec = {"symbol": p["symbol"], "llama_pool": p["pool"], "tvl_now": p["tvlUsd"]}
        if len(mints) != 2:
            rec["status"] = "mints_absents"
            rows.append(rec)
            continue
        try:
            d = json_get("https://api-v3.raydium.io/pools/info/mint", m, f"raydium_mint_{p['pool']}_{TAG}.json",
                         params={"mint1": mints[0], "mint2": mints[1], "poolType": "standard",
                                 "poolSortField": "liquidity", "sortType": "desc", "pageSize": "10", "page": "1"})
            cands = [x for x in d["data"]["data"] if x["programId"] == AMM_V4 and abs(x["feeRate"] - 0.0025) < 1e-9]
            if not cands:
                rec["status"] = "pas_de_pool_amm_v4"
                rows.append(rec)
                continue
            addr = cands[0]["id"]
            cached = (DATA_DIR / "json" / f"gt_ohlcv_day1000_{addr}_{TAG}.json").exists()
            gt = gt_daily(addr, m)
            if not cached:
                time.sleep(2.2)
            ch = json_get(f"https://yields.llama.fi/chart/{p['pool']}", m, f"llama_chart_u_{p['pool']}_{TAG}.json")
        except RuntimeError as e:
            rec["status"] = f"erreur_source: {str(e)[:80]}"
            rows.append(rec)
            continue
        dl = pd.DataFrame(ch["data"])
        dl.index = pd.to_datetime(dl["timestamp"]).dt.floor("D")
        dl = dl[~dl.index.duplicated(keep="last")]
        r = np.log(gt["c"].where(gt["c"] > 0)).diff()
        idx = dl.index.intersection(r.dropna().index)
        idx = idx[(idx >= pd.Timestamp("2025-01-23", tz="UTC")) & (idx <= pd.Timestamp(END, tz="UTC"))]
        rec.update({"address": addr, "days": int(len(idx))})
        if len(idx) < 60:
            rec["status"] = "historique_<60j"
            rows.append(rec)
            continue
        fee = (dl.loc[idx, "apyBase"].astype(float).fillna(0.0) * LP_SHARE / 100 / 365)
        lvr = r.reindex(idx) ** 2 / 8.0
        edge = fee - lvr
        rec.update({"status": "ok", "fee_ann": float(fee.mean() * 365), "lvr_ann": float(lvr.mean() * 365),
                    "edge_ann": float(edge.mean() * 365), "sigma_d": float(r.reindex(idx).std()),
                    "first": str(idx[0].date())})
        rows.append(rec)
    ok = [x for x in rows if x.get("status") == "ok"]
    e = np.array([x["edge_ann"] for x in ok])
    rng = np.random.default_rng(SEED)
    meds = [np.median(rng.choice(e, len(e), replace=True)) for _ in range(5000)]
    w = np.array([x["tvl_now"] for x in ok])
    return {"universe_size": len(uni), "evaluated": len(ok), "median_edge_ann": float(np.median(e)),
            "median_ci95": [float(np.quantile(meds, 0.025)), float(np.quantile(meds, 0.975))],
            "share_positive": float(np.mean(e > 0)), "tvl_weighted_edge_ann": float(np.sum(e * w) / np.sum(w)),
            "verdict": "GENERALE" if np.quantile(meds, 0.025) > 0 else "LIMITEE (pas de généralité démontrée)",
            "pools": rows}


# ----------------------------------------------------------------------------- R3.4
def r34() -> dict:
    mb = Manifest("binance")
    h = load_klines("spot", "SOLUSDT", "1h", month_range("2025-01", "2026-10"), mb)
    lr = np.log(h["close"]).diff()
    rv = (lr ** 2).groupby(lr.index.floor("D")).sum()
    dl = llama(LLAMA_SOLUSDC)
    idx = dl.index.intersection(rv.index)
    idx = idx[(idx >= pd.Timestamp("2025-01-23", tz="UTC")) & (idx <= pd.Timestamp(END, tz="UTC"))]
    fee = dl.loc[idx, "apyBase"] * LP_SHARE / 100 / 365
    edge = fee - rv.reindex(idx) / 8
    top = fee >= fee.quantile(0.95)
    return {"days": int(len(idx)), "edge_ann": float(edge.mean() * 365),
            "share_of_edge_from_top5pct_fee_days": float(edge[top].sum() / edge.sum()),
            "edge_ann_excluding_top5pct": float(edge[~top].mean() * 365),
            "rolling_90d_edge_ann_min": float(edge.rolling(90).mean().min() * 365),
            "rolling_90d_edge_ann_last": float(edge.rolling(90).mean().iloc[-1] * 365),
            "by_quarter_edge_ann": {str(k): float(v * 365) for k, v in
                                    edge.groupby(edge.index.tz_localize(None).to_period("Q")).mean().items()}}


# ----------------------------------------------------------------------------- R3.1b
def r31b() -> dict:
    files = sorted((DATA_DIR / "live").glob("raydium_*.jsonl.gz"))
    if not files:
        return {"status": "pas de fichier"}
    recs = []
    with gzip.open(files[-1], "rt") as fh:
        lines = []
        try:
            for line in fh:
                lines.append(line)
        except EOFError:  # file still being written: keep complete lines only
            pass
        for line in lines:
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                break
    df = pd.DataFrame([r for r in recs if r.get("http") == 200 and r.get("lpAmount")])
    df["t"] = pd.to_datetime(df["t_recv"], unit="s", utc=True)
    df["sqrtk_per_lp"] = np.sqrt(df["mintAmountA"] * df["mintAmountB"]) / df["lpAmount"]
    first, last = df.iloc[0], df.iloc[-1]
    growth = float(last["sqrtk_per_lp"] / first["sqrtk_per_lp"] - 1)
    m = Manifest("raydium_gecko")
    mins = json_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{POOL}/ohlcv/minute", m,
                    f"gt_ohlcv_min_{POOL}_{int(last['t_recv'])}.json",
                    params={"aggregate": "1", "limit": "1000", "currency": "usd"}, refresh=True)
    m.save()
    mv = pd.Series({pd.Timestamp(r[0], unit="s", tz="UTC"): float(r[5]) for r in mins["data"]["attributes"]["ohlcv_list"]})
    w = mv[(mv.index >= first["t"].floor("min")) & (mv.index < last["t"].floor("min"))]
    vol = float(w.sum())
    tvl = float(df["tvl"].mean())
    implied = {"fee_0.25": vol * 0.0025 / tvl, "fee_0.22": vol * 0.0022 / tvl}
    return {"file": files[-1].name, "samples": int(len(df)), "window_minutes": float((last["t"] - first["t"]).total_seconds() / 60),
            "lp_supply_change": float(last["lpAmount"] / first["lpAmount"] - 1),
            "sqrtk_per_lp_growth": growth, "gt_volume_usd_window": vol, "implied_growth": implied,
            "ratio_measured_over_0.22": growth / implied["fee_0.22"] if implied["fee_0.22"] else float("nan"),
            "note": "fenêtre courte : ordre de grandeur et part LP, pas une estimation de rendement"}


def main():
    m = Manifest("raydium_gecko")
    if len(sys.argv) > 1 and sys.argv[1] == "r31b":
        out = json.loads((RESULTS_DIR / "R3_lp_refutation.json").read_text())
        out["R3.1b"] = r31b()
        (RESULTS_DIR / "R3_lp_refutation.json").write_text(json.dumps(out, indent=1, default=str))
        print(json.dumps(out["R3.1b"], indent=1))
        return
    res = {"protocol": "R05_PREREGISTRATION_v2 §R3"}
    res["R3.1"], f_gt = r31(m)
    m.save()
    res["R3.2"] = r32(f_gt)
    res["R3.4"] = r34()
    res["R3.3"] = r33(m)
    m.save()
    (RESULTS_DIR / "R3_lp_refutation.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({"R3.1": res["R3.1"], "R3.2": [res["R3.2"]["verdict"], res["R3.2"]["criteria"]],
                      "R3.3": {k: v for k, v in res["R3.3"].items() if k != "pools"}, "R3.4": res["R3.4"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
