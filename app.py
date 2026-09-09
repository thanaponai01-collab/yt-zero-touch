"""
YT-DLP Zero-Touch — Desktop App Entrypoint
==========================================
Launches the modular desktop app from src/yt_zero_touch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from yt_zero_touch.ui.app import App, main
from yt_zero_touch.ui.theme import COLORS

if __name__ == "__main__":
    main()
