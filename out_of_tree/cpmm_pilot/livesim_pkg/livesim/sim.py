"""livesim 0.3.1 -- REAL-TIME PAPER SIMULATION of G2-3 and N1 on a universe DISTINCT from the pilots (owner's directive of
25/11 ~08:39Z relayed by R04 at 08:41Z; R02 RECEVABLE 08:42:17Z; decision R04-10 at 08:46Z: K = 8 non-pilot pools,
list produced by R03). DESCRIPTIVE DEMONSTRATION: no trial, no hypothesis test, no verdict word; never an operational
Master trade, never counted for 50 / 20.
0.3 (R02 audit of 0.1, 08:51:39Z, F1-F5; R03 file format 08:52:30Z): ONE AmmConfig PER POOL (the frozen
amm_config_for_rules called on [row] of each pool, U-1 configs anchored in LIST_L c96353b9); inputs are R03's
collection files (CONFIG, QUALIFIED, POLLS, pages collect/pre and collect/live_NNN) and LIST_L, never U2.selected;
command `eligible` writes ELIGIBLE.json (qualified pools with G-0 admitted and b3 > 0 on the history); command `bilan`
needs ELIGIBLE.json at its R02-anchored sha; fewer than 3 eligible pools -> NON ÉVALUABLE, no P&L figure (G2-3);
fewer than 3 N1 pools -> N1 NON ÉVALUABLE (n1rot's own floor); command `identity` checks the N1 wrapper against the
anchored n1rot output 6b9b02a9 on the A2r pre-T0 pages (run by R03, offline); the placebo redraw at each `now` is
declared (F5).

0.3.1 (R02 12:16Z): cpmmcost 0.3.1 (erratum E-CF, MANIFEST f635684c) in FROZEN; tests independent of the local
cpmmpilot copy (0.2.8 extraction 8c4a022 on the path). Nothing else changes.
FROZEN CODE IS CALLED, NEVER MODIFIED, AND ITS MANIFESTS ARE CHECKED before any page is read and again after the run
(`check_frozen`): cpmmcost 0.3.1, cpmmgen2 0.2, cpmmprereg 0.2, g1ind 0.6.1, g23run 0.1 (anchored), lpcost 0.2, n1rot 0.2,
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

SCHEMA = 'livesim-v0.3.1'
LABELS = ('PAPER_SIMULATION', 'DESCRIPTIVE_DEMONSTRATION', 'NOT_A_TRIAL')
PILOT_POOLS = frozenset(GR.POOLS)                       # the four G2-3 pools (N1's three are among them)
FORBIDDEN_POOLS = PILOT_POOLS | {'2yLFomCTck19BqK7EzJqsUWXPWP3uWGNBSrfKvJzNzp2'}   # as R03's collector (198b3262)
LIST_L_SHA256 = 'c96353b9f3c0bdb25fd1b7c8af85cf0c4efd66e84480d7850252b85d8a7d8ff3'    # U-1 configs, base mints
N1ROT_RESULT_SHA256 = '6b9b02a949c2dc5859332ac2fae814c17f491a21c3fa173682a8122dc26171c3'
N1ROT_LIST_SHA256 = 'c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da'
MIN_ELIGIBLE = 3                                        # R02 F4 (and R03's collector MIN_ELIGIBLE)
LIVE_S, CHUNK_S = 24 * 3_600, 2 * 3_600                 # R03's polls: 12 chunks of 2 h
HOUR_S, DAY_S = 3_600, 86_400
NM = 'NON MESURÉ'
NON_EVALUABLE = 'NON ÉVALUABLE'
N1_UNPRICED = (CC.CostError, LP.LpCostError, TL.TimelineError)
# History REQUIRED by the frozen rules, and supplied by `main` as the pre pages [start - 7 d ; start):
#   cpmmgen2.baseline_b3: the 1 008 windows of 600 s of [start - R.COUNT_DAYS d ; start);
#   n1rot 0.2 daily_rotation: the DAYS = 7 days [start - (7 - j) d ; start - (6 - j) d), j = 0..6, data at or after
#   start refused; n1rot 0.2 break_even_rotation_r04_6: the last state before start (time limit start - 1).
PRE_DAYS = 7
FROZEN = {                                  # package -> (MANIFEST file, sha256 of that file), from the anchored sheets
    'cpmmcost': ('MANIFEST_cpmmcost_v0_3_1.txt', 'f635684cb7ad652a44ceeae898fa61cc4d8a0bbdf3d9b3030ca74582d19c8832'),
    'cpmmgen2': ('MANIFEST_cpmmgen2_v0_2.txt', '70ef9a9b46145436b160ce2907c433df9532f39942124a81ce11a7a3e314fcf5'),
    'cpmmprereg': ('MANIFEST_cpmmprereg_v0_2.txt', '9d8ebde62b4a05ce64a86f526d5f729d97f49bcdfee0589a0b5a46899089e5bf'),
    'g1ind': ('MANIFEST_g1ind_v0_6_1.txt', '12a2e66170918aee1bb859ec4c6639c263ad3587f491c9143d024bb816ae117a'),
    'g23run': ('MANIFEST_g23run_v0_1.txt', '3e3cb1053b0b7a792e480460e53b14f771e1d9fdd13be81e17daf02b4054747a'),
    'lpcost': ('MANIFEST_lpcost_v0_2.txt', 'ee9c144ca85f3de9489c60e0c74edf8ee685ed1e851d8d74aa392863313849eb'),
    'n1rot': ('MANIFEST_n1rot_v0_2.txt', '2a17791d1098c6a4b1ec155cb5dd8dcfcf067bd445e4467e2ce3a0020cc53fba'),
    'cpmmpilot': ('MANIFEST_cpmmpilot_v0_2_8.txt', '7251d4fe27355d066d33e08f0c9e42dffa04f890646cc50de07e2a0acc442058'),
}
FROZEN_TREES = {'cpmmx': 'e103437142c74830e6ddc293d84529501f6b1162'}      # git tree of cpmmx_pkg (99c6688)
LIMITS = (                                  # R02's wording, verbatim (09:06:59Z)
    'L1 : démonstration descriptive. Aucun essai, aucun test ni verdict, jamais un trade du Master. Le résultat ne '
    'peut servir ni à choisir ni à modifier une stratégie.',
    'L2 : pools différents de ceux des pilotes, choisis par la règle ancrée par R02 avant toute lecture (registre '
    '08:42:17Z et 08:45:05Z ; liste 5c4fefb6…). Aucune généralisation.',
    'L3 : horizon de 6 h et de 24 h, au lieu des 12 jours. Le n est faible ; « n insuffisant » est publié quand il le '
    'faut.',
    'L4 : collecte rétrospective par blocs de 2 h, donc une latence de 2 h au plus. Données tronquées à now. L-FIN. '
    'Seules les positions fermées sont valorisées.',
    'L5 : même période de marché que la fenêtre pilote, donc une corrélation possible. Cela ne dit rien des verdicts '
    'du 6 décembre.',
    'L6 : au départ, l\'historique des acheteurs sur 600 s est tronqué et le délai de 3 600 s repart à zéro. Le témoin '
    'est retiré à chaque bilan. La config de chaque pool est celle lue à U-1, à un slot antérieur.',
    'L7 : N1 en marques intermédiaires seulement ; le résultat à 12 jours est NON MESURÉ. Coûts du modèle gelé : pas '
    'de MEV, latence gelée. PAPER seulement.',
)
N_MIN = 30          # « n insuffisant » below 30 closed positions (G2-3) or 30 pool-days (N1): the pilots' floor of 30


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
    if FORBIDDEN_POOLS & set(pools):
        raise SimError('a_pilot_or_forbidden_pool_is_not_allowed')


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
                capital_curve=curve, capital_end_sol=cum / 1e9, n_insufficient=len(rows) < N_MIN)


def by_hour(curve, *, start, now):
    """The fictitious capital at each full hour of ]start ; now] (the last exit at or before the mark)."""
    out, t = [], start + HOUR_S
    while t <= now:
        seen = [c['capital_sol'] for c in curve if c['time'] is not None and c['time'] <= t]
        out.append(dict(time=t, capital_sol=seen[-1] if seen else 0.0))
        t += HOUR_S
    return out


def n1_universe(pre_lines, configs, start):
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
            bar = N1R.break_even_rotation_r04_6(line, configs[line.pool], start)
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


def simulate(pairs, configs, *, b3, seed_sha, start, now):
    """pairs = [(pre_line, pre_txs, sim_line, sim_txs)] per pool; configs = {pool: AmmConfig of THAT pool}; the pre data
    serves b3, N1's universe and N1's entry state only. Eligible at `now` = G-0 admitted and b3 > 0 (R02 F4)."""
    pools = [p[2].pool for p in pairs]
    check_universe(pools)
    if set(configs) != set(pools) or set(b3) != set(pools):
        raise SimError('one_config_and_one_b3_per_pool')
    if not start < now:
        raise SimError('now_must_follow_start')
    gates = {sim.pool: CC.pool_gate(truncated(sim, now), configs[sim.pool]) for _p, _t, sim, _s in pairs}
    eligible = [x for x in pools if gates[x]['admitted'] and b3[x] > 0]
    doc = dict(schema=SCHEMA, labels=list(LABELS), counts_for_operational_master=False, trial=None,
               start=start, now=now, hours=(now - start) / HOUR_S, pools=pools,
               pool_gate={p: dict(admitted=g['admitted'], reasons=g['reasons']) for p, g in gates.items()},
               b3_by_pool=dict(b3), eligible=eligible, min_eligible=MIN_ELIGIBLE,
               amm_config_sha256={x: configs[x]['sha256'] for x in pools}, limits=list(LIMITS),
               placebo_note='témoin retiré à chaque « now », autant que de signaux connus ; ses positions peuvent '
                            'changer entre deux bilans')
    if len(eligible) < MIN_ELIGIBLE:
        doc.update(status=NON_EVALUABLE, g23=None, n1=None, journal=None,
                   conduct='moins de %d pools éligibles (G-0 admis et b₃ > 0) : aucun chiffre de P&L' % MIN_ELIGIBLE)
        return G1.check_vocabulary(doc)
    universe = n1_universe([p[0] for p in pairs], configs, start)
    journal, n1 = {}, {}
    series = {name: dict(closed=[], open=[], signals=0) for name in ('primary', 'placebo')}
    n1_pools = [x for x in universe['kept'] if x in eligible]
    for pre, _pre_txs, sim, sim_txs in pairs:
        if sim.pool not in eligible:
            continue
        got = g23_rows(sim, sim_txs, configs[sim.pool], b3[sim.pool], seed_sha, start=start, now=now)
        journal[sim.pool] = got
        for name in series:
            series[name]['signals'] += got[name]['signals']
            series[name]['closed'] += got[name]['closed']
            series[name]['open'] += got[name]['open']
        if sim.pool in n1_pools and len(n1_pools) >= N1R.MIN_POOLS:
            union = replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)),
                            lp_changes=tuple(sorted(pre.lp_changes + sim.lp_changes, key=lambda r: r[:3])))
            n1[sim.pool] = n1_observations(union, configs[sim.pool], start=start, now=now)
    g23 = {name: metrics(s['closed'], s['open'], signals=s['signals']) for name, s in series.items()}
    for m in g23.values():
        m['capital_by_hour'] = by_hour(m['capital_curve'], start=start, now=now)
    n1_status = 'marques intermédiaires' if len(n1_pools) >= N1R.MIN_POOLS else NON_EVALUABLE
    n1_pool_days = len(n1) * math.ceil((now - start) / DAY_S)
    doc.update(status='ÉVALUABLE (démonstration descriptive)',
               g23=dict(primary=g23['primary'], placebo=g23['placebo'], stake_sol=CC.STAKE_LAMPORTS / 1e9,
                        placebo_merged=False,
                        capital_rule='somme cumulée des P&L nets des positions fermées, par heure de sortie, depuis 0'),
               n1=dict(universe=universe, pools=n1_pools, status=n1_status, observations=n1, stake_ppm=K.STAKE_PPM,
                       result_12_days=NM, pool_days=n1_pool_days, n_insufficient=n1_pool_days < N_MIN,
                       note='marques intermédiaires seulement : valeur liquidative si retrait à la marque ; le '
                            'résultat 12 jours est NON MESURÉ'),
               journal=journal)
    return G1.check_vocabulary(doc)


def render(doc):
    """A readable Markdown dashboard (French)."""
    def pct(x):
        return NM if x == NM else '%.2f %%' % (100 * x)
    lines = ['# Simulation PAPER en temps réel — G2-3 et N1 (démonstration descriptive)', '',
             '- Aucun essai, aucun verdict ; jamais un trade du Master. Univers distinct des pilotes.',
             '- Fenêtre : %d → %d (%.1f h). Statut : %s.' % (doc['start'], doc['now'], doc['hours'], doc['status']),
             '- Pools éligibles (G-0 admis et b₃ > 0) : %d sur %d (au moins %d exigés).'
             % (len(doc['eligible']), len(doc['pools']), doc['min_eligible']), '',
             '| Pool | b₃ | G-0 | Éligible |', '|---|---|---|---|']
    for x in doc['pools']:
        g = doc['pool_gate'][x]
        lines.append('| %s | %s | %s | %s |' % (x[:8], doc['b3_by_pool'][x],
                                                'admis' if g['admitted'] else 'non admis (%s)' % ', '.join(g['reasons']),
                                                'oui' if x in doc['eligible'] else 'non'))
    if doc['g23'] is None:
        lines += ['', '**%s** : %s.' % (doc['status'], doc['conduct'])]
    else:
        g = doc['g23']
        lines += ['', '- 0,1 SOL par position G2-3 (%.1f SOL). Capital fictif : %s.' % (g['stake_sol'],
                                                                                      g['capital_rule']),
                  '- %s.' % doc['placebo_note'], '',
                  '## G2-3 (le témoin apparié est à côté, jamais additionné)', '',
                  '| Série | Signaux | Entrées | Sorties | Ouvertes | Refus de garde | Taux de réussite (net > 0) | '
                  'P&L brut (SOL) | Coûts (SOL) | P&L net = capital fictif (SOL) | Net moyen par position | '
                  'Drawdown max (SOL) |',
                  '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for name, label in (('primary', 'G2-3'), ('placebo', 'témoin apparié')):
            m = g[name]
            if m['n_insufficient']:
                label += ' (n insuffisant : %d < %d)' % (m['exits'], N_MIN)
            lines.append('| %s | %d | %d | %d | %d | %d | %s | %.6f | %.6f | %.6f | %s | %.6f |' % (
                label, m['signals'], m['entries'], m['exits'], m['open_positions'], m['guard_refusals'],
                pct(m['win_rate']), m['gross_pnl_sol'], m['costs_sol'], m['net_pnl_sol'],
                pct(m['net_return_per_position']), m['max_drawdown_sol']))
        if g['primary']['signals'] == 0:
            lines += ['', 'Aucun signal G2-3 sur la fenêtre : 0 opération.']
        lines += ['', '### Capital fictif par heure (SOL)', '', '| Heure | G2-3 | témoin apparié |', '|---|---|---|']
        for a, b in zip(g['primary']['capital_by_hour'], g['placebo']['capital_by_hour']):
            lines.append('| %d | %.6f | %.6f |' % (a['time'], a['capital_sol'], b['capital_sol']))
        n1 = doc['n1']
        u = n1['universe']
        lines += ['', '## N1 — marques intermédiaires seulement', '',
                  '- Résultat 12 jours : %s.' % n1['result_12_days'],
                  '- Pool-jours marqués : %d%s.' % (n1['pool_days'], ' — n insuffisant (< %d)' % N_MIN
                                                    if n1['n_insufficient'] else ''),
                  '- Univers (%s) : %d pool(s) retenu(s) sur %d, dont %d éligible(s) ; au moins %d exigés : %s.'
                  % (u['rule'], len(u['kept']), len(u['pools']), len(n1['pools']), u['min_pools'], n1['status']), '',
                  '| Pool | Rotation médiane | Seuil | Retenu | Dernière marque | Statut | Écart à la détention | '
                  'Net absolu | Mouvement de prix détenu |',
                  '|---|---|---|---|---|---|---|---|---|']
        for row in u['pools']:
            pool = row['pool']
            head = '| %s | %s | %s | %s ' % (pool[:8], pct(row['median_rotation']), pct(row['threshold_value']),
                                             'oui' if row['kept'] else 'non')
            obs = n1['observations'].get(pool)
            if not row['kept']:
                why = 'non retenu'
            elif pool not in n1['pools']:
                why = 'non éligible'
            elif pool not in n1['observations']:
                why = NON_EVALUABLE
            else:
                why = None
            if why:
                lines.append(head + '| — | %s | %s | %s | %s |' % (why, NM, NM, NM))
            elif not obs:
                lines.append(head + '| — | aucune marque | %s | %s | %s |' % (NM, NM, NM))
            else:
                o = obs[-1]
                lines.append(head + '| %d | %s | %s | %s | %s |' % (
                    o['time'], o['status'], pct(o.get('gap_return', NM)), pct(o.get('net_return_absolute', NM)),
                    pct(o.get('hold_price_move_return', NM))))
    lines += ['', '## Limites (7)', ''] + ['- %s' % x for x in doc['limits']]
    text = '\n'.join(lines) + '\n'
    G1.check_vocabulary(dict(text=text))
    return text


# -- inputs: R03's collection files (livesim_collect 198b3262) and LIST_L ------------------------------------------------
def _read_json(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return _sha(Path(path).read_bytes())


def pages_sha(directory):
    """sha256 of the sorted 'sha  name' lines of the pages of one directory (the pages read for one pool)."""
    pages = sorted(Path(directory).glob('page_*.json.gz'))
    if not pages:
        raise SimError('no_page:%s' % directory)
    return _sha(''.join('%s  %s\n' % (file_sha(p), p.name) for p in pages).encode())


def list_l_doc(path):
    if file_sha(path) != LIST_L_SHA256:
        raise SimError('list_l_not_anchored')
    return _read_json(path)


def pool_config(list_l, pool):
    """THIS pool's U-1 AmmConfig, through the frozen amm_config_for_rules on [row] (R02 F1)."""
    rows = [r for r in list_l['list'] if r['pool'] == pool]
    if len(rows) != 1:
        raise SimError('pool_not_once_in_list_l:%s' % pool)
    row = dict(rows[0], amm_config=list_l['configs'][rows[0]['config']])
    return GR.PILOT.amm_config_for_rules([row], list_l['t0_slot'])


def collection(collect):
    """t_start from CONFIG.json and the qualified pools from QUALIFIED.json (list sha checked, forbidden refused)."""
    collect = Path(collect)
    cfg, q = _read_json(collect / 'CONFIG.json'), _read_json(collect / 'QUALIFIED.json')
    pools = q['pools']
    if _sha('\n'.join(pools).encode()) != q['list_sha256']:
        raise SimError('qualified_list_corrupt')
    check_universe(pools)
    if type(cfg['t_start']) is not int:
        raise SimError('t_start_must_be_an_integer')
    return dict(t_start=cfg['t_start'], pools=pools, qualified_sha256=file_sha(collect / 'QUALIFIED.json'),
                config_sha256=file_sha(collect / 'CONFIG.json'))


def pre_pair(collect, pool, mint, start):
    d = Path(collect) / 'collect' / 'pre' / pool
    line, txs = GR.window_line(pool, mint, d, start=start - PRE_DAYS * DAY_S, end=start)
    return line, txs, pages_sha(d)


def chunks_until(collect, start, now):
    """The done 2-h chunks of POLLS.json covering [start ; now) exactly, in order (now = the end of a chunk)."""
    polls = _read_json(Path(collect) / 'POLLS.json')
    out = []
    for i, c in enumerate(polls):
        if c['window'] != [start + i * CHUNK_S, start + (i + 1) * CHUNK_S] or c['name'] != 'live_%03d' % i:
            raise SimError('polls_not_the_fixed_chunks')
        if c['window'][1] <= now:
            if not c['done']:
                raise SimError('chunk_not_done:%s' % c['name'])
            out.append(c)
    if not out or out[-1]['window'][1] != now or now > start + LIVE_S:
        raise SimError('now_must_be_the_end_of_a_done_chunk')
    return out


def live_pair(collect, pool, mint, chunks):
    """(line, txs, {chunk: pages sha}) of the chunks' pages of one pool, each page inside its chunk's window."""
    txs, shas = {}, {}
    for c in chunks:
        d = Path(collect) / 'collect' / c['name'] / pool
        _line, got = GR.window_line(pool, mint, d, start=c['window'][0], end=c['window'][1])
        txs.update(got)
        shas[c['name']] = pages_sha(d)
    return TL.build(pool, txs, base_mint=mint), txs, shas


def eligibility(collect, list_l):
    """ELIGIBLE.json content: per qualified pool, b3 (frozen rule, 7 days before t_start) and G-0 on the history with
    THIS pool's config; eligible = admitted and b3 > 0, in QUALIFIED order."""
    col = collection(collect)
    mint = {r['pool']: r['base_mint'] for r in list_l['list']}
    rows, eligible = [], []
    for x in col['pools']:
        cfg = pool_config(list_l, x)
        pre, pre_txs, sha = pre_pair(collect, x, mint[x], col['t_start'])
        b3 = G2.baseline_b3(pre, pre_txs, col['t_start'])
        gate = CC.pool_gate(pre, cfg)
        ok = gate['admitted'] and b3 > 0
        if ok:
            eligible.append(x)
        rows.append(dict(pool=x, b3=b3, g0_admitted=gate['admitted'], g0_reasons=gate['reasons'], eligible=ok,
                         amm_config_sha256=cfg['sha256'], pre_pages_sha256=sha))
    return dict(schema=SCHEMA, pools=eligible, list_sha256=_sha('\n'.join(eligible).encode()),
                evaluable=len(eligible) >= MIN_ELIGIBLE, min_eligible=MIN_ELIGIBLE,
                conduct=None if len(eligible) >= MIN_ELIGIBLE else
                'NON ÉVALUABLE : moins de %d pools éligibles, aucun relevé de 24 h' % MIN_ELIGIBLE,
                t_start=col['t_start'], qualified_sha256=col['qualified_sha256'],
                config_sha256=col['config_sha256'], list_l_sha256=LIST_L_SHA256, rows=rows)


def bilan(collect, list_l, eligible_doc, now):
    """The dashboard at `now` from the anchored ELIGIBLE.json: pre pages and b3 must be those it recorded."""
    col = collection(collect)
    if eligible_doc['t_start'] != col['t_start'] or eligible_doc['qualified_sha256'] != col['qualified_sha256']:
        raise SimError('eligible_from_another_collection')
    pools = eligible_doc['pools']
    if not set(pools) <= set(col['pools']) or [x for x in col['pools'] if x in pools] != pools:
        raise SimError('eligible_not_the_qualified_order')
    if len(pools) < MIN_ELIGIBLE:
        raise SimError('non_evaluable_fewer_than_3_eligible')
    recorded = {r['pool']: r for r in eligible_doc['rows']}
    mint = {r['pool']: r['base_mint'] for r in list_l['list']}
    start = col['t_start']
    chunks = chunks_until(collect, start, now)
    pairs, b3, configs, pages = [], {}, {}, {}
    for x in pools:
        configs[x] = pool_config(list_l, x)
        pre, pre_txs, sha = pre_pair(collect, x, mint[x], start)
        b3[x] = G2.baseline_b3(pre, pre_txs, start)
        if sha != recorded[x]['pre_pages_sha256'] or b3[x] != recorded[x]['b3']:
            raise SimError('pre_pages_or_b3_differ_from_eligible:%s' % x)
        sim, sim_txs, shas = live_pair(collect, x, mint[x], chunks)
        pages[x] = dict(pre=sha, live=shas)
        pairs.append((pre, pre_txs, sim, sim_txs))
    seed = _sha(('livesim|%d|' % start + '\n'.join(pools)).encode())
    doc = simulate(pairs, configs, b3=b3, seed_sha=seed, start=start, now=now)
    doc.update(placebo_seed_sha256=seed, pages_sha256=pages, chunks=[c['name'] for c in chunks])
    return doc


def identity(a2r_out, u2_doc, result_path, t0_time, t0_slot):
    """F3: n1_universe on the 4 named pools' A2r pre-T0 pages gives the anchored n1rot output 6b9b02a9 (rows, kept,
    list sha); run by R03 offline (pages admitted for technical tests, R02 08:51:39Z)."""
    if file_sha(result_path) != N1ROT_RESULT_SHA256:
        raise SimError('n1rot_result_not_the_anchored_one')
    ref = _read_json(result_path)
    rows = [r for r in u2_doc['selected'] if r['pool'] in N1R.NAMED_POOLS]
    lines = {line.pool: line for line in GR.PILOT.timelines(a2r_out, 'pre', rows)}
    config = GR.PILOT.amm_config_for_rules(rows, t0_slot)
    mine = n1_universe([lines[x] for x in N1R.NAMED_POOLS], {x: config for x in N1R.NAMED_POOLS}, t0_time)
    keys = ('pool', 'kept', 'median_rotation_exact', 'threshold_exact', 'days')
    diffs = [k for k in ('kept', 'list_sha256') if mine[k] != ref[k]]
    diffs += ['%s:%s' % (a['pool'], k) for a, b in zip(mine['pools'], ref['pools']) for k in keys if a.get(k) != b.get(k)]
    if len(mine['pools']) != len(ref['pools']):
        diffs.append('pool_count')
    return dict(schema=SCHEMA, check='n1_universe == n1rot 0.2 output', n1rot_result_sha256=N1ROT_RESULT_SHA256,
                identical=not diffs, differences=diffs, kept=mine['kept'], list_sha256=mine['list_sha256'],
                expected_list_sha256=N1ROT_LIST_SHA256)


def _write_out(directory, doc, md=True):
    directory.mkdir(parents=True)
    out = {}
    items = [('LIVESIM.json', json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n')]
    if md:
        items.append(('LIVESIM.md', render(doc)))
    for name, text in items:
        (directory / name).write_text(text)
        out[name] = _sha(text.encode())
    return out


def main(argv=None):
    """python -B -m livesim.sim eligible --collect OUT --list-l LIST_L.json --out FILE
       python -B -m livesim.sim bilan --collect OUT --list-l LIST_L.json --eligible FILE --eligible-sha SHA --now T
                                      --out DIR
       python -B -m livesim.sim identity --a2r OUT_A2R --u2 U2.json --result N1ROT_RESULT.json --t0-time T --t0-slot S
                                         --out FILE
    The frozen code is checked before any file is read and again after the computation."""
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    e = sub.add_parser('eligible')
    b = sub.add_parser('bilan')
    i = sub.add_parser('identity')
    for q in (e, b):
        q.add_argument('--collect', type=Path, required=True)
        q.add_argument('--list-l', type=Path, required=True)
    for q in (e, b, i):
        q.add_argument('--out', type=Path, required=True)
    b.add_argument('--eligible', type=Path, required=True)
    b.add_argument('--eligible-sha', required=True)
    b.add_argument('--now', type=int, required=True)
    for k in ('--a2r', '--u2', '--result'):
        i.add_argument(k, type=Path, required=True)
    for k in ('--t0-time', '--t0-slot'):
        i.add_argument(k, type=int, required=True)
    a = p.parse_args(argv)
    if a.out.exists():
        raise SimError('out_exists')
    frozen = dict(manifests=check_frozen(), trees=check_trees())       # before any page is read
    if a.command == 'eligible':
        doc = eligibility(a.collect, list_l_doc(a.list_l))
    elif a.command == 'bilan':
        if file_sha(a.eligible) != a.eligible_sha:
            raise SimError('eligible_not_anchored')
        doc = bilan(a.collect, list_l_doc(a.list_l), _read_json(a.eligible), a.now)
    else:
        doc = identity(a.a2r, _read_json(a.u2), a.result, a.t0_time, a.t0_slot)
    if dict(manifests=check_frozen(), trees=check_trees()) != frozen:  # and after the run
        raise SimError('frozen_code_changed_during_the_run')
    doc['frozen_code'] = frozen
    G1.check_vocabulary(doc)
    if a.command == 'bilan':
        printed = _write_out(a.out, doc)
    else:
        text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n'
        a.out.write_text(text)
        printed = {a.out.name: _sha(text.encode())}
    print(json.dumps(printed, sort_keys=True))
    return doc


if __name__ == '__main__':
    main()
