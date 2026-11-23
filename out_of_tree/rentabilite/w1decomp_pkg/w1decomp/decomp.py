"""w1decomp 0.2 (0.1 e4af0d1 + R02 audit 3e714683: K-1 tests, K-2 ledger sha in the README, K-3 the .md publishes D3 with
the multiplicity warning and the label of D2 / D3c) -- w1decomp 0.1 -- R-2 of the owner's strategic directive (23/11): DESCRIPTIVE decomposition of the W1 losses, from
the ANCHORED W1 outputs only. EXPLORATOIRE: no rule, no threshold and no parameter is drawn from W1; nothing here is
a verdict; nothing changes a W1 figure. Run ONCE by RUGGER 03 under A2 (5aff3383 point 1), after the R02 audit.

INPUTS (nothing else is opened; every sha256 is checked before any row is read)
* ``ledger.json`` of the anchored W1 ledger (verdict PASS, no mismatch, ``w1_report`` null), sha256 given;
* the L1 bundle, whose file sha256 must be the one the ledger recorded (``bundles_sha256.L1``);
* the W1 pools directory (frozen export), whose MANIFEST sha256 must be the anchored one; only the pools that hold a
  population position are replayed into their timeline (frozen ``collector.summarize`` + ``hrr.usable_timeline``).

POPULATION: exactly that of w1loss 0.3 (audited, imported, unchanged): ledger rows of trial ``L1``, arms ``master``
and ``placebo_random``, pools created in [evaluation_min, evaluation_max), outcome ``closed``, verified.

CLOSED LIST OF BREAKDOWNS, written before any W1 data is read (E = 5, counted apart from N like w1loss):
D1 COSTS, in % of the spent stake, from the ledger decomposition (exact identity of w1aux ledger):
   gross = market_move; impact = slippage (round trip of our own orders); curve fees = LaunchLab buy + sell fee;
   tx = tx_costs; failed = failed_attempt_costs; rent = SPL_RENT_LAMPORTS (statelab.exits, 2 039 280) per position,
   NOT in the frozen net: the frozen net [SL] and the net with the rent lost [LP] (additive) are both given; the share
   of each cost item in the total cost; 95 % intervals of the mean net [SL] and of the mean gross.
D2 PRICE PATH AFTER THE ENTRY (« when the price turns against us »): reference = curve spot after the landing event of
   our buy (``events[buy.index]``, real events only, our own order excluded); at each slot offset k of OFFSETS
   (decided now), r_k = spot(last real event with slot <= buy.slot + k) / reference - 1, for the positions still held
   at buy.slot + k (sale slot not passed); per offset: n, mean, median, share < 0. Per position: offset of the
   post-entry maximum spot before the sale, offset of the first real event below the reference (None if none before
   the sale); their quantiles and the share without any adverse crossing.
D3 POOL TYPES, three classes fixed now (no HW1 state variable, no age class, no creator signature):
   D3a real events before the entry (buy.index + 1) in [0,10) [10,30) [30,100) >=100;
   D3b creation hour UTC, 6 blocks of 4 h;
   D3c pool that reached the migration boundary in the data, or not.
   Per class: n, mean gross and net [SL], 95 % intervals, win rate, interpretable = n >= 30.
Bootstrap, quantiles and position fields: the w1loss 0.3 functions (cluster = creator, else pool; 2 000 draws, seed
20261120). OUTPUT WHITELIST: no pool, creator or signature appears in the output (tested).
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from w1loss import analysis as A

SCHEMA = 'rugger-w1-loss-decomposition-v0.2'
STAMP = "EXPLORATOIRE — DÉCOMPOSITION DESCRIPTIVE DE W1 — AUCUNE RÈGLE NI AUCUN PARAMÈTRE N'EST TIRÉ DE W1"
RENT_LAMPORTS = 2_039_280                       # statelab.exits.SPL_RENT_LAMPORTS (checked in the tests)
OFFSETS = (0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
TRADE_EDGES = (0, 10, 30, 100)
HOUR_BLOCK = 4
BREAKDOWNS = ('D1', 'D2', 'D3a', 'D3b', 'D3c')
COST_ITEMS = ('impact', 'curve_fees', 'tx', 'failed', 'rent')
AFTER_DECISION = 'postérieur à la décision : jamais une variable de décision'
MULTIPLICITY = ('AVERTISSEMENT DE MULTIPLICITÉ : D3 publie environ 24 cellules ; leurs écarts sont attendus par le seul '
                'hasard. Toute hypothèse inspirée de D2 ou de D3 compte N + 1 et se teste sur des données NOUVELLES.')


class DecompError(RuntimeError):
    pass


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# -- population (w1loss 0.3 rule, plus the buy / sell index and slot the ledger records) -----------------------------
def positions(ledger, bundle, *, evaluation_min, evaluation_max):
    if ledger.get('verdict') != 'PASS' or ledger.get('mismatches') or ledger.get('w1_report') is not None:
        raise DecompError('ledger_is_not_a_pass_without_report')
    if type(evaluation_min) is not int or type(evaluation_max) is not int or not evaluation_min < evaluation_max:
        raise DecompError('invalid_evaluation_range')
    pools = {pool['pool']: pool for pool in bundle['pools']}
    out = {arm: [] for arm in A.ARMS}
    for row in ledger['entries']:
        if row.get('trial') != A.TRIAL or row.get('arm') not in out or row.get('outcome') != 'closed':
            continue
        if row['pool'] not in pools:
            raise DecompError('ledger_row_for_a_pool_absent_from_the_bundle')
        pool = pools[row['pool']]
        if not evaluation_min <= pool['creation_slot'] < evaluation_max:
            continue
        if row.get('verified') is not True or 'decomposition' not in row or type(row.get('pnl_lamports')) is not int:
            raise DecompError('closed_cycle_not_verified_or_without_figures')
        p = A._position(row, pool, (pool.get('arms') or {}).get(row['arm']))
        buy, sell = row['buy'], row.get('sell') or {}
        for name, value in (('buy_index', buy.get('index')), ('sell_index', sell.get('index')),
                            ('sell_slot', sell.get('slot'))):
            if type(value) is not int:
                raise DecompError('closed_cycle_without_' + name)
        p.update(buy_index=buy['index'], sell_index=sell['index'], buy_slot=buy['slot'], sell_slot=sell['slot'],
                 impact=row['decomposition']['slippage'])
        out[row['arm']].append(p)
    return out


# -- D1 ---------------------------------------------------------------------------------------------------------------
def costs(group):
    if not group:
        return dict(n=0)
    share = {k: A._mean([getattr_(p, k) / p['spent'] for p in group]) for k in ('gross',) + COST_ITEMS}
    total = sum(share[k] for k in COST_ITEMS)
    with_rent = [(p['pnl'] - RENT_LAMPORTS) / p['cost'] for p in group]
    return dict(n=len(group), mean_share_of_stake=share, total_cost_share_of_stake=total,
                share_of_total_cost={k: share[k] / total for k in COST_ITEMS} if total else None,
                mean_net_return_frozen_SL=A._mean([p['net_return'] for p in group]),
                mean_net_return_rent_lost_LP_additive=A._mean(with_rent),
                interval_95_mean_net_return_SL=A._interval(group),
                interval_95_mean_gross_return=A._interval(group, lambda p: p['gross_return']))


def getattr_(p, key):
    return dict(gross=p['gross'], impact=p['impact'], curve_fees=p['fees'], tx=p['tx'], failed=p['failed'],
                rent=RENT_LAMPORTS)[key]


# -- D2 ---------------------------------------------------------------------------------------------------------------
def _spot(event):
    state = event.state_after()
    return state.quote_reserve / state.base_reserve


def path(p, events):
    """Offsets profile and turning points of one position; real events only, our own order excluded."""
    k0 = p['buy_index']
    if not 0 <= k0 < len(events) or events[k0].slot > p['buy_slot'] or not k0 <= p['sell_index'] < len(events):
        raise DecompError('ledger_indices_do_not_match_the_timeline')
    ref = _spot(events[k0])
    held = [i for i in range(k0, len(events)) if events[i].slot <= p['sell_slot']]
    profile = {}
    for k in OFFSETS:
        target = p['buy_slot'] + k
        if target > p['sell_slot']:
            continue
        last = max(i for i in held if events[i].slot <= target)
        profile[k] = _spot(events[last]) / ref - 1
    peak = max(held, key=lambda i: (_spot(events[i]), -i))
    adverse = next((i for i in held if i > k0 and _spot(events[i]) < ref), None)
    return dict(profile=profile, peak_offset=events[peak].slot - p['buy_slot'],
                first_adverse_offset=None if adverse is None else events[adverse].slot - p['buy_slot'])


def price_path(group, timelines):
    paths = [path(p, timelines[p['pool']]['events']) for p in group]
    by_offset = {}
    for k in OFFSETS:
        values = [x['profile'][k] for x in paths if k in x['profile']]
        by_offset[str(k)] = dict(n=len(values), mean=A._mean(values), median=A.quantile(values, 0.5),
                                 share_below_entry=(sum(1 for v in values if v < 0) / len(values)) if values else None)
    peaks = [x['peak_offset'] for x in paths]
    adverse = [x['first_adverse_offset'] for x in paths if x['first_adverse_offset'] is not None]
    return dict(label=AFTER_DECISION, n=len(paths), relative_spot_by_slot_offset=by_offset,
                peak_offset_slots={f'p{int(q * 100)}': A.quantile(peaks, q) for q in A.QUANTILES},
                first_adverse_offset_slots={f'p{int(q * 100)}': A.quantile(adverse, q) for q in A.QUANTILES},
                share_without_adverse_crossing=(1 - len(adverse) / len(paths)) if paths else None)


# -- D3 ---------------------------------------------------------------------------------------------------------------
def trade_class(count):
    for low, high in zip(TRADE_EDGES, TRADE_EDGES[1:]):
        if low <= count < high:
            return f'[{low},{high})'
    return f'>={TRADE_EDGES[-1]}'


def _class_table(group, key, order):
    groups = A._groups(group, key)
    out = {}
    for name in order:
        if name in groups:
            g = groups[name]
            out[name] = dict(A._short(g), win_rate=sum(1 for p in g if p['pnl'] > 0) / len(g),
                             interpretable=len(g) >= A.MIN_INTERPRETABLE)
    return out


def pool_types(group, timelines):
    trades = [trade_class(e) for e in TRADE_EDGES[:-1]] + [trade_class(TRADE_EDGES[-1])]
    hours = [f'{h:02d}-{h + HOUR_BLOCK:02d}h' for h in range(0, 24, HOUR_BLOCK)]

    def hour(p):
        h = (timelines[p['pool']]['creation_block_time'] // 3600) % 24
        return hours[h // HOUR_BLOCK]
    return dict(D3a_events_before_entry=_class_table(group, lambda p: trade_class(p['buy_index'] + 1), trades),
                D3b_creation_hour_utc=_class_table(group, hour, hours),
                D3c_reached_migration=dict(label=AFTER_DECISION, classes=_class_table(
                    group, lambda p: 'migration' if timelines[p['pool']]['migrated'] else 'no_migration',
                    ['migration', 'no_migration'])))


# -- document -----------------------------------------------------------------------------------------------------------
def decompose(population, timelines):
    arms = {}
    for arm, group in population.items():
        missing = sorted({p['pool'] for p in group} - set(timelines))
        if missing:
            raise DecompError('pool_without_timeline:%d' % len(missing))
        arms[arm] = dict(D1_costs=costs(group), D2_price_path_after_entry=price_path(group, timelines),
                         D3_pool_types=pool_types(group, timelines))
    return dict(schema=SCHEMA, stamp=STAMP, category='HISTORICAL_REPLAY', breakdowns=list(BREAKDOWNS),
                E=len(BREAKDOWNS), multiplicity_warning=MULTIPLICITY, arms=arms,
                regimes=dict(SL='frozen engine, rent not modelled', LP='rent lost, added per position (additive)'),
                flags=dict(rule_or_parameter_selected=False, official_w1_verdict=False, w1_figure_changed=False,
                           profitability_demonstrated=False, failed_attempts='0 in the frozen engine (not measured)'))


def load_timelines(pools_dir, manifest_sha256, wanted):
    """Frozen export -> {pool: events, creation_block_time, migrated} for the wanted pools only."""
    from bot.market.collector import summarize
    from bot.p4 import historical_research_replay as hrr
    from w1aux.lazy import clear_cache, load_fixtures_lazy
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise DecompError('manifest_is_not_the_anchored_one')
    out = {}
    try:
        for entry, archive in entries:
            if entry['pool'] not in wanted:
                continue
            summary, timeline = summarize(archive)
            try:
                timeline, migration = hrr.usable_timeline(archive, summary, timeline)
            except hrr.PoolExcluded as exc:
                raise DecompError('population_pool_not_replayable') from exc
            out[entry['pool']] = dict(events=list(timeline.events), migrated=migration is not None,
                                      creation_block_time=hrr.creation_facts(archive)['creation_block_time'])
    finally:
        clear_cache()
    if set(wanted) - set(out):
        raise DecompError('population_pool_absent_from_the_export')
    return out


def _pct(value):
    return 'NON MESURÉ' if value is None else f'{value * 100:+.2f} %'.replace('.', ',')


def markdown(doc):
    lines = [f'# Décomposition descriptive des pertes W1 — {doc["stamp"]}', '', f'**{doc["multiplicity_warning"]}**', '',
             'Régimes : [SL] moteur gelé sans loyer ; [LP] loyer perdu, ajout additif. Échecs : 0 (non mesurés).', '']
    for arm, part in doc['arms'].items():
        d1 = part['D1_costs']
        lines += [f'## {arm}', '', f'n = {d1["n"]}', '']
        if d1['n']:
            lines += ['| Poste | Part de la mise | Part du coût total |', '|---|---|---|']
            for k in ('gross',) + COST_ITEMS:
                tot = '—' if k == 'gross' or not d1['share_of_total_cost'] else _pct(d1['share_of_total_cost'][k])
                lines.append(f'| {k} | {_pct(d1["mean_share_of_stake"][k])} | {tot} |')
            lines += ['', f'Net [SL] {_pct(d1["mean_net_return_frozen_SL"])} ; net [LP] '
                          f'{_pct(d1["mean_net_return_rent_lost_LP_additive"])}', '']
        d2 = part['D2_price_path_after_entry']
        lines += [f'### D2 — trajet du prix après l\'entrée ({d2["label"]})', '',
                  '| Slots après l\'entrée | n | Moyenne | Médiane | Part sous l\'entrée |', '|---|---|---|---|---|']
        for k, row in d2['relative_spot_by_slot_offset'].items():
            lines.append(f'| {k} | {row["n"]} | {_pct(row["mean"])} | {_pct(row["median"])} | '
                         f'{_pct(row["share_below_entry"])} |')
        lines.append('')
        d3 = part['D3_pool_types']
        for title, table, label in (('D3a — événements avant l\'entrée', d3['D3a_events_before_entry'], None),
                                    ('D3b — heure UTC de création', d3['D3b_creation_hour_utc'], None),
                                    ('D3c — pool arrivé à la migration', d3['D3c_reached_migration']['classes'],
                                     d3['D3c_reached_migration']['label'])):
            lines += [f'### {title}' + (f' ({label})' if label else ''), '',
                      '| Classe | n | Brut moyen | Net moyen [SL] | IC 95 % du net | Réussite | Interprétable |',
                      '|---|---|---|---|---|---|---|']
            for name, row in table.items():
                ci = row['interval_95_mean_net_return']
                lines.append(f'| {name} | {row["n"]} | {_pct(row["mean_gross_return"])} | {_pct(row["mean_net_return"])} | '
                             f'[{_pct(ci["low"])} ; {_pct(ci["high"])}] | {_pct(row["win_rate"])} | '
                             f'{"oui" if row["interpretable"] else "non"} |')
            lines.append('')
    return '\n'.join(lines) + '\n'


def run(ledger_path, ledger_sha256, bundle_path, pools_dir, manifest_sha256, out_dir, *, evaluation_min,
        evaluation_max):
    if _sha_file(ledger_path) != ledger_sha256:
        raise DecompError('ledger_is_not_the_anchored_one')
    ledger = json.loads(Path(ledger_path).read_bytes())
    if _sha_file(bundle_path) != (ledger.get('bundles_sha256') or {}).get('L1'):
        raise DecompError('bundle_is_not_the_one_the_ledger_recorded')
    bundle = json.loads(gzip.decompress(Path(bundle_path).read_bytes()))
    population = positions(ledger, bundle, evaluation_min=evaluation_min, evaluation_max=evaluation_max)
    wanted = {p['pool'] for group in population.values() for p in group}
    doc = decompose(population, load_timelines(pools_dir, manifest_sha256, wanted))
    out = Path(out_dir)
    if out.exists():
        raise DecompError('output_exists')
    out.mkdir(parents=True)
    (out / 'DECOMPOSITION_W1.json').write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                                encoding='utf-8')
    (out / 'DECOMPOSITION_W1.md').write_text(markdown(doc), encoding='utf-8')
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(prog='w1decomp')
    for name in ('--ledger', '--ledger-sha256', '--bundle', '--pools', '--manifest-sha256', '--out'):
        parser.add_argument(name, required=True)
    parser.add_argument('--evaluation-min', type=int, required=True)
    parser.add_argument('--evaluation-max', type=int, required=True)
    a = parser.parse_args(argv)
    run(a.ledger, a.ledger_sha256, a.bundle, a.pools, a.manifest_sha256, a.out, evaluation_min=a.evaluation_min,
        evaluation_max=a.evaluation_max)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
