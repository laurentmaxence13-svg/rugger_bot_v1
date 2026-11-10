"""Profitability table per trial and segment, from registered V3 bundles. Descriptive: it decides nothing.

  python -B -m v3lab.tables <bundles_dir> [--markdown <file>]

Reads only what ``v3lab evaluate`` already read (the bundles of the plan's trials, sha256 checked) and
adds no trial: same rows, other sums. Not part of the V3 fingerprint. Columns (owner's format):
trades, net P&L in SOL and in % of the capital committed, win rate, profit factor, maximum drawdown,
transaction costs and instant round-trip cost, positions not closed, difference with the reference.
Conventions: P&L counts CLOSED cycles (frozen rule); ``pnl_if_non_closed_lost`` also writes off every
position that is not a closed cycle. The drawdown is the largest peak-to-trough fall of the cumulative
realised P&L, cycles taken in the order of their exit slot.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from v3lab import plan
from v3lab.evaluate import _cost, load_bundles

SEGMENTS = ('exploration', 'train', 'validation')
STAKE_LAMPORTS = 100_000_000


def row(bundle, segment=None):
    """One table row; ``segment`` None pools the three visible segments (never an independent sample)."""
    entered = [r for r in bundle['pools'] if r['trade']['entry_index'] is not None
               and (segment is None or r['segment'] == segment)]
    closed = sorted((r for r in entered if r['trade']['outcome'] == 'closed'),
                    key=lambda r: (r['trade'].get('exit_slot') or 0, r['pool']))
    others = [r for r in entered if r['trade']['outcome'] != 'closed']
    pnl = [r['trade']['pnl_lamports'] for r in closed]
    capital = sum(_cost(r['trade']) for r in closed)
    at_risk = sum(_cost(r['trade']) for r in others)
    gains, losses = sum(p for p in pnl if p > 0), -sum(p for p in pnl if p < 0)
    running = peak = drawdown = 0
    for value in pnl:
        running += value
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    known = [r for r in closed if r['v3'].get('immediate_mark') is not None]
    round_trip = sum(r['v3']['cost_lamports'] - r['v3']['immediate_mark'] for r in known)
    return dict(
        trades=len(entered), closed=len(closed), creators=len({r['creator'] for r in entered}),
        pnl_sol=sum(pnl) / 1e9, capital_sol=capital / 1e9, pnl_pct=None if not capital else 100 * sum(pnl) / capital,
        win_rate_pct=None if not pnl else 100 * sum(p > 0 for p in pnl) / len(pnl),
        profit_factor=None if not losses else gains / losses, gains_sol=gains / 1e9, losses_sol=losses / 1e9,
        max_drawdown_sol=drawdown / 1e9, max_drawdown_stakes=drawdown / STAKE_LAMPORTS,
        tx_costs_sol=sum(r['trade']['tx_costs'] + r['trade']['failed_attempt_costs'] for r in entered) / 1e9,
        round_trip_cost_sol=round_trip / 1e9, round_trip_cost_cycles=len(known),
        round_trip_cost_pct=None if not known else 100 * round_trip / sum(r['v3']['cost_lamports'] for r in known),
        non_closed=dict(sorted(Counter(r['trade']['outcome'] for r in others).items())),
        non_closed_capital_sol=at_risk / 1e9, pnl_if_non_closed_lost_sol=(sum(pnl) - at_risk) / 1e9,
        pnl_if_non_closed_lost_pct=None if not capital + at_risk else 100 * (sum(pnl) - at_risk) / (capital + at_risk))


def tables(bundles):
    out = dict(schema='v3lab-profit-table-v1', status='EXPLORATORY', plan_sha256=plan.plan_sha256(),
               reference=plan.PLAN.get('reference', 'V3-01'), trials={},
               notes=['closed cycles only in pnl_sol / pnl_pct (frozen rule); see pnl_if_non_closed_lost',
                      'P0 visible segments: already used by 25 + V3 trials; nothing here is a proof of profitability',
                      'the reference V3-01 is the policy of the previous research reference (fixed delay 5 s, clock 25 s)'])
    reference = bundles.get(out['reference'])
    for trial, bundle in sorted(bundles.items()):
        block = {}
        for segment in SEGMENTS + (None,):
            item = row(bundle, segment)
            if reference is not None:
                base = row(reference, segment)
                item['vs_reference'] = dict(
                    pnl_sol=item['pnl_sol'] - base['pnl_sol'],
                    pnl_pct_points=None if item['pnl_pct'] is None or base['pnl_pct'] is None
                    else item['pnl_pct'] - base['pnl_pct'])
            block[segment or 'all_visible'] = item
        out['trials'][trial] = dict(role=bundle.get('role'), policy=bundle.get('policy'),
                                    bundle_sha256=bundle['bundle_sha256'], segments=block)
    return out


def _cell(value, digits=2, suffix=''):
    return '—' if value is None else f'{value:.{digits}f}{suffix}'


def markdown(document):
    lines = ['| Essai | Segment | Trades | Clos | P&L net (SOL) | P&L net (%) | Réussite | Profit factor | Drawdown max (SOL) '
             '| Frais de transaction (SOL) | Coût aller-retour instantané | Non clos | P&L si non clos perdus (SOL) '
             '| Écart vs référence (points) |', '|' + '---|' * 14]
    for trial, body in document['trials'].items():
        for segment, r in body['segments'].items():
            other = ', '.join(f'{k} {v}' for k, v in r['non_closed'].items()) or '0'
            lines.append(
                f"| {trial} | {segment} | {r['trades']} | {r['closed']} | {_cell(r['pnl_sol'], 4)} | "
                f"{_cell(r['pnl_pct'], 2, ' %')} | {_cell(r['win_rate_pct'], 1, ' %')} | {_cell(r['profit_factor'])} | "
                f"{_cell(r['max_drawdown_sol'], 4)} | {_cell(r['tx_costs_sol'], 4)} | "
                f"{_cell(r['round_trip_cost_pct'], 2, ' %')} | {other} | {_cell(r['pnl_if_non_closed_lost_sol'], 4)} | "
                f"{_cell((r.get('vs_reference') or {}).get('pnl_pct_points'), 2)} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='profitability table of registered V3 bundles (descriptive)')
    parser.add_argument('bundles', type=Path)
    parser.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    document = tables(load_bundles(a.bundles))
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
