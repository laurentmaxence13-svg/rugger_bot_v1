"""g23run 0.1.1 -- the G2-3 RUNNER (R03 23:09Z: collection with R03, verdict code with R01, audited by R02): from the raw
GTFA pages of the window to the g23five report, by FROZEN functions only. No rule of its own.

PILOT (sheet G2-3 v0.6, anchored f0129441, seed 3807920413; g23five 0.1.1):
  lines of the WINDOW pages only (<root>/<pool>/page_*.json.gz, every transaction in [T0 ; T0 + 12 d)), as
  cpmmpilot.step1.g1 for R-CP1 / B1; decisions cpmmgen2.decisions_g23 with the FROZEN b3 (2 / 1 / 6 / 1);
  positions and placebo cpmmprereg (the placebo count = the pool's decisions, its seed from the anchored sheet);
  every raw unpriced row becomes a zero-sale row (K01, cpmmpilot.step1.zero_sale, as step1._converted);
  g23five.report. The rows are written with the report (the confirmation reads sigma and r from them).
CONFIRMATION (sheet C-169; g23five 0.3; read ONLY if the pilot is GO_PILOTE):
  the same on the confirmation window [T0_C ; T0_C + D_c d) with the Holm threshold alpha; plus c5 (latency 10 slots)
  and A1 (failures (1, 1, 1)) on the SAME decisions; D_c = min(30, max(12, ceil(n_c / r))) from the PILOT rows,
  sigma_c = max(sample std of the counted pilot net returns, 2.5 %), n_c at alpha_2 / K (Holm's first step: the rank
  is unknown before reading), r = pilot entries / 12. Criteria c1 .. A1 are evaluated; CONFIRMÉ also needs Holm with
  N1 (final_words).
FINDING (declared, frozen code untouched): cpmmprereg.positions catches a CostError of cpmmcost.position but NOT one of
its own exit_point (e.g. an LP event between the decision swap and the buy landing): one such decision would stop the
whole pool. positions_each calls the frozen function ONE decision at a time and turns that CostError into the same
raw unpriced row that positions would have produced, which K01 then converts (an entered position that cannot be
priced). Without such an error the rows are identical to positions (tested).
DECLARED: window-only lines (as R-CP1): the first 600 s of a window see a truncated buyers history and the 3 600 s
cooldown restarts at the window start.
R02 DECISIONS (registry 2026-11-24T23:18:54Z, b1a0d629):
  L-FIN (option (i)): the de-facto behaviour of the frozen code (cpmmprereg.exit_point then cpmmcost.position) is the
    rule: without TP / SL among the collected swaps, the sale is valued on the state after the LAST collected swap
    before T0 + D, status entered (as R-CP1). Published, descriptive only: per pool, the number of decisions whose clock
    exit falls after T0 + D. Also valid for C-169, C-170 and N1 (N1 keeps L4).
  G-0: cpmmcost.pool_gate on every named pool, as step1.g1. g0_passed = True when the gate was evaluated on the 4 pools
    without an integrity failure (admitted or not); an exception (decoding, AmmConfig, unknown status) -> False -> STOP.
    Non-admitted pools are excluded and published with their reasons; the sheet's floors judge afterwards.
  T1 slot: not needed (the AmmConfig is U2's, slot 473309024, never re-read).
ERRATUM C-169 (08b14a6b, R04-9), published at the PILOT: c_j = credits of the g23 registry / 12; sigma, r; n_c and D_c*
  for K = 1 and K = 2; P = ceil(1.25 x c_j x D_c*); D_c33 = min(D_c*, floor(32 340 / (1.25 x c_j))). The confirmation
  run takes D_c explicitly and accepts only D_c* or D_c33 of the kept K.
0.1.1 (R02 audit of 0.1, registry 4df09aff: PILOT PASS and anchored; confirmation corrected here, separate package, the
  pilot path unchanged except the published flag of F2):
  F1/F3 (erratum 08b14a6b, R04-9): the owner's answer on P is an input. accepted -> P <= 60 000 required and D_c = D_c*;
    refused -> D_c = D_c33 and D_c33 >= 12 required. Otherwise C-169 is NON ÉVALUABLE: published, no page is read.
    --d-c is an equality check only.
  F2: at the pilot, each K of erratum_c169 publishes p_above_60000 (-> NON ÉVALUABLE if the owner accepts).
  F4: K = 1 -> alpha 0.025 only.  F5: K = 2 -> ONE run computes the criteria and the word at 0.0125 AND at 0.025 (the
    bootstrap p does not depend on alpha); final_words gives each hypothesis the word at the threshold Holm assigns
    to it (rank by p, an INCONCLUSIF / STOP counts p = 1, as sheet C-169 § 4).
  Minor: per pool, the number of primary rows that come from an exit_point CostError.
"""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmpilot import step1 as PILOT
from cpmmpilot.store import read_gz_page
from cpmmprereg import rule as R
from cpmmx import timeline as TL
from g23five import verdict as V

SCHEMA = 'g23run-v0.1.1'
POOLS = ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr',
         'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh', 'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')
POOLS_SHA256 = '812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80'
B3 = dict(zip(POOLS, (2, 1, 6, 1)))                               # FROZEN (G2_3_PER_DAY_K 6def2254, sheet v0.6)
T0, T0_C, D_PILOT = 1795515686, 1796552486, 12
DAY_S = 86_400
VERSIONS = dict(pilot='g23five-v0.1.1', confirmation='g23five-v0.3')
ALPHA_2, SIGMA_FLOOR, DELTA = 0.025, 0.025, 0.005
CREDIT_CAP, CREDIT_MARGIN = 32_340, 1.25
P_LIMIT, D_C_MIN = 60_000, 12
OWNER_P = ('accepted', 'refused')


class RunError(ValueError):
    pass


def window_line(pool, base_mint, directory, *, start, end):
    """(line, raw transactions) of the window pages of one pool; a transaction outside [start ; end) stops."""
    txs = {}
    pages = sorted(Path(directory).glob('page_*.json.gz'))
    if not pages:
        raise RunError('no_window_page')
    for page in pages:
        for tx in read_gz_page(page).get('data') or []:
            when = tx.get('blockTime')
            if type(when) is not int:
                raise RunError('transaction_without_block_time')
            if not start <= when < end:
                raise RunError('page_outside_the_window')
            txs[tx['transaction']['signatures'][0]] = tx
    return TL.build(pool, txs, base_mint=base_mint), txs


def converted(line, rows, failures=CC.FROZEN_FAILURES):
    """K01 (as cpmmpilot.step1._converted): a raw unpriced row becomes a zero-sale row of ITS failure series."""
    return [r if 'net_return' in r else
            PILOT.zero_sale(dict(r, decision_slot=line.swaps[r['decision_index']].slot), failures) for r in rows]


def positions_each(line, config, indices, errors=None, **kw):
    """cpmmprereg.positions one decision at a time; an exit_point CostError becomes its raw unpriced row (counted in
    errors when a list is given)."""
    out = []
    for i in indices:
        try:
            out += R.positions(line, config, [i], **kw)
        except CC.CostError as exc:
            out.append(dict(pool=line.pool, decision_index=i, unpriced=str(exc),
                            decision_time=line.swaps[i].block_time))
            if errors is not None:
                errors.append(i)
    return out


def pool_rows(line, txs, config, b3, sheet_sha, *, variants=False):
    idx = G2.decisions_g23(line, txs, b3)
    errors = []
    out = dict(decisions=len(idx), primary=converted(line, positions_each(line, config, idx, errors)),
               placebo=converted(line, positions_each(line, config, R.placebo(line, len(idx), sheet_sha))))
    if variants:
        out['c5_10_slots'] = converted(line, positions_each(line, config, idx,
                                                            latency_slots=CC.SENSITIVITY_LATENCY_SLOTS))
        out['a1_one_failure'] = converted(line, positions_each(line, config, idx, failures=CC.SENSITIVITY_FAILURES),
                                          CC.SENSITIVITY_FAILURES)
        out['exit_point_errors'] = len(errors)
    return out


def d_confirmation(pilot_primary, *, kept):
    """D_c of the confirmation from the PILOT counted rows (sheet C-169 § 2, R02 22:47Z)."""
    if kept not in (1, 2):
        raise RunError('kept_hypotheses_must_be_1_or_2')
    nets = [r['net_return'] for r in pilot_primary]
    if len(nets) < 2:
        raise RunError('pilot_rows_too_few_for_sigma')
    sigma = statistics.stdev(nets)
    entries = len(V.entries(pilot_primary))
    r = entries / D_PILOT
    sigma_c = max(sigma, SIGMA_FLOOR)
    alpha = ALPHA_2 / kept
    n_c = R.n_required(sigma=sigma_c, delta=DELTA, alpha=alpha)
    d_c = 30 if r == 0 else min(30, max(12, math.ceil(n_c / r)))
    return dict(sigma_pilot=sigma, sigma_c=sigma_c, entries_pilot=entries, r_per_day=r, alpha_first_step=alpha,
                n_c=n_c, d_c=d_c)


def evaluability(design, owner_p):
    """F1 / F3: (D_c, None) when C-169 can be read, (None, reason) when it is NON ÉVALUABLE."""
    if owner_p not in OWNER_P:
        raise RunError('owner_p_must_be_accepted_or_refused')
    if design['p'] == V.NM:
        raise RunError('credits_required_for_the_confirmation')
    if owner_p == 'accepted':
        if design['p'] > P_LIMIT:
            return None, 'p_above_60000'
        return design['d_c'], None
    if design['d_c33'] < D_C_MIN:
        return None, 'd_c33_below_12'
    return design['d_c33'], None


def budget(design, credits):
    """ERRATUM C-169: c_j, P and D_c33 from the pilot's registry credits (None -> NON MESURÉ)."""
    if credits is None:
        return dict(c_j=V.NM, p=V.NM, d_c33=V.NM)
    if type(credits) not in (int, float) or not credits > 0:
        raise RunError('credits_must_be_positive')
    c_j = credits / D_PILOT
    return dict(c_j=c_j, p=math.ceil(CREDIT_MARGIN * c_j * design['d_c']),
                d_c33=min(design['d_c'], math.floor(CREDIT_CAP / (CREDIT_MARGIN * c_j))))


def clock_exits_after(line, config, indices, end):
    """L-FIN, descriptive: decisions whose clock exit (no TP / SL among the collected swaps) falls after the end."""
    n = 0
    for i in indices:
        try:
            _slot, exit_time = R.exit_point(line, i, config)
        except CC.CostError:
            continue
        if exit_time is not None and exit_time > end:
            n += 1
    return n


def gates(pairs, config):
    """G-0 (R02): pool_gate on every pool; an integrity failure (an exception) makes g0_passed False."""
    out, ok = {}, True
    for line, _txs in pairs:
        try:
            out[line.pool] = CC.pool_gate(line, config)
        except (ValueError, KeyError, TypeError) as exc:
            out[line.pool] = dict(admitted=False, reasons=['integrity_failure:%s' % exc])
            ok = False
    return out, ok


def _lines(selected, root, *, start, end):
    by_pool = {r['pool']: r for r in selected}
    if any(p not in by_pool for p in POOLS):
        raise RunError('a_named_pool_is_missing_from_the_selection')
    return [window_line(p, by_pool[p]['base_mint'], Path(root) / p, start=start, end=end) for p in POOLS]


def criteria(main, c5, a1):
    gap = main['placebo']['difference_bounds_95']['lower']
    out = dict(
        c1=main['lower_bound_95'] is not None and main['lower_bound_95'] > 0,
        c2=type(gap) is float and gap > 0,
        c3=main['halves']['both_positive'],
        c4=True,                                                   # K01: every unpriced position counted (converted)
        c5=(type(c5['mean_net_return']) is float and c5['mean_net_return'] > 0
            and main['without_top_pool']['lower_bound_95'] is not None
            and main['without_top_pool']['lower_bound_95'] > 0),
        a1=type(a1['mean_net_return']) is float and a1['mean_net_return'] > 0)
    return out


def confirmation_word(main, crit):
    """Before Holm: STOP / INCONCLUSIF (floors) / NON CONFIRMÉ / CRITÈRES REMPLIS (CONFIRMÉ only with Holm)."""
    if main['decision'] == 'STOP':
        return 'STOP'
    if not main['floors']['passed']:
        return 'INCONCLUSIF'
    return 'CRITÈRES REMPLIS' if all(crit.values()) else 'NON CONFIRMÉ'


def alphas_for(kept):
    """F4 / F5: the thresholds at which one confirmation run evaluates its criteria."""
    if kept == 1:
        return (ALPHA_2,)
    if kept == 2:
        return (ALPHA_2 / 2, ALPHA_2)
    raise RunError('kept_hypotheses_must_be_1_or_2')


def final_words(hypotheses):
    """Holm over the kept hypotheses, sheet C-169 § 4. hypotheses = {name: dict(p=p, words={alpha: word})}.
    Rank by p (an INCONCLUSIF or STOP counts p = 1; ties by name); rank r is tested at alpha_2 / (K - r); the step-down
    stops at the first p above its threshold. A rejected hypothesis is CONFIRMÉ only if its word AT ITS threshold is
    CRITÈRES REMPLIS; every other one keeps INCONCLUSIF / STOP, or becomes NON CONFIRMÉ."""
    k = len(hypotheses)
    for name, h in hypotheses.items():
        if set(h['words']) != set(alphas_for(k)):
            raise RunError('words_must_be_given_at_every_holm_threshold')
    def p_eff(name):
        h = hypotheses[name]
        return 1.0 if h['words'][ALPHA_2] in ('INCONCLUSIF', 'STOP') or h['p'] is None else h['p']
    out = {name: (h['words'][ALPHA_2] if h['words'][ALPHA_2] in ('INCONCLUSIF', 'STOP') else 'NON CONFIRMÉ')
           for name, h in hypotheses.items()}
    for rank, name in enumerate(sorted(hypotheses, key=lambda n: (p_eff(n), n))):
        threshold = ALPHA_2 / (k - rank)
        if p_eff(name) > threshold:
            break
        word = hypotheses[name]['words'][threshold]
        out[name] = 'CONFIRMÉ' if word == 'CRITÈRES REMPLIS' else out[name]
    return out


def run(phase, *, selected, root, config, sheet_sha, alpha=0.05, pilot_rows=None, pilot_decision=None, kept=None,
        d_c=None, credits=None, owner_p=None, draws=V.DRAWS):
    if V.SCHEMA != VERSIONS.get(phase):
        raise RunError('g23five_version_does_not_match_the_phase')
    if hashlib.sha256('\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:
        raise RunError('named_list_altered')
    if phase == 'pilot':
        if alpha != 0.05:
            raise RunError('pilot_alpha_is_0_05')
        start, d_days, design = T0, D_PILOT, None
    else:
        if alpha != 0.05:
            raise RunError('confirmation_alphas_follow_k')                     # F4 / F5: never chosen by hand
        if pilot_decision != 'GO_PILOTE':
            raise RunError('confirmation_read_only_after_a_go_pilote')
        if pilot_rows is None:
            raise RunError('pilot_rows_required')
        alphas = alphas_for(kept)
        design = d_confirmation(pilot_rows, kept=kept)
        design.update(budget(design, credits))
        used, reason = evaluability(design, owner_p)
        design.update(owner_p=owner_p, p_above_60000=design['p'] > P_LIMIT)
        if used is None:
            doc = dict(schema=SCHEMA, phase=phase, design=design, conduct='NON ÉVALUABLE', reason=reason,
                       pages_read=False)
            return V.G1.check_vocabulary(doc), dict(primary=[], placebo=[], c5_10_slots=[], a1_one_failure=[])
        if d_c != used:
            raise RunError('d_c_differs_from_the_rule')
        design['d_c_used'] = used
        start, d_days = T0_C, used
    end = start + d_days * DAY_S
    pairs = _lines(selected, root, start=start, end=end)
    gate, g0_passed = gates(pairs, config)
    rows = dict(primary=[], placebo=[], c5_10_slots=[], a1_one_failure=[])
    decisions, after_end, exit_errors = {}, {}, {}
    for (line, txs) in pairs:
        if not gate[line.pool]['admitted']:
            continue
        got = pool_rows(line, txs, config, B3[line.pool], sheet_sha, variants=phase == 'confirmation')
        decisions[line.pool] = got.pop('decisions')
        if 'exit_point_errors' in got:
            exit_errors[line.pool] = got.pop('exit_point_errors')
        after_end[line.pool] = clock_exits_after(line, config, G2.decisions_g23(line, txs, B3[line.pool]), end)
        for k, v in got.items():
            rows[k] += v
    published = dict(pool_gate={p: dict(admitted=g['admitted'], reasons=g['reasons']) for p, g in gate.items()},
                     g0_passed=g0_passed, decisions=decisions,
                     l_fin=dict(rule="sortie horloge au-delà de T0 + D : vente sur l'état après le dernier swap collecté",
                                clock_exits_after_the_end=after_end))
    common = dict(pools=list(POOLS), g0_passed=g0_passed, freeze_sheet_sha256=sheet_sha, t0=start, d_days=d_days,
                  draws=draws)
    if phase == 'pilot':
        report = V.report(rows['primary'], rows['placebo'], **common)
        doc = dict(schema=SCHEMA, phase=phase, report=report, **published)
        if report['decision'] != 'STOP' and len(rows['primary']) >= 2:
            doc['erratum_c169'] = {'K=%d' % k: dict(d_confirmation(rows['primary'], kept=k),
                                                   **budget(d_confirmation(rows['primary'], kept=k), credits))
                                   for k in (1, 2)}
            for e in doc['erratum_c169'].values():                             # F2
                e['p_above_60000'] = V.NM if e['p'] == V.NM else e['p'] > P_LIMIT
    else:
        at = {}
        for a in alphas:
            main = V.report(rows['primary'], rows['placebo'], alpha=a, **common)
            c5 = V.report(rows['c5_10_slots'], [], alpha=a, **common)
            a1 = V.report(rows['a1_one_failure'], [], alpha=a, **common)
            crit = criteria(main, c5, a1) if main['decision'] != 'STOP' else {}
            at[a] = dict(report=main, c5_10_slots=c5, a1_one_failure=a1, criteria=crit,
                         word_before_holm=confirmation_word(main, crit))
        ps = {at[a]['report'].get('p_value') for a in alphas}
        if len(ps) != 1:
            raise RunError('p_value_depends_on_alpha')                         # never: same draws
        doc = dict(schema=SCHEMA, phase=phase, design=design, kept=kept, alphas=list(alphas), **published,
                   exit_point_errors=exit_errors, at_alpha={str(a): v for a, v in at.items()}, p_value=ps.pop(),
                   words={a: at[a]['word_before_holm'] for a in alphas})
    return V.G1.check_vocabulary(doc), rows


def main(argv=None):
    """python -B -m g23run.run --phase pilot|confirmation --u2 U2.json --root DIR --t0-slot S --sheet-sha HEX
    --g23-credits C [--pilot-dir <the pilot's OUT> --kept K --owner-p accepted|refused --d-c D] --out DIR"""
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=tuple(VERSIONS), required=True)
    for k in ('--u2', '--root', '--out'):
        p.add_argument(k, type=Path, required=True)
    p.add_argument('--t0-slot', type=int, required=True)
    p.add_argument('--sheet-sha', required=True)
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--g23-credits', type=float)
    p.add_argument('--d-c', type=int)
    p.add_argument('--owner-p', choices=OWNER_P)
    p.add_argument('--pilot-dir', type=Path)
    p.add_argument('--kept', type=int)
    a = p.parse_args(argv)
    if a.out.exists():
        raise RunError('out_exists')
    u2 = json.loads(a.u2.read_text())
    if u2.get('t0_time') != T0:
        raise RunError('t0_mismatch')
    selected = [r for r in u2['selected'] if r['pool'] in POOLS]
    config = PILOT.amm_config_for_rules(selected, a.t0_slot)
    pilot_rows = pilot_decision = None
    if a.pilot_dir is not None:
        pilot_rows = json.loads((a.pilot_dir / 'ROWS.json').read_text())['primary']
        pilot_decision = json.loads((a.pilot_dir / 'RESULT.json').read_text())['report']['decision']
    doc, rows = run(a.phase, selected=selected, root=a.root, config=config, sheet_sha=a.sheet_sha, alpha=a.alpha,
                    pilot_rows=pilot_rows, pilot_decision=pilot_decision, kept=a.kept, d_c=a.d_c,
                    credits=a.g23_credits, owner_p=a.owner_p)
    a.out.mkdir(parents=True)
    out = {}
    for name, content in (('ROWS.json', rows), ('RESULT.json', doc)):
        text = json.dumps(content, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n'
        (a.out / name).write_text(text)
        out[name] = hashlib.sha256(text.encode()).hexdigest()
    print(json.dumps(out, sort_keys=True))


if __name__ == '__main__':
    main()
