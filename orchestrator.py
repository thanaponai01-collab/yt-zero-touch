"""
YT-DLP Zero-Touch — Batch Orchestrator (UI-free)
================================================
The download *policy* — resolve phase, output-template selection, concurrency,
retry with backoff, permanent-error classification, history writes — lives here
so it can be unit-tested without a Tk window and shared by every front-end
(GUI, watcher) instead of being re-implemented (and drifting) in each.

Front-ends supply two callbacks:
    log(msg, tag)        — render a log line
    set_status(text)     — render a one-line status (optional; defaults to no-op)

Everything else (the executor, retry timing, history persistence) is owned here.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from resolver import resolve_url, _launch_temp_browser, _PLAYWRIGHT_OK, LogFn, _print_log
from ytdlp_skill import save_history

# ---------------------------------------------------------------------------
# Permanent-error classification
# ---------------------------------------------------------------------------

# Phrases in yt-dlp error output that indicate a permanent, non-retryable
# failure. These are deliberately whole phrases — earlier versions used bare
# substrings like "age"/"geo"/"403", which match inside common transient-error
# words ("message" contains "age"), silently disabling the retry path.
PERMANENT_ERR_KEYWORDS = [
    "video unavailable",
    "has been removed",
    "private video",
    "this video is not available",
    "geo-restricted",
    "geo restricted",
    "age-restricted",
    "age restricted",
    "sign in to confirm",
    "http error 404",
    "http error 403",
    "not found",
    "no video formats",
    "no formats found",
]


def is_permanent_error(messages: list[str], keywords=PERMANENT_ERR_KEYWORDS) -> bool:
    """True if any captured error message names a permanent (non-retryable) failure."""
    combined = " ".join(messages).lower()
    return any(kw in combined for kw in keywords)


# ---------------------------------------------------------------------------
# Output template selection
# ---------------------------------------------------------------------------

_SLUG_BAD = re.compile(r"[^\w\s-]")
_SLUG_WS  = re.compile(r"\s+")


def build_output_template(idx: int, url: str, resolved: str, total: int, pad: int) -> str:
    """Pick a yt-dlp output template for one item.

    Direct streams (a resolved .m3u8/.mp4?… that differs from the page URL) have
    no usable yt-dlp title/id, so we slugify the page URL's last path segment.
    Everything else uses yt-dlp's own title/id metadata.
    """
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
# Policy + result
# ---------------------------------------------------------------------------

@dataclass
class BatchPolicy:
    out_dir: Path
    audio_only: bool = False
    fmt: "str | None" = None
    sub_langs: list = field(default_factory=list)
    cookie_file: "Path | None" = None
    browser_cookie: "str | None" = None
    force: bool = False
    write_metadata: bool = False
    playlist: bool = False
    max_workers: int = 3
    retry_max: int = 3
    retry_delays: tuple = (5, 15, 30)


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0


# ---------------------------------------------------------------------------
# Per-URL download with retry + backoff
# ---------------------------------------------------------------------------

def download_with_retry(
    download_fn: "Callable[[LogFn, Callable[[dict], None]], bool]",
    *,
    policy: BatchPolicy,
    url: str,
    idx: "int | None" = None,
    log: LogFn = _print_log,
    set_status: "Callable[[str], None]" = lambda *_: None,
    sleep: "Callable[[float], None]" = time.sleep,
) -> bool:
    """Run download_fn, retrying transient failures with backoff.

    download_fn receives (log, progress_hook) and returns True on success. Error
    messages logged with tag "error" are captured and classified; a permanent
    failure short-circuits the retry loop.
    """
    prefix = f"[#{idx}] " if idx is not None else ""

    def base_log(msg: str, tag: str = "info"):
        log(f"{prefix}{msg}", tag)

    def progress_hook(d: dict):
        if d["status"] == "downloading":
            pct   = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "?").strip()
            eta   = d.get("_eta_str", "?").strip()
            set_status(f"Downloading  {pct}  •  {speed}  •  ETA {eta}")
        elif d["status"] == "finished":
            set_status("Merging…")

    base_log(f"Starting: {url[:80]}", "accent")

    for attempt in range(1, policy.retry_max + 2):
        captured_errors: list[str] = []

        def log_capture(msg: str, tag: str = "info"):
            base_log(msg, tag)
            if tag == "error":
                captured_errors.append(msg)

        if download_fn(log_capture, progress_hook):
            return True

        if is_permanent_error(captured_errors):
            base_log("  Permanent error — not retrying", "error")
            return False

        if attempt <= policy.retry_max:
            delay = policy.retry_delays[attempt - 1]
            base_log(f"  Attempt {attempt} failed — retrying in {delay}s…", "warn")
            for s in range(delay, 0, -1):
                label = f"#{idx} " if idx is not None else ""
                set_status(f"Retry #{attempt} for {label}in {s}s…")
                sleep(1)

    base_log(f"  All {policy.retry_max + 1} attempts failed.", "error")
    return False


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def _make_download_fn(downloader, policy: BatchPolicy, resolved: str, tpl: str):
    """Bind a downloader call to (log, progress_hook) for download_with_retry."""
    def _fn(log: LogFn, progress_hook):
        return downloader.download(
            resolved,
            out_dir=policy.out_dir,
            audio_only=policy.audio_only,
            playlist=policy.playlist,
            write_metadata=policy.write_metadata,
            fmt=policy.fmt,
            sub_langs=policy.sub_langs,
            cookie_file=policy.cookie_file,
            browser_cookie=policy.browser_cookie,
            force=policy.force,
            out_template=tpl,
            log=log,
            progress_hook=progress_hook,
            pre_resolved=True,
        )
    return _fn


def run_batch(
    urls: list[str],
    policy: BatchPolicy,
    downloader,
    *,
    history: set,
    history_lock,
    history_path: "Path | str",
    log: LogFn = _print_log,
    set_status: "Callable[[str], None]" = lambda *_: None,
    resolve_fn: "Callable" = resolve_url,
    browser_factory: "Callable" = _launch_temp_browser,
    playwright_ok: bool = _PLAYWRIGHT_OK,
) -> BatchResult:
    """Resolve, then concurrently download a list of URLs.

    Phase 1 resolves every URL sequentially while one Playwright browser stays
    warm (created here, in the calling thread — Playwright's sync greenlet
    dispatcher binds to its creating thread). Phase 2 downloads concurrently,
    retrying transient failures and recording successes to history.
    """
    result = BatchResult()
    policy.out_dir.mkdir(parents=True, exist_ok=True)
    pad = len(str(len(urls)))

    # ── Phase 1: resolve sequentially with a warm browser ──────────────────
    worker_browser = browser_factory() if playwright_ok else None
    work_items: list[tuple[int, str, str, str]] = []
    try:
        for idx, url in enumerate(urls, 1):
            ts = datetime.now().strftime("%H:%M:%S")
            if url in history and not policy.force:
                log(f"[{ts}] Skipping (already downloaded): {url[:80]}", "muted")
                continue
            log(f"\n[{ts}] Resolving {idx}/{len(urls)}: {url[:80]}", "accent")
            resolved = resolve_fn(
                url, cookie_file=policy.cookie_file, log=log, _browser=worker_browser,
            )
            tpl = build_output_template(idx, url, resolved, len(urls), pad)
            work_items.append((idx, url, resolved, tpl))
    finally:
        if worker_browser:
            try:
                worker_browser.close()
            except Exception:
                pass

    if not work_items:
        return result

    total = len(work_items)
    result.total = total
    workers = min(policy.max_workers, total)
    done = [0]  # mutable for closure across threads
    log(f"\nStarting {total} download(s) with up to {workers} concurrent thread(s)…", "info")
    set_status(f"0 / {total} done")

    # ── Phase 2: concurrent downloads ──────────────────────────────────────
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_with_retry,
                _make_download_fn(downloader, policy, resolved, tpl),
                policy=policy, url=url, idx=idx, log=log, set_status=set_status,
            ): (idx, url)
            for idx, url, resolved, tpl in work_items
        }
        for future in as_completed(futures):
            idx, url = futures[future]
            try:
                ok = future.result()
            except Exception as exc:
                log(f"  [#{idx}] Unexpected error: {exc}", "error")
                ok = False

            if ok:
                with history_lock:
                    history.add(url)
                    save_history(history_path, history)
                done[0] += 1
                set_status(f"{done[0]} / {total} done")
            else:
                log(f"  [#{idx}] Download failed.", "error")

    result.succeeded = done[0]
    result.failed = total - done[0]
    return result
