"""Liste des 21 décisions primaires G2-3 de livesim (24 h) pour le recoupement de R02 : python -B decisions21.py <be_scripts> COLLECT LIST_L ELIGIBLE OUT"""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import be_calc as B
from cpmmgen2 import rule as G2

start, now, pools = B.load(*sys.argv[2:5])
rows = []
for x, p in pools.items():
    line = p['line']
    for i in [i for i in G2.decisions_g23(line, p['txs'], p['b3']) if line.swaps[i].block_time >= start]:
        got = B.realized(line, p['fees'], p['cfg'], i)
        move, st, on_input = (None, None, None) if got is None else (float(got[0]), got[1], got[2])
        F = B.fees_at(p['fees'], 2_500)
        row = dict(pool=x, swap_index=i, signature=line.swaps[i].signature, decision_time=line.swaps[i].block_time,
                   buy_state_base=st[0] if st else None, buy_state_quote=st[1] if st else None, on_input=on_input,
                   realized_move=move, fee_rate_ppm=2_500, fixed_lamports=B.FIXED_G23)
        for stake, tag in ((100_000_000, '0_1'), (5_000_000_000, '5')):
            row['threshold_A_%s_SOL' % tag] = B.break_even(st, stake, F, on_input) if st else None
            row['threshold_B_%s_SOL' % tag] = B.break_even(st, stake, F, on_input, frozen=True) if st else None
        rows.append(row)
rows.sort(key=lambda r: (r['pool'], r['swap_index']))
text = json.dumps(dict(sorted_by=['pool', 'swap_index'], n=len(rows), rows=rows), indent=1, sort_keys=True) + '\n'
Path(sys.argv[5]).write_text(text)
print(sys.argv[5], hashlib.sha256(text.encode()).hexdigest(), len(rows))
