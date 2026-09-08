"""
YT-DLP Zero-Touch — Watcher CLI Entrypoint
===========================================
Forwards to src/yt_zero_touch.ui.cli.watcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from yt_zero_touch.ui.cli.watcher import (
    POLL_INTERVAL,
    Downloader,
    _download_worker,
    _harvest_completed,
    is_known_domain,
    main,
    read_urls_from_file,
    watch,
)

if __name__ == "__main__":
    main()
