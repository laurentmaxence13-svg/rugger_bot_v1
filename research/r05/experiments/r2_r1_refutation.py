"""R2 (momentum 30 d refutation) and R1 (carry rejection counter-checks), per
R05_PREREGISTRATION_v2. Offline on verified data."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from experiments import s1_carry as s1
from experiments import s2_systematic as s2
from r05lab import backtest, signals, stats
from r05lab.data import RESULTS_DIR

OOS = ("2023-01-01", "2026-10-31")
SEED = 20261126
COST = s2.COST["spot"]


def f1_asset_nets(daily, L=30):
    nets, poss = {}, {}
    for s, d in daily.items():
        ret = d["close"].pct_change()
        pos = signals.tsmom(d["close"], L, True)
        bt = backtest.run(pos, ret, COST)
        nets[s], poss[s] = bt["net"], bt["pos"]
    return nets, poss


def port_sharpe(nets: dict, a=OOS[0], b=OOS[1]) -> float:
    return stats.sharpe(pd.DataFrame(nets).mean(axis=1).loc[a:b].dropna().to_numpy())


def runs(x: np.ndarray) -> list[tuple[float, int]]:
    out, i = [], 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[j + 1] == x[i]:
            j += 1
        out.append((x[i], j - i + 1))
        i = j + 1
    return out


def placebo_positions(held: np.ndarray, rng) -> np.ndarray:
    """Shuffle in-segments and out-segments separately, re-interleave alternately from the same
    starting state: exposure and number of position changes are preserved exactly."""
    r = runs(held)
    ins = [n for v, n in r if v > 0]
    outs = [n for v, n in r if v == 0]
    rng.shuffle(ins)
    rng.shuffle(outs)
    seq, first_in = [], r[0][0] > 0
    a, b = iter(ins), iter(outs)
    cur = first_in
    for _ in range(len(r)):
        n = next(a) if cur else next(b)
        seq += [1.0 if cur else 0.0] * n
        cur = not cur
    return np.array(seq)


def r21(daily, nets, poss) -> dict:
    target = port_sharpe(nets)
    rng = np.random.default_rng(SEED)
    oos_ret = {s: d["close"].pct_change().loc[OOS[0]:OOS[1]] for s, d in daily.items()}
    held = {s: poss[s].loc[OOS[0]:OOS[1]].to_numpy() for s in daily}
    srs = []
    for _ in range(2000):
        pn = {}
        for s in daily:
            h = placebo_positions(held[s], rng)
            r = oos_ret[s].to_numpy()
            turn = np.abs(np.diff(np.concatenate([[held[s][0]], h])))
            pn[s] = pd.Series(h * np.nan_to_num(r) - turn * COST, index=oos_ret[s].index)
        srs.append(stats.sharpe(pd.DataFrame(pn).mean(axis=1).to_numpy()))
    srs = np.array(srs)
    p = float(np.mean(srs >= target))
    return {"f1_oos_sharpe": target, "placebo_median": float(np.median(srs)),
            "placebo_q95": float(np.quantile(srs, 0.95)), "p_value": p, "n_placebo": 2000,
            "verdict": "PASSE" if p <= 0.05 else "ELIMINE"}


def r22(hourly, daily) -> dict:
    """Execution at the close of the following hour (01:00Z) vs at the daily close."""
    out = {}
    for lag in (0, 1):
        nets = {}
        for s, h in hourly.items():
            sig = signals.tsmom(daily[s]["close"], 30, True)  # decided at daily close of day d
            # daily bar d closes at the open of day d+1 00:00 ; hourly bar 23:00 of day d is its last bar
            stamp = sig.index + pd.Timedelta(hours=23 + lag)
            hp = pd.Series(sig.to_numpy(), index=stamp).reindex(h.index).ffill().fillna(0.0)
            bt = backtest.run(hp, h["close"].pct_change(), COST)
            nets[s] = backtest.to_daily(bt)
        out[f"lag_{lag}h"] = port_sharpe(nets)
    out["verdict"] = "PASSE" if out["lag_1h"] >= 0.5 else "ELIMINE"
    return out


def r23(nets) -> dict:
    out = {}
    for drop in nets:
        out[f"sans_{drop}"] = port_sharpe({k: v for k, v in nets.items() if k != drop})
    out["verdict"] = "PASSE" if all(v > 0 for v in out.values()) else "ELIMINE"
    return out


def r24(nets, bh) -> dict:
    p = pd.DataFrame(nets).mean(axis=1)
    out = {}
    for y in range(2023, 2027):
        a, b = f"{y}-01-01", f"{y}-12-31" if y < 2026 else "2026-10-31"
        out[str(y)] = {"f1_ret": stats.ann_return(p.loc[a:b].to_numpy()) if y < 2026 else float(np.prod(1 + p.loc[a:b]) - 1),
                       "f1_sharpe": stats.sharpe(p.loc[a:b].to_numpy()), "bh_sharpe": stats.sharpe(bh.loc[a:b].dropna().to_numpy()),
                       "f1_max_dd": stats.max_drawdown(p.loc[a:b].to_numpy()), "bh_max_dd": stats.max_drawdown(bh.loc[a:b].dropna().to_numpy())}
    return out


def r25(daily) -> dict:
    return {str(L): port_sharpe(f1_asset_nets(daily, L)[0]) for L in (20, 25, 30, 35, 40, 50, 60)}


def r1(spot, perp, fund, rf) -> dict:
    out = {}
    # R1.1 portfolio margin: capital 1.10 per unit notional
    nets = {}
    for s in s1.SYMS:
        pnl, f, idx = s1.carry_a(spot, perp, fund, s)
        nets[s] = backtest.run(pd.Series(1.0, index=idx), pnl / 1.10, s1.COST_A / 1.10)["net"]
    port = pd.DataFrame(nets).mean(axis=1)
    o = s1.period_stats(port, pd.Series(1.0, index=port.index), rf, *OOS)
    out["R1.1"] = {"capital": 1.10, "OOS": o, "verdict": "REOUVERTURE" if o["ann_excess_over_rf"] > 0 and
                   o["monthly_excess_ci95"][0] > 0 else "REJET CONFIRME"}
    # R1.2 post hoc: short Hyperliquid perp / long Binance spot, permanent, leverage 3
    nets, per = {}, {}
    for s, coin in s1.HL_COIN.items():
        hl_d, _, hl_close = s1.hl_series(coin)
        idx = hl_d.index.intersection(spot[s].index).intersection(hl_close.index)
        idx = idx[idx >= pd.Timestamp("2023-05-13", tz="UTC")]
        pnl = (spot[s].reindex(idx).pct_change() - hl_close.reindex(idx).pct_change() + hl_d.reindex(idx)).fillna(0.0)
        cost = (0.0010 + 0.0002) + (0.00045 + 0.0002)
        nets[s] = backtest.run(pd.Series(1.0, index=idx), pnl / s1.CAP_A, cost / s1.CAP_A)["net"]
        per[s] = {k: float(hl_d.reindex(idx).loc[a:b].mean() * 365) for k, (a, b) in s1.B_PERIODS.items()}
    port = pd.DataFrame(nets).mean(axis=1)
    out["R1.2_post_hoc"] = {"hl_funding_ann_by_period": per,
                            "by_period": {k: s1.period_stats(port, pd.Series(1.0, index=port.index), rf, a, b)
                                          for k, (a, b) in s1.B_PERIODS.items()},
                            "status": "DESCRIPTIF POST HOC — jugé seulement en prospectif (règle P-HL1)"}
    return out


def main():
    hourly, funding = s2.load_all()
    daily = {s: s2.to_daily_bars(h) for s, h in hourly.items()}
    bh = s2.bh_portfolio(daily)
    nets, poss = f1_asset_nets(daily)
    res = {"protocol": "R05_PREREGISTRATION_v2 §R2 §R1",
           "R2.1": r21(daily, nets, poss), "R2.2": r22(hourly, daily), "R2.3": r23(nets),
           "R2.4": r24(nets, bh), "R2.5_post_hoc": r25(daily)}
    res["R2_verdict"] = "SURVIT" if all(res[k]["verdict"] == "PASSE" for k in ("R2.1", "R2.2", "R2.3")) else "ELIMINE"
    spot, perp, fund, _ = s1.load()
    res.update(r1(spot, perp, fund, s1.rf_daily()))
    (RESULTS_DIR / "R2_R1_refutation.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "R1.2_post_hoc"}, indent=1, default=str)[:4000])
    print(json.dumps(res["R1.2_post_hoc"]["hl_funding_ann_by_period"]),
          {k: (round(v["ann_return"], 4), round(v["ann_excess_over_rf"], 4)) for k, v in res["R1.2_post_hoc"]["by_period"].items()})


if __name__ == "__main__":
    main()
