"""
YT-DLP Zero-Touch — Reusable Download Skill
============================================
Drop this file into any project to get smart URL resolution + yt-dlp download.

Quick start:
    from ytdlp_skill import download

    download("https://youtube.com/watch?v=...", out_dir="./downloads")
    download("https://formula1.com/...", out_dir="./downloads", cookie_file="cookies.txt")
    download("https://vimeo.com/...", audio_only=True)

    # Batch with a shared Playwright browser (faster for multiple unknown URLs)
    from ytdlp_skill import Downloader
    with Downloader(cookie_file="cookies.txt") as dl:
        for url in urls:
            dl.download(url, out_dir="./downloads")

Dependencies:
    pip install yt-dlp playwright
    playwright install chromium
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Callable

# URL resolution (F1/Brightcove/Outseta/headless-browser interception) lives in
# resolver.py so this downloader stays generic and reusable. Re-exported here so
# existing callers can keep importing them from ytdlp_skill.
from resolver import (
    resolve_url,
    _launch_temp_browser,
    _PLAYWRIGHT_OK,
    _BROWSER_ARGS,
    _KNOWN_DOMAINS,
    LogFn,
    _print_log,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # _PLAYWRIGHT_OK (from resolver) is already False

try:
    import yt_dlp as _yt_dlp
    _YT_DLP_API_OK = True
except ImportError:
    _YT_DLP_API_OK = False

try:
    import gdown as _gdown
    _GDOWN_OK = True
except ImportError:
    _GDOWN_OK = False

# ---------------------------------------------------------------------------
# Public constants — override before calling download() if needed
# ---------------------------------------------------------------------------

FORMAT_VIDEO = (
    "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]"
    "/bestvideo[ext=mp4][vcodec!^=av01]+bestaudio[ext=m4a]"
    "/bestvideo[vcodec!^=av01]+bestaudio[ext=m4a]"
    "/bestvideo[vcodec!^=av01]+bestaudio"
    "/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
    "/bestvideo+bestaudio"
    "/best"
)
FORMAT_AUDIO = "bestaudio/best"

# Quality presets — prefer H.264 + AAC (Premiere-ready) at each resolution.
# Falls back to any codec so the download always succeeds, then the merger
# step re-encodes audio to AAC regardless of what was selected.
QUALITY_PRESETS: dict[str, str] = {
    "Best": (
        "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]"
        "/bestvideo[vcodec^=avc1]+bestaudio"
        "/bestvideo+bestaudio/best"
    ),
    "4K": (
        "bestvideo[height<=2160][vcodec^=avc1]+bestaudio[ext=m4a]"
        "/bestvideo[height<=2160][vcodec^=avc1]+bestaudio"
        "/bestvideo[height<=2160]+bestaudio/best[height<=2160]"
    ),
    "1080p": (
        "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]"
        "/bestvideo[height<=1080][vcodec^=avc1]+bestaudio"
        "/bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    ),
    "720p": (
        "bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]"
        "/bestvideo[height<=720][vcodec^=avc1]+bestaudio"
        "/bestvideo[height<=720]+bestaudio/best[height<=720]"
    ),
    "480p": (
        "bestvideo[height<=480][vcodec^=avc1]+bestaudio[ext=m4a]"
        "/bestvideo[height<=480]+bestaudio/best[height<=480]"
    ),
}

# FFmpeg args applied during the video+audio merge step.
# -c:v copy  → keep H.264 as-is (no re-encode, fast)
# -c:a aac   → always output AAC audio (Opus/Vorbis → AAC if needed)
# -b:a 192k  → good broadcast-quality audio bitrate
# -movflags +faststart → move MP4 index to front for instant Premiere import
PREMIERE_MERGE_ARGS = [
    "-c:v", "copy",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
]

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_GDRIVE_RE = re.compile(
    r'drive\.google\.com/(?:file/d/|open\?.*?id=|uc\?.*?id=)([a-zA-Z0-9_-]+)'
)


# ---------------------------------------------------------------------------
# Core download functions
# ---------------------------------------------------------------------------

def _gdrive_file_id(url: str) -> "str | None":
    """Extract a Google Drive file ID from any Drive share URL."""
    m = _GDRIVE_RE.search(url)
    if m:
        return m.group(1)
    # Also handle ?id=FILE_ID at top-level (open?id= / uc?id=)
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(url).query)
    return (qs.get("id") or [None])[0]


def _download_gdrive(file_id: str, out_dir: Path, log: LogFn) -> bool:
    """Download a Google Drive file by ID using gdown."""
    if not _GDOWN_OK:
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


def download(
    url: str,
    out_dir: "Path | str" = "./downloads",
    *,
    audio_only: bool = False,
    playlist: bool = False,
    write_metadata: bool = True,
    sub_langs: "list[str] | None" = None,
    cookie_file: "Path | str | None" = None,
    browser_cookie: "str | None" = None,
    force: bool = False,
    fmt: "str | None" = None,
    out_template: "str | None" = None,
    log: LogFn = _print_log,
    progress_hook: "Callable[[dict], None] | None" = None,
    pre_resolved: bool = False,
    _browser=None,
) -> bool:
    """Download a single URL (or full playlist).

    Args:
        url:            Video/playlist page URL or direct stream URL.
        out_dir:        Destination folder. Created if absent.
        audio_only:     Extract audio only (opus).
        playlist:       Download all items in a playlist (default: single video only).
        write_metadata: Write a .info.json sidecar next to each file.
        sub_langs:      Subtitle language codes, e.g. ["en", "th"].
        cookie_file:    Path to Netscape cookies.txt.
        browser_cookie: Browser name for yt-dlp's --cookies-from-browser (chrome/firefox/edge/brave).
        force:          Re-download even if file already exists.
        fmt:            Override yt-dlp format string.
        out_template:   Override yt-dlp -o template (relative to out_dir).
        log:            Callable(msg, tag) for progress output.
        progress_hook:  Optional yt-dlp progress_hook (called with dict containing
                        status/_percent_str/_speed_str/_eta_str/filename).
        pre_resolved:   If True, skip resolve_url() — caller already resolved.
        _browser:       Pass an open Playwright browser to reuse (advanced).

    Returns:
        True on success, False on failure.
    """
    out_dir     = Path(out_dir)
    cookie_file = Path(cookie_file) if cookie_file else None
    sub_langs   = sub_langs or []
    fmt         = fmt or (FORMAT_AUDIO if audio_only else FORMAT_VIDEO)
    # Playlist-aware output template: organise into a sub-folder per playlist
    tpl = out_template or (
        "%(playlist_title)s/%(playlist_index)02d - %(title).80B - [%(id)s].%(ext)s"
        if playlist else
        "%(title).100B - [%(id)s].%(ext)s"
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    # Google Drive: use gdown (handles large files + virus-scan bypass)
    gdrive_id = _gdrive_file_id(url)
    if gdrive_id:
        ok = _download_gdrive(gdrive_id, out_dir, log)
        if ok:
            return True
        log("gdown failed — falling back to yt-dlp", "warn")

    if pre_resolved:
        resolved = url
    else:
        log(f"Resolving: {url[:80]}", "info")
        resolved = resolve_url(url, cookie_file=cookie_file, log=log, _browser=_browser)

    outtmpl = out_dir / tpl

    if not _YT_DLP_API_OK:
        log("yt-dlp is not installed — run: pip install yt-dlp", "error")
        return False
    return _download_api(
        resolved, outtmpl, fmt, audio_only, playlist, write_metadata,
        sub_langs, cookie_file, browser_cookie, force, log, progress_hook,
    )


def _download_api(
    resolved: str,
    outtmpl: Path,
    fmt: str,
    audio_only: bool,
    playlist: bool,
    write_metadata: bool,
    sub_langs: list,
    cookie_file: "Path | None",
    browser_cookie: "str | None",
    force: bool = False,
    log: LogFn = _print_log,
    extra_progress_hook: "Callable[[dict], None] | None" = None,
) -> bool:
    class _Logger:
        def debug(self, msg):
            if not msg.startswith("[debug]"):
                log(f"  {msg}", "muted")
        def info(self, msg):
            log(f"  {msg}", "muted")
        def warning(self, msg):
            log(f"  {msg}", "warn")
        def error(self, msg):
            log(f"  {msg}", "error")

    last_milestone = [-1]

    def _progress(d: dict):
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "").strip().rstrip("%")
            speed   = d.get("_speed_str", "?").strip()
            eta     = d.get("_eta_str", "?").strip()
            try:
                milestone = (int(float(pct_str)) // 10) * 10
            except (ValueError, TypeError):
                return
            if milestone != last_milestone[0]:
                last_milestone[0] = milestone
                log(f"  {milestone}%  {speed}  ETA {eta}", "success")
        elif d["status"] == "finished":
            log(f"  Finished: {Path(d.get('filename', '')).name}", "success")

    postprocessors = [
        {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
        {"key": "EmbedThumbnail", "already_have_thumbnail": False},
    ]
    if sub_langs:
        postprocessors.append(
            {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"}
        )
    if audio_only:
        postprocessors.insert(
            0,
            {"key": "FFmpegExtractAudio", "preferredcodec": "best", "preferredquality": "0"},
        )

    ydl_opts: dict = {
        "format":                        fmt,
        "outtmpl":                       str(outtmpl),
        "noplaylist":                    not playlist,
        "merge_output_format":           "opus" if audio_only else "mp4",
        "overwrites":                    force,
        "addmetadata":                   True,
        "writethumbnail":                True,
        "writeinfojson":                 write_metadata,
        "sponsorblock_mark":             "all",
        "restrictfilenames":             False,
        "windowsfilenames":              True,
        "ignoreerrors":                  True,
        "quiet":                         True,
        "logger":                        _Logger(),
        "progress_hooks":                [_progress] + ([extra_progress_hook] if extra_progress_hook else []),
        "postprocessors":                postprocessors,
        # Force H.264+AAC in the merge step so Premiere Pro can open the file
        # without re-encoding.  c:v copy keeps H.264 as-is; c:a aac converts
        # any Opus/Vorbis audio to AAC.  Skipped for audio-only downloads.
        **({"postprocessor_args": {"merger": PREMIERE_MERGE_ARGS}} if not audio_only else {}),
        "socket_timeout":                60,
        "concurrent_fragment_downloads": 4,
        "retries":                       10,
        "fragment_retries":              10,
        # tv_simply + android_vr don't require PO tokens or JS challenge solving
        # and avoid the DRM experiment that hits the regular tv client.
        # generic:impersonate retries with browser impersonation on Cloudflare 403s.
        "extractor_args":                {
            "youtube": {
                "player_client":     ["tv_simply", "android_vr", "android", "web"],
                "remote_components": ["ejs:github"],
            },
            "generic": {"impersonate": [""]},
        },
    }
    if sub_langs:
        ydl_opts.update({
            "writesubtitles":    True,
            "writeautomaticsub": True,
            "subtitleslangs":    sub_langs,
            "subtitlesformat":   "srt",
        })
    if cookie_file and cookie_file.exists():
        ydl_opts["cookiefile"] = str(cookie_file)
    elif browser_cookie:
        ydl_opts["cookiesfrombrowser"] = (browser_cookie,)

    try:
        with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret = ydl.download([resolved])
        return ret == 0
    except Exception as exc:
        log(f"  yt-dlp API error: {exc}", "error")
        return False


# ---------------------------------------------------------------------------
# Downloader context manager — reuses one Playwright browser across many URLs
# ---------------------------------------------------------------------------

class Downloader:
    """Context manager that keeps one Chromium instance alive for all downloads.

    Use this when downloading multiple unknown-site URLs to avoid relaunching
    the browser for every URL.

    Example:
        with Downloader(cookie_file="cookies.txt") as dl:
            for url in my_urls:
                dl.download(url, out_dir="./downloads")
    """

    def __init__(
        self,
        cookie_file: "Path | str | None" = None,
        log: LogFn = _print_log,
    ):
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.log         = log
        self._lock       = threading.Lock()
        self._pw         = None
        self._browser    = None

    def __enter__(self):
        if _PLAYWRIGHT_OK:
            self._pw      = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True, args=_BROWSER_ARGS)
        return self

    def __exit__(self, *_):
        with self._lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw:
                try:
                    self._pw.stop()
                except Exception:
                    pass
                self._pw = None

    def download(
        self,
        url: str,
        out_dir: "Path | str" = "./downloads",
        *,
        audio_only: bool = False,
        playlist: bool = False,
        write_metadata: bool = True,
        sub_langs: "list[str] | None" = None,
        cookie_file: "Path | str | None" = None,
        browser_cookie: "str | None" = None,
        force: bool = False,
        fmt: "str | None" = None,
        out_template: "str | None" = None,
        log: "LogFn | None" = None,
        progress_hook: "Callable[[dict], None] | None" = None,
        pre_resolved: bool = False,
    ) -> bool:
        """Same as module-level download(), but reuses the shared browser."""
        ck = cookie_file or self.cookie_file
        with self._lock:
            browser = self._browser
        return download(
            url,
            out_dir=out_dir,
            audio_only=audio_only,
            playlist=playlist,
            write_metadata=write_metadata,
            sub_langs=sub_langs,
            cookie_file=ck,
            browser_cookie=browser_cookie,
            force=force,
            fmt=fmt,
            out_template=out_template,
            log=log or self.log,
            progress_hook=progress_hook,
            pre_resolved=pre_resolved,
            _browser=browser,
        )


# ---------------------------------------------------------------------------
# History helpers (optional — track which URLs were already downloaded)
# ---------------------------------------------------------------------------

def load_history(history_file: "Path | str") -> set[str]:
    """Load a set of processed URLs from a JSON file."""
    p = Path(history_file)
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception as exc:
            backup = p.with_suffix(".bak.json")
            try:
                import shutil as _sh
                _sh.copy2(p, backup)
            except Exception:
                pass
            print(f"[WARN] History file corrupted ({exc}). "
                  f"Backed up to '{backup.name}', starting fresh.")
    return set()


def save_history(history_file: "Path | str", history: "set[str]"):
    """Persist the set of processed URLs to a JSON file."""
    p = Path(history_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(history), indent=2))


# ---------------------------------------------------------------------------
# System / environment helpers
# ---------------------------------------------------------------------------

def check_disk_space(
    out_dir: "Path | str",
    min_free_gb: float = 1.0,
) -> "tuple[bool, float]":
    """Return (has_enough, free_gb). Returns (True, inf) if the check cannot run."""
    import shutil as _sh
    try:
        free = _sh.disk_usage(Path(out_dir)).free / (1024 ** 3)
        return free >= min_free_gb, free
    except Exception:
        return True, float("inf")


def has_partial_files(out_dir: "Path | str") -> bool:
    """Return True if any yt-dlp .part files exist in out_dir."""
    try:
        return any(Path(out_dir).glob("*.part"))
    except Exception:
        return False


def check_dependencies() -> bool:
    """Check for yt-dlp and ffmpeg. Prints warnings. Returns False if yt-dlp is missing."""
    import shutil as _sh
    ok = True
    if not _YT_DLP_API_OK and _sh.which("yt-dlp") is None:
        print("[ERR ] yt-dlp not found. Install with: pip install yt-dlp")
        ok = False
    if _sh.which("ffmpeg") is None:
        print("[WARN] ffmpeg not found — video merging and audio conversion will fail.")
        print("[WARN] Install from: https://ffmpeg.org/download.html")
    return ok


# ---------------------------------------------------------------------------
# CLI — run as a script for quick one-off downloads
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="YT-DLP Zero-Touch skill")
    parser.add_argument("urls", nargs="+", help="Video URLs to download")
    parser.add_argument("-o", "--output",  default="./downloads")
    parser.add_argument("-c", "--cookies", default=None)
    parser.add_argument("--audio-only",    action="store_true")
    parser.add_argument("--sub-langs",     default=None,
                        help="Comma-separated lang codes, e.g. en,th")
    args = parser.parse_args()

    sub_langs = args.sub_langs.split(",") if args.sub_langs else []

    with Downloader(cookie_file=args.cookies) as dl:
        for url in args.urls:
            ok = dl.download(
                url,
                out_dir=args.output,
                audio_only=args.audio_only,
                sub_langs=sub_langs,
            )
            if not ok:
                sys.exit(1)
