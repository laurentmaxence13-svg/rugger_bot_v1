import json, sys
from pathlib import Path
from cpmmgen2 import rule as G2
from livesim import sim as L
collect, llp = Path(sys.argv[1]), Path(sys.argv[2])
ll = json.loads(llp.read_text()); col = json.loads((collect / 'CONFIG.json').read_text())
q = json.loads((collect / 'QUALIFIED.json').read_text()); mint = {r['pool']: r['base_mint'] for r in ll['list']}
out = {}
for x in q['pools']:
    cfg = L.pool_config(ll, x)
    line, txs, _ = L.pre_pair(collect, x, mint[x], col['t_start'])
    new, _r = L.rebuilt(line, txs, L.pool_wsol_vault(ll, x), cfg)
    out[x] = dict(b3_A=G2.baseline_b3(line, txs, col['t_start']), b3_B=G2.baseline_b3(new, txs, col['t_start']))
print(json.dumps(out, indent=1))
