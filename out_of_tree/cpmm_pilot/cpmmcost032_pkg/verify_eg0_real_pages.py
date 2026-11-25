"""cpmmcost 0.3.2 (PROJECT) / E-G0: G-0 with and without the tolerance on anchored pre-T0 / pre-start pages (offline,
0 credit, no position, no P&L). python -B verify_eg0_real_pages.py LIST_L.json OUT.json ROOT [ROOT ...]"""
import hashlib
import json
import sys
from pathlib import Path

from cpmmcost import model as CC
from cpmmpilot.store import read_gz_page
from cpmmx import timeline as TL


def main(argv):
    list_l, out, roots = argv[0], argv[1], argv[2:]
    ll = json.loads(Path(list_l).read_text())
    rows = {r['pool']: r for r in ll['list']}
    res = dict(list_l_sha256=hashlib.sha256(Path(list_l).read_bytes()).hexdigest(), pools={})
    for root in roots:
        for d in sorted(Path(root).iterdir()):
            if not d.is_dir() or d.name not in rows:
                continue
            txs = {}
            for page in sorted(d.glob('page_*.json.gz')):
                for tx in read_gz_page(page).get('data') or []:
                    txs[tx['transaction']['signatures'][0]] = tx
            line = TL.build(d.name, txs, base_mint=rows[d.name]['base_mint'])
            cfg = dict(ll['configs'][rows[d.name]['config']], slot=ll['t0_slot'])
            cfg['sha256'] = cfg['raw_sha256']
            plain = CC.pool_gate(line, cfg)
            tol = CC.pool_gate(line, cfg, tolerance=dict(positions=CC.skipped_positions(line, txs), transactions=len(txs)))
            row = dict(transactions=len(txs), swaps=len(line.swaps), skipped=len(line.skipped),
                       g0_0_3_1=plain['reasons'], g0_e_g0=tol['reasons'], admitted_e_g0=tol['admitted'],
                       undecoded_tolerated=tol.get('undecoded_tolerated'))
            res['pools']['%s/%s' % (Path(root).parent.name, d.name)] = row
            print(d.name[:6], json.dumps(row))
    Path(out).write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main(sys.argv[1:])
