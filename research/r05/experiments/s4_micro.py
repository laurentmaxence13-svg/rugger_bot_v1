"""S4-A markouts (Binance aggTrades), S4-B quoted spreads vs maker fees, S1-C cross-venue
and DEX-CEX executable gaps (live snapshot). R05_PREREGISTRATION_v1 §3 (S1-C) and §5.
Fee schedules are base-tier HYPOTHESES (public grids), to re-check before any PAPER run.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.fetch_binance import MM_SYMBOLS, mm_dates
from r05lab import micro
from r05lab.data import DATA_DIR, RESULTS_DIR

MAKER = {"okx": 8.0, "okx_swap": 2.0, "coinbase": 60.0, "kraken": 25.0, "hyperliquid": 1.5, "binance_spot": 10.0,
         "binance_spot_bnb": 7.5, "binance_perp": 2.0}
TAKER = {"okx": 10.0, "coinbase": 120.0, "kraken": 40.0, "hyperliquid": 4.5}
TAKER_BEST = {"okx": 1.5, "coinbase": 5.0, "kraken": 8.0}  # top public tiers (hypothesis), sensitivity only
CTVAL = {"BTC-USDT-SWAP": 0.01, "SOL-USDT-SWAP": 1.0}
KRAKEN = {"XXBTZUSD": "BTC", "XETHZUSD": "ETH", "SOLUSD": "SOL", "USDTZUSD": "USDT", "USDCUSD": "USDC",
          "WIFUSD": "WIF", "BONKUSD": "BONK", "JTOUSD": "JTO"}


# ------------------------------------------------------------------ S4-A
def run_s4a() -> dict:
    out = {}
    for s in MM_SYMBOLS:
        for d in mm_dates():
            p = DATA_DIR / "binance" / "spot" / "daily" / "aggTrades" / s / f"{s}-aggTrades-{d}.zip"
            if not p.exists():
                out[f"{s}_{d}"] = {"status": "missing"}
                continue
            df = micro.read_aggtrades_zip(p)
            m = micro.markouts(df)
            m["notional_usd_day"] = float((df["price"] * df["qty"]).sum())
            out[f"{s}_{d}"] = m
    summ = {}
    for s in MM_SYMBOLS:
        recs = [v for k, v in out.items() if k.startswith(s) and "h10s" in v]
        if not recs:
            continue
        row = {"days": len(recs), "half_spread_bps_median": float(np.median([r["half_spread_bps_median"] for r in recs]))}
        for h in ("h1s", "h10s", "h60s", "h300s"):
            row[f"{h}_opt_bps"] = float(np.mean([r[h]["opt_mean_bps"] for r in recs]))
            row[f"{h}_pes_bps"] = float(np.mean([r[h]["pes_mean_bps"] for r in recs]))
        row["net_pes_10s_vip0_bps"] = row["h10s_pes_bps"] - MAKER["binance_spot"]
        row["net_pes_10s_perp_maker_bps"] = row["h10s_pes_bps"] - MAKER["binance_perp"]
        row["breakeven_maker_fee_bps"] = row["h10s_pes_bps"]
        row["verdict"] = "VIABLE" if row["net_pes_10s_vip0_bps"] > 0 else "ABANDON (palier VIP0)"
        summ[s] = row
    return {"by_day": out, "summary": summ}


# ------------------------------------------------------------------ snapshot parsing
def _f(x):
    return float(x)


def top_and_depth(venue: str, sym: str, body, level: str | None = None):
    """Returns (bid, ask, bid_depth_usd_10bp, ask_depth_usd_10bp) in quote units; None if unusable."""
    try:
        if venue == "okx":
            b = body["data"][0]
            bids = [(_f(x[0]), _f(x[1]) * CTVAL.get(sym, 1.0)) for x in b["bids"]]
            asks = [(_f(x[0]), _f(x[1]) * CTVAL.get(sym, 1.0)) for x in b["asks"]]
        elif venue == "coinbase":
            bids = [(_f(x[0]), _f(x[1])) for x in body["bids"]]
            asks = [(_f(x[0]), _f(x[1])) for x in body["asks"]]
        elif venue == "kraken":
            k = list(body["result"].values())[0]
            bids = [(_f(x[0]), _f(x[1])) for x in k["bids"]]
            asks = [(_f(x[0]), _f(x[1])) for x in k["asks"]]
        elif venue == "hyperliquid":
            bids = [(_f(x["px"]), _f(x["sz"])) for x in body["levels"][0]]
            asks = [(_f(x["px"]), _f(x["sz"])) for x in body["levels"][1]]
        else:
            return None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not bids or not asks:
        return None
    bid, ask = bids[0][0], asks[0][0]
    mid = 0.5 * (bid + ask)
    full = venue != "coinbase" or level == "2"
    dbid = sum(p * q for p, q in bids if p >= mid * (1 - 1e-3)) if full else float("nan")
    dask = sum(p * q for p, q in asks if p <= mid * (1 + 1e-3)) if full else float("nan")
    return bid, ask, dbid, dask


def parse_snapshot(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    rows, jup, sync = [], [], []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                break  # truncated last line if the run was cut; recorded by round count
            res = d["results"]
            ok = [r for r in res if r["http"] == 200]
            if ok:
                sync.append(max(r["t_recv"] for r in ok) - min(r["t_send"] for r in ok))
            for r in res:
                if r["http"] != 200:
                    rows.append({"round": d["round"], "venue": r["venue"], "sym": r["sym"], "ok": False})
                    continue
                if r["venue"] == "kraken" and r["sym"] == "TICKER":
                    for pair, v in r["body"]["result"].items():
                        a = KRAKEN.get(pair, pair)
                        rows.append({"round": d["round"], "venue": "kraken_ticker", "sym": a, "ok": True,
                                     "bid": _f(v["b"][0]), "ask": _f(v["a"][0]), "t": r["t_recv"]})
                    continue
                if r["venue"] == "jupiter":
                    b = r["body"]
                    jup.append({"round": d["round"], "sym": r["sym"], "in": int(b["inAmount"]), "out": int(b["outAmount"]),
                                "impact": float(b.get("priceImpactPct") or 0), "t": r["t_recv"],
                                "route": "+".join(x["swapInfo"].get("label", "?") for x in b.get("routePlan", []))})
                    continue
                td = top_and_depth(r["venue"], r["sym"], r["body"], r.get("level"))
                if td is None:
                    rows.append({"round": d["round"], "venue": r["venue"], "sym": r["sym"], "ok": False})
                    continue
                bid, ask, db, da = td
                rows.append({"round": d["round"], "venue": r["venue"], "sym": r["sym"], "ok": True, "bid": bid,
                             "ask": ask, "depth_bid_10bp": db, "depth_ask_10bp": da, "t": r["t_recv"]})
    return pd.DataFrame(rows), pd.DataFrame(jup), sync


def asset_of(venue, sym):
    s = sym.replace("-USDT-SWAP", "").replace("-USDT", "").replace("-USDC", "").replace("-USD", "")
    s = {"XBTUSD": "BTC", "SOLUSD": "SOL"}.get(s, s)
    return s


def run_s4b_s1c(path: Path) -> dict:
    df, jup, sync = parse_snapshot(path)
    ok = df[df["ok"]].copy()
    ok["mid"] = 0.5 * (ok["bid"] + ok["ask"])
    ok["spread_bps"] = (ok["ask"] - ok["bid"]) / ok["mid"] * 1e4
    ok["asset"] = [asset_of(v, s) for v, s in zip(ok["venue"], ok["sym"])]
    res = {"file": path.name, "rounds": int(df["round"].max() + 1), "requests": int(len(df)),
           "failed_requests": int((~df["ok"]).sum()),
           "round_sync_s_median": float(np.median(sync)), "round_sync_s_p95": float(np.quantile(sync, 0.95))}
    # S4-B quoted spread vs maker fee
    sp = []
    for (v, s), g in ok[ok["venue"] != "kraken_ticker"].groupby(["venue", "sym"]):
        fee_key = "okx_swap" if s.endswith("SWAP") else v
        if s in ("USDC-USDT", "USDT-USD"):
            continue
        hs = 0.5 * g["spread_bps"].median()
        sp.append({"venue": v, "sym": s, "n": int(len(g)), "spread_bps_median": float(g["spread_bps"].median()),
                   "spread_bps_p90": float(g["spread_bps"].quantile(0.9)),
                   "depth_10bp_quote_median": float(np.nanmedian((g["depth_bid_10bp"] + g["depth_ask_10bp"]) / 2)),
                   "maker_fee_bps": MAKER[fee_key], "half_spread_minus_maker_bps": float(hs - MAKER[fee_key])})
    res["S4B_spreads"] = sp
    # USD conversion per round: USDT/USD and USDC/USD from Kraken ticker mids
    kt = ok[ok["venue"] == "kraken_ticker"].pivot_table(index="round", columns="sym", values="mid")
    conv = {"USDT": kt.get("USDT"), "USDC": kt.get("USDC")}
    # S1-C cross-venue spot gaps (BTC, ETH, SOL) in USD
    legs = []
    for _, r in ok.iterrows():
        if r["sym"].endswith("SWAP") or r["venue"] in ("hyperliquid", "kraken_ticker"):
            continue
        if r["asset"] not in ("BTC", "ETH", "SOL"):
            continue
        q = "USD" if r["venue"] in ("coinbase", "kraken") else r["sym"].split("-")[1]
        fx = 1.0 if q == "USD" else (conv[q].get(r["round"]) if conv[q] is not None else np.nan)
        legs.append({"round": r["round"], "asset": r["asset"], "venue": f"{r['venue']}:{r['sym']}", "fee": TAKER.get(r["venue"], np.nan),
                     "fee_best": TAKER_BEST.get(r["venue"], np.nan), "bid": r["bid"] * fx, "ask": r["ask"] * fx})
    L = pd.DataFrame(legs).dropna(subset=["bid", "ask"])
    arb = []
    for (rd, a), g in L.groupby(["round", "asset"]):
        mid = np.median(0.5 * (g["bid"] + g["ask"]))
        best_gross, best_net, best_net_besttier = -np.inf, -np.inf, -np.inf
        for _, s in g.iterrows():
            for _, b in g.iterrows():
                if s["venue"] == b["venue"]:
                    continue
                gross = (s["bid"] - b["ask"]) / mid * 1e4
                best_gross = max(best_gross, gross)
                best_net = max(best_net, gross - s["fee"] - b["fee"])
                best_net_besttier = max(best_net_besttier, gross - s["fee_best"] - b["fee_best"])
        arb.append({"round": rd, "asset": a, "gross_bps": best_gross, "net_bps": best_net, "net_best_tier_bps": best_net_besttier})
    A = pd.DataFrame(arb)
    res["S1C_cross_venue"] = {a: {"n": int(len(g)), "gross_bps_median": float(g["gross_bps"].median()),
                                  "gross_bps_max": float(g["gross_bps"].max()),
                                  "share_gross_pos": float((g["gross_bps"] > 0).mean()),
                                  "share_net_pos_base_tier": float((g["net_bps"] > 0).mean()),
                                  "share_net_pos_best_tier": float((g["net_best_tier_bps"] > 0).mean()),
                                  "net_best_tier_bps_max": float(g["net_best_tier_bps"].max())}
                              for a, g in A.groupby("asset")}
    # S1-C DEX-CEX: Jupiter effective price vs CEX mid (median of OKX SOL-USDC, Coinbase SOL-USD, Kraken SOL)
    sol = ok[(ok["asset"] == "SOL") & ~ok["sym"].str.endswith("SWAP") & (ok["venue"] != "hyperliquid")].copy()
    cex_mid = sol.groupby("round")["mid"].median()
    jr = []
    for _, j in jup.iterrows():
        side, size = j["sym"].split(":")
        if side == "SOL->USDC":
            px = (j["out"] / 1e6) / (j["in"] / 1e9)
            ref = cex_mid.get(j["round"])
            cost = (ref - px) / ref * 1e4 if ref else np.nan  # selling SOL below mid = cost
        else:
            px = (j["in"] / 1e6) / (j["out"] / 1e9)
            ref = cex_mid.get(j["round"])
            cost = (px - ref) / ref * 1e4 if ref else np.nan
        jr.append({"side": side, "size": size, "cost_vs_cex_mid_bps": cost, "impact_pct": j["impact"], "route": j["route"]})
    J = pd.DataFrame(jr)
    res["S1C_dex_vs_cex"] = [{"side": s, "size": z, "n": int(len(g)), "cost_bps_median": float(g["cost_vs_cex_mid_bps"].median()),
                              "cost_bps_min": float(g["cost_vs_cex_mid_bps"].min()),
                              "share_better_than_cex_mid": float((g["cost_vs_cex_mid_bps"] < 0).mean()),
                              "top_route": g["route"].mode().iloc[0] if len(g) else ""}
                             for (s, z), g in J.groupby(["side", "size"], sort=False)]
    return res


def write_md(r):
    L = ["# S4 / S1-C — Microstructure : market making et arbitrage spatial", "",
         "Frais = **HYPOTHÈSES** de grilles publiques de base, à revérifier. Markouts = bornes optimistes "
         "(pas de latence, pas de course à l'annulation, pas de limite d'inventaire).", "",
         "## S4-A — markouts sur transactions réelles Binance spot (3 jours tirés au sort : "
         + ", ".join(mm_dates()) + ")", "",
         "| Actif | Demi-spread médian (pb) | Markout 1 s opt./pess. | 10 s opt./pess. | 60 s opt./pess. | 300 s opt./pess. | Net 10 s pess. VIP0 (10 pb) | Frais maker de point mort (pb) | Verdict |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s, v in r["S4A"]["summary"].items():
        L.append(f"| {s} | {v['half_spread_bps_median']:.2f} | {v['h1s_opt_bps']:.2f} / {v['h1s_pes_bps']:.2f} | "
                 f"{v['h10s_opt_bps']:.2f} / {v['h10s_pes_bps']:.2f} | {v['h60s_opt_bps']:.2f} / {v['h60s_pes_bps']:.2f} | "
                 f"{v['h300s_opt_bps']:.2f} / {v['h300s_pes_bps']:.2f} | {v['net_pes_10s_vip0_bps']:.2f} | "
                 f"{v['breakeven_maker_fee_bps']:.2f} | **{v['verdict']}** |")
    if "snapshot" in r:
        s = r["snapshot"]
        L += ["", f"## S4-B — spreads affichés vs frais maker (photographie {s['file']}, {s['rounds']} tours, "
              f"{s['failed_requests']} requêtes en échec sur {s['requests']}, désynchronisation médiane d'un tour "
              f"{s['round_sync_s_median']:.2f} s, p95 {s['round_sync_s_p95']:.2f} s)", "",
              "| Plateforme | Instrument | Spread médian (pb) | p90 (pb) | Profondeur médiane ±10 pb par côté (devise de cotation) | Frais maker (pb) | Demi-spread − maker (pb) |",
              "|---|---|---|---|---|---|---|"]
        for x in sorted(s["S4B_spreads"], key=lambda x: (x["venue"], x["sym"])):
            dq = x["depth_10bp_quote_median"]
            L.append(f"| {x['venue']} | {x['sym']} | {x['spread_bps_median']:.2f} | {x['spread_bps_p90']:.2f} | "
                     f"{'n/d (niveau 1)' if not np.isfinite(dq) else format(dq, ',.0f')} | {x['maker_fee_bps']:.1f} | {x['half_spread_minus_maker_bps']:.2f} |")
        L += ["", "## S1-C — meilleur écart exécutable entre plateformes (achat ask / vente bid, en USD)", "",
              "| Actif | Instantanés | Écart brut médian (pb) | max (pb) | Part brut > 0 | Part net > 0 (frais de base) | Part net > 0 (meilleurs paliers) | Net max meilleurs paliers (pb) |",
              "|---|---|---|---|---|---|---|---|"]
        for a, v in s["S1C_cross_venue"].items():
            L.append(f"| {a} | {v['n']} | {v['gross_bps_median']:.2f} | {v['gross_bps_max']:.2f} | {v['share_gross_pos'] * 100:.0f} % | "
                     f"{v['share_net_pos_base_tier'] * 100:.0f} % | {v['share_net_pos_best_tier'] * 100:.0f} % | {v['net_best_tier_bps_max']:.2f} |")
        L += ["", "### DEX (Jupiter) vs médiane des mids CEX, SOL", "",
              "| Sens | Taille | Devis | Coût médian vs mid CEX (pb) | Meilleur (pb) | Part meilleure que le mid CEX | Route la plus fréquente |",
              "|---|---|---|---|---|---|---|"]
        for x in s["S1C_dex_vs_cex"]:
            L.append(f"| {x['side']} | {x['size']} | {x['n']} | {x['cost_bps_median']:.2f} | {x['cost_bps_min']:.2f} | "
                     f"{x['share_better_than_cex_mid'] * 100:.0f} % | {x['top_route']} |")
    (RESULTS_DIR / "S4_S1C_micro.md").write_text("\n".join(L) + "\n")


def main():
    r = {"protocol": "R05_PREREGISTRATION_v1 §3 S1-C, §5", "maker_fees_bps": MAKER, "taker_fees_bps": TAKER,
         "S4A": run_s4a()}
    snaps = sorted((DATA_DIR / "live").glob("snap_*.jsonl.gz"))
    if snaps:
        r["snapshot"] = run_s4b_s1c(snaps[-1])
    (RESULTS_DIR / "S4_S1C_micro.json").write_text(json.dumps(r, indent=1, default=str))
    write_md(r)
    print(json.dumps(r["S4A"]["summary"], indent=1))


if __name__ == "__main__":
    main()
