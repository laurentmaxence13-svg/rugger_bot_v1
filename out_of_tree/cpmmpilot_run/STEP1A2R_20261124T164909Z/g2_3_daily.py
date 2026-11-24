"""COUNT ONLY of the G2-3 triggers PER POOL AND PER UTC DAY over [T0 - 7 d ; T0) (R04 18:56Z, frame of f53f79f), for
the 5 pools with G2-3 triggers. OFFLINE, 0 credit, no call, NO position, exit or return, no trial. Same frozen functions
as g2_trigger_count.py (cpmmgen2 0.2: baseline_b3, decisions_g23); the only addition is the grouping of the decision
block times by UTC day. Check: the per-pool totals must equal G2_TRIGGERS_PER_POOL.json (119838726c...).
Usage: python -B g2_3_daily.py <run dir STEP1A_...> <U2.json> <G2_TRIGGERS_PER_POOL.json> <out.json>"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

from cpmmgen2 import rule as G
from cpmmpilot import step1

POOLS = ('AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc', '2yLFom')
run, u2, g2, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
doc = json.loads(u2.read_bytes())
t0 = doc['t0_time']
start = t0 - 7 * 86_400
ref = json.loads(g2.read_bytes())['per_pool']
sel = [r for r in doc['selected'] if r['pool'].startswith(POOLS)]
if len(sel) != len(POOLS):
    raise SystemExit('pools_not_found')
days = [datetime.datetime.fromtimestamp(start + k * 86_400, datetime.timezone.utc).strftime('%Y-%m-%d') for k in range(8)]
table, check = {}, {}
for r in sel:
    line = step1.timelines(run / 'step1', 'pre', [r])[0]
    txs = step1.transactions_of(run / 'step1', 'pre', r['pool'])
    b3 = G.baseline_b3(line, txs, t0)
    idx = [i for i in G.decisions_g23(line, txs, b3) if line.swaps[i].block_time >= start]
    per_day = {}
    for i in idx:
        d = datetime.datetime.fromtimestamp(line.swaps[i].block_time, datetime.timezone.utc).strftime('%Y-%m-%d')
        per_day[d] = per_day.get(d, 0) + 1
    table[r['pool']] = dict(b3=b3, total=len(idx), per_utc_day={d: per_day.get(d, 0) for d in days if d in per_day or True})
    check[r['pool']] = len(idx) == ref[r['pool']]['g2_3']
res = dict(schema='g2-3-daily-v1', stamp='COMPTAGE SEUL - aucun rendement, aucun essai', t0=t0, window=[start, t0],
           note='UTC days; the first and last days are partial ([T0 - 7 d ; T0) does not start at 00:00 UTC)',
           per_pool=table, totals_equal_f53f79f=check,
           total_per_utc_day={d: sum(v['per_utc_day'].get(d, 0) for v in table.values()) for d in days})
if not all(check.values()):
    res['WARNING'] = 'per-pool totals differ from G2_TRIGGERS_PER_POOL.json'
out.write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
print(json.dumps(res['total_per_utc_day']), json.dumps(check))
print('out_sha256', hashlib.sha256(out.read_bytes()).hexdigest())
