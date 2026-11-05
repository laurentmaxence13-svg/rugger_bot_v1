#!/usr/bin/env python3
"""Offline report: per-pool fee schedule and one fixed baseline replay.

Reads only the local archives in data/launchlab_trades (no network, no keys).

The baseline was fixed before it was run and is not tuned: buy 0.05 SOL after
the third observed trade of a pool, exit once 30 slots have elapsed. It checks
that the pipeline runs end to end on real pools. With a handful of pools it is
NOT evidence of an economic edge.

  python -B tools/launchlab_baseline_report.py
"""
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.market.collector import load_archive, summarize  # noqa: E402
from bot.market.launchlab_curve import FEE_DENOMINATOR  # noqa: E402
from bot.market.replay import ExecutionModel, Strategy, replay  # noqa: E402

DEFAULT_DIR = ROOT / 'data' / 'launchlab_trades'
ENTRY_TRADE_COUNT = 3
SPEND_LAMPORTS = 50_000_000          # 0.05 SOL
HOLD_SLOTS = 30
LATENCY_SLOTS = 2


class Baseline(Strategy):
    def entry(self, history):
        return SPEND_LAMPORTS if len(history) == ENTRY_TRADE_COUNT else None

    def exit(self, history, position, mark):
        return history[-1].slot - position.entry_slot >= HOLD_SLOTS


def fee_rate_interval(events):
    """Total fee rates (ppm) consistent with every event's observed ceil-fee."""
    low, high = 0, FEE_DENOMINATOR
    for event in events:
        basis, fee = event.quote_volume, event.total_fee
        r_min = ((fee - 1) * FEE_DENOMINATOR) // basis + 1 if fee > 0 else 0
        r_max = (fee * FEE_DENOMINATOR) // basis
        low, high = max(low, r_min), min(high, r_max)
    return low, high


def report_pool(directory, pool):
    archive = load_archive(directory, pool)
    summary, timeline = summarize(archive)
    low, high = fee_rate_interval(timeline.events)
    fees = [tx['meta']['fee'] for tx in archive.transactions.values()
            if (tx.get('meta') or {}).get('err') is None]
    info = {
        'pool': pool, 'quote_is_sol': summary['quote_is_sol'], 'complete': summary['complete'],
        'trades': len(timeline.events), 'fee_rate_ppm_interval': [low, high],
        'single_fee_schedule': low <= high,
        'median_tx_fee_lamports': int(statistics.median(fees)) if fees else 0,
    }
    # Only complete, SOL-quoted pools with one fee schedule are replayed. The
    # pool's own quote mint is passed on, so the engine's SOL check still applies.
    if summary['complete'] and summary['quote_is_sol'] and low <= high:
        model = ExecutionModel(latency_slots=LATENCY_SLOTS, fee_rate_ppm=low,
                               base_fee_lamports=info['median_tx_fee_lamports'],
                               priority_fee_lamports=0)
        result = replay(timeline, Baseline(), model, quote_mint=archive.account['mint_quote'])
        info['replay'] = {
            'outcome': result.outcome, 'decision_index': result.decision_index,
            'entry_index': result.entry_index, 'exit_index': result.exit_index,
            'spent_SOL': result.spent / 1e9, 'received_SOL': result.received / 1e9,
            'tx_costs_SOL': result.tx_costs / 1e9,
            'pnl_SOL': None if result.pnl is None else result.pnl / 1e9,
            'net_return': None if result.net_return is None else round(result.net_return, 6),
            'hold_slots': result.hold_slots, 'notes': result.notes,
        }
    return info


def main(argv=None):
    directory = DEFAULT_DIR
    pools = [p.name[:-len('.json.gz')] for p in sorted(directory.glob('*.json.gz'))]
    for pool in pools:
        print(json.dumps(report_pool(directory, pool), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
