"""Five-call READ-ONLY public mainnet program snapshot, never code approval."""
import sys

from bot.live.public_program_observer import main

if __name__ == "__main__":
    sys.exit(main())
