"""Loss anatomy of registered V3 bundles: where the money of every entered position went. Descriptive.

  python -B -m v3lab.anatomy <bundles_dir> [--census <census.json>] [--positions <trial>] [--markdown <file>]

Reads only what ``v3lab.tables`` reads (the registered bundles of the plan, sha256 checked): no pool
file, no replay, no new trial; it decides nothing and is not part of the V3 fingerprint.

EXACT IDENTITY of a closed cycle (integers, checked for every row; a row that breaks it raises):

    pnl = drift - buy_fee - sell_fee_at_entry - rounding - tx_costs - failed_attempt_costs

* ``buy_fee``            curve fee of our buy, ``ceil(spent * rate / 1e6)`` (the frozen curve rule);
* ``sell_fee_at_entry``  curve fee of selling at once on the state our own buy left (``immediate_mark``
                         is that sale, net; its gross is recovered from the same fee rule; when two
                         gross values give the same net the smaller is kept: at most 1 lamport);
* ``rounding``           quote we put on the curve minus the gross quote that immediate sale takes
                         back. On a constant-product curve an immediate round trip gives the own price
                         impact back, so this is integer rounding only (a few lamports, never negative;
                         R02 L-1): the own impact shows up in ``drift`` when others trade in between;
* ``tx_costs``           network and priority fees of our two transactions (frozen model);
* ``drift``              ``received - immediate_mark``: what the other traders did to the value of
                         our position during the hold (net of the sale fee, as ``v3lab.evaluate``).
The first four are paid at the entry whatever happens next: their sum is the instant round-trip
cost. NOT measurable from a bundle (said, not estimated): the share of the drift due to the order
latency, and anything about entries that were not taken.

``rent`` is reported apart (the frozen accounting does not model it): the token account opened by
the buy is not recovered by today's chain (R02 E-1). With a census the rent of the token class is
used; without one, the SPL Token rent is assumed for every row and the document says so.

Exit anatomy (needs the probe V3-06, which records the exact liquidation value after every real
event for 900 s): for the positions a trial shares with the probe (same entry event, same fill),
the best value any exit could have taken (HINDSIGHT: an upper bound for every exit rule on these
entries, never a strategy), how concentrated it is, when it occurs, and how much trading follows
our entry. Groups (fee tier, events before the decision, creator's earlier pools, token class) are
descriptive breakdowns; ``pool_events_total`` uses the whole life of the pool and is HINDSIGHT.

Segments (R02 C-2): the money tables repeat sums already audited for every visible segment. The
breakdowns, the exit bound and the position listing are DISCOVERY tables: exploration and train
only, never validation. Version 1 of this module (commit 35de13f) printed them over all visible
segments and that output was read on 2026-11-11: any hypothesis formed from those views has
consumed the P0 validation screen and can only be tested on other data.
"""
import argparse
from collections import Counter, OrderedDict
import hashlib
import json
from pathlib import Path
import statistics

from v3lab import plan
from v3lab.evaluate import _cost, _interval, cluster_bootstrap_means, load_bundles

SCHEMA = 'v3lab-loss-anatomy-v2'
FEE_DENOMINATOR = 1_000_000
SPL_RENT_LAMPORTS = 2_039_280
COMPONENTS = ('buy_fee', 'sell_fee_at_entry', 'rounding', 'tx_costs', 'failed_attempt_costs', 'drift')
ENTRY_COSTS = ('buy_fee', 'sell_fee_at_entry', 'rounding', 'tx_costs')
DISCOVERY_SEGMENTS = ('exploration', 'train')          # R02 C-2: breakdowns, exit bound and listing never read validation
SMALL_GROUP = 20
N_BOOT = 2_000
EVENT_BUCKETS = ((1, 1), (2, 3), (4, 9), (10, 29), (30, None))
TOTAL_BUCKETS = ((1, 9), (10, 29), (30, 99), (100, 299), (300, None))
AFTER_WINDOWS_S = (25, 60, 900)
NOTES = [
    'descriptive: registered rows only, no replay, no new trial; nothing here chooses or promotes a strategy',
    'P0 visible only, already used by 34 trials: any pattern read here is a hypothesis, not a result',
    'hindsight columns (best exit, pool_events_total) are upper bounds or context, never achievable rules',
    'closed cycles only in the identity; positions that are not a closed cycle are counted apart',
    'the share of the drift due to the order latency cannot be read from a bundle',
    'groups, exits and positions are discovery tables: exploration and train only (R02 C-2)',
    'version 1 (commit 35de13f) showed groups and exits over all visible segments and was read on 2026-11-11: '
    'a hypothesis formed from those views has consumed the P0 validation screen',
]


def _ceil_div(a, b):
    return -(-a // b)


def _gross_of_net(net, rate_ppm):
    """Smallest gross with ``gross - ceil(gross * rate / 1e6) == net`` (the frozen sale fee rule)."""
    guess = net * FEE_DENOMINATOR // (FEE_DENOMINATOR - rate_ppm)
    for gross in range(max(0, guess - 3), guess + 4):
        if gross - _ceil_div(gross * rate_ppm, FEE_DENOMINATOR) == net:
            return gross
    raise ValueError('immediate_mark_not_a_sale_of_this_fee_rate')


def decompose(record):
    """Exact components (lamports) of one CLOSED cycle; None when its instant sale was not priced."""
    trade, block = record['trade'], record.get('v3') or {}
    if trade['outcome'] != 'closed':
        raise ValueError('not_a_closed_cycle')
    immediate = block.get('immediate_mark')
    if immediate is None:
        return None
    spent, rate = trade['spent'], trade['fee_rate_ppm']
    if type(rate) is not int or not 0 <= rate < FEE_DENOMINATOR:
        raise ValueError('fee_rate_missing')
    if block['cost_lamports'] != spent + trade['tx_costs']:
        raise ValueError('cost_identity_broken:%s' % record['pool'])
    buy_fee = _ceil_div(spent * rate, FEE_DENOMINATOR)
    gross = _gross_of_net(immediate, rate)
    parts = dict(buy_fee=buy_fee, sell_fee_at_entry=gross - immediate, rounding=spent - buy_fee - gross,
                 tx_costs=trade['tx_costs'], failed_attempt_costs=trade['failed_attempt_costs'],
                 drift=trade['received'] - immediate)
    if parts['rounding'] < 0:
        raise ValueError('negative_rounding:%s' % record['pool'])
    total = parts['drift'] - sum(parts[name] for name in COMPONENTS if name != 'drift')
    if total != trade['pnl_lamports']:
        raise ValueError('pnl_identity_broken:%s' % record['pool'])
    return parts


def _entered(bundle, segment=None):
    if any(r.get('segment') not in plan.SEGMENTS for r in bundle['pools']):
        raise ValueError('row_outside_the_visible_segments')          # never a sealed or unknown segment
    return [r for r in bundle['pools'] if r['trade']['entry_index'] is not None
            and (segment is None or r['segment'] == segment)]


def _discovery(bundle, segment=None):
    """Entered positions of the discovery segments only (R02 C-2); ``segment`` must be one of them."""
    if segment is not None and segment not in DISCOVERY_SEGMENTS:
        raise ValueError('not_a_discovery_segment')
    return [r for r in _entered(bundle, segment) if r['segment'] in DISCOVERY_SEGMENTS]


def _pct(value, base):
    return None if not base else 100 * value / base


def _rent(record, rents):
    if rents is None:
        return SPL_RENT_LAMPORTS
    return rents.get(record['pool'], (None, None))[1]


def money(records, rents=None):
    """Where the money of these entered positions went (sums in lamports and in % of the capital committed)."""
    closed = [r for r in records if r['trade']['outcome'] == 'closed']
    parts = [(r, decompose(r)) for r in closed]
    known = [(r, p) for r, p in parts if p is not None]
    capital = sum(_cost(r['trade']) for r, _p in known)
    sums = {name: sum(p[name] for _r, p in known) for name in COMPONENTS}
    entry_cost = sum(sums[name] for name in ENTRY_COSTS)
    pnl = sum(r['trade']['pnl_lamports'] for r, _p in known)
    drifts = [p['drift'] for _r, p in known]
    rent_rows = [(r, _rent(r, rents)) for r, _p in known]
    rent = None if any(v is None for _r, v in rent_rows) else sum(v for _r, v in rent_rows)
    others = [r for r in records if r['trade']['outcome'] != 'closed']
    out = dict(
        entered=len(records), closed=len(closed), decomposed=len(known),
        closed_without_instant_sale=len(closed) - len(known),
        capital_lamports=capital, pnl_lamports=pnl, pnl_pct=_pct(pnl, capital),
        components_lamports=sums, components_pct={name: _pct(sums[name], capital) for name in COMPONENTS},
        instant_round_trip_cost_lamports=entry_cost, instant_round_trip_cost_pct=_pct(entry_cost, capital),
        drift=dict(positive_cycles=sum(d > 0 for d in drifts), zero_cycles=sum(d == 0 for d in drifts),
                   negative_cycles=sum(d < 0 for d in drifts),
                   positive_sum_lamports=sum(d for d in drifts if d > 0),
                   negative_sum_lamports=sum(d for d in drifts if d < 0)),
        rent_lost_today_lamports=rent, rent_lost_today_pct=None if rent is None else _pct(rent, capital),
        pnl_with_rent_lamports=None if rent is None else pnl - rent,
        pnl_with_rent_pct=None if rent is None else _pct(pnl - rent, capital + rent),
        non_closed=dict(sorted(Counter(r['trade']['outcome'] for r in others).items())),
        non_closed_capital_lamports=sum(_cost(r['trade']) for r in others))
    losses = dict({name: sums[name] for name in ENTRY_COSTS + ('failed_attempt_costs',)},
                  negative_drift=-out['drift']['negative_sum_lamports'])
    if rent is not None:
        losses['rent_lost_today'] = rent
    gross_loss = sum(losses.values())
    out['loss_sources_ranked'] = [dict(source=name, lamports=value, share_of_gross_losses_pct=_pct(value, gross_loss))
                                  for name, value in sorted(losses.items(), key=lambda kv: (-kv[1], kv[0]))]
    out['gains_lamports'] = out['drift']['positive_sum_lamports']
    out['gains_cover_pct_of_gross_losses'] = _pct(out['gains_lamports'], gross_loss)
    return out


def _bucket(value, buckets):
    for low, high in buckets:
        if value >= low and (high is None or value <= high):
            return f'{low}+' if high is None else (str(low) if low == high else f'{low}-{high}')
    return 'below_%d' % buckets[0][0]


def _earlier_pools(bundle):
    """Pools of the same creator created BEFORE each pool, among the bundle's pools (a truncated history)."""
    by_creator = {}
    for r in sorted(bundle['pools'], key=lambda r: (r.get('created_slot') or 0, r['pool'])):
        by_creator.setdefault(r['creator'], []).append(r['pool'])
    return {pool: rank for pools in by_creator.values() for rank, pool in enumerate(pools)}


def group_keys(record, earlier, rents):
    trade = record['trade']
    keys = OrderedDict(
        segment=record['segment'],
        fee_rate_ppm=str(trade.get('fee_rate_ppm')),
        # causal: the events known at the decision; those that land during the order latency are not (R02 C-1)
        events_before_decision=_bucket(trade['decision_index'] + 1, EVENT_BUCKETS),
        creator_earlier_pools='0' if earlier.get(record['pool'], 0) == 0 else '1+',
        pool_events_total_HINDSIGHT=_bucket(record.get('trades') or 0, TOTAL_BUCKETS))
    if rents is not None:
        keys['token_class'] = rents.get(record['pool'], ('unknown', None))[0]
    return keys


def _group_row(records, n_boot, seed):
    closed = [r for r in records if r['trade']['outcome'] == 'closed']
    known = [(r, decompose(r)) for r in closed]
    known = [(r, p) for r, p in known if p is not None]
    returns = [r['trade']['pnl_lamports'] / _cost(r['trade']) for r in closed]
    row = dict(entered=len(records), closed=len(closed), creators=len({r['creator'] for r in records}),
               small_sample=len(closed) < SMALL_GROUP,
               pnl_lamports=sum(r['trade']['pnl_lamports'] for r in closed),
               mean_return=statistics.fmean(returns) if returns else None,
               win_rate=sum(v > 0 for v in returns) / len(returns) if returns else None,
               mean_instant_cost=statistics.fmean(
                   -sum(p[name] for name in ENTRY_COSTS) / _cost(r['trade']) for r, p in known) if known else None,
               mean_drift=statistics.fmean(p['drift'] / _cost(r['trade']) for r, p in known) if known else None,
               share_drift_positive=sum(p['drift'] > 0 for _r, p in known) / len(known) if known else None)
    if len(closed) >= 5 and n_boot:
        means = cluster_bootstrap_means(returns, [r['creator'] for r in closed], n_boot=n_boot, seed=seed)
        row['mean_return_ci95_creator_cluster'] = _interval(means, 0.05)
    return row


def groups(bundle, rents=None, *, n_boot=N_BOOT, seed=plan.SEED):
    """Descriptive breakdowns of the entered positions; every group carries its size and a small-sample flag."""
    earlier = _earlier_pools(bundle)
    table = {}
    for record in _discovery(bundle):
        for dimension, key in group_keys(record, earlier, rents).items():
            table.setdefault(dimension, {}).setdefault(key, []).append(record)
    return {dimension: {key: _group_row(rows, n_boot, seed) for key, rows in sorted(by_key.items())}
            for dimension, by_key in table.items()}


def _same_entry(a, b):
    ta, tb = a['trade'], b['trade']
    return all(ta.get(k) == tb.get(k) for k in ('entry_index', 'entry_signature', 'spent', 'tokens'))


def _quantile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def exits(bundle, probe, rents=None, segment=None):
    """What the exit could change at most on this trial's entries (hindsight on the probe path)."""
    paths = {r['pool']: r for r in _discovery(probe) if r['v3'].get('immediate_mark') is not None and 'path' in r['v3']}
    rows = [(r, paths[r['pool']]) for r in _discovery(bundle, segment)
            if r['pool'] in paths and _same_entry(r, paths[r['pool']])]
    if not rows:
        return dict(paired=0)
    best_excess, best_age, realised_gap, after, final = [], [], [], {w: [] for w in AFTER_WINDOWS_S}, []
    with_rent = []
    for record, probe_row in rows:
        block = probe_row['v3']
        cost = block['cost_lamports']
        points = [(0, block['immediate_mark'])] + [tuple(p) for p in block['path']]
        age, mark = max(points, key=lambda p: (p[1], -p[0]))
        best_excess.append((mark - cost) / cost)
        best_age.append(age)
        final.append((points[-1][1] - cost) / cost)
        rent = _rent(record, rents)
        if rent is not None:
            with_rent.append((mark - cost - rent) / (cost + rent))
        for window in AFTER_WINDOWS_S:
            after[window].append(sum(a <= window for a, _m in points[1:]))
        if record['trade']['outcome'] == 'closed':
            realised_gap.append((mark - record['trade']['received']) / cost)
    positive = sorted((v for v in best_excess if v > 0), reverse=True)
    total_positive = sum(positive)
    out = dict(
        paired=len(rows), label='HINDSIGHT upper bound on these entries; never an exit rule',
        best_exit_mean=statistics.fmean(best_excess), best_exit_median=statistics.median(best_excess),
        best_exit_share_positive=len(positive) / len(best_excess),
        best_exit_mean_with_rent=statistics.fmean(with_rent) if len(with_rent) == len(rows) else None,
        best_exit_share_positive_with_rent=(sum(v > 0 for v in with_rent) / len(with_rent)
                                            if len(with_rent) == len(rows) else None),
        best_exit_gain_share_of_top1=None if not total_positive else positive[0] / total_positive,
        best_exit_gain_share_of_top5=None if not total_positive else sum(positive[:5]) / total_positive,
        best_exit_mean_without_top1=(statistics.fmean(sorted(best_excess)[:-1]) if len(best_excess) > 1 else None),
        best_age_s=dict(median=statistics.median(best_age), p75=_quantile(best_age, 0.75), p90=_quantile(best_age, 0.90),
                        share_at_entry=sum(a == 0 for a in best_age) / len(best_age)),
        last_recorded_value_mean=statistics.fmean(final),
        realised_minus_best_mean=-statistics.fmean(realised_gap) if realised_gap else None,
        events_after_entry={str(w): dict(mean=statistics.fmean(v), median=statistics.median(v),
                                         share_none=sum(x == 0 for x in v) / len(v)) for w, v in after.items()})
    return out


def positions(bundle, probe=None, rents=None):
    """Trade-by-trade listing of one trial (closed cycles decomposed; others with their outcome)."""
    earlier = _earlier_pools(bundle)
    paths = {} if probe is None else {r['pool']: r for r in _discovery(probe) if 'path' in r['v3']}
    rows = []
    for record in sorted(_discovery(bundle), key=lambda r: (r.get('created_slot') or 0, r['pool'])):
        trade = record['trade']
        row = dict(pool=record['pool'], creator=record['creator'], created_slot=record.get('created_slot'),
                   outcome=trade['outcome'], hold_slots=trade.get('hold_slots'),
                   exit_reason=(trade.get('exit_trigger') or {}).get('reason'),
                   capital_lamports=_cost(trade), **group_keys(record, earlier, rents))
        trigger = trade.get('exit_trigger') or {}
        if trigger.get('index') is not None:
            row['events_during_hold'] = trigger['index'] - trade['entry_index']
        if trade['outcome'] == 'closed':
            parts = decompose(record)
            row.update(pnl_lamports=trade['pnl_lamports'], net_return=trade['pnl_lamports'] / _cost(trade))
            if parts is not None:
                row['components_lamports'] = parts
        probe_row = paths.get(record['pool'])
        if probe_row is not None and _same_entry(record, probe_row) and probe_row['v3'].get('immediate_mark') is not None:
            cost = probe_row['v3']['cost_lamports']
            points = [(0, probe_row['v3']['immediate_mark'])] + [tuple(p) for p in probe_row['v3']['path']]
            age, mark = max(points, key=lambda p: (p[1], -p[0]))
            row.update(best_exit_return_HINDSIGHT=(mark - cost) / cost, best_exit_age_s=age,
                       events_after_entry_900s=len(points) - 1)
        rows.append(row)
    return rows


def anatomy(bundles, census=None, *, positions_of=None, n_boot=N_BOOT):
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    probe = next((b for b in bundles.values() if b.get('role') == 'probe'), None)
    out = dict(schema=SCHEMA, status='EXPLORATORY', plan_sha256=plan.plan_sha256(),
               discovery_segments=list(DISCOVERY_SEGMENTS),
               rent_basis='token class of the census' if rents is not None else
               'ASSUMED: SPL Token rent for every row (no census supplied)',
               probe=None if probe is None else probe['trial'], notes=list(NOTES), trials={})
    for trial, bundle in sorted(bundles.items()):
        block = dict(role=bundle.get('role'), policy=bundle.get('policy'), bundle_sha256=bundle['bundle_sha256'],
                     money={segment or 'all_visible': money(_entered(bundle, segment), rents)
                            for segment in plan.SEGMENTS + (None,)},
                     groups=groups(bundle, rents, n_boot=n_boot))
        if probe is not None:
            block['exits'] = {segment or 'discovery': exits(bundle, probe, rents, segment)
                              for segment in DISCOVERY_SEGMENTS + (None,)}
        out['trials'][trial] = block
    if positions_of is not None:
        out['positions'] = dict(trial=positions_of, rows=positions(bundles[positions_of], probe, rents))
    return out


def _cell(value, digits=2, suffix='', scale=1.0):
    return '—' if value is None else f'{value * scale:.{digits}f}{suffix}'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + ['> loyer : ' + document['rent_basis'], '']
    lines += ['### Où part l’argent (cycles clos, tous segments visibles, en % du capital engagé)', '',
              '| Essai | Clos | P&L net | Frais de courbe achat | Frais de courbe vente | Arrondis | Frais de transaction '
              '| Échecs | Dérive pendant la détention | Coût aller-retour instantané | Loyer perdu aujourd’hui | P&L avec loyer '
              '| Cycles à dérive + / 0 / − |', '|' + '---|' * 13]
    for trial, body in document['trials'].items():
        m = body['money']['all_visible']
        c, d = m['components_pct'], m['drift']
        lines.append(
            f"| {trial} | {m['decomposed']} | {_cell(m['pnl_pct'], 2, ' %')} | {_cell(c['buy_fee'], 2, ' %', -1)} | "
            f"{_cell(c['sell_fee_at_entry'], 2, ' %', -1)} | {_cell(c['rounding'], 4, ' %', -1)} | "
            f"{_cell(c['tx_costs'], 2, ' %', -1)} | {_cell(c['failed_attempt_costs'], 2, ' %', -1)} | "
            f"{_cell(c['drift'], 2, ' %')} | {_cell(m['instant_round_trip_cost_pct'], 2, ' %', -1)} | "
            f"{_cell(m['rent_lost_today_pct'], 2, ' %', -1)} | {_cell(m['pnl_with_rent_pct'], 2, ' %')} | "
            f"{d['positive_cycles']} / {d['zero_cycles']} / {d['negative_cycles']} |")
    lines += ['', '### Sources de perte classées (tous segments visibles)', '',
              '| Essai | Source | SOL | Part des pertes brutes |', '|---|---|---|---|']
    for trial, body in document['trials'].items():
        for item in body['money']['all_visible']['loss_sources_ranked']:
            lines.append(f"| {trial} | {item['source']} | {item['lamports'] / 1e9:.4f} | "
                         f"{_cell(item['share_of_gross_losses_pct'], 1, ' %')} |")
    if document.get('probe'):
        lines += ['', '### Borne supérieure de toute règle de sortie (rétrospective, sonde %s ; exploration + train seulement)'
                  % document['probe'], '',
                  '| Essai | Positions appariées | Meilleure sortie possible (moyenne) | Médiane | Part > 0 | Avec loyer (moyenne) '
                  '| Part du gain due à la 1re position | aux 5 premières | Moyenne sans la 1re | Âge médian du maximum (s) '
                  '| Aucune transaction dans les 25 s |', '|' + '---|' * 11]
        for trial, body in document['trials'].items():
            e = body['exits']['discovery']
            if not e['paired']:
                continue
            lines.append(
                f"| {trial} | {e['paired']} | {_cell(e['best_exit_mean'], 2, ' %', 100)} | "
                f"{_cell(e['best_exit_median'], 2, ' %', 100)} | {_cell(e['best_exit_share_positive'], 1, ' %', 100)} | "
                f"{_cell(e['best_exit_mean_with_rent'], 2, ' %', 100)} | {_cell(e['best_exit_gain_share_of_top1'], 1, ' %', 100)} | "
                f"{_cell(e['best_exit_gain_share_of_top5'], 1, ' %', 100)} | {_cell(e['best_exit_mean_without_top1'], 2, ' %', 100)} | "
                f"{_cell(e['best_age_s']['median'], 0)} | {_cell(e['events_after_entry']['25']['share_none'], 1, ' %', 100)} |")
    reference = document['trials'].get(plan.PLAN.get('reference', 'V3-01'))
    if reference is not None:
        lines += ['', '### Ventilations de la référence (descriptif ; exploration + train seulement ; un groupe de moins de %d '
                  'clos est marqué *)' % SMALL_GROUP, '',
                  '| Dimension | Groupe | Entrées | Clos | Rendement net moyen | IC 95 % (créateurs) | Réussite | Coût instantané '
                  '| Dérive moyenne | Part dérive > 0 |', '|' + '---|' * 10]
        for dimension, by_key in reference['groups'].items():
            for key, g in by_key.items():
                ci = g.get('mean_return_ci95_creator_cluster')
                lines.append(
                    f"| {dimension} | {key}{' *' if g['small_sample'] else ''} | {g['entered']} | {g['closed']} | "
                    f"{_cell(g['mean_return'], 2, ' %', 100)} | "
                    f"{'—' if ci is None else f'[{100 * ci[0]:.2f} ; {100 * ci[1]:.2f}]'} | "
                    f"{_cell(g['win_rate'], 1, ' %', 100)} | {_cell(g['mean_instant_cost'], 2, ' %', 100)} | "
                    f"{_cell(g['mean_drift'], 2, ' %', 100)} | {_cell(g['share_drift_positive'], 1, ' %', 100)} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='loss anatomy of registered V3 bundles (descriptive)')
    parser.add_argument('bundles', type=Path)
    parser.add_argument('--census', type=Path)
    parser.add_argument('--positions', help='also list this trial position by position')
    parser.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    census = raw = None
    if a.census:
        raw = a.census.read_bytes()
        census = json.loads(raw)
    document = anatomy(load_bundles(a.bundles), census, positions_of=a.positions)
    if raw is not None:
        document['census_sha256'] = hashlib.sha256(raw).hexdigest()
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
