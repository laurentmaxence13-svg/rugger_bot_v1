"""H2b — replication of PAPER-2's rule (TSMOM 30 d long/flat) on 18 untouched coins
(R05_PREREGISTRATION_v3). Daily Binance klines, CHECKSUM-verified."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from experiments.fetch_v3 import H2B
from experiments.r2_r1_refutation import placebo_positions
from r05lab import backtest, signals, stats
from r05lab.data import RESULTS_DIR, Manifest, load_klines, month_range

OOS = ("2023-01-01", "2026-10-31")
COST = 0.0012
SEED = 20261126


def main():
    m = Manifest("binance")
    nets, bh, held, rets, per = {}, {}, {}, {}, {}
    for c in H2B:
        s = f"{c}USDT"
        try:
            k = load_klines("spot", s, "1d", month_range("2017-08", "2026-10"), m)
        except RuntimeError:
            per[c] = {"status": "aucune donnée"}
            continue
        close = k["close"].loc[:"2026-10-31"]
        ret = close.pct_change()
        bt = backtest.run(signals.tsmom(close, 30, True), ret, COST)
        nets[c], bh[c], held[c], rets[c] = bt["net"], ret, bt["pos"], ret
        o_f1 = bt["net"].loc[OOS[0]:OOS[1]].dropna().to_numpy()
        o_bh = ret.loc[OOS[0]:OOS[1]].dropna().to_numpy()
        per[c] = {"first": str(close.index[0].date()), "last": str(close.index[-1].date()),
                  "oos_days": int(len(o_f1)),
                  "f1_sharpe": stats.sharpe(o_f1), "bh_sharpe": stats.sharpe(o_bh),
                  "f1_ann": stats.ann_return(o_f1), "bh_ann": stats.ann_return(o_bh),
                  "f1_dd": stats.max_drawdown(o_f1), "bh_dd": stats.max_drawdown(o_bh),
                  "full_f1_sharpe": stats.sharpe(bt["net"].dropna().to_numpy()),
                  "full_bh_sharpe": stats.sharpe(ret.dropna().to_numpy())}
    P = pd.DataFrame(nets).loc[OOS[0]:OOS[1]].mean(axis=1, skipna=True)
    B = pd.DataFrame(bh).loc[OOS[0]:OOS[1]].mean(axis=1, skipna=True)
    port = {"f1": stats.summarize(P.to_numpy()), "bh": stats.summarize(B.dropna().to_numpy())}
    # (b) placebo, segment permutation per coin on its own OOS availability
    target = stats.sharpe(P.to_numpy())
    rng = np.random.default_rng(SEED)
    srs = []
    for _ in range(2000):
        pn = {}
        for c in nets:
            h = held[c].loc[OOS[0]:OOS[1]]
            r = rets[c].loc[OOS[0]:OOS[1]]
            if len(h) < 30:
                continue
            hv = h.to_numpy()
            pv = placebo_positions(hv, rng)
            turn = np.abs(np.diff(np.concatenate([[hv[0]], pv])))
            pn[c] = pd.Series(pv * np.nan_to_num(r.to_numpy()) - turn * COST, index=h.index)
        srs.append(stats.sharpe(pd.DataFrame(pn).mean(axis=1, skipna=True).to_numpy()))
    srs = np.array(srs)
    ok = [v for v in per.values() if "f1_sharpe" in v and v["oos_days"] >= 180]
    share = float(np.mean([v["f1_sharpe"] > v["bh_sharpe"] for v in ok]))
    tests = {"a_dd_le_0.7_bh": port["f1"]["max_dd"] <= 0.7 * port["bh"]["max_dd"],
             "b_placebo_p": float(np.mean(srs >= target)), "b_pass": bool(np.mean(srs >= target) <= 0.05),
             "c_share_f1_beats_bh_sharpe": share, "c_pass": share >= 0.60,
             "D_ann_return_diff": port["f1"]["ann_return"] - port["bh"]["ann_return"],
             "placebo_median": float(np.median(srs)), "placebo_q95": float(np.quantile(srs, 0.95))}
    verdict = ("REPLIQUE" if tests["a_dd_le_0.7_bh"] and tests["b_pass"] and tests["c_pass"]
               else "PARTIEL" if tests["a_dd_le_0.7_bh"] else "NON REPLIQUE")
    res = {"protocol": "R05_PREREGISTRATION_v3 §H2b", "window": OOS, "coins_evaluated": len(ok),
           "portfolio": port, "tests": tests, "verdict": verdict, "per_coin": per}
    (RESULTS_DIR / "H2b_replication.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({"verdict": verdict, "tests": tests, "f1": {k: round(v, 3) for k, v in port["f1"].items() if isinstance(v, float)},
                      "bh": {k: round(v, 3) for k, v in port["bh"].items() if isinstance(v, float)}}, indent=1))
    for c, v in per.items():
        if "f1_sharpe" in v:
            print(c, v["first"], v["last"], v["oos_days"], "F1", round(v["f1_sharpe"], 2), round(v["f1_dd"], 2),
                  "BH", round(v["bh_sharpe"], 2), round(v["bh_dd"], 2))


if __name__ == "__main__":
    main()
