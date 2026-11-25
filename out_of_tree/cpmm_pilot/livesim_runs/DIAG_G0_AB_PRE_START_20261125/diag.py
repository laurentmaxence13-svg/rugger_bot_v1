"""Diagnostic 0 crédit (R04 13:58Z) : G-0 variante A (cpmmcost 0.3.1) vs B (+ cpmmrecon 0.1), pages pré-départ / pré-T0
seulement. Aucun rendement calculé."""
import json, sys
from collections import Counter
from pathlib import Path
from cpmmcost import model as CC
from cpmmpilot import step1 as PILOT
from livesim import sim as L
from g23run import run as GR
from cpmmx import timeline as TL

out = {}
def one(tag, pool, line, txs, cfg, wsol):
    a = CC.pool_gate(line, cfg)
    new, rep = L.rebuilt(line, txs, wsol, cfg)
    b = CC.pool_gate(new, cfg)
    out[tag] = dict(pool=pool, transactions=len(txs), swaps=len(line.swaps), undecoded=len(line.skipped),
                    undecoded_reasons=dict(Counter(r for _s, r in line.skipped)),
                    rebuilt=rep['rebuilt'], kept=rep['kept'], still_undecoded=len(new.skipped),
                    A=dict(admitted=a['admitted'], reasons=a['reasons'], breaks=a['continuity_breaks']),
                    B=dict(admitted=b['admitted'], reasons=b['reasons'], breaks=b['continuity_breaks']))

collect, list_l_path, pre_pages, u2_path = map(Path, sys.argv[1:5])
ll = json.loads(list_l_path.read_text())
col = json.loads((collect / 'CONFIG.json').read_text()); q = json.loads((collect / 'QUALIFIED.json').read_text())
mint = {r['pool']: r['base_mint'] for r in ll['list']}
for x in q['pools']:
    cfg = L.pool_config(ll, x)
    line, txs, _sha = L.pre_pair(collect, x, mint[x], col['t_start'])
    one('demo/' + x, x, line, txs, cfg, L.pool_wsol_vault(ll, x))
u2 = json.loads(u2_path.read_text())
rows = [r for r in u2['selected'] if r['pool'] in GR.POOLS]
config = PILOT.amm_config_for_rules(rows, u2['t0_slot'])
for r in rows:
    if r['pool'] not in ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh',
                         'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A', 'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr'):
        continue
    line, txs = GR.window_line(r['pool'], r['base_mint'], pre_pages / r['pool'], start=0, end=u2['t0_time'])
    one('pilot/' + r['pool'], r['pool'], line, txs, config, r['wsol_vault'])
print(json.dumps(out, indent=1, sort_keys=True))
