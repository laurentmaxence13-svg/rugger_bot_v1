#!/usr/bin/env python3
"""Offline HISTORICAL_REPLAY of the Master scorers on the committed LaunchLab pools.

No network, no keys, no orders. Cycles are research only: never PAPER-ledger
entries, Master-gate evidence or operational Master trades.

  python -B tools/historical_research_replay.py
  python -B tools/historical_research_replay.py --sol-usd 150 \
      --sol-usd-provenance ASSUMED_DECLARED --exclude-launchlab-vault --out bundle.json
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.p4.historical_research_replay import ARMS, ExitOptions, ReplayParams, run_replay  # noqa: E402
from bot.p4.sol_usd_series import load_series  # noqa: E402

DEFAULT_FIXTURES = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'


def summary_lines(bundle, top=6):
    flags = bundle['flags']
    yield (f"{bundle['category']} {bundle['schema']}  sol_usd={flags.get('sol_usd_source') or flags['sol_usd']} "
           f"({flags['sol_usd_provenance']})  exclude_launchlab_vault="
           f"{bundle['params']['exclude_launchlab_vault']}  asof_inputs_causal={flags['asof_inputs_causal']}")
    for pool in bundle['pools']:
        arms = '  '.join(f"{arm}={pool['arms'][arm]['outcome']}" for arm in ARMS)
        migrated = (f"  migrated_at_slot={pool['migration']['boundary_slot']}" if 'migration' in pool else '')
        yield (f"  {pool['pool'][:8]} trades={pool['trades']} signed_creator="
               f"{pool['signed_creator_verified']} ({pool['signed_creator_reason']})  {arms}{migrated}")
    for row in bundle.get('excluded_pools', ()):
        yield f"  EXCLUDED {row['pool'][:8]} ({row['file']}): {', '.join(row['reasons'])}"
    for arm in ARMS:
        totals = bundle['totals'][arm]
        reasons = ', '.join(f'{k}={v}' for k, v in list(totals['blocking_reasons'].items())[:top])
        yield (f"  [{arm}] decisions={totals['decisions']} entries={totals['entries']} "
               f"outcomes={totals['outcomes']} pnl_lamports={totals['pnl_lamports']}")
        yield f'    top blocking reasons: {reasons or "-"}'
    yield f"params_sha256 {bundle['params_sha256']}"
    yield f"bundle_sha256 {bundle['bundle_sha256']}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--fixtures', type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument('--sol-usd', type=float, default=None,
                        help='declared SOL/USD rate; absent from the fixtures, never verified')
    parser.add_argument('--sol-usd-provenance', default=None,
                        help='required with --sol-usd, e.g. ASSUMED_DECLARED')
    parser.add_argument('--sol-usd-series', type=Path, default=None,
                        help='rugger-sol-usd-series-v1 file (JSON or .gz); exclusive with --sol-usd')
    parser.add_argument('--exclude-launchlab-vault', action='store_true',
                        help='leave the curve vault authority out of holder statistics')
    parser.add_argument('--trailing-stop', action='store_true',
                        help="also exit on the scorer plan's trailing stop (off by default)")
    parser.add_argument('--max-hold', action='store_true',
                        help="also exit after the scorer plan's hold_seconds (off by default)")
    parser.add_argument('--clock-horizon', action='store_true',
                        help='enforce exit_horizon_ms by the clock, even on a silent curve (off by default)')
    parser.add_argument('--out', type=Path, default=None, help='write the bundle JSON here')
    args = parser.parse_args(argv)
    try:
        params = ReplayParams(sol_usd=args.sol_usd, sol_usd_provenance=args.sol_usd_provenance,
                              exclude_launchlab_vault=args.exclude_launchlab_vault)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        series = load_series(args.sol_usd_series) if args.sol_usd_series else None
        bundle = run_replay(args.fixtures, params, series,
                            ExitOptions(trailing_stop=args.trailing_stop, max_hold=args.max_hold,
                                        clock_horizon=args.clock_horizon))
    except ValueError as exc:
        parser.error(str(exc))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(bundle, sort_keys=True, indent=1, allow_nan=False) + '\n',
                            encoding='utf-8')
    for line in summary_lines(bundle):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
