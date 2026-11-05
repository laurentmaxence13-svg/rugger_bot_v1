#!/usr/bin/env python3
"""Offline append-only Bitquery Solana.DEXTrades page merger for PAPER research.

Usage: python tools/bitquery_dextrades_pages.py page1.json page2.json --out DIR
No wallet, network, purchase, paper trade, price prediction or profit claims.
"""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

VALID_PROGRAMS = {
    'raydium_launchpad': 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj',
    'raydium_cp_swap': 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C',
}
PAGE_LIMIT = 200


def parse_page(obj):
    if isinstance(obj, dict) and 'data' in obj and 'Solana' not in obj:
        if obj.get('errors'):
            raise ValueError('GraphQL response contains errors')
        obj = obj['data']
    trades = (obj.get('Solana') or {}).get('DEXTrades') if isinstance(obj, dict) else None
    if not isinstance(trades, list):
        raise ValueError('Expected Solana.DEXTrades JSON array')
    previous_slot = None
    for row in trades:
        try:
            block, transaction, trade = row['Block'], row['Transaction'], row['Trade']
            slot = int(block['Slot'])
            time = datetime.fromisoformat(block['Time'].replace('Z', '+00:00'))
            sig, protocol = transaction['Signature'], trade['Dex']['ProtocolName']
            program = trade['Dex']['ProgramAddress']
            pool = trade['Market']['MarketAddress']
            buy, sell = trade['Buy'], trade['Sell']
            for side in (buy, sell):
                amount = Decimal(str(side['Amount']))
                if not amount.is_finite() or amount <= 0:
                    raise ValueError('Nonpositive or nonfinite amount')
                if not side['Currency']['MintAddress']:
                    raise ValueError('Missing mint')
            if time.tzinfo is None or slot < 1 or not sig or not pool or VALID_PROGRAMS[protocol] != program:
                raise ValueError('Invalid Solana DEXTrades trade')
            if previous_slot is not None and slot > previous_slot:
                raise ValueError('Page not sorted by descending Block_Slot')
            previous_slot = slot
        except (KeyError, ValueError, TypeError, AttributeError, ArithmeticError) as exc:
            raise ValueError('Invalid DEXTrades row') from exc
    return trades


def identity(row):
    # Distinct swaps in one transaction can share signature. Use entire row.
    serialized = json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def build_query(bound, count=PAGE_LIMIT):
    if not isinstance(bound, int) or bound < 1:
        raise ValueError('Invalid slot boundary')
    if not (1 <= count <= 1000):
        raise ValueError('Invalid page size')
    return f'''# Bitquery DEXTrades: older page with slot-frontier overlap (READ ONLY)
# Repeating the slot frontier is intentional; merge by full-row occurrence,
# never by signature. A full page with one slot is NOT safe to paginate.
query RuggerBot_Swaps_OlderPage {{
  Solana(dataset: realtime) {{
    DEXTrades(
      limit: {{count: {count}}}
      orderBy: {{descending: Block_Slot}}
      where: {{
        Block: {{Slot: {{le: "{bound}"}}}}
        Transaction: {{Result: {{Success: true}}}}
        Trade: {{Dex: {{ProtocolName: {{in: ["raydium_launchpad", "raydium_cp_swap"]}}}}}}
      }}
    ) {{
      Block {{Time Slot}}
      Transaction {{Signature Signer}}
      Trade {{
        Dex {{ProtocolName ProgramAddress}}
        Market {{MarketAddress}}
        Buy {{Amount AmountInUSD Currency {{Symbol MintAddress Decimals}}}}
        Sell {{Amount AmountInUSD Currency {{Symbol MintAddress Decimals}}}}
      }}
    }}
  }}
}}
'''


def merge_pages(pages, page_limit=PAGE_LIMIT):
    """Conservative occurrence-based merge. No proof of archive completeness.

    For an identical raw row occurring twice within the same page, retain both.
    A later page may re-include boundary-slot rows; retain max count seen for
    each fingerprint, not sum. Without event/instruction index, identical rows
    on separate pages cannot be proven distinct.
    """
    combined = []
    seen_count = Counter()
    reports = []
    last_frontier = None
    for i, (name, raw) in enumerate(pages):
        current = parse_page(raw)
        slots = [int(r['Block']['Slot']) for r in current]
        if i and current and last_frontier is not None and max(slots) > last_frontier:
            raise ValueError(f'Page {name} is newer than preceding frontier; incorrect cursor/order')
        local_count = Counter()
        new_rows = 0
        overlap_rows = 0
        for row in current:
            fp = identity(row)
            local_count[fp] += 1
            if local_count[fp] <= seen_count[fp]:
                overlap_rows += 1
                continue
            combined.append(row)
            new_rows += 1
        for key, count in local_count.items():
            seen_count[key] = max(seen_count[key], count)
        frontier = min(slots) if slots else None
        if i and current and len(current) >= page_limit and not new_rows:
            raise ValueError(f'Page {name}: no new swaps, cursor stalled')
        if last_frontier is not None and frontier is not None and frontier >= last_frontier and len(current) == page_limit:
            raise ValueError(f'Page {name}: full page did not advance past boundary slot')
        reports.append({
            'page': name, 'received': len(current), 'new_records': new_rows,
            'overlap_records': overlap_rows, 'min_slot': frontier,
            'max_slot': max(slots) if slots else None,
            'complete_page': len(current) < page_limit,
            'frontier_order_proven': not i or (not current or max(slots) <= last_frontier),
        })
        if frontier is not None:
            last_frontier = frontier
    sigcounts = Counter(r['Transaction']['Signature'] for r in combined)
    programs = Counter(r['Trade']['Dex']['ProtocolName'] for r in combined)
    report = {
        'schema': 'rugger-bitquery-dextrades-paged-observations-v1',
        'source_cube': 'Solana.DEXTrades',
        'observed_rows': len(combined),
        'distinct_signatures': len(sigcounts),
        'multi_swap_rows_not_deduplicated_by_signature': sum(c - 1 for c in sigcounts.values()),
        'program_rows': dict(programs),
        'pages': reports,
        'oldest_slot': min((int(r['Block']['Slot']) for r in combined), default=None),
        'newest_slot': max((int(r['Block']['Slot']) for r in combined), default=None),
        'history_complete': False,
        'creator_cohort_verified': False,
        'executable_exit_proven': False,
        'master_vs_baseline_net_profit': None,
        'economic_gate': 'NO_GO_INCOMPLETE_HISTORY_AND_EXECUTION_EVIDENCE',
        'warnings': [
            'GraphQL orderBy Block_Slot has no intra-slot event ordering.',
            'Identical rows spanning pages are ambiguous without transaction/instruction index.',
            'Boundary page overlaps are merged by full-row multiplicity, never by signature alone.',
            'A short realtime page does not prove complete history; Bitquery rolling retention applies.',
            'No realized or paper trading PnL can be inferred from third-party swap data.',
        ],
    }
    return report, combined


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pages', nargs='+', type=Path)
    p.add_argument('--out', type=Path, default=Path('research/bitquery_dextrades'))
    args = p.parse_args()
    inputs, hashes = [], {}
    for path in args.pages:
        raw = path.read_bytes()
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        inputs.append((path.name, json.loads(raw.decode('utf-8-sig'))))
    report, combined = merge_pages(inputs)
    report['page_sha256'] = hashes
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'manifest.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (args.out / 'swaps.jsonl').write_text(
        ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n'
                for r in combined), encoding='utf-8')
    if report['oldest_slot']:
        (args.out / 'next_page.graphql').write_text(
            build_query(report['oldest_slot']), encoding='utf-8')
    print('RECEIVED:', sum(p['received'] for p in report['pages']))
    print('UNIQUE OBSERVED RECORDS:', report['observed_rows'])
    print('PROTOCOLS:', report['program_rows'])
    print('NEXT SLOT:', report['oldest_slot'])
    print('ECONOMIC GATE:', report['economic_gate'])


if __name__ == '__main__':
    main()
