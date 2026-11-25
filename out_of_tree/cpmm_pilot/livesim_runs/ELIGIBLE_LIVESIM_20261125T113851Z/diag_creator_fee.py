import json, sys
from dataclasses import replace
from livesim import sim as L
from cpmmcost import model as CC
from cpmmx import timeline as TL
C, LL = sys.argv[1], sys.argv[2]
ll = json.load(open(LL)); col = L.collection(C)
row = {r['pool']: r for r in ll['list']}
out = {}
for x in col['pools']:
    line, txs, _ = L.pre_pair(C, x, row[x]['base_mint'], col['t_start'])
    fees = CC.fees_from_amm_config(L.pool_config(ll, x))
    side = CC.creator_side(line, len(line.swaps) - 1)
    zero = replace(fees, creator_fee_rate=0)
    rep = TL.reproduce(line, {'buy': (zero, side), 'sell': (zero, side)})
    nonzero = sum(1 for s in line.swaps if s.event.creator_fee)
    out[x] = dict(swaps=rep['swaps'], exact_with_creator_rate_0=rep['exact'], swaps_with_creator_fee_logged=nonzero,
                  skipped=len(line.skipped))
    print(x[:6], out[x])
json.dump(out, open(sys.argv[3], 'w'), indent=1, sort_keys=True)
