"""
YT-DLP Zero-Touch — Batch Orchestrator Service (UI-free)
=========================================================
The download policy — resolve phase, output-template selection, concurrency,
retry with backoff, permanent-error classification, history writes.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from yt_zero_touch.core.failures import (
    _CLIENT_RETRY,
    _LOGIN,
    FailureClass,
    classify_failure,
    is_permanent_error,
)
from yt_zero_touch.core.history import HistoryStore, save_history
from yt_zero_touch.core.models import (
    BatchPolicy,
    BatchResult,
    DownloadOutcome,
    build_output_template,
)
from yt_zero_touch.services.resolver import (
    LogFn,
    _PLAYWRIGHT_OK,
    _launch_temp_browser,
    _print_log,
    resolve_url,
)

_DEFAULT_RETRY_MAX = 3
_DEFAULT_RETRY_DELAYS = (5, 15, 30)


def download_with_retry(
    download_fn: Callable[[LogFn, Callable[[dict], None]], bool],
    *,
    retry_max: int = _DEFAULT_RETRY_MAX,
    retry_delays: tuple[int, ...] = _DEFAULT_RETRY_DELAYS,
    url: str,
    idx: int | None = None,
    log: LogFn = _print_log,
    set_status: Callable[[str], None] = lambda *_: None,
    set_item: Callable[[str, float | None], None] = lambda *a: None,
    sleep: Callable[[float], None] = time.sleep,
    login_wall_fallback_fn: Callable[[LogFn, Callable[[dict], None]], bool] | None = None,
    client_retry_fallback_fn: Callable[[LogFn, Callable[[dict], None]], bool] | None = None,
) -> DownloadOutcome:
    """Run download_fn, retrying transient failures with backoff.

    login_wall_fallback_fn, if given, is tried exactly once — outside the
    retry_max budget — the first time classify_failure calls "needs_cookies":
    that message also fires when a valid session's default player client just
    fails YouTube's bot-check, which a different client can clear without any
    new cookies. Only if the fallback also comes back login-walled is the
    failure reported as permanent.

    client_retry_fallback_fn is the analogous one-shot fallback for
    _CLIENT_RETRY (a client served a format URL ffmpeg can't fetch). Kept
    separate from login_wall_fallback_fn because the two need different
    client lists: the login-wall fallback leans on android_vr specifically
    for its no-PO-token property, but android_vr is also the documented
    source of the _CLIENT_RETRY failure itself, so reusing it here would
    just fail the same way again.
    """
    prefix = f"[#{idx}] " if idx is not None else ""

    def base_log(msg: str, tag: str = "info"):
        log(f"{prefix}{msg}", tag)

    def _pct_float(d: dict) -> float | None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        got   = d.get("downloaded_bytes")
        if total and got is not None:
            try:
                return max(0.0, min(100.0, got / total * 100.0))
            except Exception:
                pass
        raw = (d.get("_percent_str") or "").strip().rstrip("%")
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    def progress_hook(d: dict):
        if d["status"] == "downloading":
            pct   = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "?").strip()
            eta   = d.get("_eta_str", "?").strip()
            set_status(f"Downloading  {pct}  •  {speed}  •  ETA {eta}")
            set_item("downloading", _pct_float(d))
        elif d["status"] == "finished":
            set_status("Merging…")
            set_item("merging", 100.0)

    base_log(f"Starting: {url[:80]}", "accent")
    set_item("downloading", None)

    last_errors: list[str] = []
    for attempt in range(1, retry_max + 2):
        captured_errors: list[str] = []

        def log_capture(msg: str, tag: str = "info"):
            base_log(msg, tag)
            if tag == "error":
                captured_errors.append(msg)

        if download_fn(log_capture, progress_hook):
            return DownloadOutcome(ok=True)

        last_errors = captured_errors
        failure = classify_failure(captured_errors)

        if failure is _LOGIN and login_wall_fallback_fn is not None:
            login_wall_fallback_fn, fallback_fn = None, login_wall_fallback_fn
            base_log(f"  {failure.label} with the default client — trying an "
                      "alternate player client before giving up…", "warn")
            if fallback_fn(log_capture, progress_hook):
                return DownloadOutcome(ok=True)
            failure = classify_failure(captured_errors)
        elif failure is _CLIENT_RETRY and client_retry_fallback_fn is not None:
            client_retry_fallback_fn, fallback_fn = None, client_retry_fallback_fn
            base_log(f"  {failure.label} with the default client — trying an "
                      "alternate player client before giving up…", "warn")
            if fallback_fn(log_capture, progress_hook):
                return DownloadOutcome(ok=True)
            # The default client is confirmed broken (that's what _CLIENT_RETRY
            # means) — keep using the alternate client for any remaining
            # retries in this loop instead of reverting to a client that will
            # 403 again every time.
            download_fn = fallback_fn
            failure = classify_failure(captured_errors)

        if failure and failure.permanent:
            base_log(f"  {failure.label} — not retrying. {failure.remedy}", "warn")
            set_item("failed", None)
            return DownloadOutcome(ok=False, failure=failure)

        if attempt <= retry_max:
            delay = retry_delays[attempt - 1]
            base_log(f"  Attempt {attempt} failed — retrying in {delay}s…", "warn")
            set_item("retrying", None)
            for s in range(delay, 0, -1):
                label = f"#{idx} " if idx is not None else ""
                set_status(f"Retry #{attempt} for {label}in {s}s…")
                sleep(1)

    base_log(f"  All {retry_max + 1} attempts failed.", "error")
    set_item("failed", None)
    return DownloadOutcome(ok=False, failure=classify_failure(last_errors))


# yt-dlp's built-in default player client is retuned upstream as YouTube's
# PO-token requirements shift, so pinning one by default would itself go
# stale. This is instead an explicit override used only after the default
# has already failed a bot-check on this URL (login wall) — a known-good
# client list that needs no PO token.
LOGIN_WALL_FALLBACK_CLIENT = "tv_simply,android_vr,tv,web"

# _CLIENT_RETRY fallback: same idea, but android_vr deliberately dropped.
# android_vr's format URLs are the confirmed source of that failure — ffmpeg
# (forced as external downloader by --download-sections) gets an HTTP 403
# fetching them, deterministically, every attempt.
CLIENT_RETRY_FALLBACK_CLIENT = "tv_simply,tv,web"


def _make_download_fn(downloader, policy: BatchPolicy, resolved: str, tpl: str,
                       player_client: str | None = None):
    def _fn(log: LogFn, progress_hook):
        return downloader.download(
            resolved,
            out_dir=policy.out_dir,
            audio_only=policy.audio_only,
            gallery=policy.gallery,
            playlist=policy.playlist,
            write_metadata=policy.write_metadata,
            fmt=policy.fmt,
            sub_langs=policy.sub_langs,
            cookie_file=policy.cookie_file,
            browser_cookie=policy.browser_cookie,
            force=policy.force,
            out_template=tpl,
            sections=policy.sections,
            target_codec=policy.target_codec,
            log=log,
            progress_hook=progress_hook,
            pre_resolved=True,
            player_client=player_client,
        )
    return _fn


def run_batch(
    urls: list[str],
    policy: BatchPolicy,
    downloader,
    *,
    history: set | HistoryStore,
    history_lock=None,
    history_path: Path | str | None = None,
    log: LogFn = _print_log,
    set_status: Callable[[str], None] = lambda *_: None,
    on_item: Callable[[int, str, str, float | None], None] = lambda *a: None,
    resolve_fn: Callable = resolve_url,
    browser_factory: Callable = _launch_temp_browser,
    playwright_ok: bool = _PLAYWRIGHT_OK,
) -> BatchResult:
    """Resolve, then concurrently download a list of URLs."""
    result = BatchResult()
    policy.out_dir.mkdir(parents=True, exist_ok=True)
    pad = len(str(len(urls)))

    # Support either HistoryStore instance or legacy (set, lock, path)
    if isinstance(history, HistoryStore):
        store = history
        lock = store.lock
        history_set = store.urls
        history_file = store.path
    else:
        history_set = history
        lock = history_lock
        history_file = Path(history_path) if history_path else None

    worker_browser = (
        browser_factory() if (playwright_ok and not policy.gallery) else None
    )
    work_items: list[tuple[int, str, str, str]] = []
    try:
        for idx, url in enumerate(urls, 1):
            ts = datetime.now().strftime("%H:%M:%S")
            if url in history_set and not policy.force:
                log(f"[{ts}] Skipping (already downloaded): {url[:80]}", "muted")
                on_item(idx, url, "skipped", None)
                continue
            if policy.gallery:
                resolved, tpl = url, ""
            else:
                log(f"\n[{ts}] Resolving {idx}/{len(urls)}: {url[:80]}", "accent")
                on_item(idx, url, "resolving", None)
                resolved = resolve_fn(
                    url, cookie_file=policy.cookie_file, log=log, _browser=worker_browser,
                )
                tpl = build_output_template(idx, url, resolved, len(urls), pad)
            on_item(idx, url, "queued", None)
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
    done = [0]
    log(f"\nStarting {total} download(s) with up to {workers} concurrent thread(s)…", "info")
    set_status(f"0 / {total} done")

    def _item_cb(i, u):
        return lambda status, pct=None: on_item(i, u, status, pct)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_with_retry,
                _make_download_fn(downloader, policy, resolved, tpl),
                retry_max=policy.retry_max, retry_delays=policy.retry_delays,
                url=url, idx=idx, log=log, set_status=set_status,
                set_item=_item_cb(idx, url),
                login_wall_fallback_fn=(
                    None if policy.gallery else
                    _make_download_fn(downloader, policy, resolved, tpl,
                                       player_client=LOGIN_WALL_FALLBACK_CLIENT)
                ),
                client_retry_fallback_fn=(
                    None if policy.gallery else
                    _make_download_fn(downloader, policy, resolved, tpl,
                                       player_client=CLIENT_RETRY_FALLBACK_CLIENT)
                ),
            ): (idx, url)
            for idx, url, resolved, tpl in work_items
        }
        for future in as_completed(futures):
            idx, url = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                log(f"  [#{idx}] Unexpected error: {exc}", "error")
                outcome = DownloadOutcome(ok=False)

            if outcome.ok:
                if isinstance(history, HistoryStore):
                    history.add(url)
                else:
                    if lock:
                        with lock:
                            history_set.add(url)
                            if history_file:
                                save_history(history_file, history_set)
                    else:
                        history_set.add(url)
                        if history_file:
                            save_history(history_file, history_set)
                done[0] += 1
                set_status(f"{done[0]} / {total} done")
                on_item(idx, url, "done", 100.0)
            else:
                if outcome.failure:
                    log(f"  [#{idx}] {outcome.failure.label}: {outcome.failure.remedy}", "warn")
                else:
                    log(f"  [#{idx}] Download failed.", "error")
                on_item(idx, url, "failed", None)
                result.failures.append((idx, url, outcome.failure))

    result.succeeded = done[0]
    result.failed = total - done[0]
    return result
