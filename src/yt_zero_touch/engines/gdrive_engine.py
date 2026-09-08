"""
Google Drive Engine adapter (using gdown).
===========================================
Handles Google Drive share links, bypassing virus scan prompts for large files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_zero_touch.engines.base import BaseEngine, LogFn

try:
    import gdown as _gdown
    GDOWN_OK = True
except ImportError:
    _gdown = None  # type: ignore
    GDOWN_OK = False

_GDRIVE_RE = re.compile(
    r'drive\.google\.com/(?:file/d/|open\?.*?id=|uc\?.*?id=)([a-zA-Z0-9_-]+)'
)


def extract_gdrive_id(url: str) -> str | None:
    """Extract a Google Drive file ID from any Drive share URL."""
    m = _GDRIVE_RE.search(url)
    if m:
        return m.group(1)
    qs = parse_qs(urlparse(url).query)
    return (qs.get("id") or [None])[0]


def download_gdrive(file_id: str, out_dir: Path, log: LogFn) -> bool:
    """Download a Google Drive file by ID using gdown."""
    if not GDOWN_OK:
        log("gdown not installed — run: pip install gdown", "error")
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    gdrive_url = f"https://drive.google.com/uc?id={file_id}"
    log(f"Google Drive file ID: {file_id}", "info")
    try:
        output = _gdown.download(
            gdrive_url,
            output=str(out_dir) + "/",
            quiet=False,
        )
        if output:
            log(f"Saved: {Path(output).name}", "success")
            return True
        log("gdown returned no output path", "error")
        return False
    except Exception as exc:
        log(f"gdown error: {exc}", "error")
        return False


class GDriveEngine(BaseEngine):
    def can_handle(self, url: str, **kwargs: Any) -> bool:
        return extract_gdrive_id(url) is not None

    def download(self, url: str, out_dir: Path, log: LogFn, **kwargs: Any) -> bool:
        file_id = extract_gdrive_id(url)
        if not file_id:
            return False
        return download_gdrive(file_id, out_dir, log)
