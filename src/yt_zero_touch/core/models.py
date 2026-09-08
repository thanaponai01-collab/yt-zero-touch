"""
Core Domain Models & Constants for YT-DLP Zero-Touch.
=====================================================
Shared data structures, policies, presets, and utility parsers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt_zero_touch.core.failures import FailureClass

# ---------------------------------------------------------------------------
# Constants & Formats
# ---------------------------------------------------------------------------

FORMAT_VIDEO = "bestvideo+bestaudio/best"
FORMAT_AUDIO = "bestaudio/best"

QUALITY_PRESETS: dict[str, str] = {
    "Best":   "bestvideo+bestaudio/best",
    "4K":     "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1080p":  "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":   "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":   "bestvideo[height<=480]+bestaudio/best[height<=480]",
}

URL_RE = re.compile(
    r'https?://(?:www\.)?'
    r'[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}'
    r'\b[-a-zA-Z0-9()@:%_\+.~#?&/=]*'
)

IMAGE_HOSTS = (
    "instagram.com", "twitter.com", "x.com", "reddit.com", "redd.it",
    "pinterest.com", "pin.it", "flickr.com", "imgur.com", "tumblr.com",
    "deviantart.com", "artstation.com", "weibo.com", "pixiv.net",
    "facebook.com", "fbcdn.net", "threads.net",
)


def is_image_host(url: str) -> bool:
    """True if the URL is on a host where gallery-dl handles photos/galleries."""
    return any(h in url for h in IMAGE_HOSTS)


# ---------------------------------------------------------------------------
# Section Trim Parser
# ---------------------------------------------------------------------------

def _parse_timestamp(t: str) -> float | None:
    """Parse 'SS', 'MM:SS', or 'HH:MM:SS' (fractions allowed) into seconds."""
    t = t.strip()
    if not t:
        return None
    try:
        parts = [float(p) for p in t.split(":")]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_sections(spec: str | None) -> list[tuple[float, float]] | None:
    """Turn a human time-range spec into (start, end) second pairs for yt-dlp.

    Accepts e.g. '10:00-20:00', '*00:10-01:30', '90-120', and
    comma-separated multiples '0:30-1:00, 2:00-2:30'.
    """
    if not spec:
        return None
    spec = spec.strip().lstrip("*").strip()
    ranges: list[tuple[float, float]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk or "-" not in chunk:
            continue
        start_s, end_s = chunk.split("-", 1)
        start = _parse_timestamp(start_s)
        end   = _parse_timestamp(end_s)
        start = 0.0 if start is None else start
        if end is None or end <= start:
            continue
        ranges.append((start, end))
    return ranges or None


# ---------------------------------------------------------------------------
# Output template selection
# ---------------------------------------------------------------------------

_SLUG_BAD = re.compile(r"[^\w\s-]")
_SLUG_WS  = re.compile(r"\s+")


def build_output_template(idx: int, url: str, resolved: str, total: int, pad: int) -> str:
    """Pick a yt-dlp output template for one item."""
    is_stream = resolved != url and (
        ".m3u8" in resolved or (".mp4" in resolved and "?" in resolved)
    )
    num_prefix = f"{idx:0{pad}d} - " if total > 1 else ""
    if is_stream:
        slug = _SLUG_BAD.sub("", url.rstrip("/").split("/")[-1])
        slug = _SLUG_WS.sub("-", slug)[:80] or "video"
        return f"{num_prefix}{slug}.%(ext)s"
    return f"{num_prefix}%(title).100B - [%(id)s].%(ext)s"


# ---------------------------------------------------------------------------
# Batch Policies & Results
# ---------------------------------------------------------------------------

_DEFAULT_RETRY_MAX = 3
_DEFAULT_RETRY_DELAYS = (5, 15, 30)


@dataclass
class BatchPolicy:
    out_dir: Path
    audio_only: bool = False
    gallery: bool = False          # Photos mode — route every URL to gallery-dl
    fmt: str | None = None
    sub_langs: list[str] = field(default_factory=list)
    cookie_file: Path | None = None
    browser_cookie: str | None = None
    force: bool = False
    write_metadata: bool = False
    playlist: bool = False
    sections: str | None = None    # e.g. "10:00-20:00" — trim to a clip
    target_codec: str = "h264"       # merge target: "h264" | "prores"
    max_workers: int = 3
    retry_max: int = _DEFAULT_RETRY_MAX
    retry_delays: tuple[int, ...] = _DEFAULT_RETRY_DELAYS


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    # (idx, url, FailureClass | None) for each failed item
    failures: list = field(default_factory=list)


@dataclass
class DownloadOutcome:
    """Result of one (retried) download: success plus the classified cause on failure."""
    ok: bool
    failure: FailureClass | None = None

    def __bool__(self) -> bool:
        return self.ok
