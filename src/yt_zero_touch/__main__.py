"""
YT-DLP Zero-Touch Main Entrypoint.
==================================
Invoked when running `python -m yt_zero_touch`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure root workspace is discoverable if needed
src_root = Path(__file__).resolve().parent.parent
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))

from yt_zero_touch.ui.app import main

if __name__ == "__main__":
    main()
