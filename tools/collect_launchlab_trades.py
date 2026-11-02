#!/usr/bin/env python3
"""Read-only, budgeted collection of LaunchLab trade histories.

Examples (archives go to data/launchlab_trades, which git ignores):

  python -B tools/collect_launchlab_trades.py discover --program-txs 60 --max-calls 80
  python -B tools/collect_launchlab_trades.py collect --pool <POOL> --max-calls 500
  python -B tools/collect_launchlab_trades.py summarize

``--rpc helius`` reads HELIUS_API_KEY from .env (never printed); ``--rpc public``
uses the free public mainnet endpoint. No signing, wallet or order code.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.market.collector import (  # noqa: E402
    MAX_TX_VERSION, Budget, BudgetExhausted, JsonRpc, RpcError, collect_pool, load_archive,
    summarize,
)
from bot.market.launchlab_events import (  # noqa: E402
    LAUNCHLAB_PROGRAM, EventDecodeError, extract_trade_events,
)

PUBLIC_RPC = 'https://api.mainnet-beta.solana.com'
DEFAULT_DIR = ROOT / 'data' / 'launchlab_trades'


def _rpc(kind, max_calls):
    if kind == 'public':
        return JsonRpc(PUBLIC_RPC, Budget(max_calls), min_interval=0.45)
    key = os.environ.get('HELIUS_API_KEY')
    if not key:
        try:
            from dotenv import dotenv_values
            key = dotenv_values(ROOT / '.env').get('HELIUS_API_KEY')
        except ImportError:
            key = None
    if not key:
        raise SystemExit('HELIUS_API_KEY absent (variable or .env); use --rpc public')
    return JsonRpc(f'https://mainnet.helius-rpc.com/?api-key={key}', Budget(max_calls),
                   min_interval=0.12)


def discover(rpc, program_txs):
    """Pools seen in the most recent successful LaunchLab transactions."""
    rows = rpc.call('getSignaturesForAddress',
                    [LAUNCHLAB_PROGRAM, {'limit': program_txs, 'commitment': 'finalized'}]) or []
    pools, errors = {}, {}
    for row in rows:
        if row.get('err') is not None:
            continue
        try:
            result = rpc.call('getTransaction', [row['signature'], {
                'encoding': 'json', 'maxSupportedTransactionVersion': MAX_TX_VERSION,
                'commitment': 'finalized'}])
            events = extract_trade_events(result) if result else []
        except BudgetExhausted:
            break
        except (RpcError, EventDecodeError) as exc:
            errors[str(exc)] = errors.get(str(exc), 0) + 1
            continue
        for event in events:
            entry = pools.setdefault(event.pool, {'trades_seen': 0, 'max_progress_ppm': 0})
            entry['trades_seen'] += 1
            entry['max_progress_ppm'] = max(entry['max_progress_ppm'],
                                            event.state_after().progress_ppm)
    if errors:
        print(f'discover_errors={json.dumps(errors, sort_keys=True)}', file=sys.stderr)
    return pools


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rpc', choices=('helius', 'public'), default='helius')
    parser.add_argument('--dir', type=Path, default=DEFAULT_DIR)
    sub = parser.add_subparsers(dest='command', required=True)
    d = sub.add_parser('discover')
    d.add_argument('--program-txs', type=int, default=50)
    d.add_argument('--max-calls', type=int, default=60)
    c = sub.add_parser('collect')
    c.add_argument('--pool', action='append', required=True)
    c.add_argument('--max-calls', type=int, required=True)
    c.add_argument('--max-signature-pages', type=int, default=20)
    s = sub.add_parser('summarize')
    s.add_argument('--pool', action='append')
    args = parser.parse_args(argv)

    if args.command == 'summarize':
        pools = args.pool or sorted(p.name[:-len('.json.gz')] for p in args.dir.glob('*.json.gz'))
        for pool in pools:
            print(json.dumps(summarize(load_archive(args.dir, pool))[0], sort_keys=True))
        return 0

    rpc = _rpc(args.rpc, args.max_calls)
    if args.command == 'discover':
        print(json.dumps(discover(rpc, args.program_txs), indent=1, sort_keys=True))
    else:
        for pool in args.pool:
            try:
                archive = collect_pool(rpc, pool, args.dir,
                                       max_signature_pages=args.max_signature_pages)
                status = 'ok'
            except BudgetExhausted:
                archive, status = load_archive(args.dir, pool), 'budget_exhausted'
            except (RpcError, EventDecodeError) as exc:
                archive, status = load_archive(args.dir, pool), f'error:{exc}'
            summary = summarize(archive)[0]
            summary['collect_status'] = status
            print(json.dumps(summary, sort_keys=True))
            if status == 'budget_exhausted':
                break
    print(f'rpc_calls_used={rpc.budget.used}/{rpc.budget.max_calls}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
