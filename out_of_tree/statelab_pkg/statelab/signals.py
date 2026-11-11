"""Ranking of the causal signals available at the reference entry by their link with the net result.

  python -B -m statelab.signals <rows.json> --declared-k 34 [--census <census.json>] [--markdown <file>]

SELECTION ENGINE, screening step. Everything is declared here before any row is read:
* entries   the probes of the reference cell ``age:5`` (the entry of the current MASTER), one per pool;
* target    ``r`` of ``statelab.table`` at 25 s (frozen clock exit, every cost, rent lost, migrated = -1);
            the drift alone, (value - immediate) / cost, is given beside it to tell a cost effect
            (fee tier) from a price effect;
* signals   the ``FEATURES`` below: the causal features stored in every row (history up to the
            decision event only). A missing value drops the pool for that signal; a constant signal
            has no rank correlation;
* measure   Spearman rank correlation (average ranks) between the signal and r, with a
            creator-cluster bootstrap interval and a two-sided p-value; mean r of the bottom, middle
            and top thirds of the signal and the top-minus-bottom difference with its interval;
* screening a signal is RETAINED (a hypothesis to test on other data, never a result) when its
            correlation passes Benjamini-Hochberg at q = 0.10 over the ``K`` signals.
Reading the thirds of a signal is reading the net result of a selection rule: computing this table
adds ``K`` = len(FEATURES) to the cumulative trial count N; ``--declared-k`` must equal it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics

from statelab.points import REFERENCE_CELL
from statelab.table import BH_Q, benjamini_hochberg, probe_return

SCHEMA = 'statelab-signals-v1'
HORIZON = '25'
N_BOOT = 5_000                    # the smallest p-value (1 / 5001) must be able to pass the first BH step (0.10 / 34)
SEED = 20261111
FEATURES = (
    'age_s', 'trades', 'buys', 'sells', 'unique_buyers', 'unique_sellers', 'quote_raised_lamports', 'progress_ppm',
    'buy_volume_lamports', 'sell_volume_lamports', 'price_vs_launch', 'drawdown_from_peak', 'creator_bought_lamports',
    'creator_sold_lamports', 'creator_token_share', 'top1_token_share', 'top5_token_share', 'early_slot_payers',
    'seconds_since_previous_trade',
    'trades_10s', 'buyers_10s', 'net_flow_10s_lamports', 'price_change_10s',
    'trades_30s', 'buyers_30s', 'net_flow_30s_lamports', 'price_change_30s',
    'trades_60s', 'buyers_60s', 'net_flow_60s_lamports', 'price_change_60s',
    'fee_rate_ppm_causal', 'progress_gain_30s_ppm', 'progress_gain_60s_ppm')
K = len(FEATURES)                                               # 34


def ranks(values):
    """Average ranks (1-based), ties share the mean of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for position in range(i, j + 1):
            out[order[position]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs, ys):
    """Rank correlation; None when a side is constant or fewer than 3 pairs."""
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    if not sxx or not syy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sxx * syy) ** 0.5


def _clusters(groups):
    index = {}
    for i, group in enumerate(groups):
        index.setdefault(group, []).append(i)
    return list(index.values())


def _interval(values, alpha=0.05):
    values = sorted(values)
    n = len(values)
    return [values[int(alpha / 2 * (n - 1))], values[min(n - 1, int(round((1 - alpha / 2) * (n - 1))))]]


def signal_row(name, rows, returns, drifts, *, n_boot=N_BOOT):
    pairs = [(r['features'].get(name), ret, drift, r['creator'], r['pool'])
             for r, ret, drift in zip(rows, returns, drifts) if r['features'].get(name) is not None]
    xs, ys, groups = [p[0] for p in pairs], [p[1] for p in pairs], [p[3] for p in pairs]
    rho = spearman(xs, ys)
    out = dict(signal=name, pools=len(pairs), rho=rho, rho_ci95=None, p_two_sided=None,
               rho_with_drift=spearman([p[0] for p in pairs if p[2] is not None], [p[2] for p in pairs if p[2] is not None]))
    order = sorted(range(len(pairs)), key=lambda i: (xs[i], pairs[i][4]))
    third = len(order) // 3
    if third >= 1:
        parts = dict(bottom=order[:third], middle=order[third:len(order) - third], top=order[len(order) - third:])
        out['thirds'] = {key: dict(pools=len(idx), mean_r=statistics.fmean(ys[i] for i in idx),
                                   signal_range=[xs[idx[0]], xs[idx[-1]]]) for key, idx in parts.items()}
        out['top_minus_bottom'] = out['thirds']['top']['mean_r'] - out['thirds']['bottom']['mean_r']
    if rho is None or not n_boot:
        return out
    rng = random.Random(f'{SEED}:{name}')
    clusters = _clusters(groups)
    side = {i: (1 if i in set(parts['top']) else -1 if i in set(parts['bottom']) else 0) for i in range(len(pairs))} \
        if third >= 1 else {}
    rhos, diffs = [], []
    for _ in range(n_boot):
        sample = [i for _k in range(len(clusters)) for i in clusters[rng.randrange(len(clusters))]]
        value = spearman([xs[i] for i in sample], [ys[i] for i in sample])
        if value is not None:
            rhos.append(value)
        top = [ys[i] for i in sample if side.get(i) == 1]
        bottom = [ys[i] for i in sample if side.get(i) == -1]
        if top and bottom:
            diffs.append(statistics.fmean(top) - statistics.fmean(bottom))
    if rhos:
        out['rho_ci95'] = _interval(rhos)
        low, high = sum(v <= 0 for v in rhos), sum(v >= 0 for v in rhos)
        out['p_two_sided'] = min(1.0, 2 * (min(low, high) + 1) / (len(rhos) + 1))
    if diffs:
        out['top_minus_bottom_ci95'] = _interval(diffs)
    return out


def signals(document, census=None, *, declared_k, n_boot=N_BOOT):
    if document.get('schema') not in ('statelab-rows-v2', 'statelab-rows-v3'):
        raise ValueError('not_a_statelab_rows_document')
    if type(declared_k) is not int or declared_k != K:
        raise ValueError('declared_k_is_not_the_number_of_signals:%d' % K)
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    kind, level = REFERENCE_CELL.split(':')
    rows = [r for r in document['rows'] if r['entered'] and [kind, int(level)] in r['labels']]
    returns = [probe_return(r, HORIZON, rents) for r in rows]
    if any(v is None for v in returns):
        raise ValueError('token_class_unknown_for_a_probe')
    drifts = [None if r['horizons'][HORIZON]['migrated'] else (r['horizons'][HORIZON]['value'] - r['immediate']) / r['cost']
              for r in rows]
    table = [signal_row(name, rows, returns, drifts, n_boot=n_boot) for name in FEATURES]
    passed = benjamini_hochberg({row['signal']: row['p_two_sided'] for row in table}, K)
    for row in table:
        row['retained'] = row['signal'] in passed
    table.sort(key=lambda row: (-(abs(row['rho']) if row['rho'] is not None else -1), row['signal']))
    return dict(schema=SCHEMA, status='EXPLORATORY', rows_sha256=document['rows_sha256'],
                pack_manifest_sha256=document['pack_manifest_sha256'], segments=document['segments'],
                population=document.get('population', 'signed'), entries=REFERENCE_CELL, horizon_s=int(HORIZON),
                pools=len(rows), creators=len({r['creator'] for r in rows}),
                mean_r=statistics.fmean(returns) if returns else None, k=K, trials_added_to_n=K,
                rule=dict(bh_q=BH_Q, n_boot=n_boot, seed=SEED), signals=table,
                retained=[row['signal'] for row in table if row['retained']],
                notes=['screening on discovery data: a retained signal is a hypothesis for other data, never a result',
                       f'computing this table added {K} to the cumulative trial count N',
                       'r includes every cost and the rent lost by today\'s chain; a migrated position counts -1',
                       'thirds are cut on this sample: their means are optimistic for the extreme thirds'])


def _pct(value, digits=2):
    return '—' if value is None else f'{100 * value:.{digits}f} %'


def _num(value, digits=2):
    return '—' if value is None else f'{value:+.{digits}f}'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + [
        f"> entrées : {document['entries']} ; horizon {document['horizon_s']} s ; {document['pools']} pools, "
        f"{document['creators']} créateurs ; rendement net moyen {_pct(document['mean_r'])} ; population {document['population']}", '',
        '| Rang | Signal (connu à la décision) | Pools | Corrélation de rang avec le rendement net | IC 95 % | p | Avec la dérive seule '
        '| Tiers bas | Tiers milieu | Tiers haut | Haut − bas | IC 95 % | Retenu |', '|' + '---|' * 13]
    for rank, row in enumerate(document['signals'], 1):
        thirds = row.get('thirds') or {}
        ci, dci = row.get('rho_ci95'), row.get('top_minus_bottom_ci95')
        lines.append(
            f"| {rank} | {row['signal']} | {row['pools']} | {_num(row['rho'])} | "
            f"{'—' if ci is None else f'[{ci[0]:+.2f} ; {ci[1]:+.2f}]'} | {_num(row['p_two_sided'], 3).lstrip('+')} | "
            f"{_num(row['rho_with_drift'])} | {_pct((thirds.get('bottom') or {}).get('mean_r'))} | "
            f"{_pct((thirds.get('middle') or {}).get('mean_r'))} | {_pct((thirds.get('top') or {}).get('mean_r'))} | "
            f"{_pct(row.get('top_minus_bottom'))} | "
            f"{'—' if dci is None else f'[{100 * dci[0]:.2f} ; {100 * dci[1]:.2f}]'} | {'OUI' if row['retained'] else 'non'} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='ranking of causal signals at the reference entry (screening)')
    parser.add_argument('rows', type=Path)
    parser.add_argument('--declared-k', type=int, required=True)
    parser.add_argument('--census', type=Path)
    parser.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    raw = a.rows.read_bytes()
    census = json.loads(a.census.read_bytes()) if a.census else None
    document = signals(json.loads(raw), census, declared_k=a.declared_k)
    document['rows_file_sha256'] = hashlib.sha256(raw).hexdigest()
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
