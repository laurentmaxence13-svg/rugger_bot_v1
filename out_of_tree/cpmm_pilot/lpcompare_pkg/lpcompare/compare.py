"""lpcompare 0.1 -- the stopped live PAPER test against livesim on the same period, decision by decision, offline, 0
credit (R04 12:16Z; conventions declared to R02 BEFORE any datum was read, R01 12:2xZ). It reads anchored files only,
never calls the network and never modifies frozen code: livesim 0.3.2 (truncated, g23_rows, exit_time_of, rebuilt,
pool_config, live_pair), cpmmgen2 (decisions_g23, buyers), cpmmcost (pool_gate) and livepaper.journal are imported.

K1 now = receipt_time of the LAST STEP of the journal; nothing after it is read on either side.
K2 three views, the frozen functions of livesim 0.3.2 / livepaper cli.compare:
   L = the live journal as recorded (DECISION, LANDING, EXIT);
   P = a posteriori on the live pages (TL.build, cpmmrecon, LS.g23_rows; live start, live seed, now);
   S = livesim on its own pages (transactions with blockTime <= now, cpmmrecon, G-0 at now as livesim.simulate,
       LS.g23_rows with the livesim start and seed), restricted to the decisions of [live start ; now].
K3 key = (pool, signature of the trigger swap); L & S / L only / S only, P presence noted, P only listed. The L-only and
   S-only rows left on one pool are paired "shifted" when |dt| < 3 600 s (cooldown), nearest first, chronologically.
K4 per row: segment, trigger shift (s, slots), live latency = receipt - trigger (s, slots), entry (buy_landing_slot,
   tokens), exit (rule, declared point, exit_time by LS.exit_time_of, status), net_lamports of each; a position open
   at now is 'open', its net NON MESURÉ; the livesim T+24 h outcome (anchored LIVESIM.json) is shown beside.
K5 the reason of every divergence, the declared deterministic tree (`reasons_*`).
K6 the witness: L (journal) and S (livesim draw) listed apart; paired only on the same pool AND the same entry swap.
K7 segments: conforming = trigger (witness: entry time) in [live start ; CONFORM_END[, out of protocol = [CONFORM_END ;
   now]; a conforming row whose exit is after CONFORM_END (or open) is flagged.
K8 annex: the transactions present on one side and absent from the other, per pool, in [live start ; now].
R02 12:23Z accord under seven conditions: C-1 the D15 mention heads COMPARE.md, D13 and D14 head the out-of-protocol
segment; C-2 a conforming entry whose exit (either side) is at or after CONFORM_END, or open, is published apart
('conforme à l'entrée, sortie hors protocole') and never added to the conforming sums; C-3 the livesim witness is drawn
at THIS now, not comparable to the T+24 h draw (the T+24 h control is for the primaries only); C-4 the 3 600 s of the
shifted pairing is frozen and the strict-key counts are published without it; C-5 limit L4 (livesim retrospective by
2-h chunks, the live polls every 30 s: the latency gap is structural; no net sum compares as a proof of one side over
the other); C-6 '<= now' on both sides (live records up to the last STEP, receipt_time <= now; livesim blockTime <=
now); C-7 MANIFEST, tests, mutants, R02 audit BEFORE any reading of the data, then a double run R01 / R02.
LABELS PAPER_LIVE_DEMO / PAPER_SIMULATION: never an operational Master trade, never counted for 50/20; no verdict; a
descriptive result, no economic conclusion."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmpilot import step1 as PILOT
from cpmmpilot.store import read_gz_page
from cpmmprereg import rule as R
from cpmmx import timeline as TL
from g1ind import report as G1
from livepaper import journal as J
from livesim import sim as LS

SCHEMA = 'lpcompare-v0.1'
LABELS = ('PAPER_LIVE_DEMO', 'PAPER_SIMULATION', 'DESCRIPTIVE_COMPARISON')
NM = LS.NM
LIVE_START = 1_795_632_000                  # 25/11 18:40:00Z, START of the journal (checked)
CONFORM_END = 1_795_637_403                 # 25/11 20:10:03Z (R04 12:16Z: getSlot ratified up to it)
D13 = ('GaPTvXuog95vxJii7qwvfNVNdpgAcEmjFqYdZnxxgzLV', 473_875_242)   # d13_verify 9d6f8b6, adopted by R02
PAIR_S = R.COOLDOWN_S
LOOKBACK_S = R.LOOKBACK_S
SEGMENTS = ('conforme', 'conforme_sortie_hors_protocole', 'hors_protocole')
SPLIT = 'conforme_sortie_hors_protocole'
SEGMENT_TITLES = {
    'conforme': 'Segment conforme [18:40:00Z ; 20:10:03Z[ (getSlot ratifié) : entrée et sortie avant 20:10:03Z',
    SPLIT: 'Conforme à l\'entrée, sortie hors protocole (publié à part, non additionné au segment conforme)',
    'hors_protocole': 'Segment hors protocole [20:10:03Z ; now]'}
HEADER_D15 = ('getSlot, hors du texte 1366025b, a été utilisé (écart D15) ; usage ratifié a posteriori par le '
              'propriétaire le 26/11 à 07:14:54Z (événement e383a010), l\'écart restant documenté.')
OUT_OF_PROTOCOL = ('Écarts de ce segment : D13 (transaction manquée de GaPTvX, slot 473875242 ; exclusion G-0 à partir '
                   'de 20:11:03Z) ; D14 (erreurs tolérées).')
LIMIT_L4 = ('Limite L4 : livesim est rétrospectif par blocs de 2 h, le live interroge toutes les 30 s ; l\'écart de '
            'latence est structurel. Aucune somme nette ne se compare comme preuve d\'un côté sur l\'autre.')
PLACEBO_NOTE = 'tirage au now de la comparaison, non comparable au T+24 h'


class CompareError(ValueError):
    pass


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hms(t):
    return time.strftime('%H:%M:%SZ', time.gmtime(t)) if type(t) is int else '—'


def segment(t, conform_end):
    return 'conforme' if t < conform_end else 'hors_protocole'


def place(row, t, sides, conform_end):
    """K7 + R02 C-2: the entry segment of t; a conforming entry whose exit on either side is at or after
    conform_end, or still open at now, goes to the apart sub-category (never added to the conforming sums)."""
    row['entry_segment'] = segment(t, conform_end)
    ends = [x['outcome']['exit_time'] for x in sides if x]
    opened = any(x['outcome']['status'] == 'open' for x in sides if x)
    row['exit_after_conform_end'] = row['entry_segment'] == 'conforme' and (
        opened or any(e is not None and e >= conform_end for e in ends))
    row['segment'] = SPLIT if row['exit_after_conform_end'] else row['entry_segment']
    return row


# -- normalised position --------------------------------------------------------------------------------------------
def outcome(row, known):
    """(status, landing, tokens, rule, declared, exit_time, net) of a priced row; None -> open."""
    if row is None:
        return dict(status='open', landing=None, tokens=None, rule=None, declared=None, exit_time=None, net=None)
    entered = row.get('status') == 'entered'
    ex = row.get('exit') if entered else None
    if 'exit_time' in row:
        exit_time = row['exit_time'] if entered else None
    else:
        exit_time = LS.exit_time_of(known, row) if entered else None
    return dict(status=row.get('status'), landing=row.get('buy_landing_slot'), tokens=row.get('tokens'),
                rule=ex['rule'] if ex else None, declared=ex['declared'] if ex else None, exit_time=exit_time,
                net=row['net_lamports'])


# -- facts ----------------------------------------------------------------------------------------------------------
def distinct_buyers(line, txs, t, key=None):
    """Distinct buyers of ]t - 600 ; t] over the swaps up to the trigger key (cpmmgen2._window), on one side."""
    payer = G2.buyers(line, txs)
    upto = [k for k, s in enumerate(line.swaps) if (key is None or tuple(s.key) <= tuple(key)) and s.block_time <= t]
    if not upto:
        return 0
    return len({payer[k] for k in upto if t - LOOKBACK_S < line.swaps[k].block_time <= t and payer[k]})


def missing(a, b, low, high):
    """Signatures of side a absent from side b with low < blockTime <= high: [(sig, slot, blockTime)]."""
    return sorted(((s, v[0], v[1]) for s, v in a.items() if s not in b and low < v[1] <= high),
                  key=lambda x: (x[2], x[1], x[0]))


def is_d13(pool, slot, d13):
    return (pool, slot) == tuple(d13)


def admission_at(timeline, t):
    """The live G-0 state at the first STEP with receipt_time >= t: (admitted, reasons, receipt_time) or None."""
    for rt, ok, reasons in timeline:
        if rt >= t:
            return ok, reasons, rt
    return None


def ever_admitted(timeline, t):
    return any(ok for rt, ok, _r in timeline if rt >= t)


def inside(intervals, t):
    return [list(iv) for iv in intervals if iv[0] <= t <= iv[1]]


def prior(chain, t, *, window=PAIR_S):
    """Signals of a chain [(time, sig)] in (t - window ; t)."""
    return [list(c) for c in chain if t - window < c[0] < t]


# -- the declared reason trees (K5) ---------------------------------------------------------------------------------
def reasons_livesim_only(pool, sig, t, live, livesim, d13):
    """S only. (a) never admitted at the live G-0 between t and now; (b) trigger absent from the live pages; (c) in P but
    not L; (d) otherwise a different chain of signals."""
    side = live['pools'][pool]
    if not ever_admitted(side['admission'], t):
        st = admission_at(side['admission'], t)
        return ['exclusion G-0 live (%s)' % ', '.join(st[1] if st else ['aucune réception après t'])]
    if sig not in side['sigs']:
        slot = livesim['pools'][pool]['sigs'][sig][0]
        return ['transaction absente des pages live' + (' (D13)' if is_d13(pool, slot, d13) else '')]
    if (pool, sig) in live['P']:
        out = ['décidable a posteriori, non décidé en direct']
        if inside(live['gaps'], t):
            out.append('trou d\'observation GAP couvrant t')
        if inside(live['resumptions'], t):
            out.append('reprise couvrant t')
        return out
    return ['chaîne de signaux différente']


def reasons_live_only(pool, sig, t, live, livesim):
    """L only. (a) trigger absent from the livesim pages; (b) pool not eligible in livesim at now; (c) L without P;
    (d) otherwise a different chain of signals."""
    side = livesim['pools'][pool]
    if sig not in side['sigs']:
        return ['transaction absente de la collecte livesim']
    if not side['eligible']:
        return ['pool non éligible dans livesim au now (%s)' % ', '.join(side['gate_reasons'] or ['b3_zero'])]
    if (pool, sig) not in live['P']:
        return ['décision live non confirmée a posteriori sur ses propres pages']
    return ['chaîne de signaux différente']


def reasons_both(lo, so):
    """L & S: the gaps of entry and exit."""
    if (lo['status'] == 'open') != (so['status'] == 'open'):
        return ['troncature (%s ouvert à now ; règlement du live 150 slots / 60 s)'
                % ('live' if lo['status'] == 'open' else 'livesim')]
    if lo['status'] == 'open':
        return ['ouvert des deux côtés à now']
    out = []
    if lo['status'] != so['status']:
        out.append('statut différent (%s / %s) : garde d\'achat sur une autre ancre' % (lo['status'], so['status']))
    if lo['landing'] != so['landing']:
        out.append('latence du live (ancre à la réception)')
    if lo['rule'] != so['rule']:
        out.append('règle de sortie (%s / %s)' % (lo['rule'], so['rule']))
    elif lo['declared'] != so['declared']:
        out.append('point de sortie différent, même règle')
    return out or ['aucun écart']


def facts(pool, t, key, live, livesim, d13):
    lp, sp = live['pools'][pool], livesim['pools'][pool]
    miss_live = missing(sp['sigs'], lp['sigs'], t - LOOKBACK_S, t)
    miss_ls = missing(lp['sigs'], sp['sigs'], t - LOOKBACK_S, t)
    return dict(
        missing_in_live_600=len(miss_live), missing_in_livesim_600=len(miss_ls),
        d13_in_600=any(is_d13(pool, m[1], d13) for m in miss_live),
        buyers_live=distinct_buyers(lp['known'], lp['txs'], t, key),
        buyers_livesim=distinct_buyers(sp['known'], sp['txs'], t, key),
        threshold=G2.BUYERS_MULTIPLIER * lp['b3'],
        prior_live_signal=prior(lp['chain'], t), prior_livesim_signal=prior(sp['chain'], t),
        gap=inside(live['gaps'], t), resumption=inside(live['resumptions'], t))


# -- primary comparison ---------------------------------------------------------------------------------------------
def _pair(rows, pair_s):
    """Pair the remaining L-only and S-only rows of one pool when |dt| < pair_s, nearest first, chronologically."""
    lo = [r for r in rows if r['category'] == 'live_only']
    so = [r for r in rows if r['category'] == 'livesim_only']
    taken, pairs = set(), []
    for a in sorted(lo, key=lambda r: (r['live']['trigger_time'], r['sig'])):
        best = None
        for b in so:
            if id(b) in taken or b['pool'] != a['pool']:
                continue
            d = abs(a['live']['trigger_time'] - b['livesim']['trigger_time'])
            if d < pair_s and (best is None or (d, b['livesim']['trigger_time']) < best[0]):
                best = ((d, b['livesim']['trigger_time']), b)
        if best is not None:
            taken.add(id(best[1]))
            pairs.append((a, best[1]))
    return pairs


def primary_rows(live, livesim, *, conform_end, d13, pair_s=PAIR_S):
    keys = set(live['L']) | set(livesim['S']) | set(live['P'])
    rows = []
    for key in keys:
        pool, sig = key
        l, s, p = live['L'].get(key), livesim['S'].get(key), live['P'].get(key)
        t = (l or s or p)['trigger_time']
        row = dict(pool=pool, sig=sig, in_live=l is not None, in_livesim=s is not None, in_a_posteriori=p is not None,
                   live=l, livesim=s, a_posteriori=p)
        if l and s:
            row['category'] = 'both'
            row['reasons'] = reasons_both(l['outcome'], s['outcome'])
        elif l:
            row['category'] = 'live_only'
            row['reasons'] = reasons_live_only(pool, sig, t, live, livesim)
        elif s:
            row['category'] = 'livesim_only'
            row['reasons'] = reasons_livesim_only(pool, sig, t, live, livesim, d13)
        else:
            row['category'] = 'a_posteriori_only'
            row['reasons'] = ['décidable sur les pages live a posteriori seulement']
        row['trigger_time'] = t
        row['facts'] = facts(pool, t, (l or s or p)['trigger_key'], live, livesim, d13)
        rows.append(row)
    rows.sort(key=lambda r: (r['trigger_time'], r['pool'], r['sig']))
    for pool in sorted({r['pool'] for r in rows}):
        for a, b in _pair([r for r in rows if r['pool'] == pool], pair_s):
            a['shifted_with'] = b['sig']
            b['shifted_with'] = a['sig']
            a['shift'] = b['shift'] = dict(
                seconds=a['live']['trigger_time'] - b['livesim']['trigger_time'],
                slots=a['live']['trigger_slot'] - b['livesim']['trigger_slot'])
    for r in rows:
        place(r, r['trigger_time'], (r['live'], r['livesim']), conform_end)
        if r['category'] == 'both':
            r['shift'] = dict(seconds=0, slots=0)
    return rows


# -- witness --------------------------------------------------------------------------------------------------------
def placebo_rows(live, livesim, *, conform_end):
    out = []
    s_by_key = {(x['pool'], tuple(x['entry_key'])): x for x in livesim['S_placebo']}
    used = set()
    for x in live['L_placebo']:
        k = (x['pool'], tuple(x['entry_key']))
        s = s_by_key.get(k)
        if s is not None:
            used.add(k)
        out.append(place(dict(pool=x['pool'], category='both' if s else 'live_only', live=x, livesim=s,
                              entry_time=x['entry_time'], reasons=['même swap d\'entrée'] if s else
                              ['mécanismes de témoin différents par construction']),
                         x['entry_time'], (x, s), conform_end))
    for k, s in s_by_key.items():
        if k in used:
            continue
        out.append(place(dict(pool=s['pool'], category='livesim_only', live=None, livesim=s, entry_time=s['entry_time'],
                              reasons=['mécanismes de témoin différents par construction']),
                         s['entry_time'], (None, s), conform_end))
    out.sort(key=lambda r: (r['entry_time'], r['pool'], r['category']))
    return out


# -- annex ----------------------------------------------------------------------------------------------------------
def annex(live, livesim, *, start, now, conform_end, d13):
    out = {}
    for pool in live['order']:
        lp, sp = live['pools'][pool]['sigs'], livesim['pools'][pool]['sigs']
        rows = []
        for side, a, b in (('absent_live', sp, lp), ('absent_livesim', lp, sp)):
            for sig, slot, bt in missing(a, b, start - 1, now):
                rows.append(dict(side=side, sig=sig, slot=slot, block_time=bt, segment=segment(bt, conform_end),
                                 d13=side == 'absent_live' and is_d13(pool, slot, d13)))
        out[pool] = dict(rows=rows, live_before_start=sum(1 for v in lp.values() if v[1] < start),
                         live_in_window=sum(1 for v in lp.values() if start <= v[1] <= now),
                         livesim_in_window=sum(1 for v in sp.values() if start <= v[1] <= now))
    return out


# -- summary --------------------------------------------------------------------------------------------------------
def summary(prim, plac):
    out = {}
    for seg in SEGMENTS:
        p = [r for r in prim if r['segment'] == seg]
        w = [r for r in plac if r['segment'] == seg]
        cats = {}
        for r in p:
            cats[r['category']] = cats.get(r['category'], 0) + 1
        reasons = {}
        for r in p:
            for why in r['reasons']:
                reasons[why] = reasons.get(why, 0) + 1

        def nets(rows, side):
            got = [r[side]['outcome'] for r in rows if r[side]]
            closed = [o['net'] for o in got if o['status'] != 'open']
            return dict(positions=len(got), closed=len(closed), open=len(got) - len(closed),
                        net_lamports_closed_sum=sum(closed))
        out[seg] = dict(primary=dict(rows=len(p), strict_key_categories=cats, reasons=reasons,
                                     shifted_rows=sum(1 for r in p if r.get('shifted_with')),
                                     live=nets(p, 'live'), livesim=nets(p, 'livesim')),
                        placebo=dict(rows=len(w), strict_key_categories={c: sum(1 for r in w if r['category'] == c)
                                                              for c in ('both', 'live_only', 'livesim_only')},
                                     live=nets(w, 'live'), livesim=nets(w, 'livesim')),
                        descriptive=True)
    return out


def build(live, livesim, *, conform_end=CONFORM_END, d13=D13, t24=None):
    prim = primary_rows(live, livesim, conform_end=conform_end, d13=d13)
    plac = placebo_rows(live, livesim, conform_end=conform_end)
    if t24 is not None:
        for r in prim:
            if r['livesim'] is None:
                continue
            k = (r['pool'], r['livesim']['decision_index'])
            got = t24.get(k)
            if got is None or (got['decision_slot'] if got['decision_slot'] is not None else got['decision_time']) \
                    != (r['livesim']['trigger_slot'] if got['decision_slot'] is not None
                        else r['livesim']['trigger_time']):
                raise CompareError('t24_row_missing_or_other:%s:%s' % k)
            if r['livesim']['outcome']['status'] != 'open' and got['outcome'] != r['livesim']['outcome']:
                raise CompareError('t24_row_differs_from_now:%s:%s' % k)
            r['livesim_t24'] = got['outcome']
    doc = dict(schema=SCHEMA, labels=list(LABELS), counts_for_operational_master=False, verdict=None,
               economic_conclusion=None, now=live['now'], live_start=live['start'], livesim_start=livesim['start'],
               conform_end=conform_end, d13=list(d13), pair_s=PAIR_S,
               notes=dict(header_d15=HEADER_D15, limit_l4=LIMIT_L4, out_of_protocol=OUT_OF_PROTOCOL,
                          placebo=PLACEBO_NOTE, t24='contrôle T+24 h pour les primaires seulement',
                          cut='≤ now des deux côtés : enregistrement live retenu si receipt_time ≤ now, transaction '
                              'livesim si blockTime ≤ now'), journal_head=live['head'],
               journal_records=live['records'], journal_records_total=live['records_total'], pools=live['order'],
               livesim_gate={p: dict(eligible=v['eligible'], reasons=v['gate_reasons'])
                             for p, v in livesim['pools'].items()},
               gaps=live['gaps'], resumptions=live['resumptions'],
               primary=prim, placebo=plac, summary=summary(prim, plac),
               annex=annex(live, livesim, start=live['start'], now=live['now'], conform_end=conform_end, d13=d13),
               inputs=dict(live.get('inputs', {}), **livesim.get('inputs', {})))
    return G1.check_vocabulary(json.loads(json.dumps(doc, default=str)))


# -- loaders --------------------------------------------------------------------------------------------------------
def _sigs(txs):
    return {s: (t['slot'], t['blockTime']) for s, t in txs.items()}


def _line(pool, txs, row):
    line = TL.build(pool, txs, base_mint=row['base_mint'])
    line, _rep = LS.rebuilt(line, txs, row['wsol_vault'], row['config'])
    return line


def live_view(journal_path, pages_dir, pools, *, variant='B'):
    """pools: [dict(pool, base_mint, wsol_vault, config, b3)] in the journal order (checked against START)."""
    records = J.read(journal_path)
    J.verify_records(records)
    first = records[0]
    if first['kind'] != 'START' or first.get('counts_for_operational_master') is not False:
        raise CompareError('journal_without_a_paper_start')
    if first['variant'] != variant:
        raise CompareError('journal_of_another_variant')
    if [p['pool'] for p in first['pools']] != [p['pool'] for p in pools]:
        raise CompareError('pools_differ_from_start')
    for a, b in zip(first['pools'], pools):
        if a['b3'] != b['b3'] or a['amm_config_sha256'] != b['config']['sha256'] or a['base_mint'] != b['base_mint']:
            raise CompareError('pool_row_differs_from_start:%s' % a['pool'])
    steps = [k for k, r in enumerate(records) if r['kind'] == 'STEP']
    if not steps:
        raise CompareError('journal_without_step')
    total = len(records)
    now, start, seed = records[steps[-1]]['receipt_time'], first['start'], first['seed_sha']
    records = records[:steps[-1] + 1]                    # K1 / R02 C-6: the prefix up to the last STEP (<= now)
    out = dict(now=now, start=start, seed=seed, head=records[-1]['sha'], records=len(records), records_total=total,
               order=[p['pool'] for p in pools], pools={}, L={}, P={}, L_placebo=[])
    g0 = {p['pool']: None for p in pools}
    adm = {p['pool']: [] for p in pools}
    for r in records:
        if r['kind'] == 'G0':
            g0[r['pool']] = (r['admitted'], list(r['reasons']))
        elif r['kind'] == 'STEP':
            for p in g0:
                st = g0[p] or (False, ['no_record'])
                adm[p].append((r['receipt_time'], st[0], st[1]))
    gaps = [[r['gap_start'], r['gap_end']] for r in records if r['kind'] == 'GAP']
    resumptions, last_step = [], None
    for r in records:
        if r['kind'] == 'STEP':
            if resumptions and resumptions[-1][1] is None:
                resumptions[-1][1] = r['receipt_time']
            last_step = r['receipt_time']
        elif r['kind'] == 'STOP':
            resumptions.append([last_step, None])
    out['gaps'] = gaps
    out['resumptions'] = [iv for iv in resumptions if iv[0] is not None and iv[1] is not None]
    for row in pools:
        name = row['pool']
        txs = {}
        for page in sorted((Path(pages_dir) / name).glob('page_*.json.gz')):
            for t in read_gz_page(page)['data']:
                txs[t['transaction']['signatures'][0]] = t
        line = _line(name, txs, row) if txs else TL.build(name, {}, base_mint=row['base_mint'])
        known = LS.truncated(line, now)
        chain = [(known.swaps[i].block_time, known.swaps[i].signature)
                 for i in G2.decisions_g23(known, txs, row['b3'])] if known.swaps else []
        after = LS.g23_rows(line, txs, row['config'], row['b3'], seed, start=start, now=now)['primary'] \
            if known.swaps else dict(closed=[], open=[])
        for r in after['closed'] + after['open']:
            sw = known.swaps[r['decision_index']]
            out['P'][(name, sw.signature)] = dict(trigger_time=sw.block_time, trigger_slot=sw.slot,
                                                   trigger_key=list(sw.key), decision_index=r['decision_index'],
                                                   outcome=outcome(None if r.get('status') == 'open' else r, known))
        out['pools'][name] = dict(txs=txs, known=known, sigs=_sigs({s: t for s, t in txs.items()
                                                                     if t['blockTime'] <= now}),
                                  chain=chain, b3=row['b3'], admission=adm[name])
    exits = {r['id']: r for r in records if r['kind'] == 'EXIT'}
    landings = {r['id']: r for r in records if r['kind'] == 'LANDING'}
    for r in records:
        if r['kind'] != 'DECISION':
            continue
        known = out['pools'][r['pool']]['known']
        e = exits.get(r['id'])
        o = outcome(e['row'] if e else None, known)
        if e is None and r['id'] in landings:
            o['landing'] = landings[r['id']]['buy_landing_slot']
        if r['series'] == 'primary':
            out['L'][(r['pool'], r['trigger_signature'])] = dict(
                id=r['id'], trigger_time=r['trigger_time'], trigger_slot=r['trigger_slot'],
                trigger_key=r['trigger_key'], receipt_time=r['receipt_time'], receipt_slot=r['receipt_slot'],
                latency_s=r['receipt_time'] - r['trigger_time'], latency_slots=r['receipt_slot'] - r['trigger_slot'],
                decided_after_gap=r['decided_after_gap'], outcome=o)
        else:
            out['L_placebo'].append(dict(id=r['id'], pool=r['pool'], primary=r['primary'], entry_time=r['receipt_time'],
                                         entry_slot=r['receipt_slot'], entry_key=r['anchor_key'], outcome=o))
    return out


def livesim_view(collect, list_l, eligible_doc, now, *, window_start):
    """S: the livesim pages with blockTime <= now, cpmmrecon, G-0 at now, LS.g23_rows (livesim start and seed)."""
    col = LS.collection(collect)
    if eligible_doc['t_start'] != col['t_start'] or eligible_doc['qualified_sha256'] != col['qualified_sha256']:
        raise CompareError('eligible_from_another_collection')
    start = col['t_start']
    pools = eligible_doc['pools']
    polls = json.loads((Path(collect) / 'POLLS.json').read_text())
    chunks = []
    for i, c in enumerate(polls):
        if c['window'] != [start + i * LS.CHUNK_S, start + (i + 1) * LS.CHUNK_S] or c['name'] != 'live_%03d' % i:
            raise CompareError('polls_not_the_fixed_chunks')
        if c['window'][0] <= now:
            if not c['done']:
                raise CompareError('chunk_not_done:%s' % c['name'])
            chunks.append(c)
    if not chunks or chunks[-1]['window'][1] <= now:
        raise CompareError('now_not_covered_by_the_chunks')
    b3 = {r['pool']: r['b3'] for r in eligible_doc['rows']}
    mint = {r['pool']: r['base_mint'] for r in list_l['list']}
    seed = hashlib.sha256(('livesim|%d|' % start + '\n'.join(pools)).encode()).hexdigest()
    out = dict(start=start, seed=seed, pools={}, S={}, S_placebo=[], chunks=[c['name'] for c in chunks])
    for x in pools:
        cfg = LS.pool_config(list_l, x)
        _line0, txs, _shas = LS.live_pair(collect, x, mint[x], chunks)
        txs = {s: t for s, t in txs.items() if t['blockTime'] <= now}
        row = dict(base_mint=mint[x], wsol_vault=LS.pool_wsol_vault(list_l, x), config=cfg)
        line = _line(x, txs, row)
        known = LS.truncated(line, now)
        gate = CC.pool_gate(known, cfg)
        eligible = gate['admitted'] and b3[x] > 0
        chain = [(known.swaps[i].block_time, known.swaps[i].signature) for i in G2.decisions_g23(known, txs, b3[x])]
        out['pools'][x] = dict(txs=txs, known=known, sigs=_sigs(txs), chain=chain, b3=b3[x], eligible=eligible,
                               gate_reasons=list(gate['reasons']), config=cfg)
        if not eligible:
            continue
        got = LS.g23_rows(line, txs, cfg, b3[x], seed, start=start, now=now)
        for r in got['primary']['closed'] + got['primary']['open']:
            sw = known.swaps[r['decision_index']]
            if sw.block_time < window_start:
                continue
            out['S'][(x, sw.signature)] = dict(trigger_time=sw.block_time, trigger_slot=sw.slot,
                                                trigger_key=list(sw.key), decision_index=r['decision_index'],
                                                outcome=outcome(None if r.get('status') == 'open' else r, known))
        for r in got['placebo']['closed'] + got['placebo']['open']:
            sw = known.swaps[r['decision_index']]
            if sw.block_time < window_start:
                continue
            out['S_placebo'].append(dict(pool=x, decision_index=r['decision_index'], entry_time=sw.block_time,
                                         entry_slot=sw.slot, entry_key=list(sw.key),
                                         outcome=outcome(None if r.get('status') == 'open' else r, known)))
    return out


def t24_rows(livesim_doc):
    """{(pool, decision_index): dict(decision_time, outcome)} of the primary rows of an anchored livesim bilan."""
    out = {}
    for pool, got in (livesim_doc.get('journal') or {}).items():
        for r in got['primary']['closed'] + got['primary']['open']:
            o = outcome(None if r.get('status') == 'open' else r, None)
            out[(pool, r['decision_index'])] = dict(decision_slot=r.get('decision_slot'),
                                                    decision_time=r.get('decision_time'), outcome=o)
    return out


# -- rendering ------------------------------------------------------------------------------------------------------
CATEGORY = {'both': 'les deux', 'live_only': 'live seul', 'livesim_only': 'livesim seul',
            'a_posteriori_only': 'a posteriori seul'}


def sol(lamports):
    return NM if lamports is None else '%+.6f' % (lamports / 1e9)


def _side(x, *, latency=False):
    if not x:
        return '—', '—', '—', '—'
    o = x['outcome']
    trig = '%s / %d' % (hms(x['trigger_time']), x['trigger_slot'])
    if latency:
        trig += ' (+%d s / +%d sl.)' % (x['latency_s'], x['latency_slots'])
    entry = '—' if o['landing'] is None else str(o['landing'])
    if o['status'] == 'open':
        ex = 'ouverte'
    elif o['rule'] is None:
        ex = o['status']
    else:
        ex = '%s %s' % ('TP/SL' if o['rule'] == 'slot' else 'horloge', hms(o['exit_time']))
    return trig, entry, ex, sol(o['net'])


def render(doc):
    lines = ['# Comparaison décision par décision : test PAPER en direct arrêté ↔ livesim', '',
             doc['notes']['header_d15'], '', doc['notes']['limit_l4'], '',
             'Labels : %s. counts_for_operational_master = false. Aucun verdict, aucune conclusion économique : '
             'résultat descriptif. Jamais une transaction Master opérationnelle, jamais compté pour 50/20.'
             % ', '.join(doc['labels']), '',
             'now commun = %s (%d), dernier STEP du journal ; départ live %s ; départ livesim %s ; fin du segment '
             'conforme %s. Tête du journal %s (%d enregistrements).'
             % (hms(doc['now']), doc['now'], hms(doc['live_start']), hms(doc['livesim_start']),
                hms(doc['conform_end']), doc['journal_head'], doc['journal_records']), '',
             'Vues : L = journal live ; P = a posteriori sur les pages live ; S = livesim sur ses pages. Raisons : '
             'arbre déterministe déclaré à R02 avant lecture.', '',
             'Éligibilité livesim au now : ' + '; '.join(
                 '%s… %s' % (p[:6], 'éligible' if g['eligible'] else 'non éligible (%s)' % ', '.join(g['reasons']))
                 for p, g in doc['livesim_gate'].items()), '']
    for seg in SEGMENTS:
        s = doc['summary'][seg]
        lines += ['## ' + SEGMENT_TITLES[seg], '']
        if seg == 'hors_protocole':
            lines += [doc['notes']['out_of_protocol'], '']
        lines += ['Signaux G2-3 : %d lignes. Comptes à clé stricte (sans appariement décalé) : %s. Lignes appariées '
                  '« décalées » (seuil figé %d s), à part : %d.'
                  % (s['primary']['rows'], ', '.join('%s %d' % (CATEGORY[c], n) for c, n in
                                                     sorted(s['primary']['strict_key_categories'].items())) or 'aucun',
                     doc['pair_s'], s['primary']['shifted_rows']),
                  'Live : %d positions (%d fermées, %d ouvertes), somme nette des fermées %s SOL. Livesim : %d '
                  'positions (%d fermées, %d ouvertes), somme nette des fermées %s SOL (descriptif).'
                  % (s['primary']['live']['positions'], s['primary']['live']['closed'], s['primary']['live']['open'],
                     sol(s['primary']['live']['net_lamports_closed_sum']), s['primary']['livesim']['positions'],
                     s['primary']['livesim']['closed'], s['primary']['livesim']['open'],
                     sol(s['primary']['livesim']['net_lamports_closed_sum'])), '',
                  '| # | pool | présence | déclencheur L (latence) | déclencheur S | Δ décl. s / slots | entrée L / S '
                  '(slot) | sortie L | sortie S | net L | net S | S à T+24 h | raisons |',
                  '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        k = 0
        for r in doc['primary']:
            if r['segment'] != seg:
                continue
            k += 1
            lt, le, lx, ln = _side(r['live'], latency=True)
            st, se, sx, sn = _side(r['livesim'])
            pres = CATEGORY[r['category']] + (' (P)' if r['in_a_posteriori'] else '') + \
                (' ; décalé avec %s…' % r['shifted_with'][:6] if r.get('shifted_with') else '')
            shift = '%+d / %+d' % (r['shift']['seconds'], r['shift']['slots']) if r.get('shift') else '—'
            t24 = r.get('livesim_t24')
            t24s = '—' if not t24 else sol(t24['net'])
            why = '; '.join(r['reasons'])
            lines.append('| %d | %s… | %s | %s | %s | %s | %s / %s | %s | %s | %s | %s | %s | %s |'
                         % (k, r['pool'][:6], pres, lt, st, shift, le, se, lx, sx, ln, sn, t24s, why))
        lines += ['', 'Témoin (%s) : %d lignes ; comptes à clé stricte : %s. Live : %d positions (%d fermées), somme nette des fermées %s SOL. '
                  'Livesim : %d positions (%d fermées), somme nette des fermées %s SOL (descriptif).'
                  % (doc['notes']['placebo'], s['placebo']['rows'],
                     ', '.join('%s %d' % (CATEGORY[c], n) for c, n in
                               sorted(s['placebo']['strict_key_categories'].items()) if n) or 'aucun',
                     s['placebo']['live']['positions'], s['placebo']['live']['closed'],
                     sol(s['placebo']['live']['net_lamports_closed_sum']), s['placebo']['livesim']['positions'],
                     s['placebo']['livesim']['closed'], sol(s['placebo']['livesim']['net_lamports_closed_sum'])), '',
                  '| # | pool | présence | entrée L | entrée S | sortie L | sortie S | net L | net S | raison |',
                  '|---|---|---|---|---|---|---|---|---|---|']
        k = 0
        for r in doc['placebo']:
            if r['segment'] != seg:
                continue
            k += 1
            cells = []
            for x in (r['live'], r['livesim']):
                if not x:
                    cells.append(('—', '—', '—'))
                    continue
                o = x['outcome']
                ex = 'ouverte' if o['status'] == 'open' else (o['status'] if o['rule'] is None else '%s %s' % (
                    'TP/SL' if o['rule'] == 'slot' else 'horloge', hms(o['exit_time'])))
                cells.append(('%s / %d' % (hms(x['entry_time']), x['entry_slot']), ex, sol(o['net'])))
            lines.append('| %d | %s… | %s | %s | %s | %s | %s | %s | %s | %s |'
                         % (k, r['pool'][:6], CATEGORY[r['category']], cells[0][0], cells[1][0], cells[0][1],
                            cells[1][1], cells[0][2], cells[1][2], '; '.join(r['reasons'])))
        lines.append('')
    lines += ['## Annexe : transactions présentes d\'un côté seulement, [départ live ; now]', '',
              '| pool | côté | signature | slot | heure | segment | D13 |', '|---|---|---|---|---|---|---|']
    for pool, a in doc['annex'].items():
        for r in a['rows']:
            lines.append('| %s… | %s | %s… | %d | %s | %s | %s |'
                         % (pool[:6], 'absente du live' if r['side'] == 'absent_live' else 'absente de livesim',
                            r['sig'][:12], r['slot'], hms(r['block_time']), r['segment'], 'oui' if r['d13'] else ''))
    lines.append('')
    for pool, a in doc['annex'].items():
        lines.append('- %s… : %d transactions live et %d livesim dans la fenêtre ; %d transactions live avant le '
                     'départ.' % (pool[:6], a['live_in_window'], a['livesim_in_window'], a['live_before_start']))
    lines += ['', 'Interruptions du live : GAP %s ; reprises %s.'
              % (', '.join('[%s ; %s]' % (hms(a), hms(b)) for a, b in doc['gaps']) or 'aucun',
                 ', '.join('[%s ; %s]' % (hms(a), hms(b)) for a, b in doc['resumptions']) or 'aucune'), '']
    text = '\n'.join(lines)
    PILOT.assert_closed_vocabulary(text)
    return text


def _write(path, text):
    Path(path).write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def pools_of(pools_doc):
    by = {r['pool']: r for r in pools_doc['rows']}
    return [by[p] for p in pools_doc['eligible']]


def main(argv=None):
    ap = argparse.ArgumentParser(prog='lpcompare.compare')
    ap.add_argument('--live-dir', type=Path, required=True, help='LIVEPAPER run folder (J.jsonl, PAGES, POOLS_RUN.json)')
    ap.add_argument('--journal-sha', required=True)
    ap.add_argument('--collect', type=Path, required=True)
    ap.add_argument('--list-l', type=Path, required=True)
    ap.add_argument('--eligible', type=Path, required=True)
    ap.add_argument('--eligible-sha', required=True)
    ap.add_argument('--livesim-json', type=Path, required=True)
    ap.add_argument('--livesim-json-sha', required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args(argv)
    journal = a.live_dir / 'J.jsonl'
    for path, want, why in ((journal, a.journal_sha, 'journal'), (a.eligible, a.eligible_sha, 'eligible'),
                            (a.livesim_json, a.livesim_json_sha, 'livesim_json')):
        if file_sha(path) != want:
            raise CompareError('%s_not_the_anchored_file' % why)
    pools_doc = json.loads((a.live_dir / 'POOLS_RUN.json').read_text())
    if pools_doc['start'] != LIVE_START:
        raise CompareError('live_start_not_the_declared_one')
    if pools_doc['eligible_sha256'] != a.eligible_sha:
        raise CompareError('live_pools_from_another_eligible')
    live = live_view(journal, a.live_dir / 'PAGES', pools_of(pools_doc), variant=pools_doc['variant'])
    if live['start'] != LIVE_START:
        raise CompareError('journal_start_not_the_declared_one')
    eligible = json.loads(a.eligible.read_text())
    list_l = LS.list_l_doc(a.list_l)
    if eligible['pools'] != live['order']:
        raise CompareError('livesim_and_live_universes_differ')
    livesim = livesim_view(a.collect, list_l, eligible, live['now'], window_start=live['start'])
    live['inputs'] = dict(journal_sha256=a.journal_sha, pools_run_sha256=file_sha(a.live_dir / 'POOLS_RUN.json'))
    livesim['inputs'] = dict(eligible_sha256=a.eligible_sha, list_l_sha256=file_sha(a.list_l),
                             livesim_json_sha256=a.livesim_json_sha, chunks=livesim['chunks'])
    doc = build(live, livesim, t24=t24_rows(json.loads(a.livesim_json.read_text())))
    a.out.mkdir(parents=True, exist_ok=True)
    js = _write(a.out / 'COMPARE.json', json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + '\n')
    md = _write(a.out / 'COMPARE.md', render(doc))
    print('COMPARE.json', js)
    print('COMPARE.md', md)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
