"""DESCRIPTIVE diagnostic of G-0 on the 4 pilot pools' A2r PRE-T0 pages (no window datum, no position, no P&L)."""
import json, sys, collections
from pathlib import Path
from dataclasses import replace
from livesim import sim as L
from cpmmcost import model as CC
from cpmmx import timeline as TL
from g23run import run as GR
A, LL, OUT = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
T0 = GR.T0
ll = json.load(open(LL)); row = {r['pool']: r for r in ll['list']}
res = {}
for x in GR.POOLS:
    line, txs = GR.window_line(x, row[x]['base_mint'], A / 'pre_pages' / x, start=T0 - 7 * 86_400, end=T0)
    cfg = L.pool_config(ll, x)
    fees = CC.fees_from_amm_config(cfg)
    side = CC.creator_side(line, len(line.swaps) - 1)
    rep = TL.reproduce(line, {'buy': (fees, side), 'sell': (fees, side)})
    zero = replace(fees, creator_fee_rate=0)
    rep0 = TL.reproduce(line, {'buy': (zero, side), 'sell': (zero, side)})
    g = CC.pool_gate(line, cfg)
    g0 = CC.pool_gate(line, dict(cfg, creator_fee_rate=0))
    skipped = collections.Counter(str(s.get('reason') if isinstance(s, dict) else s)[:40] for s in line.skipped)
    res[x] = dict(config_sha=cfg['sha256'], swaps=rep['swaps'], exact_anchored=rep['exact'], exact_creator_0=rep0['exact'],
                  swaps_logging_creator_fee=sum(1 for s in line.swaps if s.event.creator_fee),
                  skipped=len(line.skipped), skipped_kinds=dict(skipped.most_common(3)),
                  gate_anchored=g['reasons'], gate_creator_0=g0['reasons'], breaks_creator_0=g0.get('continuity_breaks'))
    print(x[:6], json.dumps(res[x])[:600])
json.dump(res, open(OUT, 'w'), indent=1, sort_keys=True)
