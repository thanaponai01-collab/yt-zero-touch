"""
Self-update Service — Keep extractors fresh.
=============================================
Throttled updater for yt-dlp nightly and gallery-dl.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

LogFn = Callable[[str, str], None]


def _print_log(msg: str, tag: str = "info") -> None:
    prefix = {"warn": "[WARN]", "error": "[ERR ]", "success": "[OK  ]"}.get(tag, "[    ]")
    print(f"{prefix} {msg}")


YTDLP_NIGHTLY = (
    "yt-dlp @ https://github.com/yt-dlp/yt-dlp-nightly-builds"
    "/releases/latest/download/yt-dlp.tar.gz"
)


def get_pkg_version(pkg: str) -> str:
    """Return installed version of a pip package or 'unknown'."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for ln in r.stdout.splitlines():
            if ln.lower().startswith("version:"):
                return ln.split(":", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def update_tools(
    log: LogFn = _print_log,
    *,
    include_gallery: bool = True,
    gallery_ok: bool = True,
    timeout: int = 180,
) -> bool:
    """Update yt-dlp (nightly) and gallery-dl.

    Returns True if any package changed version.
    """
    changed = False
    jobs: list[tuple[str, list[str]]] = [
        ("yt-dlp", ["-U", "--force-reinstall", "--no-deps", YTDLP_NIGHTLY]),
    ]
    if include_gallery and gallery_ok:
        jobs.append(("gallery-dl", ["-U", "gallery-dl"]))

    for name, args in jobs:
        before = get_pkg_version(name)
        log(f"Updating {name}…", "info")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except Exception as exc:
            log(f"  {name} update failed: {exc}", "error")
            continue
        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            if "WinError 32" in out or "being used by another process" in out:
                log(f"  {name} files are locked — close the app and update from a terminal.", "error")
            else:
                for line in out.strip().splitlines()[-8:]:
                    log(f"  {line}", "error")
            continue
        after = get_pkg_version(name)
        if after != before:
            log(f"  {name}: {before} → {after}", "success")
            changed = True
        else:
            log(f"  {name} already current ({after}).", "success")
    return changed


class ToolUpdateScheduler:
    """Handles weekly background checks so extractors remain fresh."""

    def __init__(self, stamp_path: Path | str, interval_days: int = 7):
        self.stamp_path = Path(stamp_path)
        self.interval_days = interval_days

    def stamp(self) -> None:
        try:
            self.stamp_path.write_text(str(int(time.time())))
        except Exception:
            pass

    def should_check(self) -> bool:
        try:
            last = float(self.stamp_path.read_text().strip())
        except Exception:
            last = 0.0
        return (time.time() - last) >= (self.interval_days * 86400)
