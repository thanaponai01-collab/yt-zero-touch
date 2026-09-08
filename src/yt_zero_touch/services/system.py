"""
System & Environment Utilities.
================================
Environment verification, external tool presence (ffmpeg, deno), disk space.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def find_deno() -> str | None:
    """Find deno executable on PATH or in default user locations (~/.deno/bin)."""
    found = shutil.which("deno")
    if found:
        return found
    candidate = Path.home() / ".deno" / "bin" / ("deno.exe" if os.name == "nt" else "deno")
    return str(candidate) if candidate.exists() else None


DENO_PATH = find_deno()


def check_ffmpeg() -> bool:
    """Check if ffmpeg is executable."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except Exception:
        return False


def check_disk_space(out_dir: Path | str, min_free_gb: float = 1.0) -> tuple[bool, float]:
    """Return (has_enough, free_gb). Returns (True, inf) if check cannot run."""
    try:
        free = shutil.disk_usage(Path(out_dir)).free / (1024 ** 3)
        return free >= min_free_gb, free
    except Exception:
        return True, float("inf")


def check_dependencies(yt_dlp_ok: bool = True, gallery_dl_ok: bool = True) -> bool:
    """Check for yt-dlp, ffmpeg, gallery-dl. Prints warnings. Returns False if yt-dlp is missing."""
    ok = True
    if not yt_dlp_ok and shutil.which("yt-dlp") is None:
        print("[ERR ] yt-dlp not found. Install with: pip install yt-dlp")
        ok = False
    if not check_ffmpeg():
        print("[WARN] ffmpeg not found — video merging and audio conversion will fail.")
        print("[WARN] Install from: https://ffmpeg.org/download.html")
    if not gallery_dl_ok:
        print("[WARN] gallery-dl not found — photo/carousel downloads are disabled.")
    return ok
