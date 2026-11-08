#!/usr/bin/env python3
"""Entry point of the bounded LaunchLab window backfill (see bot/market/backfill_cli.py).

Dry run by default: no request is sent without --network.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.market.backfill_cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
