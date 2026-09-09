"""
YT-DLP Zero-Touch Extraction Watcher
=====================================
Monitors a text file (urls.txt) for video URLs. When new URLs are added,
automatically runs yt-dlp to pull native H.264 video + isolated audio.
"""

from __future__ import annotations

import argparse
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from yt_zero_touch.core.history import HistoryStore, load_history, save_history
from yt_zero_touch.core.models import URL_RE
from yt_zero_touch.engines.ytdlp_engine import Downloader
from yt_zero_touch.services.orchestrator import (
    CLIENT_RETRY_FALLBACK_CLIENT,
    LOGIN_WALL_FALLBACK_CLIENT,
    DownloadOutcome,
    download_with_retry,
)
from yt_zero_touch.services.resolver import _KNOWN_DOMAINS, _print_log
from yt_zero_touch.services.system import check_dependencies, check_disk_space

POLL_INTERVAL = 1.0


def is_known_domain(url: str) -> bool:
    return any(d in url for d in _KNOWN_DOMAINS)


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
    sections: str | None = None,
    target_codec: str = "h264",
) -> DownloadOutcome:
    def _make_fn(player_client: str | None = None):
        def download_fn(log, progress_hook):
            return dl.download(
                url,
                out_dir=out_dir,
                audio_only=audio_only,
                gallery=gallery,
                playlist=playlist,
                write_metadata=True,
                sub_langs=sub_langs,
                sections=None if gallery else sections,
                target_codec=target_codec,
                log=log,
                progress_hook=progress_hook,
                player_client=player_client,
            )
        return download_fn

    return download_with_retry(
        _make_fn(), url=url, log=_print_log,
        login_wall_fallback_fn=None if gallery else _make_fn(LOGIN_WALL_FALLBACK_CLIENT),
        client_retry_fallback_fn=None if gallery else _make_fn(CLIENT_RETRY_FALLBACK_CLIENT),
    )


def _harvest_completed(
    in_flight: dict[str, Future],
    *,
    history: set[str],
    history_lock: threading.Lock,
    history_file: Path,
    stats: dict[str, int],
) -> None:
    """Record every download that has finished, and drop it from in_flight."""
    for url in [u for u, f in list(in_flight.items()) if f.done()]:
        future = in_flight.pop(url)
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            outcome = future.result()
        except Exception as exc:
            print(f"[{ts}] Worker exception for {url}: {exc}")
            outcome = None

        if outcome:
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
    sections: str | None = None,
    target_codec: str = "h264",
):
    sub_langs = sub_langs or []
    out_dir.mkdir(parents=True, exist_ok=True)
    history_file = out_dir / "processed_urls.json"
    history = load_history(history_file)
    history_lock = threading.Lock()
    stats = {"detected": 0, "downloaded": 0, "failed": 0}
    last_mtime = 0.0

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
        "Audio only" if audio_only else
        ("ProRes 422 Proxy video + audio" if target_codec == "prores"
         else "H.264 video + audio"))
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
                    _harvest_completed(
                        in_flight,
                        history=history,
                        history_lock=history_lock,
                        history_file=history_file,
                        stats=stats,
                    )

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
                                continue

                            label = "known" if is_known_domain(url) else "unknown-site"
                            print(f"[{ts}] Queued ({label}): {url}")
                            stats["detected"] += 1

                            ok_space, free_gb = check_disk_space(out_dir)
                            if not ok_space:
                                print(f"[{ts}] WARNING: only {free_gb:.1f} GB free — "
                                      f"download may not complete.")

                            if dry_run:
                                continue

                            future = executor.submit(
                                _download_worker, dl, url, out_dir, audio_only,
                                playlist, sub_langs, gallery, sections, target_codec,
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


def main():
    base = Path(__file__).resolve().parent.parent.parent.parent
    if not check_dependencies():
        raise SystemExit(1)

    parser = argparse.ArgumentParser(description="Zero-touch yt-dlp file watcher")
    parser.add_argument("-f", "--file", default=str(base / "urls.txt"), help="Text file to watch")
    parser.add_argument("-o", "--output", default=str(base / "downloads"), help="Download directory")
    parser.add_argument("--audio-only", action="store_true", help="Extract audio only")
    parser.add_argument("--playlist", action="store_true", help="Download full playlists")
    parser.add_argument("--photos", action="store_true", help="Photos mode with gallery-dl")
    parser.add_argument("--dry-run", action="store_true", help="Detect but do not download")
    parser.add_argument("-c", "--cookies", default=None, help="Path to cookies.txt")
    parser.add_argument("--max-workers", type=int, default=3, help="Concurrent worker count")
    parser.add_argument("--sub-langs", default=None, help="Comma-separated subtitle lang codes")
    parser.add_argument("--sections", default=None, help="Clip trim range e.g. 10:00-20:00")
    parser.add_argument("--prores", "--prores-proxy", dest="prores_proxy", action="store_true", help="Target ProRes 422 Proxy MOV")
    args = parser.parse_args()

    sub_langs = args.sub_langs.split(",") if args.sub_langs else []
    cookie_path = Path(args.cookies) if args.cookies else None
    target_codec = "prores" if args.prores_proxy else "h264"

    watch(
        url_file=Path(args.file),
        out_dir=Path(args.output),
        audio_only=args.audio_only,
        dry_run=args.dry_run,
        cookie_file=cookie_path,
        max_workers=args.max_workers,
        playlist=args.playlist,
        sub_langs=sub_langs,
        gallery=args.photos,
        sections=args.sections,
        target_codec=target_codec,
    )


if __name__ == "__main__":
    main()
