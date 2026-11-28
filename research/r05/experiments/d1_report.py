"""D-1 report: direct LP fee accrual per pool from daily pool-state snapshots.

fee yield over an interval = growth of sqrt(x*y)/LP supply (constant-product pools only).
Intervals shorter than 12 h or longer than 48 h are not used (gaps are reported, never filled).
Compared with DefiLlama x LP share for SOL-USDC (PAPER-1 criterion 5: within +/-20 %).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "prospective" / "pool_state"
SOL_USDC = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"


def load_states(state_dir: Path = STATE) -> pd.DataFrame:
    rows = []
    for f in sorted(state_dir.rglob("state_*.json")):
        d = json.loads(f.read_text())
        for p in d["pools"]:
            if p.get("sqrtk_per_lp"):
                rows.append({"file": f.name, "t": pd.Timestamp(p["t_recv"], unit="s", tz="UTC"), "id": p["id"], "pair": p["pair"],
                             "k": p["sqrtk_per_lp"], "tvl": p["tvl"], "lp": p["lpAmount"]})
    return pd.DataFrame(rows)


def intervals(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for pid, g in df.sort_values("t").groupby("id"):
        g = g.reset_index(drop=True)
        for i in range(1, len(g)):
            hours = (g.loc[i, "t"] - g.loc[i - 1, "t"]).total_seconds() / 3600
            growth = g.loc[i, "k"] / g.loc[i - 1, "k"] - 1
            out.append({"id": pid, "pair": g.loc[i, "pair"], "start": g.loc[i - 1, "t"], "end": g.loc[i, "t"],
                        "hours": hours, "growth": growth, "usable": 12 <= hours <= 48,
                        "per_day": growth / hours * 24 if hours > 0 else np.nan})
    return pd.DataFrame(out)


def report(state_dir: Path = STATE) -> dict:
    df = load_states(state_dir)
    if df.empty:
        return {"status": "aucun instantané"}
    iv = intervals(df)
    res = {"snapshots": int(df["file"].nunique()), "first": str(df["t"].min()), "last": str(df["t"].max())}
    if iv.empty:
        res["status"] = "un seul instantané : pas encore d'intervalle"
        return res
    u = iv[iv["usable"]]
    res["intervals_total"] = int(len(iv))
    res["intervals_usable"] = int(len(u))
    res["negative_growth_intervals"] = int((u["growth"] < -1e-9).sum())  # should not happen on a CPMM
    by = u.groupby(["id", "pair"]).agg(days=("hours", lambda h: h.sum() / 24), fee_per_day=("per_day", "mean"))
    by["fee_ann"] = by["fee_per_day"] * 365
    res["pools"] = [{"id": i, "pair": p, "days": float(r.days), "direct_fee_ann": float(r.fee_ann)}
                    for (i, p), r in by.iterrows()]
    s = by.loc[by.index.get_level_values(0) == SOL_USDC]
    res["sol_usdc_direct_fee_ann"] = float(s["fee_ann"].iloc[0]) if len(s) else None
    return res


def main():
    r = report()
    (ROOT / "results" / "D1_direct_fees.json").write_text(json.dumps(r, indent=1, default=str))
    print(json.dumps({k: v for k, v in r.items() if k != "pools"}, indent=1, default=str))


if __name__ == "__main__":
    main()
