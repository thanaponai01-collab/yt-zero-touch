"""Subprocess keyword arguments shared by every child process the app starts.

When the app runs without a console (``pythonw app.pyw``), Windows gives each
console child such as ffmpeg, ffprobe, gallery-dl or pip its own black window.
CREATE_NO_WINDOW stops that. yt-dlp already hides the ffmpeg it starts itself.
"""

from __future__ import annotations

import os
import subprocess

NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
)
