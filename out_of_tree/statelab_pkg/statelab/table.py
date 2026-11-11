"""Primary table of a state study: forward NET return by decision cell and horizon, against the placebo.

  python -B -m statelab.table <rows.json> --declared-k <K> [--census <census.json>] [--markdown <file>]

EVERYTHING BELOW IS DECLARED BEFORE ANY ROW IS READ (RUGGER 02: R-a..R-f of 243e2cca, C-S1..C-S3 of
bfb18f0a). Computing this table reads K net results: it adds K to the cumulative trial count N.

Cells       the ``age`` and ``progress`` labels of ``statelab.points`` crossed with the horizons
            (``K_GRID`` = 90). A label is computed only if it has at least ``MIN_PROBES`` entered
            probes and ``MIN_CREATORS`` creators (sample sizes only; printed by ``statelab.study``
            without any value); K = computed labels x horizons, and ``--declared-k`` must equal it.
Unit        one probe per pool and cell. ``r`` of an entered probe at horizon h:
              (value - cost - rent) / (cost + rent)   when the clock exit at h is priced,
              -1                                       when the curve completed before the sale landed.
            ``value`` is the frozen clock exit (sale latency included), ``cost`` the stake plus both
            transaction costs, ``rent`` the rent of our token account LOST by today's chain (class of
            the census; SPL rent assumed and said so without a census). Main metric: ``mean_r``.
Placebo     the ``placebo:0`` probe of the same pool at the same horizon (random entry age, fixed
            salt: the frozen V3-02 rule). ``vs_placebo`` = mean of r(cell) - r(placebo) over the pools
            that have both, creator-cluster percentile interval. Secondary: ``vs_reference`` (the
            ``age:5`` cell, the entry of V3-01), same pairing.
Martingale  secondary benchmark: ``mean_drift`` = mean of (value - immediate) / cost over priced
            probes, i.e. what the other traders did to the position; a martingale price gives 0.
Screening   a cell is RETAINED (a hypothesis to send to a confirmation, never a result) only if ALL of:
            mean_r > 0; lower bound of the 95 % interval of vs_placebo > 0; Benjamini-Hochberg at
            q = 0.10 over the ``K_GRID`` cells of the grid (cells not computed count in the family
            with p = 1) on the one-sided creator-cluster bootstrap p-value of mean_r <= 0.
Not counted the pre-declared sensitivities, published for every computed cell and used for no choice:
            ``mean_r_no_sale_latency``, ``mean_r_rent_recovered`` (cleanup activated: NOT executable
            today), and the same table on rows produced with ``--latency-slots 1`` and ``10``.
``hindsight_best`` is an upper bound of any exit, never a rule.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from v3lab.evaluate import _interval, cluster_bootstrap_means

from statelab.points import HORIZONS_S, K_GRID, PLACEBO_CELL, REFERENCE_CELL
from statelab.study import MIN_CREATORS, MIN_PROBES

SCHEMA = 'statelab-table-v2'
SPL_RENT_LAMPORTS = 2_039_280
CLEANUP_FEE_LAMPORTS = 5_001               # as v3lab.scenarios (R02 probe of the offline cleanup)
BH_Q = 0.10
N_BOOT = 10_000
SEED = 20261111
ALPHA = 0.05


def _mean(values):
    return statistics.fmean(values) if values else None


def _boot(values, groups, n_boot):
    """(interval, one-sided p of mean <= 0) by creator clusters; (None, None) without resampling."""
    if not values or not n_boot:
        return None, None
    means = cluster_bootstrap_means(values, groups, n_boot=n_boot, seed=SEED)
    return _interval(means, ALPHA), (sum(m <= 0 for m in means) + 1) / (n_boot + 1)


def _rent(row, rents):
    return SPL_RENT_LAMPORTS if rents is None else rents.get(row['pool'], (None, None))[1]


def probe_return(row, horizon, rents=None, *, field='value', extra=None):
    """r of one entered probe (see the module text); None when the rent of its token class is unknown."""
    cell = row['horizons'][horizon]
    extra = _rent(row, rents) if extra is None else extra
    if extra is None:
        return None
    if cell['migrated'] or cell[field] is None:
        return -1.0
    return (cell[field] - row['cost'] - extra) / (row['cost'] + extra)


def _paired(rows, others, horizon, rents, n_boot):
    pairs = [(r, others[r['pool']]) for r in rows if r['pool'] in others]
    diffs = [probe_return(a, horizon, rents) - probe_return(b, horizon, rents) for a, b in pairs]
    interval, _p = _boot(diffs, [a['creator'] for a, _b in pairs], n_boot)
    return dict(pairs=len(pairs), mean=_mean(diffs), ci95=interval)


def cell(rows, horizon, placebo, reference, rents=None, *, n_boot=N_BOOT):
    """One computed cell: ``rows`` are the entered probes of a label (one per pool)."""
    returns = [probe_return(r, horizon, rents) for r in rows]
    if any(v is None for v in returns):
        raise ValueError('token_class_unknown_for_a_probe')          # no guess: the census must cover the rows
    groups = [r['creator'] for r in rows]
    interval, p = _boot(returns, groups, n_boot)
    priced = [r for r in rows if not r['horizons'][horizon]['migrated']]
    drift = [(r['horizons'][horizon]['value'] - r['immediate']) / r['cost'] for r in priced]
    drift_interval, _p = _boot(drift, [r['creator'] for r in priced], n_boot)
    return dict(
        probes=len(rows), creators=len(set(groups)), migrated=len(rows) - len(priced),
        mean_r=_mean(returns), median_r=statistics.median(returns), mean_r_ci95=interval, p_one_sided=p,
        share_r_positive=sum(v > 0 for v in returns) / len(returns),
        vs_placebo=_paired(rows, placebo, horizon, rents, n_boot),
        vs_reference=_paired(rows, reference, horizon, rents, n_boot),
        mean_instant_cost=_mean([(r['immediate'] - r['cost']) / r['cost'] for r in priced]),
        mean_drift=_mean(drift), mean_drift_ci95=drift_interval,
        share_no_event=(sum(r['horizons'][horizon]['events'] == 0 for r in priced) / len(priced)) if priced else None,
        sensitivities=dict(
            mean_r_no_sale_latency=_mean([probe_return(r, horizon, rents, field='value_no_latency') for r in rows]),
            mean_r_rent_recovered=_mean([probe_return(r, horizon, extra=CLEANUP_FEE_LAMPORTS) for r in rows]),
            label='not counted, published for every cell, used for no choice; rent_recovered is NOT executable today'),
        hindsight_best_mean=_mean([(r['horizons'][horizon]['best'] - r['cost']) / r['cost'] for r in rows]))


def benjamini_hochberg(pvalues, family, q=BH_Q):
    """Keys rejected by the BH step-up at level ``q`` in a family of ``family`` tests (absent tests have p = 1)."""
    ordered = sorted((p, key) for key, p in pvalues.items() if p is not None)
    last = 0
    for rank, (p, _key) in enumerate(ordered, 1):
        if p <= q * rank / family:
            last = rank
    return {key for _p, key in ordered[:last]}


def table(document, census=None, *, declared_k, n_boot=N_BOOT):
    if document.get('schema') != 'statelab-rows-v2':
        raise ValueError('not_a_statelab_rows_v2_document')
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    horizons = [str(h) for h in document['constants']['horizons_s']]
    if horizons != [str(h) for h in HORIZONS_S]:
        raise ValueError('rows_made_with_other_horizons')
    by_label = {}
    for row in document['rows']:
        if row['entered']:
            for kind, level in row['labels']:
                by_label.setdefault(f'{kind}:{level}', []).append(row)
    floors = lambda rows: len(rows) >= MIN_PROBES and len({r['creator'] for r in rows}) >= MIN_CREATORS   # noqa: E731
    grid = sorted((key for key, rows in by_label.items() if key != PLACEBO_CELL and floors(rows)),
                  key=lambda key: (key.split(':')[0], int(key.split(':')[1])))
    k = len(grid) * len(horizons)
    if type(declared_k) is not int or declared_k != k:
        raise ValueError('declared_k_is_not_the_number_of_cells_this_table_computes:%d' % k)
    placebo = {r['pool']: r for r in by_label.get(PLACEBO_CELL, [])}
    reference = {r['pool']: r for r in by_label.get(REFERENCE_CELL, [])}
    cells = {key: {h: cell(by_label[key], h, placebo, reference, rents, n_boot=n_boot) for h in horizons}
             for key in grid}
    rejected = benjamini_hochberg({(key, h): c['p_one_sided'] for key, by_h in cells.items() for h, c in by_h.items()},
                                  K_GRID)
    retained = []
    for key, by_h in cells.items():
        for h, c in by_h.items():
            low = (c['vs_placebo']['ci95'] or [None])[0]
            c['screening'] = dict(mean_r_positive=c['mean_r'] > 0, beats_placebo=low is not None and low > 0,
                                  bh_q10_of_90=(key, h) in rejected)
            c['retained'] = all(c['screening'].values())
            if c['retained']:
                retained.append([key, h])
    placebo_rows = by_label.get(PLACEBO_CELL, [])
    placebo_below = not floors(placebo_rows)                    # R02 E-S1: said in every output, automatically
    baseline = None
    if by_label.get(PLACEBO_CELL):
        rows = by_label[PLACEBO_CELL]
        baseline = {h: dict(probes=len(rows), creators=len({r['creator'] for r in rows}),
                            mean_r=_mean([probe_return(r, h, rents) for r in rows])) for h in horizons}
    return dict(
        schema=SCHEMA, status='EXPLORATORY', rows_sha256=document['rows_sha256'],
        pack_manifest_sha256=document['pack_manifest_sha256'], segments=document['segments'],
        confirm_validation=document.get('confirm_validation'), constants=document['constants'],
        rent_basis='token class of the census' if rents is not None else
        'ASSUMED: SPL Token rent for every row (no census supplied)',
        k=k, k_grid=K_GRID, trials_added_to_n=k, labels_not_computed=sorted(
            key for key in by_label if key != PLACEBO_CELL and key not in grid),
        placebo_baseline=baseline, placebo_below_floors=placebo_below,
        placebo_sample=dict(probes=len(placebo_rows), creators=len({r['creator'] for r in placebo_rows})),
        cells=cells, retained=retained,
        rule=dict(min_probes=MIN_PROBES, min_creators=MIN_CREATORS, bh_q=BH_Q, bh_family=K_GRID, n_boot=n_boot,
                  seed=SEED, alpha=ALPHA, reference_cell=REFERENCE_CELL, placebo_cell=PLACEBO_CELL),
        notes=['fixed cells, horizons, placebo and screening rule, declared in the code before any row was read',
               f'computing this table added {k} to the cumulative trial count N (R02 R-b)',
               'a RETAINED cell is a hypothesis for one confirmation on other data, never a result or a proof',
               'r includes the rent lost by today\'s chain; a position whose curve completed first counts -1',
               'hindsight_best is an upper bound of any exit, not a rule']
        + (['PLACEBO BELOW THE SAMPLE FLOORS on this pack (%d probes, %d creators): the paired comparison rests on '
            'few pools and the screening is under-powered' % (len(placebo_rows), len({r['creator'] for r in placebo_rows}))]
           if placebo_below else []))


def _pct(value, digits=2):
    return '—' if value is None else f'{100 * value:.{digits}f} %'


def _span(interval):
    return '—' if interval is None else f'[{100 * interval[0]:.2f} ; {100 * interval[1]:.2f}]'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + [
        '> loyer : ' + document['rent_basis'],
        *(['> PLACEBO SOUS PLANCHER sur ce pack (%d sondes, %d créateurs) : la comparaison appariée repose sur peu de '
           'pools, le criblage manque de puissance' % (document['placebo_sample']['probes'],
                                                        document['placebo_sample']['creators'])]
          if document['placebo_below_floors'] else []),
        f"> K = {document['k']} cellules calculées sur {document['k_grid']} ; non calculées (échantillon insuffisant) : "
        + (', '.join(document['labels_not_computed']) or 'aucune'), '',
        '| Cellule | Horizon (s) | Sondes | Créateurs | Rendement net moyen (loyer perdu, migrées −1) | IC 95 % | Part > 0 '
        '| Écart au placebo | IC 95 % de l’écart | Coût instantané | Dérive (martingale = 0) | Migrées '
        '| Sans latence de vente | Loyer récupéré (non exécutable) | Meilleure sortie rétrospective | Retenue |',
        '|' + '---|' * 16]
    for key, by_h in document['cells'].items():
        for h, c in by_h.items():
            s = c['sensitivities']
            lines.append(
                f"| {key} | {h} | {c['probes']} | {c['creators']} | {_pct(c['mean_r'])} | {_span(c['mean_r_ci95'])} | "
                f"{_pct(c['share_r_positive'], 1)} | {_pct(c['vs_placebo']['mean'])} | {_span(c['vs_placebo']['ci95'])} | "
                f"{_pct(c['mean_instant_cost'])} | {_pct(c['mean_drift'])} | {c['migrated']} | "
                f"{_pct(s['mean_r_no_sale_latency'])} | {_pct(s['mean_r_rent_recovered'])} | "
                f"{_pct(c['hindsight_best_mean'])} | {'OUI' if c['retained'] else 'non'} |")
    if document['placebo_baseline']:
        lines += ['', '| Placebo (âge aléatoire) | Horizon (s) | Sondes | Créateurs | Rendement net moyen |', '|---|---|---|---|---|']
        lines += [f"| placebo:0 | {h} | {b['probes']} | {b['creators']} | {_pct(b['mean_r'])} |"
                  for h, b in document['placebo_baseline'].items()]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='forward net return by decision cell and horizon, against the placebo')
    parser.add_argument('rows', type=Path)
    parser.add_argument('--declared-k', type=int, required=True)
    parser.add_argument('--census', type=Path)
    parser.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    raw = a.rows.read_bytes()
    census = json.loads(a.census.read_bytes()) if a.census else None
    document = table(json.loads(raw), census, declared_k=a.declared_k)
    document['rows_file_sha256'] = hashlib.sha256(raw).hexdigest()
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
