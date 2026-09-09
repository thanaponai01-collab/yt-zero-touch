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

import contextlib
import os
import threading
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

# Default install path install.bat's bgutil-ytdlp-pot-provider step writes to
# (see ADR-0004) — passed explicitly so the plugin's HTTP PO Token provider
# knows script mode is in use and logs its always-failing localhost:4416
# ping as expected info rather than a warning.
_POT_SCRIPT_PATH = str(
    Path.home() / "bgutil-ytdlp-pot-provider" / "server" / "build" / "generate_once.js")

# A section trim always goes through yt-dlp's FFmpegFD external downloader
# (the seek needs ffmpeg's -ss), which spawns ffmpeg and blocks on plain
# `proc.wait()` — see yt_dlp/downloader/external.py ExternalFD.real_download /
# FFmpegFD._call_downloader. It fires progress_hooks exactly once, *after*
# ffmpeg has already exited, never while the process is running. So a
# watchdog living in a progress hook can never see a stuck download, let
# alone abort one. The only place that can actually see and kill the live
# ffmpeg process is whatever spawns it, so we intercept that: patch the
# `Popen` yt-dlp's external downloader uses to hand every spawned process to
# a per-thread watchdog, which kills it if the deadline passes before the
# download finishes on its own.
_section_watchdogs: "dict[int, _FFmpegSectionWatchdog]" = {}
_section_watchdogs_lock = threading.Lock()
_popen_patch_lock = threading.Lock()
_popen_patched = False


def _ensure_ffmpeg_popen_patched() -> None:
    """Patch yt_dlp's external-downloader Popen once so every process it
    spawns is handed to whichever _FFmpegSectionWatchdog is active on the
    spawning thread (if any). Idempotent and safe to call unconditionally —
    downloads with no active watchdog on their thread are a no-op lookup.
    """
    global _popen_patched
    with _popen_patch_lock:
        if _popen_patched:
            return
        import yt_dlp.downloader.external as _ext

        _real_popen = _ext.Popen

        class _DispatchingPopen(_real_popen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                with _section_watchdogs_lock:
                    watchdog = _section_watchdogs.get(threading.get_ident())
                if watchdog is not None:
                    watchdog._capture(self)

        _ext.Popen = _DispatchingPopen
        _popen_patched = True


class _FFmpegSectionWatchdog:
    """Context manager that enforces _SECTION_DOWNLOAD_TIMEOUT_S by killing
    the actual ffmpeg subprocess a section trim spawns, rather than relying on
    a progress hook that never fires while ffmpeg is running (see above).

    Scoped to the calling thread via a thread-id-keyed registry, so concurrent
    section trims on different worker threads each only ever see and kill
    their own ffmpeg process.
    """

    def __init__(self, timeout_s: float):
        self._timeout_s = timeout_s
        self._done = threading.Event()
        self._procs: "list" = []
        self._procs_lock = threading.Lock()
        self._thread: "threading.Thread | None" = None
        self.timed_out = False

    def _capture(self, proc) -> None:
        with self._procs_lock:
            self._procs.append(proc)

    def _watch(self) -> None:
        if self._done.wait(self._timeout_s):
            return
        self.timed_out = True
        with self._procs_lock:
            procs = list(self._procs)
        for proc in procs:
            try:
                if proc.poll() is None:
                    proc.kill(timeout=None)
            except Exception:
                pass

    def __enter__(self) -> "_FFmpegSectionWatchdog":
        _ensure_ffmpeg_popen_patched()
        with _section_watchdogs_lock:
            _section_watchdogs[threading.get_ident()] = self
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._done.set()
        with _section_watchdogs_lock:
            _section_watchdogs.pop(threading.get_ident(), None)


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
    player_client: str | None = None,
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
        sections=parsed_sections, target_codec=target_codec, player_client=player_client,
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
    player_client: str | None = None,
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
        # player_client is an explicit override (see download_with_retry's
        # login-wall / client-retry fallbacks in services/orchestrator.py),
        # used only after the default client has already failed on this URL.
        "extractor_args":                {
            "generic": {"impersonate": [""]},
            **({"youtube": {"player_client": player_client.split(",")}}
               if player_client else {}),
            # Tells the bgutil PO Token HTTP provider that script mode
            # (ADR-0004) is in use, so its always-failing ping to the
            # unused localhost:4416 server logs as an expected info line
            # instead of a warning that looks like a real failure.
            "youtubepot-bgutilscript": {"script_path": [_POT_SCRIPT_PATH]},
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
            # yt-dlp's socket_timeout doesn't reach the ffmpeg downloader; give
            # ffmpeg its own read timeout so a genuinely stalled connection
            # aborts (30s of zero bytes) instead of blocking forever. The
            # _FFmpegSectionWatchdog below covers the slow-but-progressing
            # deep-seek case that -rw_timeout can't see.
            #
            # "ffmpeg" (not "ffmpeg_i"/"ffmpeg_o") lands in FFmpegFD's general
            # arg list, appended after its own "-loglevel quiet" (added because
            # our top-level ydl_opts["quiet"]=True) — the later flag wins, so
            # this un-silences ffmpeg's stderr. Without it, a CDN rejection
            # (e.g. HTTP 403 on a stale/erratic-client URL) is invisible:
            # ffmpeg reports only a meaningless raw exit code, captured_errors
            # never contains "403", and classify_failure/client-retry-fallback
            # — built to catch exactly this — never fires.
            ydl_opts["external_downloader_args"] = {
                "ffmpeg_i": ["-rw_timeout", "30000000"],
                "ffmpeg": ["-loglevel", "warning"],
            }
        except Exception as exc:
            log(f"  Section trim unavailable ({exc}) — downloading full video.", "warn")

    # Real enforced timeout for section trims: kills the actual ffmpeg
    # subprocess if it's still running past _SECTION_DOWNLOAD_TIMEOUT_S. See
    # the comment above _ensure_ffmpeg_popen_patched for why a progress-hook
    # watchdog can't do this. Non-section downloads skip it entirely.
    watchdog_cm = _FFmpegSectionWatchdog(_SECTION_DOWNLOAD_TIMEOUT_S) if sections \
        else contextlib.nullcontext()
    watchdog: "_FFmpegSectionWatchdog | None" = None

    try:
        with watchdog_cm as watchdog:
            with merge:
                with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ret = ydl.download([resolved])
            if watchdog is not None and watchdog.timed_out:
                _log_section_timeout(sections, log)
                return False
        if ret != 0:
            return False
        return merge.verify()
    except Exception as exc:
        if watchdog is not None and watchdog.timed_out:
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
        player_client: str | None = None,
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
            player_client=player_client,
            _browser=browser,
        )


class YtdlpEngine(BaseEngine):
    def can_handle(self, url: str, **kwargs: Any) -> bool:
        return True

    def download(self, url: str, out_dir: Path, log: LogFn, **kwargs: Any) -> bool:
        return download_ytdlp(url, out_dir=out_dir, log=log, **kwargs)
