"""COUNT ONLY of the G2-3 triggers PER POOL AND PER DAY ALIGNED ON T0 (R02 rule 4e08d2a2: k = (t - (T0 - 7 d)) // 86 400,
k = 0..6, 7 complete days) over [T0 - 7 d ; T0) (R04 18:56Z, frame of f53f79f), for
the 5 pools with G2-3 triggers. OFFLINE, 0 credit, no call, NO position, exit or return, no trial. Same frozen functions
as g2_trigger_count.py (cpmmgen2 0.2: baseline_b3, decisions_g23); the only addition is the grouping of the decision
block times by day k aligned on T0 (no calendar day, no partial day). Check: the per-pool totals must equal G2_TRIGGERS_PER_POOL.json (119838726c...).
Usage: python -B g2_3_daily.py <run dir STEP1A_...> <U2.json> <G2_TRIGGERS_PER_POOL.json> <out.json>"""
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
table, check = {}, {}
for r in sel:
    line = step1.timelines(run / 'step1', 'pre', [r])[0]
    txs = step1.transactions_of(run / 'step1', 'pre', r['pool'])
    b3 = G.baseline_b3(line, txs, t0)
    idx = [i for i in G.decisions_g23(line, txs, b3) if line.swaps[i].block_time >= start]
    per_k = [0] * 7
    for i in idx:
        k = (line.swaps[i].block_time - start) // 86_400
        if not 0 <= k <= 6:
            raise SystemExit('decision_outside_the_7_days')
        per_k[k] += 1
    table[r['pool']] = dict(b3=b3, total=len(idx), per_day_k=per_k)
    check[r['pool']] = len(idx) == ref[r['pool']]['g2_3']
res = dict(schema='g2-3-daily-v2', stamp='COMPTAGE SEUL - aucun rendement, aucun essai', t0=t0, window=[start, t0],
           day_rule='R02 4e08d2a2: k = (t - (T0 - 7 x 86 400)) // 86 400, k = 0..6 (7 complete days aligned on T0)',
           note='2yLFom included for information only (excluded by the rule: 2 < 3)',
           per_pool=table, totals_equal_f53f79f=check,
           total_per_day_k=[sum(v['per_day_k'][k] for v in table.values()) for k in range(7)])
if not all(check.values()):
    res['WARNING'] = 'per-pool totals differ from G2_TRIGGERS_PER_POOL.json'
out.write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
print(json.dumps(res['total_per_day_k']), json.dumps(check))
print('out_sha256', hashlib.sha256(out.read_bytes()).hexdigest())
