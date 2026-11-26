"""lpbilan 0.1.3 -- the bilan of a livepaper journal at a cut time, offline, 0 credit (R04 01:12Z; conventions C1-C8 sent
to R02 BEFORE any datum was read). It reads the journal only; it never calls the network and never modifies frozen
code: livesim 0.3.2 `metrics` / `by_hour` (the method of the livesim bilans) and livepaper.journal are imported.

C1 cut: the prefix of the journal up to and including the LAST STEP whose receipt_time <= cut, then the STOP records
   that follow it with wall <= cut. The whole chain is verified, the head at the cut is published. The journal must
   cover the cut (a STEP after it), STEP receipt times must never decrease, START must carry PAPER_LIVE_DEMO and
   counts_for_operational_master = false.
C2 counted: the DECISION records of the prefix. CLOSED = its EXIT is in the prefix; otherwise OPEN, never valued (its
   last MARK is shown apart, descriptive, never added).
C3 metrics: livesim.sim.metrics and by_hour, unmodified. Exit time (orders the fictitious capital) = receipt_time of
   the STEP that wrote the EXIT: when the live run knew it. Ties: (pool, position id). Declared difference with
   livesim: an exit point <= cut whose EXIT is written after the cut (settled view, 60 s) is OPEN here.
C4 latencies: delay_s of the primary DECISIONs (the placebo has none); latency_slots = buy_landing_slot - receipt slot
   of the decision (LANDING records); trigger -> landing slots for the primary; processing_ms of the STEPs; fetch_ms if
   the STEPs carry it, otherwise NON MESURÉ. Percentiles: livepaper.cli._pct (the method of `compare`).
C5 interruptions: GAP and STOP records; intervals between consecutive STEPs (count >= 2 x poll_s, maximum).
C6 credits: the ledger total AT THE SNAPSHOT, labelled so; at the cut: NON MESURÉ (neither the ledger nor the calls
   log is time-stamped).
C7 per position: the frozen decomposition_share_of_stake; brut + pool fees + impact + fixed = net within 1 lamport,
   otherwise an error.
C8 the closed vocabulary (cpmmpilot.step1.assert_closed_vocabulary) on every rendered document.
C9 (R02 01:17Z): the G-0 state of every pool AT THE CUT, from its G0 records (written on change): admitted or not, the
   reasons, and since when it is continuously not admitted (first record of the trailing run of refusals); declared
   defects (e.g. D13) are published verbatim from a notes file, under the closed vocabulary.
C10 (0.1.1, R02 reserve (2) on livepaper 0.1.4): the runner records of a livepaper 0.1.4 journal are published,
   never used by the metrics: every ERROR (type, redacted message, wall) and every CATCHUP (pool, outcome, signatures,
   receipt slot) of the prefix, and the count of RECEIVED transactions whose index source is 'gsfa_rank_catchup'. The
   STOP and ERROR records that follow the last STEP <= cut belong to the prefix when their wall <= cut. A journal is read
   with the livepaper.journal on the path (0.1.4 knows ERROR and CATCHUP; 0.1.2 refuses them as a broken chain).
C11 (0.1.2, R02 03:07Z / R04 03:08Z: "every interruption is measured and published"): every resumption between
   processes, whatever its length (even under 2 x poll, i.e. without a GAP record): for each STOP of the prefix, its
   reason and wall, the wall of the first STEP after it in the prefix, and the duration between the two (host clock);
   a STOP with no later STEP before the cut is listed with no resumption.
   0.1.3 (R02 03:20Z reserve, R04 04:06Z): also the wall of the LAST STEP before the STOP and the observation gap, from
   that STEP to the next one (the real hole of observation, longer by up to one poll); a missing bound renders '—'.
LABEL PAPER_LIVE_DEMO: never an operational Master trade, never counted for 50/20; no verdict."""
import argparse
import json
import statistics
from pathlib import Path

from cpmmcost import model as CC
from cpmmpilot import step1 as PILOT
from livepaper import cli as LPCLI, journal as J
from livesim import sim as LS

SCHEMA = 'lpbilan-v0.1.3'
TRAILING = ('ERROR', 'STOP')                         # 0.1.1: runner records that may follow the last STEP
LABEL = 'PAPER_LIVE_DEMO'
NM = LS.NM
SERIES = ('primary', 'placebo')
FIXED = ('transactions', 'wsol_close', 'cleanup', 'rent_lost')
PARTS = ('price_move', 'trade_and_creator_fees', 'price_impact') + FIXED


class BilanError(ValueError):
    pass


def cut_prefix(records, cut):
    """C1."""
    J.verify_records(records)
    if not records or records[0]['kind'] != 'START':
        raise BilanError('journal_without_start')
    start = records[0]
    if start.get('label') != LABEL or start.get('counts_for_operational_master') is not False:
        raise BilanError('not_a_paper_live_demo_journal')
    times = [r['receipt_time'] for r in records if r['kind'] == 'STEP']
    if any(b < a for a, b in zip(times, times[1:])):
        raise BilanError('step_times_decrease')
    last = max((i for i, r in enumerate(records) if r['kind'] == 'STEP' and r['receipt_time'] <= cut), default=None)
    if last is None:
        raise BilanError('no_step_before_the_cut')
    if not any(t > cut for t in times):
        raise BilanError('journal_does_not_cover_the_cut')
    end = last + 1
    while end < len(records) and records[end]['kind'] in TRAILING and records[end].get('wall', cut + 1) <= cut:
        end += 1
    return records[:end]


def _stats(values):
    if not values:
        return dict(n=0, p50=NM, p95=NM, p99=NM, max=NM, mean=NM)
    return dict(n=len(values), p50=LPCLI._pct(values, 0.5), p95=LPCLI._pct(values, 0.95),
                p99=LPCLI._pct(values, 0.99), max=max(values), mean=statistics.mean(values))


def decomposition(row):
    """C7: the frozen shares of the stake; None for a row without one (guard refusal, zero sale)."""
    d = row.get('decomposition_share_of_stake')
    if row.get('status') != 'entered':
        return None
    if d is None:
        raise BilanError('entered_row_without_decomposition:%s' % row.get('pool'))
    if set(d) != set(PARTS):
        raise BilanError('unexpected_decomposition_keys')
    out = dict(gross=d['price_move'], pool_fees=d['trade_and_creator_fees'], impact=d['price_impact'],
               fixed=sum(d[k] for k in FIXED))
    if abs(sum(d.values()) * CC.STAKE_LAMPORTS - row['net_lamports']) > 1:
        raise BilanError('decomposition_differs_from_net:%s' % row.get('pool'))
    return out


def positions(pre):
    """C2: every decision of the prefix, closed or open, with its journal facts."""
    steps = {r['step']: r for r in pre if r['kind'] == 'STEP'}
    exits = {r['id']: r for r in pre if r['kind'] == 'EXIT'}
    landings = {r['id']: r for r in pre if r['kind'] == 'LANDING'}
    marks = {}
    for r in pre:
        if r['kind'] == 'MARK':
            marks[r['id']] = r
    out = []
    for d in (r for r in pre if r['kind'] == 'DECISION'):
        if d['series'] not in SERIES:
            raise BilanError('unknown_series:%s' % d['series'])
        p = dict(id=d['id'], pool=d['pool'], series=d['series'], decision_time=d['receipt_time'],
                 decision_slot=d['receipt_slot'], delay_s=d.get('delay_s'), trigger_slot=d.get('trigger_slot'),
                 decided_after_gap=d.get('decided_after_gap'), primary=d.get('primary'))
        land = landings.get(d['id'])
        p['buy_landing_slot'] = land['buy_landing_slot'] if land else None
        e = exits.get(d['id'])
        if e is None:
            m = marks.get(d['id'])
            p.update(closed=False, landed=land is not None,
                     last_mark=None if m is None else dict(mark_time=m['mark_time'], value_lamports=m['value_lamports'],
                                                           unpriced=m['unpriced'], descriptive=True))
        else:
            row = e['row']
            if row['net_lamports'] != e['net_lamports'] or row['status'] != e['status']:
                raise BilanError('exit_record_differs_from_its_row:%s' % d['id'])
            p.update(closed=True, status=row['status'], net_lamports=row['net_lamports'],
                     exit_time=steps[e['step']]['receipt_time'], exit=row.get('exit'),
                     decomposition=decomposition(row))
        out.append(p)
    return out


def _metric_rows(ps, series):
    closed = [dict(status=p['status'], net_lamports=p['net_lamports'], exit_time=p['exit_time'], pool=p['pool'],
                   decision_index=p['id'],
                   **({} if p['decomposition'] is None else dict(decomposition_share_of_stake=dict(
                       price_move=p['decomposition']['gross']))))
              for p in ps if p['series'] == series and p['closed']]
    opened = [p for p in ps if p['series'] == series and not p['closed']]
    return closed, opened


def g0_at_cut(pre):
    """C9: per pool of START, its last G0 record and, when not admitted, the start of the trailing run of refusals."""
    runs = {p['pool']: [] for p in pre[0]['pools']}
    for r in pre:
        if r['kind'] == 'G0':
            runs.setdefault(r['pool'], []).append(r)
    out = []
    for pool, rs in runs.items():
        if not rs:
            out.append(dict(pool=pool, admitted=NM, reasons=[], since=None))
            continue
        last = rs[-1]
        since = None
        if not last['admitted']:
            k = len(rs) - 1
            while k > 0 and not rs[k - 1]['admitted']:
                k -= 1
            since = rs[k]['receipt_time']
        out.append(dict(pool=pool, admitted=last['admitted'], reasons=list(last['reasons']), since=since,
                        changes=len(rs)))
    return out


def resumptions(pre):
    """C11: each STOP and the first STEP after it (host walls), whatever the duration."""
    out = []
    for i, r in enumerate(pre):
        if r['kind'] != 'STOP':
            continue
        nxt = next((x for x in pre[i + 1:] if x['kind'] == 'STEP'), None)
        last = next((x for x in reversed(pre[:i]) if x['kind'] == 'STEP'), None)
        out.append(dict(reason=r['reason'], stop_wall=r.get('wall'), next_step_wall=None if nxt is None else nxt['wall'],
                        seconds=NM if nxt is None or r.get('wall') is None else nxt['wall'] - r['wall'],
                        last_step_wall=None if last is None else last['wall'],
                        observation_gap_s=NM if nxt is None or last is None else nxt['wall'] - last['wall']))
    return out


def bilan(records, cut, *, ledger=None, calls_lines=None, notes=()):
    pre = cut_prefix(records, cut)
    start = pre[0]
    ps = positions(pre)
    series = {}
    for name in SERIES:
        closed, opened = _metric_rows(ps, name)
        m = LS.metrics(closed, opened, signals=sum(1 for p in ps if p['series'] == name))
        m['capital_by_hour'] = LS.by_hour(m['capital_curve'], start=start['start'], now=cut)
        series[name] = m
    steps = [r for r in pre if r['kind'] == 'STEP']
    times = [r['receipt_time'] for r in steps]
    intervals = [b - a for a, b in zip(times, times[1:])]
    fetch = [r['fetch_ms'] for r in steps if r.get('fetch_ms') is not None]
    primary = [p for p in ps if p['series'] == 'primary']
    landed = [p for p in ps if p['buy_landing_slot'] is not None]
    credits = dict(at_cut=NM, why='ni le grand livre ni le journal d\'appels ne sont horodatés')
    if ledger is not None:
        credits.update(at_snapshot=dict(credits=ledger['credits'], requests=ledger['requests'],
                                        by_method=ledger['by_method'], ceiling=ledger['ceiling'],
                                        hard_stop=ledger['hard_stop']))
    if calls_lines is not None:
        credits.update(calls_log_lines=len(calls_lines),
                       calls_log_last_credits_after=calls_lines[-1]['credits_after'] if calls_lines else NM)
    return dict(
        schema=SCHEMA, label=LABEL, counts_for_operational_master=False, verdict=None, cut=cut,
        start=start['start'], hours=(cut - start['start']) / 3_600, journal=dict(
            records_total=len(records), head_total=records[-1]['sha'], records_at_cut=len(pre),
            seq_at_cut=pre[-1]['seq'], head_at_cut=pre[-1]['sha'], start_schema=start['schema'],
            code_sha256=start.get('code_sha256'), mode=start['mode'], poll_s=start['poll_s'],
            variant=start['variant'], seed_sha=start['seed_sha']),
        pools=[p['pool'] for p in start['pools']],
        series=series, placebo_merged=False, stake_sol=CC.STAKE_LAMPORTS / 1e9,
        placebo_not_entered=sum(1 for r in pre if r['kind'] == 'WAIT' and r.get('series') == 'placebo'),
        positions=ps,
        latency=dict(
            delay_s=_stats([p['delay_s'] for p in primary]),
            latency_slots=_stats([p['buy_landing_slot'] - p['decision_slot'] for p in landed]),
            trigger_to_landing_slots=_stats([p['buy_landing_slot'] - p['trigger_slot'] for p in landed
                                             if p['series'] == 'primary']),
            decided_after_gap=sum(1 for p in primary if p['decided_after_gap']),
            processing_ms=_stats([r['processing_ms'] for r in steps]),
            fetch_ms=_stats(fetch) if fetch else NM),
        interruptions=dict(
            gaps=[dict(start=r['gap_start'], end=r['gap_end'], seconds=r['gap_end'] - r['gap_start'])
                  for r in pre if r['kind'] == 'GAP'],
            stops=[dict(reason=r['reason'], wall=r.get('wall')) for r in pre if r['kind'] == 'STOP'],
            errors=[dict(error_type=r['error_type'], message=r['message'], wall=r.get('wall'))
                    for r in pre if r['kind'] == 'ERROR'],
            catchups=[dict(pool=r['pool'], outcome=r['outcome'], signatures=list(r['signatures']),
                           receipt_slot=r['receipt_slot'], wall=r.get('wall')) for r in pre if r['kind'] == 'CATCHUP'],
            resumptions=resumptions(pre),
            caught_up_received=sum(1 for r in pre if r['kind'] == 'RECEIVED'
                                   and r.get('index_source') == 'gsfa_rank_catchup'),
            steps=len(steps), first_step=times[0], last_step=times[-1],
            max_interval_s=max(intervals) if intervals else NM,
            intervals_at_least_2_polls=sum(1 for x in intervals if x >= 2 * start['poll_s'])),
        credits=credits, g0_at_cut=g0_at_cut(pre), declared_defects=list(notes))


# -- rendering --------------------------------------------------------------------------------------------------------
def _pct(x):
    return NM if x == NM else '%.2f %%' % (100 * x)


def _num(x, fmt='%s'):
    return NM if x == NM else fmt % x


def _hm(t):
    import time
    return time.strftime('%H:%M:%SZ', time.gmtime(t))


def _clock(t):
    return '—' if t is None else _hm(int(t))


def _secs(x):
    return '—' if x in (None, NM) else '%.1f s' % x


def render(doc):
    j, lat, it = doc['journal'], doc['latency'], doc['interruptions']
    lines = ['# Bilan du test PAPER en direct — livepaper (PAPER_LIVE_DEMO, démonstration descriptive)', '',
             '- Aucun essai, aucun verdict ; jamais un trade du Master, jamais compté pour 50/20.',
             '- Fenêtre : %d (%s) → %d (%s), %.2f h. Cut : %s.' % (doc['start'], _hm(doc['start']), doc['cut'],
                                                                  _hm(doc['cut']), doc['hours'], _hm(doc['cut'])),
             '- Journal : %d enregistrements au cut (seq %d, tête %s) sur %d (tête %s). Schéma %s, mode %s, '
             'poll %d s, variante %s.' % (j['records_at_cut'], j['seq_at_cut'], j['head_at_cut'], j['records_total'],
                                          j['head_total'], j['start_schema'], j['mode'], j['poll_s'], j['variant']),
             '- Ne comptent que les positions décidées avant le cut ; une position sans EXIT dans le préfixe est '
             'OUVERTE et jamais valorisée.', '',
             '## G2-3 (le témoin apparié est à côté, jamais additionné)', '',
             '| Série | Décisions | Entrées | Sorties | Ouvertes | Refus de garde | Taux net > 0 | P&L brut (SOL) | '
             'Coûts (SOL) | P&L net = capital fictif (SOL) | Net moyen par position | Drawdown max (SOL) |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, label in (('primary', 'G2-3'), ('placebo', 'témoin apparié')):
        m = doc['series'][name]
        if m['n_insufficient']:
            label += ' (n insuffisant : %d < %d)' % (m['exits'], LS.N_MIN)
        lines.append('| %s | %d | %d | %d | %d | %d | %s | %.6f | %.6f | %.6f | %s | %.6f |' % (
            label, m['signals'], m['entries'], m['exits'], m['open_positions'], m['guard_refusals'],
            _pct(m['win_rate']), m['gross_pnl_sol'], m['costs_sol'], m['net_pnl_sol'],
            _pct(m['net_return_per_position']), m['max_drawdown_sol']))
    lines += ['', '- Témoin non entré (WAIT) : %d.' % doc['placebo_not_entered'], '',
              '### Capital fictif par heure (SOL)', '', '| Heure | G2-3 | témoin apparié |', '|---|---|---|']
    for a, b in zip(doc['series']['primary']['capital_by_hour'], doc['series']['placebo']['capital_by_hour']):
        lines.append('| %s | %.6f | %.6f |' % (_hm(a['time']), a['capital_sol'], b['capital_sol']))
    opened = [p for p in doc['positions'] if not p['closed']]
    lines += ['', '### Positions ouvertes au cut (jamais valorisées)', '']
    if not opened:
        lines.append('Aucune.')
    else:
        lines += ['| Série | Pool | Décision | Atterrie | Dernière marque descriptive (lamports, jamais un résultat) |',
                  '|---|---|---|---|---|']
        for p in opened:
            m = p['last_mark']
            mark = '—' if m is None else ('%s à %s' % (m['value_lamports'], _hm(m['mark_time']))
                                          if m['value_lamports'] is not None else 'non valorisable : %s' % m['unpriced'])
            lines.append('| %s | %s | %s | %s | %s |' % (p['series'], p['pool'][:8], _hm(p['decision_time']),
                                                        'oui' if p['landed'] else 'non', mark))
    lines += ['', '## Latences', '', '| Mesure | n | p50 | p95 | p99 | max | moyenne |', '|---|---|---|---|---|---|---|']
    for key, label in (('delay_s', 'delay_s (déclencheur → décision, s)'), ('latency_slots', 'latency_slots'),
                       ('trigger_to_landing_slots', 'slots déclencheur → atterrissage'),
                       ('processing_ms', 'processing_ms (traitement d\'un pas)')):
        s = lat[key]
        lines.append('| %s | %d | %s | %s | %s | %s | %s |' % (label, s['n'], _num(s['p50']), _num(s['p95']),
                                                              _num(s['p99']), _num(s['max']),
                                                              _num(s['mean'], '%.3f')))
    lines += ['', '- fetch_ms : %s.' % (NM + ' (livepaper 0.1.2 ne le journalise pas)' if lat['fetch_ms'] == NM
                                         else json.dumps(lat['fetch_ms'])),
              '- Décisions prises après un GAP : %d.' % lat['decided_after_gap'], '',
              '## GAP et interruptions', '',
              '- Pas : %d, de %s à %s ; intervalle max %s s ; intervalles ≥ 2 × poll : %d.'
              % (it['steps'], _hm(it['first_step']), _hm(it['last_step']), _num(it['max_interval_s']),
                 it['intervals_at_least_2_polls'])]
    for g in it['gaps']:
        lines.append('- GAP : %s → %s (%s s).' % (_hm(int(g['start'])), _hm(int(g['end'])), _num(g['seconds'], '%.1f')))
    for s in it['stops']:
        lines.append('- STOP : %s%s.' % (s['reason'], '' if s['wall'] is None else ' à %s' % _hm(int(s['wall']))))
    lines.append('- Reprises entre processus (toutes, quelle que soit leur durée) : %d.'
                 % sum(1 for x in it['resumptions'] if x['next_step_wall'] is not None))
    for x in it['resumptions']:
        lines.append('  - STOP %s à %s ; dernier pas avant à %s ; pas suivant à %s : STOP → pas suivant %s ; '
                     'trou d\'observation (dernier pas → pas suivant) %s.' % (
                         x['reason'], _clock(x['stop_wall']), _clock(x['last_step_wall']), _clock(x['next_step_wall']),
                         _secs(x['seconds']), _secs(x['observation_gap_s'])))
    lines.append('- Incidents (ERROR) : %d.' % len(it['errors']))
    for e in it['errors']:
        lines.append('  - %s : %s%s.' % (e['error_type'], e['message'],
                                         '' if e['wall'] is None else ' à %s' % _hm(int(e['wall']))))
    lines.append('- Rattrapages (CATCHUP) : %d ; transactions rattrapées reçues : %d.'
                 % (len(it['catchups']), it['caught_up_received']))
    for c in it['catchups']:
        lines.append('  - %s : %s, %d signature(s), slot de réception %d%s.' % (
            c['pool'][:8], c['outcome'], len(c['signatures']), c['receipt_slot'],
            '' if c['wall'] is None else ' à %s' % _hm(int(c['wall']))))
    lines += ['', '## G-0 au cut (C9)', '', '| Pool | Admis | Raisons | Non admis depuis | Changements |',
              '|---|---|---|---|---|']
    for g in doc['g0_at_cut']:
        lines.append('| %s | %s | %s | %s | %s |' % (
            g['pool'][:8], g['admitted'] if g['admitted'] == NM else ('oui' if g['admitted'] else 'non'),
            ', '.join(g['reasons']) or '—', '—' if g['since'] is None else _hm(g['since']), g.get('changes', 0)))
    lines += ['', '## Défauts déclarés (C9)', '']
    lines += ['- %s' % x for x in doc['declared_defects']] or ['Aucun.']
    c = doc['credits']
    lines += ['', '## Crédits', '', '- Au cut : %s (%s).' % (c['at_cut'], c['why'])]
    if 'at_snapshot' in c:
        a = c['at_snapshot']
        lines.append('- Au snapshot : %d crédits, %d requêtes (plafond %d, arrêt %d) ; par méthode : %s.'
                     % (a['credits'], a['requests'], a['ceiling'], a['hard_stop'], json.dumps(a['by_method'])))
    if 'calls_log_lines' in c:
        lines.append('- Journal d\'appels : %d lignes, dernier credits_after %s.'
                     % (c['calls_log_lines'], c['calls_log_last_credits_after']))
    text = '\n'.join(lines) + '\n'
    PILOT.assert_closed_vocabulary(text)
    return text


def render_decomposition(doc):
    lines = ['# Décomposition des positions du bilan (descriptive)', '',
             '- Source : journal au cut %s (seq %d, tête %s) ; lecture seule, 0 crédit, hors ligne.'
             % (_hm(doc['cut']), doc['journal']['seq_at_cut'], doc['journal']['head_at_cut']),
             '- Décomposition gelée (cpmmcost `decomposition_share_of_stake`, %% de la mise de %.1f SOL) ; contrôle : '
             'brut + frais de pool + impact + frais fixes = net à 1 lamport près.' % doc['stake_sol'],
             '- Refus de garde (aucun achat : frais de transaction seuls) et vente nulle K01 (unpriced_zero_sale) : '
             'pas de décomposition (« — ») ; leur net est dans la colonne Net et dans son Σ, pas dans les composantes.',
             '']
    for name, label in (('primary', 'G2-3'), ('placebo', 'Témoin apparié')):
        closed = sorted((p for p in doc['positions'] if p['series'] == name and p['closed']),
                        key=lambda p: (p['decision_time'], p['id']))
        n_open = sum(1 for p in doc['positions'] if p['series'] == name and not p['closed'])
        lines += ['## %s : %d positions fermées (+ %d ouverte(s), non valorisée(s))' % (label, len(closed), n_open), '',
                  '| # | Pool | Décision | Sortie | Statut | Brut | Frais de pool | Impact | Frais fixes | Net (% mise) | '
                  'Net (lamports) |', '|---|---|---|---|---|---|---|---|---|---|---|']
        tot = dict(gross=0.0, pool_fees=0.0, impact=0.0, fixed=0.0)
        net_sum = 0
        for k, p in enumerate(closed, 1):
            e = p['exit'] or {}
            if e.get('rule') == 'clock':
                out = 'horloge (%d s), écrite %s' % (e['declared'] - p['decision_time'], _hm(p['exit_time']))
            elif e.get('rule') == 'slot':
                out = 'slot %d, écrite %s' % (e['declared'], _hm(p['exit_time']))
            else:
                out = 'écrite %s' % _hm(p['exit_time'])
            d = p['decomposition']
            cells = ['%+.4f %%' % (100 * d[x]) for x in ('gross', 'pool_fees', 'impact', 'fixed')] if d else ['—'] * 4
            if d:
                for x in tot:
                    tot[x] += d[x]
            net_sum += p['net_lamports']
            lines.append('| %d | %s | %s | %s | %s | %s | %+.4f %% | %d |' % (
                k, p['pool'][:6], _hm(p['decision_time']), out, p['status'], ' | '.join(cells),
                100 * p['net_lamports'] / CC.STAKE_LAMPORTS, p['net_lamports']))
        if closed:
            lines.append('| Σ | | | | | %s | %+.4f %% | %d |' % (
                ' | '.join('%+.4f %%' % (100 * tot[x]) for x in ('gross', 'pool_fees', 'impact', 'fixed')),
                100 * net_sum / CC.STAKE_LAMPORTS, net_sum))
        lines.append('')
    text = '\n'.join(lines)
    PILOT.assert_closed_vocabulary(text)
    return text


def main(argv=None):
    a = argparse.ArgumentParser(prog='lpbilan')
    a.add_argument('--journal', type=Path, required=True)
    a.add_argument('--cut', type=int, required=True)
    a.add_argument('--ledger', type=Path)
    a.add_argument('--calls', type=Path)
    a.add_argument('--notes', type=Path, help='declared defects, one per line (C9)')
    a.add_argument('--out', type=Path, required=True)
    args = a.parse_args(argv)
    ledger = json.loads(args.ledger.read_text()) if args.ledger else None
    calls = None
    if args.calls:
        calls = [json.loads(x) for x in args.calls.read_text().split('\n') if x]
    notes = [x for x in args.notes.read_text().split('\n') if x.strip()] if args.notes else ()
    doc = bilan(J.read(args.journal), args.cut, ledger=ledger, calls_lines=calls, notes=notes)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'BILAN.json').write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + '\n')
    (args.out / 'BILAN.md').write_text(render(doc))
    (args.out / 'DECOMPOSITION.md').write_text(render_decomposition(doc))
    print(json.dumps(dict(head_at_cut=doc['journal']['head_at_cut'], seq_at_cut=doc['journal']['seq_at_cut'])))


if __name__ == '__main__':
    main()
