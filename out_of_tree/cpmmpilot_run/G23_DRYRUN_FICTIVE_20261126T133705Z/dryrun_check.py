import json, gzip, glob, sys, hashlib
from pathlib import Path
import livesim.sim as LS
from cpmmcost import model as CC
from cpmmx import timeline as TL
OUT, R = Path(sys.argv[1]), Path(sys.argv[2])
T0 = 1795515686; START, END = T0 - 7 * 86400, T0           # FICTIVE window, entirely before T0
ll = json.loads((R / 'TIME1R_20261124T102126Z/LIST_L.json').read_text())
row = {r['pool']: r for r in ll['list']}
rep = {}
for d in sorted((OUT / 'window/collect/window').iterdir()):
    p = d.name
    pages = sorted(d.glob('page_*.json.gz'))
    st = json.loads((d / 'STATE.json').read_text())
    idx_ok = [int(f.stem.split('_')[1].split('.')[0]) for f in pages] == list(range(len(pages)))
    toks, sigs, bts, dup, outside = [], set(), [], 0, 0
    for f in pages:
        doc = json.loads(gzip.open(f).read())
        toks.append(doc.get('paginationToken'))
        for t in doc.get('data') or []:
            s = t['transaction']['signatures'][0]
            dup += s in sigs; sigs.add(s)
            bts.append((t['blockTime'], t['slot'], t['transactionIndex']))
            outside += not (START <= t['blockTime'] < END)
    chain_ok = all(t is not None for t in toks[:-1]) and toks[-1] is None
    sorted_ok = bts == sorted(bts)
    cfg = LS.pool_config(ll, p)
    line, txs = LS.GR.window_line(p, row[p]['base_mint'], d, start=START, end=END)
    fees = CC.fees_from_amm_config(cfg)
    br0 = [b for b in TL.continuity(line, fees.protocol_fee_rate, fees.fund_fee_rate) if b['reason'] != 'lp_change_between']
    new, rr = LS.rebuilt(line, txs, row[p]['wsol_vault'], cfg)
    br1 = [b for b in TL.continuity(new, fees.protocol_fee_rate, fees.fund_fee_rate) if b['reason'] != 'lp_change_between']
    g0 = CC.pool_gate(new, cfg)
    rep[p] = dict(pages=len(pages), state_pages=st['pages'], state_tx=st['transactions'], state_done=st['done'],
                  page_index_contiguous=idx_ok, pagination_chain_ok=chain_ok, tx=len(sigs), duplicates=dup,
                  outside_window=outside, ordered_by_slot=sorted_ok, swaps=len(line.swaps),
                  undecoded=len(line.skipped), breaks_before_recon=len(br0),
                  recon=dict(rebuilt=rr['rebuilt'], rebuilt_swaps=rr['rebuilt_swaps'], kept=rr['kept']),
                  breaks_after_recon=len(br1), g0_after_recon=dict(admitted=g0['admitted'], reasons=g0['reasons']))
print(json.dumps(rep, indent=1, sort_keys=True))
json.dump(dict(schema='g23-dryrun-continuity-v1', fictive_window=[START, END], note='FICTIVE window before T0, A2r pre-T0 pages, NOT the 06/12 data', pools=rep),
          open(OUT / 'CONTINUITY_REPORT.json', 'w'), indent=1, sort_keys=True)
