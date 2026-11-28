import json, sys
from pathlib import Path
import livesim.sim as L
from cpmmcost import model as CC
from cpmmx import timeline as TL
RUN = Path(sys.argv[1]); C = RUN / 'LIVESIM_20261125T113851Z'
ll = json.loads((RUN / 'TIME1R_20261124T102126Z/LIST_L.json').read_text())
mint = {r['pool']: r['base_mint'] for r in ll['list']}
def diag(line, cfg):
    fees = CC.fees_from_amm_config(cfg)
    on_input = CC.creator_side(line, len(line.swaps) - 1)
    rep = TL.reproduce(line, {'buy': (fees, on_input), 'sell': (fees, on_input)})
    br = [b for b in TL.continuity(line, fees.protocol_fee_rate, fees.fund_fee_rate) if b['reason'] != 'lp_change_between']
    return dict(swaps=rep['swaps'], exact=rep['exact'], skipped=len(line.skipped), breaks=len(br),
                gate=CC.pool_gate(line, cfg)['reasons'])
col = L.collection(C)
print('LIVESIM (t_start - 7 d)')
for x in col['pools']:
    pre, txs, _ = L.pre_pair(C, x, mint[x], col['t_start'])
    print(x[:6], diag(pre, L.pool_config(ll, x)))
print('PILOT pools, A2r pre-T0 pages (technical diagnostic)')
u2 = json.loads((RUN / 'TIME2_20261124T102839Z/U2.json').read_text())
rows = [r for r in u2['selected'] if r['pool'][:6] in ('AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc')]
A = Path(sys.argv[2])
lines = L.GR.PILOT.timelines(A, 'pre', rows)
for line, r in zip(lines, rows):
    cfg = L.GR.PILOT.amm_config_for_rules([r], u2['t0_slot'])
    print(r['pool'][:6], diag(line, cfg))
