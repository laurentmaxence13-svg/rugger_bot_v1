#!/usr/bin/env python3
"""Run the bounded read-only CPMM preflight; see bot.live.readonly_cli.

This is a thin entrypoint so the production CLI itself is exercised by the
offline test harness, which intentionally copies only bot/ and tests/.
"""
from pathlib import Path
import os
import sys

os.environ["RUGGER_NO_DOTENV"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from bot.live.readonly_cli import main


if __name__=="__main__":
    raise SystemExit(main())
