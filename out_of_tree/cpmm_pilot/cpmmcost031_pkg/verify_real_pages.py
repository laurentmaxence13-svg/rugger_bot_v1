"""cpmmcost 0.3.1 / E-CF: full-data check on anchored pre-T0 / pre-start pages (offline, 0 credit, no position, no P&L).
python -B verify_real_pages.py LIST_L.json OUT.json ROOT [ROOT ...]   (ROOT/<pool>/page_*.json.gz)
For every pool: swaps; swaps logging a creator fee; exact swaps with the AmmConfig creator rate charged (as in 0.3) and
under 0.3.1; G-0 reasons under 0.3.1."""
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
            row = dict(root=str(Path(root).name), config=rows[d.name]['config'], swaps=len(line.swaps),
                       swaps_logging_creator_fee=sum(1 for s in line.swaps if s.event.creator_fee),
                       skipped=len(line.skipped))
            if line.swaps:
                try:
                    side = CC.creator_side(line, len(line.swaps) - 1)
                except CC.CostError as exc:
                    row['creator_side'] = str(exc)
                else:
                    for key, c in (('exact_creator_charged', dict(cfg, pool_creator_fee_enabled=True)),
                                   ('exact_0_3_1', cfg)):
                        f = CC.fees_from_amm_config(c)
                        row[key] = TL.reproduce(line, {'buy': (f, side), 'sell': (f, side)})['exact']
            row['g0_reasons_0_3_1'] = CC.pool_gate(line, cfg)['reasons']
            res['pools']['%s/%s' % (Path(root).parent.name, d.name)] = row
            print(d.name[:6], json.dumps(row))
    Path(out).write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main(sys.argv[1:])
