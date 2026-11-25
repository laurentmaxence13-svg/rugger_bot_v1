"""livesim 0.2 -- REAL-TIME PAPER SIMULATION of G2-3 and N1 on a universe DISTINCT from the pilots (owner's directive of
25/11 ~08:39Z relayed by R04 at 08:41Z; R02 RECEVABLE 08:42:17Z; decision R04-10 at 08:46Z: K = 8 non-pilot pools,
list produced by R03). DESCRIPTIVE DEMONSTRATION: no trial, no hypothesis test, no verdict word; never an operational
Master trade, never counted for 50 / 20.

FROZEN CODE IS CALLED, NEVER MODIFIED, AND ITS MANIFESTS ARE CHECKED before any page is read and again after the run
(`check_frozen`): cpmmcost 0.3, cpmmgen2 0.2, cpmmprereg 0.2, g1ind 0.6.1, g23run 0.1 (anchored), lpcost 0.2, n1rot 0.2,
cpmmpilot 0.2.8 (MANIFEST sha of the sheets G2-3 v0.6 / N1 v0.7), and cpmmx by its git tree (sheet N1 v0.7). Every file
of these packages that is LOADED must be listed in its MANIFEST.
  G2-3: b3 = cpmmgen2.baseline_b3 recomputed by the frozen rule on the 7 days [start - 7 d ; start) of EACH new pool;
        cpmmgen2.decisions_g23; cpmmcost.pool_gate (G-0); cpmmprereg.exit_point / positions / placebo through g23run
        0.1 (positions_each, converted: K01).
  N1:   universe by n1rot 0.2's OWN functions on THIS list (`n1_universe`; n1rot.select_n1 is bound to the 4 pilot pools
        and is not called, n1rot is not modified), then lpcost 0.2 continuous_position (0.5 % of the WSOL reserve).
WHAT IS SHOWN at a time `now` (bilans at 6 h and 24 h, or any hour):
  G2-3 -- journal of signals and positions; a position is CLOSED when its exit (TP / SL found among the collected
          swaps, or the clock exit) is <= now, otherwise OPEN (never valued). Dashboard per series, the paired placebo
          BESIDE the primary and never merged with it: signals, entries, exits, guard refusals, win rate (share of the
          closed positions with net P&L > 0), gross P&L (price move), costs, net P&L; 0.1 SOL per position; FICTITIOUS
          CAPITAL = cumulative sum of the net P&L of the closed positions ordered by exit time (starts at 0); drawdown
          = largest fall of that curve from its running peak, in SOL.
  N1   -- per kept pool, hourly INTERMEDIATE marks only (liquidation value if withdrawn at the mark); the 12-day result
          is NON MESURÉ.
  Zero operations are displayed as zero; nothing is invented when no signal fires. The 7 limits are published.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from dataclasses import replace
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmprereg import rule as R
from cpmmx import timeline as TL
from g1ind import report as G1
from g23run import run as GR
from lpcost import continuous as K, model as LP
from n1rot import rotation as N1R

SCHEMA = 'livesim-v0.2'
LABELS = ('PAPER_SIMULATION', 'DESCRIPTIVE_DEMONSTRATION', 'NOT_A_TRIAL')
PILOT_POOLS = frozenset(GR.POOLS)                       # the four G2-3 pools (N1's three are among them)
HOUR_S, DAY_S = 3_600, 86_400
NM = 'NON MESURÉ'
N1_UNPRICED = (CC.CostError, LP.LpCostError, TL.TimelineError)
# History REQUIRED by the frozen rules, and supplied by `main` as the pre pages [start - 7 d ; start):
#   cpmmgen2.baseline_b3: the 1 008 windows of 600 s of [start - R.COUNT_DAYS d ; start);
#   n1rot 0.2 daily_rotation: the DAYS = 7 days [start - (7 - j) d ; start - (6 - j) d), j = 0..6, data at or after
#   start refused; n1rot 0.2 break_even_rotation_r04_6: the last state before start (time limit start - 1).
PRE_DAYS = 7
FROZEN = {                                  # package -> (MANIFEST file, sha256 of that file), from the anchored sheets
    'cpmmcost': ('MANIFEST_cpmmcost_v0_3.txt', 'a0bd2adbfaeaa5b14b79c200b066f9a14bb1408c57469e319d6e1db9b92de547'),
    'cpmmgen2': ('MANIFEST_cpmmgen2_v0_2.txt', '70ef9a9b46145436b160ce2907c433df9532f39942124a81ce11a7a3e314fcf5'),
    'cpmmprereg': ('MANIFEST_cpmmprereg_v0_2.txt', '9d8ebde62b4a05ce64a86f526d5f729d97f49bcdfee0589a0b5a46899089e5bf'),
    'g1ind': ('MANIFEST_g1ind_v0_6_1.txt', '12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a'),
    'g23run': ('MANIFEST_g23run_v0_1.txt', '3e3cb1053b0b7a792e480460e53b14f771e1d9fdd13be81e17daf02b4054747a'),
    'lpcost': ('MANIFEST_lpcost_v0_2.txt', 'ee9c144ca85f3de9489c60e0c74edf8ee685ed1e851d8d74aa392863313849eb'),
    'n1rot': ('MANIFEST_n1rot_v0_2.txt', '2a17791d1098c6a4b1ec155cb5dd8dcfcf067bd445e4467e2ce3a0020cc53fba'),
    'cpmmpilot': ('MANIFEST_cpmmpilot_v0_2_8.txt', '7251d4fe27355d066d33e08f0c9e42dffa04f890646cc50de07e2a0acc442058'),
}
FROZEN_TREES = {'cpmmx': 'e103437142c74830e6ddc293d84529501f6b1162'}      # git tree of cpmmx_pkg (99c6688)
LIMITS = (
    'L1 — Démonstration descriptive : aucun essai, aucun test, aucun mot de verdict ; jamais un trade du Master, '
    'jamais compté pour 50 / 20 ; aucune généralisation au-delà de ces pools et de cette fenêtre.',
    'L2 — Horizon court (6 h, 24 h) : peu de positions ; taux de réussite, P&L et drawdown ne sont pas des estimations '
    'et ne disent rien de la durée d\'un pilote.',
    'L3 — Seules les positions FERMÉES à « now » sont valorisées ; les positions ouvertes ne le sont jamais. Les '
    'sorties rapides (TP / SL) apparaissent avant les sorties horloge : le bilan à « now » n\'est pas celui de la '
    'fenêtre entière.',
    'L4 — Données jusqu\'à « now » seulement : les événements LP sont tronqués au slot du dernier swap connu ; une '
    'sortie est valorisée sur les swaps collectés (comportement du code gelé, L-FIN) ; le « temps réel » dépend de la '
    'fraîcheur des pages collectées par R03.',
    'L5 — Univers : 8 pools hors pilotes choisis par R03 (R04-10), pas par une règle pré-enregistrée ; b₃ recalculé '
    'par la règle gelée sur les 7 jours avant le départ ; G-0 peut exclure des pools ; le témoin apparié a une graine '
    'déclarée (sha de « livesim|départ|liste »).',
    'L6 — N1 : marques intermédiaires seulement (valeur liquidative si retrait à la marque, coûts de sortie compris) ; '
    'le résultat 12 jours est NON MESURÉ ; l\'univers N1 suit le seuil r04_6_break_even de n1rot 0.2 sur les 7 jours '
    'avant le départ, et le plancher de 3 pools de n1rot est publié, sans effet ici.',
    'L7 — Coûts du modèle gelé (cpmmcost 0.3, lpcost 0.2 : transactions, garde 20 000 ppm, échecs gelés, loyers) ; '
    'pas de MEV, latence gelée ; PAPER seulement, aucun ordre réel, aucune signature.',
)


class SimError(ValueError):
    pass


if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS or \
        N1R.R046_STAKE_PPM != K.STAKE_PPM:
    raise SimError('frozen_constants_differ_from_the_declared_design')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _package_dir(name):
    """The directory holding the package (its MANIFEST lives there): <pkg_dir>/<name>/__init__.py."""
    return Path(importlib.import_module(name).__file__).resolve().parent.parent


def _loaded_files(name):
    """Files of package `name` currently loaded, relative to the package directory."""
    root = _package_dir(name)
    out = set()
    for key, mod in list(sys.modules.items()):
        if (key == name or key.startswith(name + '.')) and getattr(mod, '__file__', None):
            out.add(os.path.normpath(str(Path(mod.__file__).resolve().relative_to(root))))
    return out


def check_frozen(expected=None, *, locate=_package_dir):
    """Each package's MANIFEST has the anchored sha, every listed file has its listed sha, every loaded file is
    listed. Raises SimError at the first difference."""
    expected = FROZEN if expected is None else expected
    out = {}
    for name in sorted(expected):
        manifest, sha = expected[name]
        root = locate(name)
        path = root / manifest
        if not path.is_file():
            raise SimError('manifest_missing:%s' % name)
        data = path.read_bytes()
        if _sha(data) != sha:
            raise SimError('manifest_sha_differs:%s' % name)
        listed = {}
        for row in data.decode().splitlines():
            if row.strip():
                digest, rel = row.split(None, 1)
                listed[os.path.normpath(rel.strip().lstrip('*'))] = digest
        for rel, digest in sorted(listed.items()):
            f = root / rel
            if not f.is_file() or _sha(f.read_bytes()) != digest:
                raise SimError('frozen_file_differs:%s:%s' % (name, rel))
        for rel in sorted(_loaded_files(name)):
            if rel not in listed:
                raise SimError('loaded_file_not_in_manifest:%s:%s' % (name, rel))
        out[name] = dict(manifest=manifest, manifest_sha256=sha, files_checked=len(listed))
    return out


def git_tree(path):
    """git's tree id of a directory on disk (files 100644 / 100755, sub-trees 40000; __pycache__ ignored)."""
    entries = []
    for child in path.iterdir():
        if child.name == '__pycache__':
            continue
        if child.is_dir():
            entries.append((child.name + '/', b'40000 ' + child.name.encode() + b'\0' + bytes.fromhex(git_tree(child))))
        else:
            mode = b'100755' if os.access(child, os.X_OK) else b'100644'
            blob = child.read_bytes()
            oid = hashlib.sha1(b'blob %d\0' % len(blob) + blob).digest()
            entries.append((child.name, mode + b' ' + child.name.encode() + b'\0' + oid))
    body = b''.join(e for _k, e in sorted(entries))
    return hashlib.sha1(b'tree %d\0' % len(body) + body).hexdigest()


def check_trees(expected=None, *, locate=_package_dir):
    expected = FROZEN_TREES if expected is None else expected
    for name, tree in sorted(expected.items()):
        if git_tree(locate(name)) != tree:
            raise SimError('frozen_tree_differs:%s' % name)
    return {name: dict(git_tree=tree) for name, tree in sorted(expected.items())}


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


def metrics(closed, opened, *, signals):
    """One series. Fictitious capital = cumulative net P&L of the closed positions by exit time, from 0."""
    rows = sorted(closed, key=lambda r: (r['exit_time'], r['pool'], r['decision_index']))
    cum, peak, worst, curve = 0, 0, 0, [dict(time=None, capital_sol=0.0)]
    gross = costs = 0.0
    for r in rows:
        g, c = _costs(r)
        gross, costs = gross + g, costs + c
        cum += r['net_lamports']
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
        curve.append(dict(time=r['exit_time'], capital_sol=cum / 1e9))
    wins = sum(1 for r in rows if r['net_lamports'] > 0)
    return dict(signals=signals, entries=sum(1 for r in rows if r.get('status') in ('entered', 'unpriced_zero_sale')),
                exits=len(rows), open_positions=len(opened),
                guard_refusals=sum(1 for r in rows if r.get('status') == 'guard_failed'), wins=wins,
                win_rate=wins / len(rows) if rows else NM, gross_pnl_sol=gross / 1e9, costs_sol=costs / 1e9,
                net_pnl_sol=cum / 1e9,
                net_return_per_position=cum / (len(rows) * CC.STAKE_LAMPORTS) if rows else NM,
                max_drawdown_sol=worst / 1e9, max_drawdown_stakes=worst / CC.STAKE_LAMPORTS,
                capital_curve=curve, capital_end_sol=cum / 1e9)


def by_hour(curve, *, start, now):
    """The fictitious capital at each full hour of ]start ; now] (the last exit at or before the mark)."""
    out, t = [], start + HOUR_S
    while t <= now:
        seen = [c['capital_sol'] for c in curve if c['time'] is not None and c['time'] <= t]
        out.append(dict(time=t, capital_sol=seen[-1] if seen else 0.0))
        t += HOUR_S
    return out


def n1_universe(pre_lines, config, start):
    """N1's universe among THIS list by n1rot 0.2's own functions, n1rot unmodified: daily_rotation and
    median_rotation on the 7 days before `start`, threshold 'r04_6_break_even' pool by pool
    (break_even_rotation_r04_6, last state before `start`); kept iff median >= threshold (select_n1's rule; select_n1
    itself is bound to the 4 pilot pools). A threshold that cannot be computed keeps the pool out, with its reason."""
    rows, kept = [], []
    for line in pre_lines:
        days = N1R.daily_rotation(line, start)
        med = N1R.median_rotation(days)
        row = dict(pool=line.pool, median_rotation=float(med), median_rotation_exact=str(med),
                   days=[dict(d, rotation=float(d['rotation'])) for d in days])
        try:
            bar = N1R.break_even_rotation_r04_6(line, config, start)
        except N1_UNPRICED + (N1R.RotationError,) as exc:
            rows.append(dict(row, kept=False, threshold_value=NM, reason='seuil non calculable : %s' % exc))
            continue
        ok = med >= bar
        if ok:
            kept.append(line.pool)
        rows.append(dict(row, kept=ok, threshold_value=float(bar), threshold_exact=str(bar)))
    return dict(rule='n1rot 0.2, seuil r04_6_break_even', window=[start - N1R.DAYS * N1R.DAY_S, start],
                pools=rows, kept=kept, list_sha256=_sha('\n'.join(kept).encode()),
                min_pools=N1R.MIN_POOLS, min_pools_met=len(kept) >= N1R.MIN_POOLS)


def n1_observations(line, config, *, start, now, step_s=HOUR_S):
    """Hourly liquidation-value marks of ONE continuous position opened at `start` (lpcost 0.2, frozen)."""
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
    """pairs = [(pre_line, pre_txs, sim_line, sim_txs)] per pool; the pre data serves b3, N1's universe and N1's entry
    state only."""
    check_universe([p[2].pool for p in pairs])
    if not start < now:
        raise SimError('now_must_follow_start')
    universe = n1_universe([p[0] for p in pairs], config, start)
    journal, gates, n1 = {}, {}, {}
    series = {name: dict(closed=[], open=[], signals=0) for name in ('primary', 'placebo')}
    for pre, _pre_txs, sim, sim_txs in pairs:
        gates[sim.pool] = CC.pool_gate(truncated(sim, now), config)
        if not gates[sim.pool]['admitted']:
            continue
        got = g23_rows(sim, sim_txs, config, b3[sim.pool], seed_sha, start=start, now=now)
        journal[sim.pool] = got
        for name in series:
            series[name]['signals'] += got[name]['signals']
            series[name]['closed'] += got[name]['closed']
            series[name]['open'] += got[name]['open']
        if sim.pool in universe['kept']:
            union = replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)),
                            lp_changes=tuple(sorted(pre.lp_changes + sim.lp_changes, key=lambda r: r[:3])))
            n1[sim.pool] = n1_observations(union, config, start=start, now=now)
    g23 = {name: metrics(s['closed'], s['open'], signals=s['signals']) for name, s in series.items()}
    for m in g23.values():
        m['capital_by_hour'] = by_hour(m['capital_curve'], start=start, now=now)
    doc = dict(schema=SCHEMA, labels=list(LABELS), counts_for_operational_master=False, trial=None,
               start=start, now=now, hours=(now - start) / HOUR_S, pools=[p[2].pool for p in pairs],
               pool_gate={p: dict(admitted=g['admitted'], reasons=g['reasons']) for p, g in gates.items()},
               g23=dict(primary=g23['primary'], placebo=g23['placebo'], stake_sol=CC.STAKE_LAMPORTS / 1e9,
                        placebo_merged=False,
                        capital_rule='somme cumulée des P&L nets des positions fermées, par heure de sortie, depuis 0'),
               n1=dict(universe=universe, observations=n1, stake_ppm=K.STAKE_PPM, result_12_days=NM,
                       note='marques intermédiaires seulement : valeur liquidative si retrait à la marque ; le '
                            'résultat 12 jours est NON MESURÉ'),
               limits=list(LIMITS), journal=journal)
    return G1.check_vocabulary(doc)


def render(doc):
    """A readable Markdown dashboard (French)."""
    def pct(x):
        return NM if x == NM else '%.2f %%' % (100 * x)
    g = doc['g23']
    lines = ['# Simulation PAPER en temps réel — G2-3 et N1 (démonstration descriptive)', '',
             '- Aucun essai, aucun verdict ; jamais un trade du Master. Univers distinct des pilotes.',
             '- Fenêtre : %d → %d (%.1f h). 0,1 SOL par position G2-3 (%.1f SOL).'
             % (doc['start'], doc['now'], doc['hours'], g['stake_sol']),
             '- Capital fictif : %s.' % g['capital_rule'], '',
             '## G2-3 (le témoin apparié est à côté, jamais additionné)', '',
             '| Série | Signaux | Entrées | Sorties | Ouvertes | Refus de garde | Taux de réussite (net > 0) | '
             'P&L brut (SOL) | Coûts (SOL) | P&L net = capital fictif (SOL) | Net moyen par position | '
             'Drawdown max (SOL) |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, label in (('primary', 'G2-3'), ('placebo', 'témoin apparié')):
        m = g[name]
        lines.append('| %s | %d | %d | %d | %d | %d | %s | %.6f | %.6f | %.6f | %s | %.6f |' % (
            label, m['signals'], m['entries'], m['exits'], m['open_positions'], m['guard_refusals'],
            pct(m['win_rate']), m['gross_pnl_sol'], m['costs_sol'], m['net_pnl_sol'],
            pct(m['net_return_per_position']), m['max_drawdown_sol']))
    if g['primary']['signals'] == 0:
        lines += ['', 'Aucun signal G2-3 sur la fenêtre : 0 opération.']
    lines += ['', '### Capital fictif par heure (SOL)', '', '| Heure | G2-3 | témoin apparié |', '|---|---|---|']
    for a, b in zip(g['primary']['capital_by_hour'], g['placebo']['capital_by_hour']):
        lines.append('| %d | %.6f | %.6f |' % (a['time'], a['capital_sol'], b['capital_sol']))
    u = doc['n1']['universe']
    lines += ['', '## N1 — marques intermédiaires seulement', '',
              '- Résultat 12 jours : %s.' % doc['n1']['result_12_days'],
              '- Univers (%s) : %d pool(s) retenu(s) sur %d ; plancher de %d pools de n1rot : %s.'
              % (u['rule'], len(u['kept']), len(u['pools']), u['min_pools'],
                 'atteint' if u['min_pools_met'] else 'non atteint'), '',
              '| Pool | Rotation médiane | Seuil | Retenu | Dernière marque | Statut | Écart à la détention | '
              'Net absolu | Mouvement de prix détenu |',
              '|---|---|---|---|---|---|---|---|---|']
    for row in u['pools']:
        pool = row['pool']
        head = '| %s | %s | %s | %s ' % (pool[:8], pct(row['median_rotation']), pct(row['threshold_value']),
                                         'oui' if row['kept'] else 'non')
        obs = doc['n1']['observations'].get(pool)
        if not row['kept'] or pool not in doc['n1']['observations']:
            lines.append(head + '| — | %s | %s | %s | %s |' % (
                'non retenu' if not row['kept'] else 'non admis par G-0', NM, NM, NM))
        elif not obs:
            lines.append(head + '| — | aucune marque | %s | %s | %s |' % (NM, NM, NM))
        else:
            o = obs[-1]
            lines.append(head + '| %d | %s | %s | %s | %s |' % (
                o['time'], o['status'], pct(o.get('gap_return', NM)), pct(o.get('net_return_absolute', NM)),
                pct(o.get('hold_price_move_return', NM))))
    lines += ['', 'Pools non admis par G-0 : %s' % (', '.join('%s (%s)' % (p[:8], ', '.join(gg['reasons']))
                                                          for p, gg in doc['pool_gate'].items()
                                                          if not gg['admitted']) or 'aucun'),
              '', '## Limites (7)', ''] + ['- %s' % x for x in doc['limits']]
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
    frozen = dict(manifests=check_frozen(), trees=check_trees())       # before any page is read
    pools = json.loads(a.pools.read_text())
    check_universe(pools)
    u2 = json.loads(a.u2.read_text())
    rows = {r['pool']: r for r in u2['selected']}
    if any(x not in rows for x in pools):
        raise SimError('a_pool_is_missing_from_the_selection')
    config = GR.PILOT.amm_config_for_rules([rows[x] for x in pools], a.t0_slot)
    pairs, b3 = [], {}
    for x in pools:
        pre, pre_txs = GR.window_line(x, rows[x]['base_mint'], a.pre_root / x, start=a.start - PRE_DAYS * DAY_S,
                                      end=a.start)
        sim, sim_txs = GR.window_line(x, rows[x]['base_mint'], a.root / x, start=a.start, end=a.now + 1)
        b3[x] = G2.baseline_b3(pre, pre_txs, a.start)
        pairs.append((pre, pre_txs, sim, sim_txs))
    seed = _sha(('livesim|%d|' % a.start + '\n'.join(pools)).encode())
    doc = simulate(pairs, config, b3=b3, seed_sha=seed, start=a.start, now=a.now)
    if dict(manifests=check_frozen(), trees=check_trees()) != frozen:  # and after the run
        raise SimError('frozen_code_changed_during_the_run')
    doc['b3'] = b3
    doc['placebo_seed_sha256'] = seed
    doc['frozen_code'] = frozen
    a.out.mkdir(parents=True)
    out = {}
    for name, text in (('LIVESIM.json', json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str)
                        + '\n'), ('LIVESIM.md', render(doc))):
        (a.out / name).write_text(text)
        out[name] = _sha(text.encode())
    print(json.dumps(out, sort_keys=True))


if __name__ == '__main__':
    main()
