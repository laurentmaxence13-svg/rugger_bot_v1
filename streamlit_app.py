"""Rugger Wallet: hosted read-only PAPER dashboard entrypoint.

Cloud instance has no access to the user's Windows SQLite database.
It only displays explicitly uploaded evidence and a clearly labelled demo.
"""
from bot.dashboard.app import main

if __name__ == "__main__":
    main()
