"""COUNT ONLY of the G2-1, G2-2 and G2-3 triggers (cpmmgen2 0.2, R01 9cd4e23, MANIFEST 70ef9a9b) on the A2r pre pages,
per pool and in total (R02 18:21Z). OFFLINE, 0 credit, no call. NO position, exit or return; no trial consumed.
G2-1: m1 = cpmmgen2.population_m1 over the 24 lines, then decisions_g21. G2-2: decisions_g22 entries (waits without
entry published). G2-3: baseline_b3 per pool from the collected transactions, then decisions_g23 (b3 = 0 -> excluded).
Counts restricted to [T0 - 7 d ; T0) by cpmmgen2.trigger_count. Same format as TRIGGERS_PER_POOL.json.
Usage: python -B g2_trigger_count.py <run dir STEP1A_...> <U2.json> <out.json>"""
import hashlib
import json
import sys
from pathlib import Path

from cpmmgen2 import rule as G
from cpmmpilot import step1

run, u2, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
doc = json.loads(u2.read_bytes())
sel, t0 = doc['selected'], doc['t0_time']
cfg = step1.amm_config_for_rules(sel, doc['t0_slot'])
lines = step1.timelines(run / 'step1', 'pre', sel)
txs = {r['pool']: step1.transactions_of(run / 'step1', 'pre', r['pool']) for r in sel}
m1 = G.population_m1(lines, cfg, t0)
g21 = G.trigger_count(lambda line: G.decisions_g21(line, cfg, m1), lines, t0)
waits = {}


def g22(line):
    entries, empty = G.decisions_g22(line, cfg)
    waits[line.pool] = empty
    return entries


g22c = G.trigger_count(g22, lines, t0)
b3 = {line.pool: G.baseline_b3(line, txs[line.pool], t0) for line in lines}
g23 = G.trigger_count(lambda line: G.decisions_g23(line, txs[line.pool], b3[line.pool]), lines, t0)
per_pool = {line.pool: dict(g2_1=g21['per_pool'][line.pool], g2_2=g22c['per_pool'][line.pool],
                            g2_2_waits_without_entry=waits[line.pool], g2_3=g23['per_pool'][line.pool],
                            g2_3_b3=b3[line.pool], g2_3_excluded_b3_zero=b3[line.pool] == 0,
                            swaps=len(line.swaps)) for line in lines}
res = dict(schema='g2-trigger-count-v1', stamp='COMPTAGE SEUL - aucun rendement, aucun essai', cpmmgen2=G.SCHEMA,
           t0=t0, window=g21['window'], m1=m1, per_pool=per_pool,
           total=dict(g2_1=g21['triggers'], g2_2=g22c['triggers'], g2_2_waits_without_entry=sum(waits.values()),
                      g2_3=g23['triggers'], g2_3_pools_excluded_b3_zero=sum(v == 0 for v in b3.values())),
           outcomes_computed=False)
out.write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
print(json.dumps(res['total']), 'm1', m1)
print('out_sha256', hashlib.sha256(out.read_bytes()).hexdigest())
