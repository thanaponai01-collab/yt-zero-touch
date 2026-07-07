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

try:
    import gallery_dl as _gallery_dl  # noqa: F401  (presence check only)
    _GALLERY_DL_OK = True
except ImportError:
    _GALLERY_DL_OK = False

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

# Shared URL finder — used to pull links out of pasted text (app.py) and
# watched files (watcher.py) so the two front-ends don't drift apart.
URL_RE = re.compile(
    r'https?://(?:www\.)?'
    r'[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}'
    r'\b[-a-zA-Z0-9()@:%_\+.~#?&/=]*'
)

# Hosts where photos / carousels / image galleries are the point — gallery-dl
# is the right tool here (yt-dlp is video-only and will fail on a photo post).
# A URL on one of these hosts is routed to gallery-dl when the user picks
# "Photos" mode, and is used as a fallback target when yt-dlp finds no video.
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
# Section trim — grab just a clip out of a long video (--download-sections)
# ---------------------------------------------------------------------------

def _parse_timestamp(t: str) -> "float | None":
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


def parse_sections(spec: "str | None") -> "list[tuple[float, float]] | None":
    """Turn a human time-range spec into (start, end) second pairs for yt-dlp.

    Accepts things like '10:00-20:00', '*00:10-01:30', '90-120', and
    comma-separated multiples '0:30-1:00, 2:00-2:30'. A leading '*' (yt-dlp's
    own syntax) is tolerated. Returns None when nothing valid is found.
    """
    if not spec:
        return None
    spec = spec.strip().lstrip("*").strip()
    ranges: "list[tuple[float, float]]" = []
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


# Hosts that redirect anonymous visitors to a login page — for these, a logged-in
# browser session is effectively mandatory, so we auto-borrow browser cookies when
# the user hasn't supplied any.
_LOGIN_WALLED_HOSTS = ("instagram.com", "facebook.com", "threads.net")

# Order to try auto-extracting cookies from when none are supplied. First one that
# has a usable, logged-in session for the host wins.
_BROWSER_COOKIE_ORDER = ("chrome", "edge", "brave", "firefox", "opera", "vivaldi")

# gallery-dl's login-redirect / rate-limit signatures — used to give the user a
# clear, actionable message instead of a raw stack trace.
_GALLERY_LOGIN_SIGNS = (
    "login", "redirect", "403", "401", "not logged in",
    "no valid session", "checkpoint", "challenge",
)


def _is_login_walled(url: str) -> bool:
    return any(h in url for h in _LOGIN_WALLED_HOSTS)


def _detect_browsers() -> "list[str]":
    """Return installed browsers (best-effort, Windows-focused) in preference order.

    We only *offer* a browser to gallery-dl/yt-dlp if its profile dir plausibly
    exists — trying to read cookies from a browser that isn't installed just wastes
    a subprocess and prints a scary error.
    """
    import os
    import sys

    candidates: "dict[str, list[Path]]" = {}
    if sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        roaming = Path(os.environ.get("APPDATA", ""))
        candidates = {
            "chrome":  [local / "Google/Chrome/User Data"],
            "edge":    [local / "Microsoft/Edge/User Data"],
            "brave":   [local / "BraveSoftware/Brave-Browser/User Data"],
            "vivaldi": [local / "Vivaldi/User Data"],
            "opera":   [roaming / "Opera Software/Opera Stable"],
            "firefox": [roaming / "Mozilla/Firefox/Profiles"],
        }
    else:
        home = Path.home()
        candidates = {
            "chrome":  [home / ".config/google-chrome"],
            "edge":    [home / ".config/microsoft-edge"],
            "brave":   [home / ".config/BraveSoftware/Brave-Browser"],
            "firefox": [home / ".mozilla/firefox"],
        }
    found = []
    for name in _BROWSER_COOKIE_ORDER:
        for p in candidates.get(name, []):
            try:
                if p.exists():
                    found.append(name)
                    break
            except Exception:
                pass
    return found


def _gallery_config_args(url: str) -> "list[str]":
    """Extra gallery-dl -o flags that make login-walled hosts behave.

    For Instagram we pin the ``rest`` API and add a conservative request delay so
    a burst of downloads doesn't trip the login wall or get the session flagged.
    """
    args: "list[str]" = []
    if "instagram.com" in url:
        args += [
            "-o", "instagram.api=rest",
            "-o", "instagram.include=posts",
            "-o", "sleep-request=2.0-4.0",
        ]
    return args


def _download_gallery(
    url: str,
    out_dir: Path,
    cookie_file: "Path | None",
    browser_cookie: "str | None",
    force: bool,
    log: LogFn,
    *,
    _auto_cookie: bool = True,
) -> bool:
    """Download photos / image galleries with gallery-dl (Instagram, Twitter, …).

    gallery-dl is the photo counterpart to yt-dlp: it handles single image posts,
    multi-image carousels, and the videos inside those same posts. We shell out to
    it (``python -m gallery_dl``) so a gallery-dl upgrade can't break our import,
    and reuse the very same cookie options the video path uses.

    Zero-touch cookies: for login-walled hosts (Instagram/Facebook/Threads) with no
    cookies supplied, we automatically try each installed browser's logged-in
    session in turn, so a pasted link "just works" as long as the user is signed in
    to that site in any browser.
    """
    if not _GALLERY_DL_OK:
        log("gallery-dl not installed — run: pip install gallery-dl", "error")
        return False

    # Build the ordered list of cookie sources to try.
    # 1) explicit cookies.txt  2) explicit browser  3) auto-detected browsers.
    cookie_sources: "list[tuple[str, str | None]]" = []
    if cookie_file and cookie_file.exists():
        cookie_sources.append(("file", str(cookie_file)))
    elif browser_cookie:
        cookie_sources.append(("browser", browser_cookie))
    elif _auto_cookie and _is_login_walled(url):
        detected = _detect_browsers()
        if detected:
            log(f"No cookies given — auto-trying logged-in browser session "
                f"({', '.join(detected)})…", "info")
            cookie_sources = [("browser", b) for b in detected]
        else:
            cookie_sources.append(("none", None))
    else:
        cookie_sources.append(("none", None))

    last_login_wall = False
    for kind, value in cookie_sources:
        ok, login_wall = _run_gallery_dl(
            url, out_dir, kind, value, force, log,
            quiet_errors=(len(cookie_sources) > 1),
        )
        if ok:
            return True
        last_login_wall = login_wall
        if not login_wall:
            # A non-login failure (e.g. deleted post, network) won't be fixed by
            # trying another browser's cookies — stop here.
            break

    if last_login_wall and _is_login_walled(url):
        log("Instagram/Facebook needs you to be logged in. Fix once, works forever:",
            "warn")
        log("  1) Open instagram.com in Chrome/Edge/Firefox and log in.", "warn")
        log("  2) Keep that browser installed — the app borrows its session "
            "automatically.", "warn")
        log("  (Or pick your browser in the cookie dropdown / supply a cookies.txt.)",
            "warn")
    return False


def _run_gallery_dl(
    url: str,
    out_dir: Path,
    cookie_kind: str,
    cookie_value: "str | None",
    force: bool,
    log: LogFn,
    *,
    quiet_errors: bool = False,
) -> "tuple[bool, bool]":
    """Run gallery-dl once. Returns (success, hit_login_wall)."""
    import subprocess
    import sys

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "--dest", str(out_dir),
        *(["--no-skip"] if force else []),
        *_gallery_config_args(url),
    ]
    if cookie_kind == "file":
        cmd += ["--cookies", cookie_value]
    elif cookie_kind == "browser":
        cmd += ["--cookies-from-browser", cookie_value]
        log(f"Downloading images with gallery-dl (cookies: {cookie_value})…", "info")
    if cookie_kind != "browser":
        log("Downloading images with gallery-dl…", "info")
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        log("  gallery-dl timed out after 600s", "error")
        return False, False
    except Exception as exc:
        log(f"  gallery-dl error: {exc}", "error")
        return False, False

    for line in (proc.stdout or "").splitlines():
        log(f"  {line}", "muted")

    if proc.returncode == 0 and (proc.stdout or "").strip():
        log("  gallery-dl finished.", "success")
        return True, False

    err = (proc.stderr or "") + (proc.stdout or "")
    login_wall = any(s in err.lower() for s in _GALLERY_LOGIN_SIGNS)
    # returncode 0 but no output usually means "found nothing" (often a silent
    # login redirect) — treat it as a login wall so we try the next cookie source.
    if proc.returncode == 0 and not (proc.stdout or "").strip():
        login_wall = login_wall or _is_login_walled(url)

    tail = err.strip().splitlines()[-5:]
    err_tag = "muted" if quiet_errors else "error"
    for line in tail:
        log(f"  {line}", err_tag)
    if not tail:
        log(f"  gallery-dl exited with code {proc.returncode}", err_tag)
    return False, login_wall


def download(
    url: str,
    out_dir: "Path | str" = "./downloads",
    *,
    audio_only: bool = False,
    gallery: bool = False,
    playlist: bool = False,
    write_metadata: bool = True,
    sub_langs: "list[str] | None" = None,
    cookie_file: "Path | str | None" = None,
    browser_cookie: "str | None" = None,
    force: bool = False,
    fmt: "str | None" = None,
    out_template: "str | None" = None,
    sections: "str | None" = None,
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
        gallery:        Force the gallery-dl photo path (Instagram/Twitter/… images).
                        When False, image-host URLs still fall back to gallery-dl
                        automatically if yt-dlp finds no video.
        playlist:       Download all items in a playlist (default: single video only).
        write_metadata: Write a .info.json sidecar next to each file.
        sub_langs:      Subtitle language codes, e.g. ["en", "th"].
        cookie_file:    Path to Netscape cookies.txt.
        browser_cookie: Browser name for yt-dlp's --cookies-from-browser (chrome/firefox/edge/brave).
        force:          Re-download even if file already exists.
        fmt:            Override yt-dlp format string.
        out_template:   Override yt-dlp -o template (relative to out_dir).
        sections:       Time-range spec to trim to, e.g. "10:00-20:00" (video/audio
                        only; ignored for playlists and gallery downloads).
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

    # Photos mode: gallery-dl owns the whole download (no yt-dlp, no resolve).
    if gallery:
        return _download_gallery(url, out_dir, cookie_file, browser_cookie, force, log)

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

    # Section trim only makes sense for a single video/audio item — a playlist
    # would try to apply one time-range to every entry, which is never intended.
    parsed_sections = None
    if sections and not playlist:
        parsed_sections = parse_sections(sections)
        if parsed_sections:
            pretty = ", ".join(f"{s:g}s–{e:g}s" for s, e in parsed_sections)
            log(f"Trimming to section(s): {pretty}", "info")
        else:
            log(f"Couldn't parse section '{sections}' — downloading in full.", "warn")
    elif sections and playlist:
        log("Section trim ignored for playlists.", "warn")

    ok = _download_api(
        resolved, outtmpl, fmt, audio_only, playlist, write_metadata,
        sub_langs, cookie_file, browser_cookie, force, log, progress_hook,
        sections=parsed_sections,
    )
    # Auto-fallback: an Instagram/Twitter/… link that yt-dlp can't handle is
    # usually a photo or carousel — let gallery-dl take a turn before giving up.
    if not ok and not audio_only and _GALLERY_DL_OK and is_image_host(url):
        log("yt-dlp found no video — trying gallery-dl for images…", "info")
        return _download_gallery(url, out_dir, cookie_file, browser_cookie, force, log)
    return ok


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
    sections: "list[tuple[float, float]] | None" = None,
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

    if sections:
        try:
            from yt_dlp.utils import download_range_func
            ydl_opts["download_ranges"] = download_range_func(None, sections)
            # Cut on the nearest keyframes so the clip starts/ends cleanly rather
            # than at a random inter-frame (needs a re-encode of the boundary).
            ydl_opts["force_keyframes_at_cuts"] = True
        except Exception as exc:
            log(f"  Section trim unavailable ({exc}) — downloading full video.", "warn")

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
        gallery: bool = False,
        playlist: bool = False,
        write_metadata: bool = True,
        sub_langs: "list[str] | None" = None,
        cookie_file: "Path | str | None" = None,
        browser_cookie: "str | None" = None,
        force: bool = False,
        fmt: "str | None" = None,
        out_template: "str | None" = None,
        sections: "str | None" = None,
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
            gallery=gallery,
            playlist=playlist,
            write_metadata=write_metadata,
            sub_langs=sub_langs,
            cookie_file=ck,
            browser_cookie=browser_cookie,
            force=force,
            fmt=fmt,
            out_template=out_template,
            sections=sections,
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


# ---------------------------------------------------------------------------
# Self-update — keep extractors fresh (the #1 cause of "unknown site" failures)
# ---------------------------------------------------------------------------

# yt-dlp's nightly channel ships extractor fixes days before the stable release,
# which matters most for the unfamiliar/changing sites this tool targets.
YTDLP_NIGHTLY = (
    "yt-dlp @ https://github.com/yt-dlp/yt-dlp-nightly-builds"
    "/releases/latest/download/yt-dlp.tar.gz"
)


def _pkg_version(pkg: str) -> str:
    """Return the installed version of a pip package, or 'unknown'."""
    import subprocess
    import sys
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True, text=True, timeout=15,
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
    timeout: int = 180,
) -> bool:
    """Update yt-dlp (nightly) and, if installed, gallery-dl.

    Returns True if any package changed version. Safe to call from a background
    thread; logs progress through ``log``. This is the single highest-leverage
    robustness lever — a stale extractor is the most common reason an unknown or
    changing site stops working.
    """
    import subprocess
    import sys

    changed = False
    jobs: "list[tuple[str, list[str]]]" = [
        ("yt-dlp", ["-U", "--force-reinstall", "--no-deps", YTDLP_NIGHTLY]),
    ]
    if include_gallery and _GALLERY_DL_OK:
        jobs.append(("gallery-dl", ["-U", "gallery-dl"]))

    for name, args in jobs:
        before = _pkg_version(name)
        log(f"Updating {name}…", "info")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", *args],
                capture_output=True, text=True, timeout=timeout,
            )
        except Exception as exc:
            log(f"  {name} update failed: {exc}", "error")
            continue
        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            if "WinError 32" in out or "being used by another process" in out:
                log(f"  {name} files are locked — close the app and update "
                    f"from a terminal.", "error")
            else:
                for line in out.strip().splitlines()[-8:]:
                    log(f"  {line}", "error")
            continue
        after = _pkg_version(name)
        if after != before:
            log(f"  {name}: {before} → {after}", "success")
            changed = True
        else:
            log(f"  {name} already current ({after}).", "success")
    return changed


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
    if not _GALLERY_DL_OK:
        print("[WARN] gallery-dl not found — photo/carousel downloads (Instagram, "
              "Twitter/X, …) are disabled. Install with: pip install gallery-dl")
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
