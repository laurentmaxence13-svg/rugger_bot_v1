"""CLI shim for the offline P3 liquidity audit; core lives under bot.p3."""
from bot.p3.replay_liquidity_gate import main


if __name__ == "__main__":
    main()
