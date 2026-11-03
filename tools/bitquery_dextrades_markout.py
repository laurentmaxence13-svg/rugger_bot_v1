#!/usr/bin/env python3
"""Offline observed price markouts for normalized Bitquery DEXTrades.

STRICT RESEARCH ONLY: no network, wallet, transaction, order, realized P&L, or
Master-vs-reference claim. The swaps describe other market participants.
Run: python tools/bitquery_dextrades_markout.py PATH/TO/rugger_bitquery_swaps_20261031.csv --out OUTPUT_DIR
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
from statistics import median

WSOL = 'So11111111111111111111111111111111111111112'
PROGRAMS = {
    'raydium_launchpad': 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj',
    'raydium_cp_swap': 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C',
}
BUY = 'BUY_TOKEN_WITH_WSOL'
SELL = 'SELL_TOKEN_FOR_WSOL'


def parse_rows(rows):
    result = []
    ids = set()
    for r in rows:
        protocol = r.get('protocol')
        if protocol not in PROGRAMS or r.get('program_address') != PROGRAMS[protocol]:
            raise ValueError('Unknown or mismatched Raydium program')
        key = r.get('event_id')
        if not key or key in ids:
            raise ValueError('Missing or duplicate event_id')
        ids.add(key)
        slot = int(r['block_slot'])
        stamp = datetime.fromisoformat(r['block_time_utc'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Timezone missing')
        is_wsol = str(r['wsol_trade']).lower() == 'true'
        direction = r.get('trade_direction')
        if is_wsol:
            if direction not in (BUY, SELL):
                raise ValueError('WSOL trade direction missing')
            wsol_buy = r.get('buy_mint') == WSOL
            wsol_sell = r.get('sell_mint') == WSOL
            if wsol_buy == wsol_sell or (direction == BUY) != wsol_sell:
                raise ValueError('Swap legs and direction inconsistent')
            mint = r.get('sell_mint') if direction == SELL else r.get('buy_mint')
            if r.get('token_mint') != mint:
                raise ValueError('Mint mismatch')
            try:
                tok = Decimal(r['token_amount'])
                wsol = Decimal(r['wsol_amount'])
                price = Decimal(r['execution_price_wsol_per_token'])
            except (InvalidOperation, TypeError) as exc:
                raise ValueError('Invalid numeric fields') from exc
            if not all(v.is_finite() and v > 0 for v in (tok, wsol, price)):
                raise ValueError('Nonpositive or nonfinite numeric fields')
            with localcontext() as ctx:
                ctx.prec = 35
                if abs(price - wsol / tok) > max(Decimal('1e-28'), price * Decimal('1e-20')):
                    raise ValueError('Price does not match WSOL and token amounts')
        else:
            if direction != 'CROSS_PAIR_NO_WSOL':
                raise ValueError('Unrecognized cross-pair direction')
            mint = tok = price = None
        result.append(dict(r, _slot=slot, _stamp=stamp, _wsol=is_wsol,
                           _mint=mint, _token=tok, _price=price))
    return result


def make_report(rows, sha256=None):
    events = parse_rows(rows)
    grouped = defaultdict(list)
    for e in events:
        if e['_wsol']:
            grouped[(e['protocol'], e['market_address'], e['_mint'])].append(e)
    markouts = []
    stats = Counter()
    ambiguous_examples = []
    for (protocol, pool, mint), group in grouped.items():
        sales = [e for e in group if e['trade_direction'] == SELL]
        buys = [e for e in group if e['trade_direction'] == BUY]
        for entry in buys:
            stats['entry_observations'] += 1
            later = [x for x in sales if x['_slot'] > entry['_slot']
                     and x['_stamp'] > entry['_stamp']]
            if not later:
                stats['no_later_exit_observation'] += 1
                continue
            first_slot = min(x['_slot'] for x in later)
            first_slot_sales = [x for x in later if x['_slot'] == first_slot]
            if len(first_slot_sales) != 1:
                stats['ambiguous_first_exit_slot'] += 1
                if len(ambiguous_examples) < 5:
                    ambiguous_examples.append(dict(pool=pool, entry_id=entry['event_id'],
                                                   exit_slot=first_slot,
                                                   sale_rows=len(first_slot_sales)))
                continue
            exit_ = first_slot_sales[0]
            with localcontext() as ctx:
                ctx.prec = 35
                markout = (exit_['_price'] / entry['_price'] - Decimal(1)) * Decimal(100)
            age = int((exit_['_stamp'] - entry['_stamp']).total_seconds())
            if age <= 0:
                raise ValueError('Causality violation')
            markouts.append({
                'entry_id': entry['event_id'],
                'exit_observation_id': exit_['event_id'],
                'protocol': protocol, 'pool': pool, 'mint': mint,
                'entry_time_utc': entry['block_time_utc'],
                'exit_observation_time_utc': exit_['block_time_utc'],
                'gap_seconds': age,
                'entry_observed_price_wsol_per_token': str(entry['_price']),
                'later_observed_price_wsol_per_token': str(exit_['_price']),
                'observed_price_markout_pct': format(markout, '.8f'),
                'later_swap_token_amount_at_least_entry_swap':
                    exit_['_token'] >= entry['_token'],
                'exit_fill_for_our_order_proven': False,
                'realizable_net_pnl_proven': False,
            })
    values = [Decimal(x['observed_price_markout_pct']) for x in markouts]
    report = {
        'schema': 'rugger-bitquery-dextrades-observed-markout-v1',
        'source_sha256': sha256,
        'total_swaps': len(events),
        'program_counts': dict(Counter(e['protocol'] for e in events)),
        'wsol_swap_rows': sum(e['_wsol'] for e in events),
        'distinct_wsol_pool_token_groups': len(grouped),
        'entry_observations': stats['entry_observations'],
        'no_later_exit_observation': stats['no_later_exit_observation'],
        'ambiguous_first_exit_slot': stats['ambiguous_first_exit_slot'],
        'strictly_later_first_opposite_side_markouts': len(markouts),
        'markout_distinct_pools': len({x['pool'] for x in markouts}),
        'later_trade_size_ge_entry_trade_size_count':
            sum(x['later_swap_token_amount_at_least_entry_swap'] for x in markouts),
        'observed_gross_price_markout_pct': {
            'min': str(min(values)) if values else None,
            'median': str(median(values)) if values else None,
            'max': str(max(values)) if values else None,
            'positive_count': sum(x > 0 for x in values),
            'negative_count': sum(x < 0 for x in values),
        },
        'ambiguous_examples': ambiguous_examples,
        'certified_paper_trades': 0,
        'net_pnl_sol': None,
        'master_minus_reference_net_pnl_sol': None,
        'economic_gate': 'NO_GO_EXECUTABLE_EXITS_AND_CREATOR_COHORT_MISSING',
        'restrictions': [
            'Observed swaps by OTHER participants, not executable bid/ask for Rugger.',
            'No verifiable own-position fill, liquidity, price impact, costs or exit.',
            'Exclude same-slot multiple first sales; slot is not instruction order.',
            'Repeated entries per pool are correlated, not independent sample trades.',
            'No verified creators, launch chronology, migrations or complete history.',
            'Observed gross price differences are NOT portfolio PnL or strategy edge.',
        ],
    }
    assert report['entry_observations'] == (
        report['no_later_exit_observation'] +
        report['ambiguous_first_exit_slot'] + len(markouts)
    )
    return report, markouts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file', type=Path)
    parser.add_argument('--out', type=Path,
                        default=Path('validation/bitquery_dextrades'))
    args = parser.parse_args()
    raw = args.csv_file.read_bytes()
    with args.csv_file.open(encoding='utf-8-sig', newline='') as f:
        report, markouts = make_report(csv.DictReader(f),
                                       hashlib.sha256(raw).hexdigest())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    with (args.out / 'observed_markouts.csv').open(
            'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(markouts[0]) if markouts
                                else ['entry_id'])
        writer.writeheader()
        writer.writerows(markouts)
    print(json.dumps({
        k: report[k] for k in (
            'total_swaps', 'wsol_swap_rows', 'entry_observations',
            'ambiguous_first_exit_slot',
            'strictly_later_first_opposite_side_markouts',
            'markout_distinct_pools', 'observed_gross_price_markout_pct',
            'economic_gate')
    }, indent=2))


if __name__ == '__main__':
    main()
