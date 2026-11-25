"""cpmmrecon 0.1: full-data check on anchored pre-T0 / pre-start pages (offline, 0 credit, no position, no P&L).
python -B verify_rebuild_real_pages.py LIST_L.json OUT.json ROOT [ROOT ...] -- G-0 (cpmmcost 0.3.1, unchanged) on the line
as cpmmx builds it, then on the rebuilt line."""
import collections
import hashlib
import json
import sys
from pathlib import Path

from cpmmcost import model as CC
from cpmmpilot.store import read_gz_page
from cpmmrecon import rebuild as RB
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
            if not line.skipped or not line.swaps:
                continue
            cfg = dict(ll['configs'][rows[d.name]['config']], slot=ll['t0_slot'])
            cfg['sha256'] = cfg['raw_sha256']
            fees = CC.fees_from_amm_config(cfg)
            try:
                side = CC.creator_side(line, len(line.swaps) - 1)
            except CC.CostError as exc:
                res['pools']['%s/%s' % (Path(root).parent.name, d.name)] = dict(error=str(exc))
                continue
            new, rep = RB.rebuild(line, txs, wsol_vault=rows[d.name]['wsol_vault'], fees=fees, on_input=side)
            g_before, g_after = CC.pool_gate(line, cfg), CC.pool_gate(new, cfg)
            row = dict(skipped=len(line.skipped), outcomes=dict(collections.Counter(v.split(':')[0] if v.startswith('rebuilt')
                                                                                  else v for v in rep.values())),
                       rebuilt_swaps=len(new.swaps) - len(line.swaps), still_skipped=len(new.skipped),
                       g0_before=g_before['reasons'], g0_after=g_after['reasons'],
                       breaks_before=g_before.get('continuity_breaks'), breaks_after=g_after.get('continuity_breaks'),
                       exact_after='%s/%s' % (g_after.get('exact'), g_after.get('swaps')))
            res['pools']['%s/%s' % (Path(root).parent.name, d.name)] = row
            print(d.name[:6], json.dumps(row))
    Path(out).write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main(sys.argv[1:])
