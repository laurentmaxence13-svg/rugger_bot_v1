import sys, math
sys.path.insert(0, sys.argv[1])
import be_calc as B
from cpmmx import timeline as TL
start, now, pools = B.load(*sys.argv[2:5])
for x, p in pools.items():
    f = p['fees']; sw = [s for s in p['line'].swaps if start <= s.block_time < now]
    spots = [(s.block_time, (lambda b, q: q / b)(*TL.after_swap(s, f.protocol_fee_rate, f.fund_fee_rate))) for s in sw]
    p0, p1 = spots[0][1], spots[-1][1]; k = p1 / p0
    il = 2 * math.sqrt(k) / (1 + k) - 1
    hi = max(v for _t, v in spots) / p0; lo = min(v for _t, v in spots) / p0
    print(x[:6], 'swaps', len(sw), 'price_end/start %.4f' % k, 'IL_24h %.5f' % il, 'max %.3f min %.3f' % (hi, lo))
