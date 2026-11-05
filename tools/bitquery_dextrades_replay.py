#!/usr/bin/env python3
"""End-to-end offline Bitquery DEXTrades -> normalized tape -> observed markouts.

No API keys, transactions, wallet access, realized PnL, nor execution simulation.
Usage: python tools/bitquery_dextrades_replay.py page1.json [page2.json ...] --out DIR
"""
import argparse
import csv
from decimal import Decimal, localcontext
import hashlib
from importlib.util import spec_from_file_location, module_from_spec
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WSOL = 'So11111111111111111111111111111111111111112'


def load_local(name):
    path = HERE / name
    spec = spec_from_file_location(name[:-3], path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(swaps):
    normalized = []
    for i, row in enumerate(swaps):
        trade = row['Trade']
        buy, sell = trade['Buy'], trade['Sell']
        buy_mint = buy['Currency']['MintAddress']
        sell_mint = sell['Currency']['MintAddress']
        quote_wsol = (buy_mint == WSOL) != (sell_mint == WSOL)
        norm = {
            'event_id': f'paged-bitquery-{i:08d}',
            'block_time_utc': row['Block']['Time'],
            'block_slot': str(row['Block']['Slot']),
            'signature': row['Transaction']['Signature'],
            'protocol': trade['Dex']['ProtocolName'],
            'program_address': trade['Dex']['ProgramAddress'],
            'market_address': trade['Market']['MarketAddress'],
            'buy_mint': buy_mint, 'sell_mint': sell_mint,
            'wsol_trade': quote_wsol,
        }
        if quote_wsol:
            is_buy_token = sell_mint == WSOL
            with localcontext() as ctx:
                ctx.prec = 35
                token = Decimal(str(buy['Amount'] if is_buy_token else sell['Amount']))
                sol = Decimal(str(sell['Amount'] if is_buy_token else buy['Amount']))
                price = sol / token
            norm.update({
                'trade_direction': 'BUY_TOKEN_WITH_WSOL' if is_buy_token else 'SELL_TOKEN_FOR_WSOL',
                'token_mint': buy_mint if is_buy_token else sell_mint,
                'token_amount': str(token),
                'wsol_amount': str(sol),
                'execution_price_wsol_per_token': str(price),
            })
        else:
            norm.update({
                'trade_direction': 'CROSS_PAIR_NO_WSOL',
                'token_mint': '', 'token_amount': '', 'wsol_amount': '',
                'execution_price_wsol_per_token': '',
            })
        normalized.append(norm)
    return normalized


def process(pages):
    merger = load_local('bitquery_dextrades_pages.py')
    markout = load_local('bitquery_dextrades_markout.py')
    manifest, swaps = merger.merge_pages(pages)
    tape = normalize(swaps)
    economic, marks = markout.make_report(tape)
    assert economic['total_swaps'] == manifest['observed_rows']
    assert economic['economic_gate'].startswith('NO_GO')
    assert economic['net_pnl_sol'] is None
    return manifest, tape, economic, marks


def write_output(paths, out):
    pages, hashes = [], {}
    for path in paths:
        raw = path.read_bytes()
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        pages.append((path.name, json.loads(raw.decode('utf-8-sig'))))
    manifest, tape, report, marks = process(pages)
    manifest['page_sha256'] = hashes
    out.mkdir(parents=True, exist_ok=True)
    (out / 'source_manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (out / 'observed_markout_report.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    with (out / 'normalized_swaps.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(tape[0]) if tape else ['event_id'])
        writer.writeheader()
        writer.writerows(tape)
    with (out / 'observed_markouts.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(marks[0]) if marks else ['entry_id'])
        writer.writeheader()
        writer.writerows(marks)
    if manifest['oldest_slot']:
        merger = load_local('bitquery_dextrades_pages.py')
        (out / 'next_page.graphql').write_text(
            merger.build_query(manifest['oldest_slot']), encoding='utf-8')
    return manifest, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pages', nargs='+', type=Path)
    p.add_argument('--out', type=Path, default=Path('research/bitquery_dextrades/replay'))
    args = p.parse_args()
    manifest, report = write_output(args.pages, args.out)
    print('SWAPS:', manifest['observed_rows'])
    print('OBSERVED CAUSAL MARKOUTS:', report['strictly_later_first_opposite_side_markouts'])
    print('POOLS:', report['markout_distinct_pools'])
    print('ECONOMIC GATE:', report['economic_gate'])


if __name__ == '__main__':
    main()
