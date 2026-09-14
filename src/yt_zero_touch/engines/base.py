"""
Shared engine types.
====================
The one thing all three adapters (yt-dlp, gallery-dl, gdown) genuinely have
in common: how they report progress back to whichever front end invoked them.

There is deliberately no BaseEngine ABC here. Routing between the adapters is
a handful of inline branches in `download_ytdlp` — gallery mode, a Drive id,
an image host yt-dlp found nothing on — driven by facts about the URL and the
request, not by polymorphism. An ABC over three adapters that nothing ever
dispatched through was documentation pretending to be code.
"""

from __future__ import annotations

from typing import Callable

LogFn = Callable[[str, str], None]
