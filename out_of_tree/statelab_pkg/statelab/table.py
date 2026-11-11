"""Primary table of a state study: forward NET value by decision cell and horizon. Descriptive.

  python -B -m statelab.table <rows.json> [--census <census.json>] [--markdown <file>]

The cells are the labels of ``statelab.points`` (fixed before any data): nothing is searched here.
For each cell and horizon, over the rows that entered:
* ``r``       = (value - cost) / cost, the net return of selling at that horizon (rent excluded);
* ``cost0``   = (immediate - cost) / cost, the instant round trip; ``drift`` = r - cost0 (what the
                other traders did): an edge needs drift > -cost0 + rent, i.e. r_with_rent > 0;
* ``r_with_rent`` = (value - cost - rent) / (cost + rent): today's chain loses the rent of our token
                account (SPL rent assumed unless a census gives the class of the pool's token);
* migrated rows are not credited: they are excluded from ``mean_r`` and counted -1 in
  ``mean_r_migrated_lost`` (R02 criteria v1);
* intervals: creator-cluster percentile bootstrap (the frozen algorithm, as ``v3lab.evaluate``);
* ``best`` is HINDSIGHT (upper bound of any exit up to that horizon), never a rule.
A cell with fewer than ``MIN_CELL`` rows is flagged; no cell of this table may be used to choose or
promote a strategy: a pattern read here is a hypothesis to pre-register and test on other data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from v3lab.evaluate import _interval, cluster_bootstrap_means

SCHEMA = 'statelab-table-v1'
SPL_RENT_LAMPORTS = 2_039_280
MIN_CELL = 30
N_BOOT = 2_000
SEED = 20261111


def _mean(values):
    return statistics.fmean(values) if values else None


def _ci(values, groups, n_boot):
    if len(values) < 5 or not n_boot:
        return None
    return _interval(cluster_bootstrap_means(values, groups, n_boot=n_boot, seed=SEED), 0.05)


def cell(rows, horizon, rents=None, *, n_boot=N_BOOT):
    entered = [r for r in rows if r['entered']]
    priced = [r for r in entered if r['horizons'][horizon]['value'] is not None]
    cost = lambda r: r['cost']                                               # noqa: E731
    ret = [(r['horizons'][horizon]['value'] - cost(r)) / cost(r) for r in priced]
    cost0 = [(r['immediate'] - cost(r)) / cost(r) for r in priced]
    late = [(r['horizons'][horizon]['value_late'] - r['horizons'][horizon]['value']) / cost(r)
            for r in priced if r['horizons'][horizon]['value_late'] is not None]
    best = [(r['horizons'][horizon]['best'] - cost(r)) / cost(r) for r in entered]
    rent = [SPL_RENT_LAMPORTS if rents is None else rents.get(r['pool'], (None, None))[1] for r in priced]
    with_rent = None if any(v is None for v in rent) else [
        (r['horizons'][horizon]['value'] - cost(r) - v) / (cost(r) + v) for r, v in zip(priced, rent)]
    lost = ret + [-1.0] * (len(entered) - len(priced))
    groups = [r['creator'] for r in priced]
    return dict(
        rows=len(rows), entered=len(entered), priced=len(priced), migrated=len(entered) - len(priced),
        pools=len({r['pool'] for r in entered}), creators=len({r['creator'] for r in entered}),
        small_sample=len(priced) < MIN_CELL,
        mean_r=_mean(ret), median_r=statistics.median(ret) if ret else None, mean_r_ci95=_ci(ret, groups, n_boot),
        share_r_positive=sum(v > 0 for v in ret) / len(ret) if ret else None,
        mean_cost0=_mean(cost0), mean_drift=_mean([a - b for a, b in zip(ret, cost0)]),
        mean_r_with_rent=_mean(with_rent) if with_rent is not None else None,
        mean_r_with_rent_ci95=_ci(with_rent, groups, n_boot) if with_rent is not None else None,
        mean_r_migrated_lost=_mean(lost),
        mean_sale_latency_effect=_mean(late),
        mean_events=_mean([r['horizons'][horizon]['events'] for r in priced]),
        share_no_event=(sum(r['horizons'][horizon]['events'] == 0 for r in priced) / len(priced)) if priced else None,
        hindsight_best_mean=_mean(best), hindsight_best_share_positive=sum(v > 0 for v in best) / len(best) if best else None)


def table(document, census=None, *, n_boot=N_BOOT):
    if document.get('schema') != 'statelab-rows-v1':
        raise ValueError('not_a_statelab_rows_document')
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    horizons = [str(h) for h in document['constants']['horizons_s']]
    cells = {}
    for row in document['rows']:
        for kind, level in row['labels']:
            cells.setdefault(f'{kind}:{level}', []).append(row)
    order = lambda key: (key.split(':')[0], int(key.split(':')[1]))            # noqa: E731
    out = dict(schema=SCHEMA, status='EXPLORATORY', rows_sha256=document['rows_sha256'],
               pack_manifest_sha256=document['pack_manifest_sha256'], segments=document['segments'],
               confirm_validation=document.get('confirm_validation'), constants=document['constants'],
               rent_basis='token class of the census' if rents is not None else
               'ASSUMED: SPL Token rent for every row (no census supplied)',
               cells={key: {h: cell(cells[key], h, rents, n_boot=n_boot) for h in horizons}
                      for key in sorted(cells, key=order)},
               notes=['descriptive: fixed cells and horizons, nothing searched, nothing chosen, no trial',
                      'a positive cell is a hypothesis to pre-register and confirm on other data, never a result',
                      f'cells with fewer than {MIN_CELL} priced rows are flagged small_sample',
                      'hindsight_best is an upper bound of any exit, not a rule'])
    return out


def _pct(value, digits=2):
    return '—' if value is None else f'{100 * value:.{digits}f} %'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + ['> loyer : ' + document['rent_basis'], '',
             '| Cellule | Horizon (s) | Sondes valorisées | Créateurs | Rendement net moyen | IC 95 % (créateurs) | Part > 0 '
             '| Coût instantané | Dérive | Avec loyer perdu | Migrées | Effet latence de vente | Sans transaction '
             '| Meilleure sortie rétrospective |', '|' + '---|' * 14]
    for key, by_h in document['cells'].items():
        for h, c in by_h.items():
            ci = c['mean_r_ci95']
            lines.append(
                f"| {key}{' *' if c['small_sample'] else ''} | {h} | {c['priced']} | {c['creators']} | {_pct(c['mean_r'])} | "
                f"{'—' if ci is None else f'[{100 * ci[0]:.2f} ; {100 * ci[1]:.2f}]'} | {_pct(c['share_r_positive'], 1)} | "
                f"{_pct(c['mean_cost0'])} | {_pct(c['mean_drift'])} | {_pct(c['mean_r_with_rent'])} | {c['migrated']} | "
                f"{_pct(c['mean_sale_latency_effect'])} | {_pct(c['share_no_event'], 1)} | {_pct(c['hindsight_best_mean'])} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='forward net value by decision cell and horizon (descriptive)')
    parser.add_argument('rows', type=Path)
    parser.add_argument('--census', type=Path)
    parser.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    raw = a.rows.read_bytes()
    census = json.loads(a.census.read_bytes()) if a.census else None
    document = table(json.loads(raw), census)
    document['rows_file_sha256'] = hashlib.sha256(raw).hexdigest()
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
