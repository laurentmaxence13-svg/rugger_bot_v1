"""livesim 0.1 -- REAL-TIME PAPER SIMULATION of G2-3 and N1 on a universe DISTINCT from the pilots (owner's directive of
25/11 ~08:39Z, relayed by R04 at 08:41Z). DESCRIPTIVE DEMONSTRATION: no trial, no hypothesis test, no verdict word;
never an operational Master trade, never counted for 50 / 20. The frozen modules are CALLED, never modified:
  G2-3: cpmmgen2.baseline_b3 and decisions_g23 (b3 from the 7 days before the start), cpmmcost.pool_gate (G-0),
        cpmmprereg.exit_point / positions / placebo through g23run 0.1 (positions_each, converted: K01), anchored;
  N1:   lpcost 0.2 continuous_position (0.5 % of the WSOL reserve, gap to holding net of all costs).
WHAT IS SHOWN at a time `now` (bilans at 6 h and 24 h, or any hour):
  G2-3 -- journal of signals and positions; a position is CLOSED when its exit (TP / SL found among the collected
          swaps, or the clock exit) is <= now, otherwise OPEN (never valued). Per strategy (primary, paired placebo):
          signals, entries, exits, wins (net > 0), gross P&L (= price move), costs (fees, impact, transactions,
          cleanup, rent), net P&L, drawdown and the fictitious capital curve (start 10 SOL, 0.1 SOL per position,
          closed positions ordered by exit time).
  N1   -- per pool, hourly INTERMEDIATE observations: the liquidation value of the position if it were withdrawn at
          the mark (continuous_position on the data up to the mark), its gap to holding and its hold price move. They
          are NOT the 12-day result.
  Zero operations are displayed as zero; nothing is invented when no signal fires.
"""
import argparse
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmprereg import rule as R
from cpmmx import timeline as TL
from g1ind import report as G1
from g23run import run as GR
from lpcost import continuous as K, model as LP

SCHEMA = 'livesim-v0.1'
LABELS = ('PAPER_SIMULATION', 'DESCRIPTIVE_DEMONSTRATION', 'NOT_A_TRIAL')
PILOT_POOLS = frozenset(GR.POOLS)                       # the four G2-3 pools (N1's three are among them)
CAPITAL_LAMPORTS = 10 * 10 ** 9
HOUR_S, DAY_S = 3_600, 86_400
NM = 'NON MESURÉ'
N1_UNPRICED = (CC.CostError, LP.LpCostError, TL.TimelineError)


class SimError(ValueError):
    pass


def check_universe(pools):
    if not pools or len(set(pools)) != len(pools):
        raise SimError('pools_required_once_each')
    if PILOT_POOLS & set(pools):
        raise SimError('a_pilot_pool_is_not_allowed')


def truncated(line, now):
    """The line as known at `now`: swaps and LP events with block_time / slot up to it (LP events by their slot)."""
    swaps = tuple(s for s in line.swaps if s.block_time <= now)
    last_slot = swaps[-1].slot if swaps else -1
    lps = tuple(r for r in line.lp_changes if r[0] <= last_slot)
    return replace(line, swaps=swaps, lp_changes=lps)


def exit_time_of(line, row):
    """Block time of the exit of a priced position (clock: declared time; TP / SL: the first swap at or after it)."""
    ex = row['exit']
    if ex['rule'] == 'clock':
        return ex['declared']
    later = [s.block_time for s in line.swaps if s.slot >= ex['declared']]
    return later[0] if later else line.swaps[-1].block_time


def g23_rows(line, txs, config, b3, seed_sha, *, start, now):
    """Signals of [start ; now) and their positions, split CLOSED (exit <= now) / OPEN; the paired placebo likewise."""
    known = truncated(line, now)
    idx = [i for i in G2.decisions_g23(known, txs, b3) if known.swaps[i].block_time >= start]
    plac = [i for i in R.placebo(known, len(idx), seed_sha) if known.swaps[i].block_time >= start]
    out = {}
    for name, indices in (('primary', idx), ('placebo', plac)):
        closed, opened = [], []
        for i in indices:
            try:
                _slot, clock = R.exit_point(known, i, config)
            except CC.CostError:
                clock = None
            if _slot is None and clock is not None and clock > now:
                opened.append(dict(pool=line.pool, decision_index=i, decision_time=known.swaps[i].block_time,
                                   status='open'))
                continue
            row = GR.converted(known, GR.positions_each(known, config, [i]))[0]
            row['exit_time'] = (exit_time_of(known, row) if row.get('status') == 'entered'
                                else known.swaps[i].block_time)
            closed.append(row)
        out[name] = dict(signals=len(indices), closed=closed, open=opened)
    return out


def _costs(row):
    if row.get('status') == 'entered':
        d = row['decomposition_share_of_stake']
        gross = d['price_move'] * CC.STAKE_LAMPORTS
        return gross, gross - row['net_lamports']
    return 0.0, -row['net_lamports']                      # guard refusal or zero sale: everything is cost / loss


def metrics(closed, opened, *, signals, capital=CAPITAL_LAMPORTS):
    rows = sorted(closed, key=lambda r: (r['exit_time'], r['pool'], r['decision_index']))
    equity, peak, worst, curve = capital, capital, 0.0, [dict(time=None, capital_sol=capital / 1e9)]
    gross = costs = net = 0.0
    for r in rows:
        g, c = _costs(r)
        gross, costs, net = gross + g, costs + c, net + r['net_lamports']
        equity += r['net_lamports']
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
        curve.append(dict(time=r['exit_time'], capital_sol=equity / 1e9))
    entered = [r for r in rows if r.get('status') in ('entered', 'unpriced_zero_sale')]
    wins = sum(1 for r in entered if r['net_lamports'] > 0)
    return dict(signals=signals, entries=len(entered), exits=len(rows), open_positions=len(opened),
                guard_refusals=sum(1 for r in rows if r.get('status') == 'guard_failed'),
                win_rate=wins / len(entered) if entered else NM, gross_pnl_sol=gross / 1e9, costs_sol=costs / 1e9,
                net_pnl_sol=net / 1e9, net_return_on_capital=net / capital, max_drawdown=worst,
                capital_curve=curve, capital_end_sol=equity / 1e9)


def n1_observations(line, config, *, start, now, step_s=HOUR_S):
    """Hourly liquidation-value observations of ONE continuous position opened at `start` (lpcost 0.2, frozen)."""
    out = []
    t = start + step_s
    while t <= now:
        days = max(1, math.ceil((t - start) / DAY_S))
        try:
            pos = K.continuous_position(truncated(line, t), config, start_time=start, end_time=start + days * DAY_S)
        except N1_UNPRICED as exc:
            out.append(dict(time=t, status='non valorisable', reason=str(exc)))
        else:
            if pos['status'] != 'entered':
                out.append(dict(time=t, status=pos['status'], gap_return=float(pos['gap_lamports'] /
                                                                             max(pos['stake_lamports'], 1))))
            else:
                d = pos['decomposition_lamports']
                out.append(dict(time=t, status='observée', stake_sol=pos['stake_lamports'] / 1e9,
                                gap_return=float(pos['gap_lamports'] / pos['stake_lamports']),
                                net_return_absolute=pos['net_lamports'] / pos['stake_lamports'],
                                hold_price_move_return=float(d['hold_price_move'] / pos['stake_lamports'])))
        t += step_s
    return out


def simulate(pairs, config, *, b3, seed_sha, start, now):
    """pairs = [(pre_line, pre_txs, sim_line, sim_txs)] per pool; the pre data serves b3 and N1's entry state only."""
    check_universe([p[2].pool for p in pairs])
    if not start < now:
        raise SimError('now_must_follow_start')
    journal, prim_closed, prim_open, plac_closed, plac_open = {}, [], [], [], []
    signals = dict(primary=0, placebo=0)
    gates, n1 = {}, {}
    for pre, pre_txs, sim, sim_txs in pairs:
        gates[sim.pool] = CC.pool_gate(truncated(sim, now), config)
        if not gates[sim.pool]['admitted']:
            continue
        got = g23_rows(sim, sim_txs, config, b3[sim.pool], seed_sha, start=start, now=now)
        journal[sim.pool] = got
        signals['primary'] += got['primary']['signals']
        signals['placebo'] += got['placebo']['signals']
        prim_closed += got['primary']['closed']
        prim_open += got['primary']['open']
        plac_closed += got['placebo']['closed']
        plac_open += got['placebo']['open']
        union = replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)),
                        lp_changes=tuple(sorted(pre.lp_changes + sim.lp_changes, key=lambda r: r[:3])))
        n1[sim.pool] = n1_observations(union, config, start=start, now=now)
    doc = dict(schema=SCHEMA, labels=list(LABELS), counts_for_operational_master=False, trial=None,
               start=start, now=now, hours=(now - start) / HOUR_S, pools=[p[2].pool for p in pairs],
               pool_gate={p: dict(admitted=g['admitted'], reasons=g['reasons']) for p, g in gates.items()},
               g23=dict(primary=metrics(prim_closed, prim_open, signals=signals['primary']),
                        placebo=metrics(plac_closed, plac_open, signals=signals['placebo']),
                        stake_sol=CC.STAKE_LAMPORTS / 1e9, capital_start_sol=CAPITAL_LAMPORTS / 1e9),
               n1=dict(observations=n1, stake_ppm=K.STAKE_PPM,
                       note='observations intermédiaires : valeur liquidative si retrait à la marque ; ce n\'est '
                            'pas le résultat 12 jours'),
               journal=journal)
    return G1.check_vocabulary(doc)


def render(doc):
    """A readable Markdown dashboard (French)."""
    def pct(x):
        return NM if x == NM else '%.2f %%' % (100 * x)
    lines = ['# Simulation PAPER en temps réel — G2-3 et N1 (démonstration descriptive)', '',
             '- Aucun essai, aucun verdict ; jamais un trade du Master. Univers distinct des pilotes.',
             '- Fenêtre : %d → %d (%.1f h). Capital fictif de départ : %.1f SOL ; 0,1 SOL par position G2-3.'
             % (doc['start'], doc['now'], doc['hours'], doc['g23']['capital_start_sol']), '',
             '## G2-3', '',
             '| Série | Signaux | Entrées | Sorties | Ouvertes | Taux de réussite | P&L brut (SOL) | Coûts (SOL) | '
             'P&L net (SOL) | Rendement net | Drawdown max | Capital final (SOL) |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, label in (('primary', 'G2-3'), ('placebo', 'témoin apparié')):
        m = doc['g23'][name]
        lines.append('| %s | %d | %d | %d | %d | %s | %.6f | %.6f | %.6f | %s | %s | %.6f |' % (
            label, m['signals'], m['entries'], m['exits'], m['open_positions'], pct(m['win_rate']),
            m['gross_pnl_sol'], m['costs_sol'], m['net_pnl_sol'], pct(m['net_return_on_capital']),
            pct(m['max_drawdown']), m['capital_end_sol']))
    if doc['g23']['primary']['signals'] == 0:
        lines += ['', 'Aucun signal G2-3 sur la fenêtre : 0 opération.']
    lines += ['', '## N1 — observations intermédiaires (pas le résultat 12 jours)', '',
              '| Pool | Dernière marque | Statut | Écart à la détention | Net absolu | Mouvement de prix détenu |',
              '|---|---|---|---|---|---|']
    for pool, obs in doc['n1']['observations'].items():
        if not obs:
            lines.append('| %s | — | aucune marque | %s | %s | %s |' % (pool[:8], NM, NM, NM))
            continue
        o = obs[-1]
        lines.append('| %s | %d | %s | %s | %s | %s |' % (
            pool[:8], o['time'], o['status'], pct(o.get('gap_return', NM)), pct(o.get('net_return_absolute', NM)),
            pct(o.get('hold_price_move_return', NM))))
    lines += ['', 'Pools non admis par G-0 : %s' % (', '.join('%s (%s)' % (p[:8], ', '.join(g['reasons']))
                                                          for p, g in doc['pool_gate'].items() if not g['admitted'])
                                                 or 'aucun')]
    text = '\n'.join(lines) + '\n'
    G1.check_vocabulary(dict(text=text))
    return text


def main(argv=None):
    """python -B -m livesim.sim --pools POOLS.json --u2 U2.json --pre-root DIR --root DIR --t0-slot S --start T
    --now T --out DIR. POOLS.json = [addresses], none of the pilot pools; pages <root>/<pool>/page_*.json.gz for
    [start ; now] and <pre-root>/<pool>/ for [start - 7 d ; start)."""
    p = argparse.ArgumentParser()
    for k in ('--pools', '--u2', '--pre-root', '--root', '--out'):
        p.add_argument(k, type=Path, required=True)
    for k in ('--t0-slot', '--start', '--now'):
        p.add_argument(k, type=int, required=True)
    a = p.parse_args(argv)
    if a.out.exists():
        raise SimError('out_exists')
    pools = json.loads(a.pools.read_text())
    check_universe(pools)
    u2 = json.loads(a.u2.read_text())
    rows = {r['pool']: r for r in u2['selected']}
    if any(x not in rows for x in pools):
        raise SimError('a_pool_is_missing_from_the_selection')
    config = GR.PILOT.amm_config_for_rules([rows[x] for x in pools], a.t0_slot)
    pairs, b3 = [], {}
    for x in pools:
        pre, pre_txs = GR.window_line(x, rows[x]['base_mint'], a.pre_root / x, start=a.start - 7 * DAY_S, end=a.start)
        sim, sim_txs = GR.window_line(x, rows[x]['base_mint'], a.root / x, start=a.start, end=a.now + 1)
        b3[x] = G2.baseline_b3(pre, pre_txs, a.start)
        pairs.append((pre, pre_txs, sim, sim_txs))
    seed = hashlib.sha256(('livesim|%d|' % a.start + '\n'.join(pools)).encode()).hexdigest()
    doc = simulate(pairs, config, b3=b3, seed_sha=seed, start=a.start, now=a.now)
    doc['b3'] = b3
    doc['placebo_seed_sha256'] = seed
    a.out.mkdir(parents=True)
    out = {}
    for name, text in (('LIVESIM.json', json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str)
                        + '\n'), ('LIVESIM.md', render(doc))):
        (a.out / name).write_text(text)
        out[name] = hashlib.sha256(text.encode()).hexdigest()
    print(json.dumps(out, sort_keys=True))


if __name__ == '__main__':
    main()
