"""Unified PAPER entry point: reproducible demo, supervised paper, read-only report."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys


def _offline_policy(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise RuntimeError('Offline command forbids network access')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        name = Path(os.fsdecode(args[0])).name
        if name == '.env' or name.startswith('.env.'):
            raise RuntimeError('Offline command forbids reading .env')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='Complete synthetic cycle, no network or secrets')
    demo.add_argument('--output', type=Path, required=True, help='New dedicated directory')
    economic = sub.add_parser('economic-demo', help='Atomic inventory and full/partial/refused simulated exits, offline')
    economic.add_argument('--output', type=Path, required=True, help='New dedicated directory')
    report = sub.add_parser('report', help='Read an existing PAPER database without migration')
    report.add_argument('--db', type=Path, required=True)
    report.add_argument('--output', type=Path, required=True, help='New JSON report file')
    report.add_argument('--data-kind', choices=['unknown', 'synthetic', 'market_observation', 'mixed'], default='unknown')
    sub.add_parser('operations', help='Offline PAPER health and consistent local backup', add_help=False)
    sub.add_parser('experiment', help='Offline frozen strategy comparison on a registered corpus', add_help=False)
    paper = sub.add_parser('paper', help='Supervised scanner + existing PAPER engine', add_help=False)
    paper.add_argument('--network', action='store_true', help='Explicit network opt-in; use a registered bounded protocol')
    args, extra = parser.parse_known_args(argv)
    if args.command in ('operations', 'experiment'):
        os.environ['RUGGER_NO_DOTENV'] = '1'
        sys.addaudithook(_offline_policy)
        if args.command == 'operations':
            from bot.operations import main as offline_main
        else:
            from bot.p4_experiment import main as offline_main
        return offline_main(extra)
    if args.command == 'paper':
        if not args.network and '--help' not in extra and '-h' not in extra:
            parser.error('paper requires --network and a bounded registered observation protocol')
        if '--help' in extra or '-h' in extra:
            os.environ['RUGGER_NO_DOTENV'] = '1'
            sys.addaudithook(_offline_policy)
        from bot.analyser.paper_engine import main as engine_main
        if not any(flag.split('=', 1)[0] in ('--model', '--shadow-final', '--shadow-baseline') for flag in extra):
            extra = ['--shadow-final', *extra]
        return engine_main(extra)
    if extra:
        parser.error('Unexpected arguments: ' + ' '.join(extra))
    os.environ['RUGGER_NO_DOTENV'] = '1'
    sys.addaudithook(_offline_policy)
    if args.command == 'economic-demo':
        from bot.economic_demo import run_economic_demo
        result = asyncio.run(run_economic_demo(args.output))
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return
    if args.command == 'demo':
        from bot.functional_demo import run_demo
        result = asyncio.run(run_demo(args.output))
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return
    if (not args.db.is_file() or args.db.is_symlink() or args.output.exists()
            or args.output.suffix != '.json' or args.db.resolve() == args.output.resolve()):
        parser.error('Existing regular database and new separate JSON output required')
    from bot.analyser.functional_report import build_functional_report
    from bot.analyser.artifacts import atomic_write_json
    con = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        result = build_functional_report(con, data_kind=args.data_kind)
    finally:
        con.close()
    atomic_write_json(args.output, result, indent=2, sort_keys=True, allow_nan=False)
    print(str(args.output))


if __name__ == '__main__':
    main()
