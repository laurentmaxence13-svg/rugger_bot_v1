import json, sys
from livesim import sim as L
from cpmmcost import model as CC
from cpmmgen2 import rule as G2
C, LL = sys.argv[1], sys.argv[2]
ll = json.load(open(LL)); col = L.collection(C)
row = {r['pool']: r for r in ll['list']}
out = {}
for x in col['pools']:
    line, txs, _ = L.pre_pair(C, x, row[x]['base_mint'], col['t_start'])
    cfg0 = dict(L.pool_config(ll, x), creator_fee_rate=0)          # DIAGNOSTIC ONLY, not the anchored config
    g = CC.pool_gate(line, cfg0)
    b3 = G2.baseline_b3(line, txs, col['t_start'])
    out[x] = dict(b3=b3, g0_admitted_if_creator_rate_0=g['admitted'], reasons_if_creator_rate_0=g['reasons'],
                  would_be_eligible=g['admitted'] and b3 > 0)
    print(x[:6], out[x])
print('would_be_eligible:', sum(v['would_be_eligible'] for v in out.values()))
json.dump(out, open(sys.argv[3], 'w'), indent=1, sort_keys=True)
