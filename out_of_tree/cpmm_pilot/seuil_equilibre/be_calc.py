"""Seuil d'équilibre G2-3 / N1 (R01, déclaré à R02 avant lecture ; calcul direct, aucun paquet).
python -B -I be_calc.py COLLECT LIST_L ELIGIBLE LIVESIM_JSON OUT_JSON
M1 coût aller-retour à mouvement nul ; M2 mouvement d'équilibre ; M3 fréquences à l'horizon gelé ; M4 N1."""
import json
import math
import statistics
import sys
from fractions import Fraction
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmpilot import step1 as PILOT
from cpmmprereg import rule as R
from cpmmx import curve, timeline as TL
from livesim import sim as LS

STAKES = (100_000_000, 500_000_000, 1_000_000_000, 5_000_000_000)
FEE_RATES = (2_500, 5_000, 10_000)
FIXED_G23 = -PILOT.zero_sale_net_lamports() - CC.STAKE_LAMPORTS   # R02 (d): every frozen failure + cleanup, as cpmmcost
FIXED_N1 = 6 * CC.TX_FEE_LAMPORTS             # lpcost.model.transactions at the frozen failures (rent 0)
N1_PPM, N1_DAYS = 5_000, 12


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def summary(xs):
    return dict(n=len(xs), p10=pct(xs, 0.1), median=pct(xs, 0.5), p90=pct(xs, 0.9),
                mean=statistics.mean(xs) if xs else None)


def fees_at(fees, rate):
    return curve.Fees(rate, 0, fees.protocol_fee_rate, fees.fund_fee_rate)


def moved(state, m):
    """(base, quote) with the spot multiplied by (1 + m) at constant k."""
    b, q = state
    r = math.sqrt(1 + m)
    return max(1, int(b / r)), int(q * r)


def round_trip(buy_state, stake, F, on_input, m=0.0, fixed=FIXED_G23, frozen=False):
    """Net lamports of buy(stake) then sale of every token on the state after our buy, spot moved by m; frozen=True:
    the worse of that state and the reserves WITHOUT our buy (cpmmcost X-1: min of real_reserves / with_our_buy)."""
    b, q = buy_state
    got = curve.swap_base_input(stake, q, b, F, on_input)
    q1, b1 = curve.reserves_after(q, b, got)
    states = [(b1, q1)] + ([(b, q)] if frozen else [])
    sale = min(curve.swap_base_input(got.output_amount, *moved(st, m), F, on_input).output_amount for st in states)
    return sale - stake - fixed


def no_fee_round_trip(buy_state, stake):
    """Constant product without any fee (the curve refuses a zero fee): the impact of the two legs only."""
    b, q = buy_state
    tokens = b * stake // (q + stake)
    return (q + stake) * tokens // b - stake


def decomposition(buy_state, stake, F, on_input, fixed=FIXED_G23):
    no_fee = no_fee_round_trip(buy_state, stake)
    with_fee = round_trip(buy_state, stake, F, on_input, fixed=0)
    return dict(impact=-no_fee, pool_fees=no_fee - with_fee, fixed=fixed, total=-(with_fee - fixed))


def break_even(buy_state, stake, F, on_input, fixed=FIXED_G23, frozen=False):
    lo, hi = 0.0, 1.0
    if round_trip(buy_state, stake, F, on_input, hi, fixed, frozen) < 0:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2
        if round_trip(buy_state, stake, F, on_input, mid, fixed, frozen) >= 0:
            hi = mid
        else:
            lo = mid
    return hi


def buy_state(line, fees, i):
    land = line.swaps[i].slot + CC.LATENCY_SLOTS
    on_input = CC.creator_side(line, i)
    states = [CC._state(line, fees, slot_limit=land - 1), CC._state(line, fees, slot_limit=land)]
    return min(states, key=lambda s: CC._buy_on(s, fees, on_input).output_amount), on_input


def realized(line, fees, cfg, i):
    """Spot move between the frozen buy state and the frozen exit point (0.1 SOL, 0.25 %), or None."""
    try:
        st, on_input = buy_state(line, fees, i)
        slot, clock = R.exit_point(line, i, cfg)
        ex = CC._state(line, fees, slot_limit=slot) if slot is not None else CC._state(line, fees, time_limit=clock)
    except (CC.CostError, R.PreregError, TL.TimelineError, curve.CurveError):
        return None
    return Fraction(ex[1], ex[0]) / Fraction(st[1], st[0]) - 1, st, on_input


def load(collect, list_l_path, eligible_path):
    col = LS.collection(collect)
    ll = LS.list_l_doc(list_l_path)
    elig = json.loads(Path(eligible_path).read_text())
    start, now = col['t_start'], col['t_start'] + LS.LIVE_S
    chunks = LS.chunks_until(collect, start, now)
    mint = {r['pool']: r['base_mint'] for r in ll['list']}
    b3 = {r['pool']: r['b3'] for r in elig['rows']}
    pools = {}
    for x in elig['pools']:
        cfg = LS.pool_config(ll, x)
        line, txs, _ = LS.live_pair(collect, x, mint[x], chunks)
        line, _rep = LS.rebuilt(line, txs, LS.pool_wsol_vault(ll, x), cfg)
        pools[x] = dict(cfg=cfg, fees=CC.fees_from_amm_config(cfg), line=LS.truncated(line, now), txs=txs, b3=b3[x])
    return start, now, pools


def g23(start, now, pools, livesim_doc):
    sig_entries, base_entries, check = [], [], dict(rows=0, equal=0)
    for x, p in pools.items():
        line, fees, cfg = p['line'], p['fees'], p['cfg']
        idx = [i for i in G2.decisions_g23(line, p['txs'], p['b3']) if line.swaps[i].block_time >= start]
        plac = [r['decision_index'] for r in livesim_doc['journal'][x]['placebo']['closed']]
        for kind, ids in (('signal', idx), ('placebo', plac)):
            for i in ids:
                got = realized(line, fees, cfg, i)
                sig_entries.append(dict(pool=x, kind=kind, i=i, move=None if got is None else float(got[0]),
                                        state=None if got is None else got[1], on_input=None if got is None else got[2]))
        for r in livesim_doc['journal'][x]['primary']['closed']:        # control of the round-trip code (0.1 SOL)
            if r.get('status') != 'entered':
                continue
            check['rows'] += 1
            st, on_input = buy_state(line, fees, r['decision_index'])
            buy_ok = r['tokens'] == curve.swap_base_input(CC.STAKE_LAMPORTS, st[1], st[0], fees, on_input).output_amount
            net_ok = r['net_lamports'] == r['received'] - CC.STAKE_LAMPORTS - FIXED_G23      # fixed to the lamport
            check['equal'] += buy_ok and net_ok
        for i, s in enumerate(line.swaps):
            if s.block_time < start or s.block_time > now - R.CLOCK_S - 60:
                continue
            got = realized(line, fees, cfg, i)
            base_entries.append(dict(pool=x, i=i, move=None if got is None else float(got[0]),
                                     state=None if got is None else got[1], on_input=None if got is None else got[2]))
    spaced = []                                   # R02 (c): entries >= 1 800 s apart, per pool, greedy from start
    for x in pools:
        last = None
        for e in sorted((e for e in base_entries if e['pool'] == x), key=lambda e: pools[x]['line'].swaps[e['i']].key):
            t = pools[x]['line'].swaps[e['i']].block_time
            if last is None or t - last >= R.CLOCK_S:
                spaced.append(e)
                last = t
    out = dict(control_tokens_and_net=check, fixed_lamports=FIXED_G23, grid={},
               base_rate_spaced_per_pool={x: sum(1 for e in spaced if e['pool'] == x) for x in pools})
    for stake in STAKES:
        for rate in FEE_RATES:
            key = '%g SOL / %.2f %%' % (stake / 1e9, rate / 1e4)
            cell = dict(cost_share={}, break_even={}, frequency={})
            for name, rows in (('signal', [e for e in sig_entries if e['kind'] == 'signal']),
                               ('placebo', [e for e in sig_entries if e['kind'] == 'placebo']),
                               ('base_rate', base_entries), ('base_rate_spaced', spaced)):
                ok = [e for e in rows if e['move'] is not None]
                F = lambda e: fees_at(pools[e['pool']]['fees'], rate)
                dec = [decomposition(e['state'], stake, F(e), e['on_input']) for e in ok]
                be = [break_even(e['state'], stake, F(e), e['on_input']) for e in ok]
                bef = [break_even(e['state'], stake, F(e), e['on_input'], frozen=True) for e in ok]
                cell.setdefault('cost_share_frozen', {})[name] = summary(
                    [-round_trip(e['state'], stake, F(e), e['on_input'], frozen=True) / stake for e in ok])
                cell.setdefault('break_even_frozen', {})[name] = summary([b for b in bef if b is not None])
                hits_f = [e['move'] >= b for e, b in zip(ok, bef) if b is not None]
                cell.setdefault('frequency_frozen', {})[name] = dict(
                    n=len(hits_f), share=(sum(hits_f) / len(hits_f)) if hits_f else None)
                cell['cost_share'][name] = {k: summary([d[k] / stake for d in dec])
                                            for k in ('pool_fees', 'impact', 'fixed', 'total')}
                cell['break_even'][name] = summary([b for b in be if b is not None])
                hits = [e['move'] >= b for e, b in zip(ok, be) if b is not None]
                cell['frequency'][name] = dict(n=len(hits), share=(sum(hits) / len(hits)) if hits else None,
                                               unpriced=len(rows) - len(ok),
                                               mean_move=statistics.mean([e['move'] for e in ok]) if ok else None)
            out['grid'][key] = cell
    out['moves'] = {name: summary([e['move'] for e in rows if e['move'] is not None]) for name, rows in
                    (('signal', [e for e in sig_entries if e['kind'] == 'signal']),
                     ('placebo', [e for e in sig_entries if e['kind'] == 'placebo']), ('base_rate', base_entries),
                     ('base_rate_spaced', spaced))}
    out['moves_spaced_per_pool'] = {x: summary([e['move'] for e in spaced if e['pool'] == x and e['move'] is not None])
                                    for x in pools}
    return out


def n1(start, now, pools, livesim_doc):
    out = {}
    for x, p in pools.items():
        line, fees = p['line'], p['fees']
        vol, quotes = 0, []
        for s in line.swaps:
            if not start <= s.block_time < now:
                continue
            e = s.event
            vol += e.input_amount if s.side == 'buy' else e.output_amount
            quotes.append(TL.after_swap(s, fees.protocol_fee_rate, fees.fund_fee_rate)[1])
        q_mean = statistics.mean(quotes)
        rotation = vol / q_mean
        t0 = next(s.block_time for s in line.swaps if s.block_time >= start)   # the first observed state
        st0 = CC._state(line, fees, time_limit=t0)
        on_input = CC.creator_side(line, len(line.swaps) - 1)
        rows = {}
        for label, stake in [('5 000 ppm', st0[1] * N1_PPM // 1_000_000)] + [('%g SOL' % (s / 1e9), s) for s in STAKES]:
            for rate in FEE_RATES:
                F = fees_at(fees, rate)
                half = stake // 2
                entry = decomposition(st0, half, F, on_input, fixed=0)['total']   # buy half and sell it back
                cost = entry + FIXED_N1                                           # the two legs of the round trip
                lp_rate = Fraction(rate, 10 ** 6) * (1 - Fraction(fees.protocol_fee_rate + fees.fund_fee_rate,
                                                                   10 ** 6))
                share = Fraction(stake, 2 * st0[1] + stake)                       # our fraction of the pool value
                income_day = float(share * lp_rate * vol)
                need = cost / (N1_DAYS * float(share * lp_rate) * q_mean) if share else None
                rows['%s / %.2f %%' % (label, rate / 1e4)] = dict(
                    stake_lamports=stake, cost_share=cost / stake, income_share_per_day=income_day / stake,
                    break_even_rotation_per_day_12d=need)
        out[x] = dict(volume_quote_lamports=vol, mean_quote_reserve=q_mean, rotation_24h=rotation, grid=rows,
                      n1_observations=(livesim_doc.get('n1') or {}).get('observations', {}).get(x))
    return out


if __name__ == '__main__':
    collect, list_l, eligible, livesim_json, out = sys.argv[1:6]
    doc = json.loads(Path(livesim_json).read_text())
    start, now, pools = load(collect, list_l, eligible)
    res = dict(start=start, now=now, pools=list(pools), g23=g23(start, now, pools, doc), n1=n1(start, now, pools, doc),
               labels=['DESCRIPTIVE', 'PAPER_SIMULATION'], counts_for_operational_master=False)
    text = json.dumps(res, indent=1, sort_keys=True, default=str) + '\n'
    Path(out).write_text(text)
    import hashlib
    print(out, hashlib.sha256(text.encode()).hexdigest())
