"""Two profitability views of the same registered V3 bundles, by the class of the launched token.

  python -B -m v3lab.scenarios <bundles_dir> <census.json> [--markdown <file>]

``census.json`` is the output of ``t22pol.census`` on the same visible pools. Scenarios:
  executable_now  entries on SPL Token mints only: what the frozen real chain can trade today;
  experimental    plus Token-2022 mints of the allowlist (metadata extensions only, no mint or freeze
                  authority): what an audited Token-2022 route would add. Not executable today.
Every other entry (refused Token-2022, unknown class) is excluded from both and counted.
Rent: the token account opened by the buy is never recovered by the frozen chain (R02 E-1, C-5), so
each closed cycle also bears the rent of OUR account (2,039,280 lamports for SPL, 2,074,080 for a
Token-2022 associated account with ImmutableOwner): ``*_with_rent`` columns. Descriptive: same rows
as ``v3lab.tables``, no new trial, nothing decided; not part of the V3 fingerprint.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from v3lab import plan
from v3lab.evaluate import _cost, load_bundles
from v3lab.tables import row

SCENARIOS = dict(executable_now=('executable_now',), experimental=('executable_now', 'token2022_allowlisted'))


def classes(census):
    if census.get('schema') != 't22pol-census-v1' or census.get('disagreements_with_frozen_reader'):
        raise ValueError('census_missing_or_disagrees_with_the_frozen_reader')
    return {r['pool']: (r['class_'], r['our_account_rent_lamports']) for r in census['rows']}


def _reasons(census):
    return {r['pool']: tuple(r.get('reasons') or ()) for r in census['rows']}


DIFFERENCE_FIELDS = ('trades', 'closed', 'pnl_sol', 'pnl_with_rent_sol', 'pnl_with_rent_pct',
                     'profit_factor_with_rent', 'win_rate_with_rent_pct', 'max_drawdown_sol')


def _difference(experimental, executable):
    out = {}
    for key in DIFFERENCE_FIELDS:
        a, b = experimental.get(key), executable.get(key)
        out[key] = None if a is None or b is None else a - b
    return out


def _filtered(bundle, keep, by_pool):
    pools = [r for r in bundle['pools'] if r['trade']['entry_index'] is None
             or by_pool.get(r['pool'], ('unknown', None))[0] in keep]
    return dict(bundle, pools=pools)


def _with_rent(bundle, segment, by_pool):
    closed = [r for r in bundle['pools'] if r['trade']['entry_index'] is not None
              and r['trade']['outcome'] == 'closed' and (segment is None or r['segment'] == segment)]
    nets = [r['trade']['pnl_lamports'] - by_pool[r['pool']][1] for r in closed]
    capital = sum(_cost(r['trade']) + by_pool[r['pool']][1] for r in closed)
    gains, losses = sum(n for n in nets if n > 0), -sum(n for n in nets if n < 0)
    return dict(rent_sol=sum(by_pool[r['pool']][1] for r in closed) / 1e9, pnl_with_rent_sol=sum(nets) / 1e9,
                pnl_with_rent_pct=None if not capital else 100 * sum(nets) / capital,
                win_rate_with_rent_pct=None if not nets else 100 * sum(n > 0 for n in nets) / len(nets),
                profit_factor_with_rent=None if not losses else gains / losses)


def scenarios(bundles, census):
    by_pool = classes(census)
    reasons = _reasons(census)
    out = dict(schema='v3lab-token-class-scenarios-v1', status='EXPLORATORY', plan_sha256=plan.plan_sha256(),
               census_rows=len(by_pool), scenarios={}, excluded_entries={},
               notes=['descriptive: same registered rows, filtered by token class; no new trial',
                      'no ranking of this table may be used to choose or promote a strategy',
                      'experimental is NOT executable today: the frozen chain refuses every Token-2022 mint',
                      'P0 visible only; already used by 34 trials; nothing here is a proof of profitability'])
    for trial, bundle in sorted(bundles.items()):
        entered = [r for r in bundle['pools'] if r['trade']['entry_index'] is not None]
        excluded = [r for r in entered if by_pool.get(r['pool'], ('unknown', None))[0] not in SCENARIOS['experimental']]
        out['excluded_entries'][trial] = dict(sorted(Counter(
            by_pool.get(r['pool'], ('unknown', None))[0] for r in excluded).items()))
        out.setdefault('excluded_reasons', {})[trial] = dict(sorted(Counter(
            reason for r in excluded for reason in (reasons.get(r['pool']) or ('not_in_census',))).items()))
        for name, keep in SCENARIOS.items():
            view = _filtered(bundle, keep, by_pool)
            block = {}
            for segment in plan.SEGMENTS + (None,):
                item = row(view, segment)
                item.update(_with_rent(view, segment, by_pool))
                block[segment or 'all_visible'] = item
            out['scenarios'].setdefault(name, {})[trial] = dict(role=bundle.get('role'),
                                                                bundle_sha256=bundle['bundle_sha256'],
                                                                segments=block)
    for trial in bundles:
        now = out['scenarios']['executable_now'][trial]['segments']
        exp = out['scenarios']['experimental'][trial]['segments']
        out.setdefault('difference_experimental_minus_executable', {})[trial] = {
            segment: _difference(exp[segment], now[segment]) for segment in now}
    return out


def _cell(value, digits=2, suffix=''):
    return '—' if value is None else f'{value:.{digits}f}{suffix}'


def markdown(document):
    lines = []
    for name, trials in document['scenarios'].items():
        lines += [f'### {name}', '', '| Essai | Segment | Trades | Clos | P&L net (SOL) | P&L net (%) | P&L avec loyer (SOL) '
                  '| P&L avec loyer (%) | Réussite avec loyer | Profit factor avec loyer | Drawdown max (SOL) | Non clos |',
                  '|' + '---|' * 12]
        for trial, body in trials.items():
            for segment, r in body['segments'].items():
                lines.append(f"| {trial} | {segment} | {r['trades']} | {r['closed']} | {_cell(r['pnl_sol'], 4)} | "
                             f"{_cell(r['pnl_pct'], 2, ' %')} | {_cell(r['pnl_with_rent_sol'], 4)} | "
                             f"{_cell(r['pnl_with_rent_pct'], 2, ' %')} | {_cell(r['win_rate_with_rent_pct'], 1, ' %')} | "
                             f"{_cell(r['profit_factor_with_rent'])} | {_cell(r['max_drawdown_sol'], 4)} | "
                             f"{sum(r['non_closed'].values())} |")
        lines.append('')
    lines += ['### Différence expérimentale − exécutable (effet de la compatibilité Token-2022)', '',
              '| Essai | Segment | Trades | Clos | P&L avec loyer (SOL) | P&L avec loyer (points de %) | Profit factor avec loyer |',
              '|' + '---|' * 7]
    for trial, segments in document['difference_experimental_minus_executable'].items():
        for segment, d in segments.items():
            lines.append(f"| {trial} | {segment} | {d['trades']} | {d['closed']} | {_cell(d['pnl_with_rent_sol'], 4)} | "
                         f"{_cell(d['pnl_with_rent_pct'], 2)} | {_cell(d['profit_factor_with_rent'])} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='executable-now vs experimental Token-2022 views (descriptive)')
    parser.add_argument('bundles', type=Path)
    parser.add_argument('census', type=Path)
    parser.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    raw = a.census.read_bytes()
    document = scenarios(load_bundles(a.bundles), json.loads(raw))
    document['census_sha256'] = hashlib.sha256(raw).hexdigest()
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
