"""
YT-DLP Zero-Touch Extraction Watcher
=====================================
Monitors a text file (urls.txt) for video URLs. When new URLs are added,
automatically runs yt-dlp to pull native H.264 video + isolated audio.

Usage:
    python watcher.py                  # Watch urls.txt, download to ./downloads
    python watcher.py -o D:/Videos     # Custom output directory
    python watcher.py --audio-only     # Extract audio only (no video)
    python watcher.py --playlist       # Download full playlists (default: single video)
    python watcher.py --dry-run        # Detect URLs but don't download
    python watcher.py --max-workers 5  # Run up to 5 concurrent downloads

Workflow:
    1. Start the watcher
    2. Open urls.txt
    3. Paste any video URL (one per line)
    4. Save the file — download starts instantly
"""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from pathlib import Path

from ytdlp_skill import (
    Downloader,
    load_history, save_history,
    check_disk_space, has_partial_files, check_dependencies,
    _KNOWN_DOMAINS, _print_log, URL_RE,
)
from orchestrator import download_with_retry, BatchPolicy, DownloadOutcome

# ---------------------------------------------------------------------------
# URL detection — URL_RE comes from ytdlp_skill so the GUI and watcher don't drift.
# ---------------------------------------------------------------------------


def is_known_domain(url: str) -> bool:
    return any(d in url for d in _KNOWN_DOMAINS)


# ---------------------------------------------------------------------------
# File watching
# ---------------------------------------------------------------------------

POLL_INTERVAL = 1.0  # seconds


def read_urls_from_file(path: Path) -> list[str]:
    """Read all URLs from the text file, one per line."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = URL_RE.findall(line)
        urls.extend(found)
    return urls


def _download_worker(
    dl: Downloader,
    url: str,
    out_dir: Path,
    audio_only: bool,
    playlist: bool,
    sub_langs: list[str],
    gallery: bool = False,
) -> DownloadOutcome:
    """Run in a thread — returns a DownloadOutcome (truthy on success, carrying
    the classified failure cause otherwise).

    Shares the orchestrator's retry + permanent-error classification with the
    GUI so a fix to one reaches both.
    """
    policy = BatchPolicy(out_dir=out_dir)  # only retry_max/retry_delays are read here

    def download_fn(log, progress_hook):
        return dl.download(
            url,
            out_dir=out_dir,
            audio_only=audio_only,
            gallery=gallery,
            playlist=playlist,
            write_metadata=True,
            sub_langs=sub_langs,
            log=log,
            progress_hook=progress_hook,
        )

    return download_with_retry(download_fn, policy=policy, url=url, log=_print_log)


def watch(
    url_file: Path,
    out_dir: Path,
    audio_only: bool,
    dry_run: bool,
    cookie_file: Path | None = None,
    max_workers: int = 3,
    playlist: bool = False,
    sub_langs: list[str] | None = None,
    gallery: bool = False,
):
    sub_langs = sub_langs or []
    out_dir.mkdir(parents=True, exist_ok=True)
    history_file = out_dir / "processed_urls.json"
    history      = load_history(history_file)
    history_lock = threading.Lock()
    stats        = {"detected": 0, "downloaded": 0, "failed": 0}
    last_mtime   = 0.0

    # Create the URL file if it doesn't exist
    if not url_file.exists():
        url_file.write_text(
            "# YT-DLP Zero-Touch Extraction\n"
            "# Paste video URLs below, one per line.\n"
            "# Lines starting with # are ignored.\n"
            "# Save the file and downloads start automatically.\n"
            "\n",
            encoding="utf-8",
        )

    print(r"""
  ╔═══════════════════════════════════════════════════════╗
  ║          YT-DLP  ZERO-TOUCH  EXTRACTION              ║
  ║                                                      ║
  ║   Watching urls.txt for video URLs ...                ║
  ║   Paste a link, save the file — download starts.     ║
  ║   Press Ctrl+C to stop.                              ║
  ╚═══════════════════════════════════════════════════════╝
""")
    print(f"  URL file    : {url_file.resolve()}")
    print(f"  Output      : {out_dir.resolve()}")
    _mode = "Photos (gallery-dl)" if gallery else (
        "Audio only" if audio_only else "H.264 video + audio")
    print(f"  Mode        : {_mode}")
    print(f"  Playlist    : {'yes' if playlist else 'no (single video)'}")
    print(f"  Subtitles   : {', '.join(sub_langs) if sub_langs else 'none'}")
    print(f"  Concurrency : {max_workers} worker(s)")
    print(f"  Dry-run     : {dry_run}")
    cookie_label = str(cookie_file) if cookie_file else "none (no login)"
    print(f"  Cookies     : {cookie_label}")
    print(f"  History     : {len(history)} previously processed URLs")
    print()

    in_flight: dict[str, Future] = {}

    with Downloader(cookie_file=cookie_file) as dl:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            try:
                while True:
                    # ── 1. Harvest completed futures ──────────────────────
                    done_urls = [u for u, f in list(in_flight.items()) if f.done()]
                    for url in done_urls:
                        future = in_flight.pop(url)
                        ts = datetime.now().strftime("%H:%M:%S")
                        try:
                            outcome = future.result()
                        except Exception as exc:
                            print(f"[{ts}] Worker exception for {url}: {exc}")
                            outcome = None
                        ok = bool(outcome)

                        # Partial-file guard: if .part files remain, treat as failed
                        if ok and has_partial_files(out_dir):
                            print(f"[{ts}] Partial files detected after download — will retry.")
                            ok = False

                        if ok:
                            stats["downloaded"] += 1
                            with history_lock:
                                history.add(url)
                                save_history(history_file, history)
                            print(f"[{ts}] Done: {url}")
                        else:
                            stats["failed"] += 1
                            failure = getattr(outcome, "failure", None)
                            if failure:
                                print(f"[{ts}] Failed ({failure.label}) — {failure.remedy}: {url}")
                            else:
                                print(f"[{ts}] Failed — will retry next time: {url}")

                    # ── 2. Check for file changes ─────────────────────────
                    try:
                        mtime = url_file.stat().st_mtime
                    except FileNotFoundError:
                        time.sleep(POLL_INTERVAL)
                        continue

                    if mtime != last_mtime:
                        last_mtime = mtime
                        urls = read_urls_from_file(url_file)

                        for url in urls:
                            ts = datetime.now().strftime("%H:%M:%S")

                            with history_lock:
                                already_done = url in history
                            if already_done:
                                print(f"[{ts}] Skipped (already done): {url}")
                                continue
                            if url in in_flight:
                                continue  # already queued

                            label = "known" if is_known_domain(url) else "unknown-site"
                            print(f"[{ts}] Queued ({label}): {url}")
                            stats["detected"] += 1

                            # Disk-space warning
                            ok_space, free_gb = check_disk_space(out_dir)
                            if not ok_space:
                                print(f"[{ts}] WARNING: only {free_gb:.1f} GB free — "
                                      f"download may not complete.")

                            if dry_run:
                                continue

                            future = executor.submit(
                                _download_worker, dl, url, out_dir, audio_only,
                                playlist, sub_langs, gallery,
                            )
                            in_flight[url] = future

                    time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                active = len(in_flight)
                if active:
                    print(f"\n\n  Ctrl+C — waiting for {active} active download(s) to finish…")
                    for url, future in list(in_flight.items()):
                        try:
                            ok = future.result(timeout=600)
                            if ok:
                                with history_lock:
                                    history.add(url)
                                    save_history(history_file, history)
                        except Exception:
                            pass

                print(f"\n  Shutting down.")
                print(f"  Session stats : {stats}")
                print(f"  Total history : {len(history)} URLs\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    base = Path(__file__).parent

    # Dependency check before doing anything else
    if not check_dependencies():
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="Zero-touch yt-dlp file watcher"
    )
    parser.add_argument(
        "-f", "--file",
        default=str(base / "urls.txt"),
        help="Text file to watch for URLs (default: ./urls.txt)",
    )
    parser.add_argument(
        "-o", "--output",
        default=str(base / "downloads"),
        help="Download directory (default: ./downloads)",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio only, skip video",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Download full playlists instead of single videos",
    )
    parser.add_argument(
        "--photos",
        action="store_true",
        help="Photos mode: download images/carousels with gallery-dl "
             "(Instagram, Twitter/X, Reddit, …) instead of video",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect URLs and log them, but don't download",
    )
    parser.add_argument(
        "-c", "--cookies",
        default=None,
        help="Path to a cookies.txt file (Netscape format) for logged-in downloads",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=3,
        help="Maximum concurrent downloads (default: 3)",
    )
    parser.add_argument(
        "--sub-langs",
        default=None,
        help="Comma-separated subtitle language codes, e.g. en,th (default: none)",
    )
    args = parser.parse_args()
    cfile = Path(args.cookies) if args.cookies else None
    sub_langs = [s.strip() for s in args.sub_langs.split(",")] if args.sub_langs else []
    watch(
        Path(args.file),
        Path(args.output),
        args.audio_only,
        args.dry_run,
        cookie_file=cfile,
        max_workers=args.max_workers,
        playlist=args.playlist,
        sub_langs=sub_langs,
        gallery=args.photos,
    )


if __name__ == "__main__":
    main()
