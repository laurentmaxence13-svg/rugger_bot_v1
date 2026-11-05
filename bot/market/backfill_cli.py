"""Bounded read-only backfill of a LaunchLab (or CPMM pool) slot window.

DRY RUN BY DEFAULT: without ``--network`` no request is sent, whatever else is given.

  # 1. Estimate (never touches the network)
  python -B tools/backfill_launchlab_window.py plan --slot-min 470000000 --slot-max 470216000 \
      --expected-tx-per-slot 0.6 --costs helius-conservative

  # 2. Run or resume (owner only, after key rotation and approval of the budget)
  RUGGER_BACKFILL_RPC_URL=... python -B tools/backfill_launchlab_window.py run --network \
      --endpoint-env RUGGER_BACKFILL_RPC_URL --slot-min ... --slot-max ... \
      --max-requests 120000 --max-credits 9500000 --costs helius-conservative --out data/backfill/w1

  # 3. Check an archive offline
  python -B tools/backfill_launchlab_window.py verify --out data/backfill/w1

The endpoint URL is read from the environment variable named by ``--endpoint-env``;
it is never printed or written (only its scheme and host). ``.env`` is not read.
Caps are cumulative across resumes of the same ``--out`` directory.
"""
import argparse
import json
from pathlib import Path
import sys

from bot.market.backfill import (
    LAUNCHLAB_PROGRAM, Backfill, BackfillError, CreditBudget, Window, endpoint_from_env,
    endpoint_label, load_costs, open_rpc, plan, verify,
)
from bot.market.collector import RpcError


def _window_args(p):
    p.add_argument('--address', default=LAUNCHLAB_PROGRAM,
                   help='address to backfill (default: the LaunchLab program)')
    p.add_argument('--slot-min', type=int, required=True)
    p.add_argument('--slot-max', type=int, required=True)
    p.add_argument('--bodies', choices=('gtfa', 'rpc'), default='gtfa',
                   help='gtfa: getTransactionsForAddress full pages (Helius); '
                        'rpc: getSignaturesForAddress + getTransaction (any RPC)')
    p.add_argument('--no-check', action='store_true',
                   help='skip the second-method signature reconciliation (not recommended)')
    p.add_argument('--costs', default='helius-conservative',
                   help='cost preset (helius-conservative, public) or JSON file')


def main(argv=None, *, environ=None, opener=None, out=sys.stdout):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan', help='estimate requests and credits; no network')
    _window_args(p)
    p.add_argument('--expected-tx-per-slot', type=float, required=True,
                   help='your volume assumption; measure it before trusting the estimate')
    r = sub.add_parser('run', help='run or resume; dry run unless --network')
    _window_args(r)
    r.add_argument('--network', action='store_true', help='actually send read-only requests')
    r.add_argument('--endpoint-env', default='RUGGER_BACKFILL_RPC_URL',
                   help='NAME of the environment variable holding the https endpoint URL')
    r.add_argument('--max-requests', type=int, required=True)
    r.add_argument('--max-credits', type=int, required=True)
    r.add_argument('--out', type=Path, required=True)
    r.add_argument('--before-signature', default=None,
                   help='anchor near slot_max for the getSignaturesForAddress listing')
    r.add_argument('--segment-pages', type=int, default=50)
    v = sub.add_parser('verify', help='check an archive against its manifest; no network')
    v.add_argument('--out', type=Path, required=True)
    x = sub.add_parser('export', help='per-pool archives + MANIFEST for the L1 replay; no network')
    x.add_argument('--out', type=Path, required=True, help='verified program-window run directory')
    x.add_argument('--pools-dir', type=Path, required=True)
    x.add_argument('--entry-cutoff-gap-slots', type=int, default=160,
                   help='entry_cutoff_slot = slot_max - this gap (minimum 79)')
    x.add_argument('--sol-usd-series', type=Path, default=None,
                   help='series file built by the sol-usd-series command')
    sm = sub.add_parser('sample', help='grid-sampled SOL/USDC pool collection; dry run unless '
                                      '--network')
    sm.add_argument('--network', action='store_true', help='actually send read-only requests')
    sm.add_argument('--endpoint-env', default='RUGGER_BACKFILL_RPC_URL')
    sm.add_argument('--pool', required=True, help='the SOL/USDC pool (window address)')
    sm.add_argument('--sol-vault', required=True)
    sm.add_argument('--usdc-vault', required=True)
    sm.add_argument('--slot-min', type=int, required=True)
    sm.add_argument('--slot-max', type=int, required=True)
    sm.add_argument('--grid-seconds', type=int, choices=(2, 4), default=4)
    sm.add_argument('--costs', default='helius-conservative')
    sm.add_argument('--max-requests', type=int, required=True)
    sm.add_argument('--max-credits', type=int, required=True)
    sm.add_argument('--expected-tx-per-slot', type=float, default=5.0,
                    help='volume assumption used only by the dry-run estimate')
    sm.add_argument('--out', type=Path, required=True)
    sm.add_argument('--before-signature', default=None)
    s2 = sub.add_parser('sol-usd-series',
                        help='causal SOL/USD series from a SOL/USDC pool window; no network')
    s2.add_argument('--out', type=Path, required=True, help='verified window of the pool address')
    s2.add_argument('--pool', required=True)
    s2.add_argument('--sol-vault', required=True)
    s2.add_argument('--usdc-vault', required=True)
    s2.add_argument('--series-out', type=Path, required=True)
    s2.add_argument('--label', default='COLLECTED', choices=('COLLECTED', 'SYNTHETIC_TEST_FIXTURE'))
    args = parser.parse_args(argv)

    def emit(obj):
        print(json.dumps(obj, indent=1, sort_keys=True), file=out)

    try:
        if args.command == 'verify':
            result = verify(args.out)
            emit(result)
            return 0 if result['ok'] else 4
        if args.command == 'export':
            from bot.market.backfill_export import export_pools
            export = export_pools(args.out, args.pools_dir,
                                  entry_cutoff_gap_slots=args.entry_cutoff_gap_slots,
                                  sol_usd_series=args.sol_usd_series)
            emit({'pools_exported': len(export['pools']), 'skipped': len(export['skipped']),
                  'active_near_window_end': sum(p['active_near_window_end']
                                                for p in export['pools']),
                  'entry_cutoff_slot': export['entry_cutoff_slot'],
                  'window_slot_max': export['window_slot_max'],
                  'sol_usd_series': export['sol_usd_series']})
            return 0
        if args.command == 'sample':
            from bot.market.sol_usd_sample import SampledBackfill, plan_sample
            window = Window(args.pool, args.slot_min, args.slot_max)
            costs = load_costs(args.costs)
            estimate = plan_sample(window, costs, expected_tx_per_slot=args.expected_tx_per_slot,
                                   grid_seconds=args.grid_seconds)
            if not args.network:
                emit({'dry_run': True, 'requests_sent': 0, 'estimate': estimate,
                      'caps': {'max_requests': args.max_requests,
                               'max_credits': args.max_credits},
                      'message': 'no request sent; add --network to run (owner decision)'})
                return 0
            url = endpoint_from_env(args.endpoint_env, environ)
            budget = CreditBudget(args.max_requests, args.max_credits, costs,
                                  ledger=args.out / 'spend.json')
            job = SampledBackfill(open_rpc(url, budget, opener=opener), window, args.out,
                                  pool=args.pool, sol_vault=args.sol_vault,
                                  usdc_vault=args.usdc_vault, grid_seconds=args.grid_seconds,
                                  endpoint=endpoint_label(url),
                                  before_signature=args.before_signature)
            manifest = job.run()
            emit({k: manifest[k] for k in ('complete', 'stopped_by', 'totals', 'budget',
                                            'endpoint', 'sampling')})
            return 0 if manifest['complete'] else 3
        if args.command == 'sol-usd-series':
            from bot.market.sol_usd_collect import build_series, density, write_series
            document = build_series(args.out, pool=args.pool, sol_vault=args.sol_vault,
                                    usdc_vault=args.usdc_vault, label=args.label)
            emit(dict(write_series(document, args.series_out), density=density(document)))
            return 0
        window =Window(args.address, args.slot_min, args.slot_max)
        costs = load_costs(args.costs)
        if args.command == 'plan':
            emit(plan(window, costs, expected_tx_per_slot=args.expected_tx_per_slot,
                      bodies=args.bodies, check=not args.no_check))
            return 0
        if not args.network:
            emit({'dry_run': True, 'requests_sent': 0,
                  'message': 'no request sent; add --network to run (owner decision)',
                  'window': window.to_json(), 'bodies': args.bodies,
                  'caps': {'max_requests': args.max_requests, 'max_credits': args.max_credits}})
            return 0
        url = endpoint_from_env(args.endpoint_env, environ)
        # spend.json is written before every send: caps stay cumulative after any
        # failure or interrupt, and a resume cannot switch to a cheaper cost table.
        budget = CreditBudget(args.max_requests, args.max_credits, costs,
                              ledger=args.out / 'spend.json')
        rpc = open_rpc(url, budget, opener=opener)
        job = Backfill(rpc, window, args.out, bodies=args.bodies, check=not args.no_check,
                       segment_pages=args.segment_pages, endpoint=endpoint_label(url),
                       before_signature=args.before_signature)
        manifest = job.run()
        emit({k: manifest[k] for k in ('complete', 'stopped_by', 'totals', 'reconciliation',
                                        'budget', 'endpoint')})
        return 0 if manifest['complete'] else 3
    except (BackfillError, RpcError) as exc:
        # Committed segments stay on disk: the same command resumes after the failure.
        emit({'error': str(exc)})
        return 2
