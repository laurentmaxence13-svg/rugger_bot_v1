#!/usr/bin/env python3
"""CLI for exactly one preregistered WSOL-mint RPC health read."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.p3.rpc_health import main

if __name__ == '__main__':
    main()
