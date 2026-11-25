import json, sys, collections
from pathlib import Path
from cpmmpilot.store import read_gz_page
from cpmmx import timeline as TL
LL, OUT = sys.argv[1], sys.argv[2]; roots = sys.argv[3:]
ll = json.loads(Path(LL).read_text()); rows = {r['pool']: r for r in ll['list']}
res = {}
for root in roots:
    for d in sorted(Path(root).iterdir()):
        if not d.is_dir() or d.name not in rows:
            continue
        txs = {}
        for page in sorted(d.glob('page_*.json.gz')):
            for tx in read_gz_page(page).get('data') or []:
                txs[tx['transaction']['signatures'][0]] = tx
        line = TL.build(d.name, txs, base_mint=rows[d.name]['base_mint'])
        failed = sum(1 for t in txs.values() if (t.get('meta') or {}).get('err') is not None)
        with_swap = len({s.signature for s in line.swaps})
        k = len(line.skipped)
        res['%s/%s' % (Path(root).parent.name, d.name)] = dict(
            transactions=len(txs), failed=failed, successful=len(txs) - failed, tx_with_decoded_swap=with_swap,
            swaps=len(line.swaps), skipped=k,
            share_of_all_tx=k / max(1, len(txs)), share_of_successful_tx=k / max(1, len(txs) - failed),
            share_of_swap_tx=k / max(1, with_swap + k), share_of_swaps=k / max(1, len(line.swaps) + k))
        r = res['%s/%s' % (Path(root).parent.name, d.name)]
        if k: print(d.name[:6], {x: (round(v, 4) if isinstance(v, float) else v) for x, v in r.items()})
Path(OUT).write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
