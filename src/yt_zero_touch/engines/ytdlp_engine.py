"""
yt-dlp Engine Adapter.
======================
Native Python API & CLI wrapper for yt-dlp.
Tuned for Premiere Pro compatibility:
- H.264 / AAC muxing
- ProRes 422 Proxy
- Faststart movflags
- Concurrent fragment downloads
- Section trim watchdog
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from yt_zero_touch.core.format_policy import FORMAT_SORT
from yt_zero_touch.core.models import (
    FORMAT_AUDIO,
    FORMAT_VIDEO,
    is_image_host,
    parse_sections,
)
from yt_zero_touch.core.transcode import (
    PRE_MERGE_DEFAULT_ARGS,
    container_for,
    merge_session,
    plan_transcode,
)
from yt_zero_touch.engines.base import BaseEngine, LogFn
from yt_zero_touch.engines.gallery_engine import download_gallery, GALLERY_DL_OK
from yt_zero_touch.engines.gdrive_engine import extract_gdrive_id, download_gdrive
from yt_zero_touch.services.resolver import (
    resolve_url,
    _launch_temp_browser,
    _PLAYWRIGHT_OK,
    _BROWSER_ARGS,
)
from yt_zero_touch.services.system import DENO_PATH

try:
    import yt_dlp as _yt_dlp
    YT_DLP_API_OK = True
except ImportError:
    _yt_dlp = None  # type: ignore
    YT_DLP_API_OK = False

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore


_SECTION_DOWNLOAD_TIMEOUT_S = 300


class _SectionTimeout(Exception):
    """Raised from the progress hook to abort a stuck section download."""


def _log_section_timeout(sections: Any, log: Callable) -> None:
    mins = _SECTION_DOWNLOAD_TIMEOUT_S // 60
    log(f"  Section download exceeded {mins} min and was aborted.", "error")
    log("  ffmpeg reads from the start of the video to reach the clip, so a "
        "clip deep in a long video can't seek quickly. Try downloading the "
        "full video, or pick a section nearer the start.", "error")


def _print_log(msg: str, tag: str = "info") -> None:
    prefix = {"warn": "[WARN]", "error": "[ERR ]", "success": "[OK  ]"}.get(tag, "[    ]")
    print(f"{prefix} {msg}")


def download_ytdlp(
    url: str,
    out_dir: Path | str = "./downloads",
    *,
    audio_only: bool = False,
    gallery: bool = False,
    playlist: bool = False,
    write_metadata: bool = True,
    sub_langs: list[str] | None = None,
    cookie_file: Path | str | None = None,
    browser_cookie: str | None = None,
    force: bool = False,
    fmt: str | None = None,
    out_template: str | None = None,
    sections: str | None = None,
    target_codec: str = "h264",
    log: LogFn = _print_log,
    progress_hook: Callable[[dict], None] | None = None,
    pre_resolved: bool = False,
    _browser=None,
) -> bool:
    """Download a single URL (or full playlist)."""
    out_dir_path = Path(out_dir)
    ck_file = Path(cookie_file) if cookie_file else None
    sub_langs = sub_langs or []
    fmt = fmt or (FORMAT_AUDIO if audio_only else FORMAT_VIDEO)
    tpl = out_template or (
        "%(playlist_title)s/%(playlist_index)02d - %(title).80B - [%(id)s].%(ext)s"
        if playlist else
        "%(title).100B - [%(id)s].%(ext)s"
    )

    out_dir_path.mkdir(parents=True, exist_ok=True)

    if gallery:
        return download_gallery(url, out_dir_path, ck_file, browser_cookie, force, log)

    gdrive_id = extract_gdrive_id(url)
    if gdrive_id:
        ok = download_gdrive(gdrive_id, out_dir_path, log)
        if ok:
            return True
        log("gdown failed — falling back to yt-dlp", "warn")

    if pre_resolved:
        resolved = url
    else:
        log(f"Resolving: {url[:80]}", "info")
        resolved = resolve_url(url, cookie_file=ck_file, log=log, _browser=_browser)

    outtmpl = out_dir_path / tpl

    if not YT_DLP_API_OK:
        log("yt-dlp is not installed — run: pip install yt-dlp", "error")
        return False

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
        sub_langs, ck_file, browser_cookie, force, log, progress_hook,
        sections=parsed_sections, target_codec=target_codec,
    )

    if not ok and not audio_only and GALLERY_DL_OK and is_image_host(url):
        log("yt-dlp found no video — trying gallery-dl for images…", "info")
        return download_gallery(url, out_dir_path, ck_file, browser_cookie, force, log)
    return ok


def _download_api(
    resolved: str,
    outtmpl: Path,
    fmt: str,
    audio_only: bool,
    playlist: bool,
    write_metadata: bool,
    sub_langs: list,
    cookie_file: Path | None,
    browser_cookie: str | None,
    force: bool = False,
    log: LogFn = _print_log,
    extra_progress_hook: Callable[[dict], None] | None = None,
    sections: list[tuple[float, float]] | None = None,
    target_codec: str = "h264",
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
    section_deadline = [None]
    section_timed_out = [False]

    def _progress(d: dict):
        if sections and d["status"] == "downloading":
            if section_deadline[0] is None:
                section_deadline[0] = time.monotonic() + _SECTION_DOWNLOAD_TIMEOUT_S
            elif time.monotonic() > section_deadline[0]:
                section_timed_out[0] = True
                raise _SectionTimeout()
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

    container = container_for(audio_only, target_codec)  # type: ignore
    merge = merge_session(log, container)

    def _tune_merge_args_for_premiere(status: dict):
        if status.get("postprocessor") != "Merger":
            return
        info = status.get("info_dict") or {}
        if status.get("status") == "finished":
            merge.merge_finished(info.get("filepath"))
            return
        if status.get("status") != "started":
            return
        formats = info.get("requested_formats") or []
        video_fmt = next((f for f in formats if f.get("vcodec") not in (None, "none")), None)
        audio_fmt = next((f for f in formats if f.get("acodec") not in (None, "none")), None)
        vcodec = ((video_fmt or {}).get("vcodec") or "").lower()
        acodec = ((audio_fmt or {}).get("acodec") or "").lower()
        plan = plan_transcode(vcodec, acodec, target_codec)  # type: ignore
        if plan.log_message:
            log(plan.log_message, plan.log_level)
        merge.merge_started(plan, info.get("filepath"))
        ydl_opts["postprocessor_args"]["merger"] = plan.merge_args

    ydl_opts: dict = {
        "format":                        fmt,
        "outtmpl":                       str(outtmpl),
        "noplaylist":                    not playlist,
        "merge_output_format":           container,
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
        **({
            "postprocessor_args": {"merger": PRE_MERGE_DEFAULT_ARGS},
            "postprocessor_hooks": [_tune_merge_args_for_premiere],
        } if not audio_only else {}),
        "format_sort":                   FORMAT_SORT,
        "socket_timeout":                60,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size":               10485760,
        "retries":                       50,
        "throttledratelimit":            102400,
        "fragment_retries":              10,
        "extractor_args":                {
            "generic": {"impersonate": [""]},
        },
        "remote_components":             ["ejs:github"],
        **({"js_runtimes": {"deno": {"path": DENO_PATH}}} if DENO_PATH else {}),
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
            ydl_opts["force_keyframes_at_cuts"] = True
            ydl_opts["external_downloader_args"] = {"ffmpeg_i": ["-rw_timeout", "30000000"]}
        except Exception as exc:
            log(f"  Section trim unavailable ({exc}) — downloading full video.", "warn")

    try:
        with merge:
            with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ret = ydl.download([resolved])
        if section_timed_out[0]:
            _log_section_timeout(sections, log)
            return False
        if ret != 0:
            return False
        return merge.verify()
    except _SectionTimeout:
        _log_section_timeout(sections, log)
        return False
    except Exception as exc:
        if section_timed_out[0]:
            _log_section_timeout(sections, log)
            return False
        log(f"  yt-dlp API error: {exc}", "error")
        return False


class Downloader:
    """Context manager that keeps one Chromium instance alive for all downloads."""

    def __init__(
        self,
        cookie_file: Path | str | None = None,
        log: LogFn = _print_log,
    ):
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.log         = log
        self._lock       = threading.Lock()
        self._pw         = None
        self._browser    = None

    def __enter__(self):
        if _PLAYWRIGHT_OK and sync_playwright is not None:
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
        out_dir: Path | str = "./downloads",
        *,
        audio_only: bool = False,
        gallery: bool = False,
        playlist: bool = False,
        write_metadata: bool = True,
        sub_langs: list[str] | None = None,
        cookie_file: Path | str | None = None,
        browser_cookie: str | None = None,
        force: bool = False,
        fmt: str | None = None,
        out_template: str | None = None,
        sections: str | None = None,
        target_codec: str = "h264",
        log: LogFn | None = None,
        progress_hook: Callable[[dict], None] | None = None,
        pre_resolved: bool = False,
    ) -> bool:
        ck = cookie_file or self.cookie_file
        with self._lock:
            browser = self._browser
        return download_ytdlp(
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
            target_codec=target_codec,
            log=log or self.log,
            progress_hook=progress_hook,
            pre_resolved=pre_resolved,
            _browser=browser,
        )


class YtdlpEngine(BaseEngine):
    def can_handle(self, url: str, **kwargs: Any) -> bool:
        return True

    def download(self, url: str, out_dir: Path, log: LogFn, **kwargs: Any) -> bool:
        return download_ytdlp(url, out_dir=out_dir, log=log, **kwargs)
