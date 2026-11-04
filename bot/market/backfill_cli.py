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
    args = parser.parse_args(argv)

    def emit(obj):
        print(json.dumps(obj, indent=1, sort_keys=True), file=out)

    try:
        if args.command == 'verify':
            result = verify(args.out)
            emit(result)
            return 0 if result['ok'] else 4
        window = Window(args.address, args.slot_min, args.slot_max)
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
        used = {'requests': 0, 'credits': 0}
        state_path = args.out / 'state.json'
        if state_path.exists():
            used = json.loads(state_path.read_text()).get('budget_used', used)
        budget = CreditBudget(args.max_requests, args.max_credits, costs,
                              used_requests=used['requests'], used_credits=used['credits'])
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
