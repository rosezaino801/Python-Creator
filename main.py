"""
Entry point for Render (and any other host that runs `python main.py`).

Adds the telegram-bot directory to the path so the bot module can be
imported cleanly, then hands off to the bot's own main() which starts
the polling loop and blocks indefinitely — keeping the process alive.
"""

import os
import sys

# Make `telegram-bot/` importable as a plain package path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "telegram-bot"))

from bot import main  # noqa: E402  (import after sys.path tweak is intentional)

if __name__ == "__main__":
    main()
