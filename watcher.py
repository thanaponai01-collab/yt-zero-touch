"""
YT-DLP Zero-Touch Extraction Watcher
=====================================
Monitors a text file (urls.txt) for video URLs. When new URLs are added,
automatically runs yt-dlp to pull native H.264 video + isolated audio.

Usage:
    python watcher.py                  # Watch urls.txt, download to ./downloads
    python watcher.py -o D:/Videos     # Custom output directory
    python watcher.py --audio-only     # Extract audio only (no video)
    python watcher.py --dry-run        # Detect URLs but don't download

Workflow:
    1. Start the watcher
    2. Open urls.txt
    3. Paste any video URL (one per line)
    4. Save the file — download starts instantly
"""

import subprocess
import time
import re
import argparse
import json
import http.cookiejar
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

URL_RE = re.compile(
    r'https?://(?:www\.)?'
    r'[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}'
    r'\b[-a-zA-Z0-9()@:%_\+.~#?&/=]*'
)

KNOWN_DOMAINS = {
    "youtube.com", "youtu.be", "m.youtube.com",
    "twitch.tv", "vimeo.com", "dailymotion.com",
    "soundcloud.com", "bandcamp.com", "reddit.com",
    "twitter.com", "x.com", "instagram.com",
    "tiktok.com", "facebook.com", "fb.watch",
    "bilibili.com", "nicovideo.jp", "crunchyroll.com",
}


def is_known_domain(url: str) -> bool:
    for d in KNOWN_DOMAINS:
        if d in url:
            return True
    return False


# ---------------------------------------------------------------------------
# URL resolvers — convert page URLs to direct downloadable URLs
# ---------------------------------------------------------------------------

# Formula1.com: uses Brightcove player (account 6057949432001)
F1_RE = re.compile(r'formula1\.com/en/video/.*?\.(\d{10,})')
# Generic Brightcove: find account ID + video ID in page source
BC_ACCOUNT_RE = re.compile(r'BRIGHTCOVE[_\s]*ACCOUNTID["\s:]+(\d+)', re.IGNORECASE)
BC_VIDEOID_RE = re.compile(r'videoId["\s:=]+["\']?(\d{10,})')


def resolve_url(url: str, cookie_file: Path | None = None) -> str:
    """Try to convert unsupported page URLs to direct Brightcove URLs."""
    # Check if it's a Formula1.com video page
    m = F1_RE.search(url)
    if m:
        video_id = m.group(1)
        bc_url = f"https://players.brightcove.net/6057949432001/default_default/index.html?videoId={video_id}"
        print(f"  -> Resolved F1 URL to Brightcove: {bc_url}")
        return bc_url

    # For other unknown sites, try fetching the page and looking for Brightcove embeds
    if not is_known_domain(url):
        try:
            bc_url = _extract_brightcove_from_page(url, cookie_file)
            if bc_url:
                print(f"  -> Resolved to Brightcove: {bc_url}")
                return bc_url
        except Exception as e:
            print(f"  -> Could not resolve page ({e}), trying URL directly")

    return url


def _extract_brightcove_from_page(url: str, cookie_file: Path | None = None) -> str | None:
    """Fetch a page and look for Brightcove account/video IDs."""
    opener = urllib.request.build_opener()
    if cookie_file and cookie_file.exists():
        cj = http.cookiejar.MozillaCookieJar(str(cookie_file))
        cj.load(ignore_discard=True, ignore_expires=True)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")]

    resp = opener.open(url, timeout=10)
    html = resp.read().decode("utf-8", errors="replace")

    account = BC_ACCOUNT_RE.search(html)
    video_id = BC_VIDEOID_RE.search(html)
    if account and video_id:
        return (f"https://players.brightcove.net/{account.group(1)}"
                f"/default_default/index.html?videoId={video_id.group(1)}")
    return None


# ---------------------------------------------------------------------------
# yt-dlp execution
# ---------------------------------------------------------------------------

FORMAT_VIDEO = (
    "bestvideo[vcodec^=avc1]+bestaudio/bestvideo+bestaudio/best"
)
FORMAT_AUDIO = "bestaudio/best"

OUTPUT_TEMPLATE = "%(title).100B - [%(id)s].%(ext)s"


def build_cmd(url: str, out_dir: Path, audio_only: bool = False,
              browser: str | None = None,
              cookie_file: Path | None = None) -> list[str]:
    fmt = FORMAT_AUDIO if audio_only else FORMAT_VIDEO
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", fmt,
        "--merge-output-format", "mp4" if not audio_only else "opus",
        "-o", str(out_dir / OUTPUT_TEMPLATE),
        "--no-overwrites",
        "--embed-metadata",
        "--embed-thumbnail",
        "--sponsorblock-mark", "all",
        "--restrict-filenames",
        "--windows-filenames",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "all",
        "--sub-format", "srt",
        "--convert-subs", "srt",
    ]
    if cookie_file and cookie_file.exists():
        cmd.extend(["--cookies", str(cookie_file)])
    elif browser:
        cmd.extend(["--cookies-from-browser", browser])
    if audio_only:
        cmd.insert(cmd.index("--merge-output-format"), "--extract-audio")
    cmd.append(url)
    return cmd


def run_download(url: str, out_dir: Path, audio_only: bool, dry_run: bool,
                 browser: str | None = None,
                 cookie_file: Path | None = None) -> bool:
    resolved = resolve_url(url, cookie_file)
    cmd = build_cmd(resolved, out_dir, audio_only, browser, cookie_file)
    tag = "[DRY-RUN] " if dry_run else ""

    print(f"\n{'='*60}")
    print(f" {tag}DOWNLOADING  {'(audio)' if audio_only else '(H.264 + audio)'}")
    print(f" {url}")
    print(f" -> {out_dir}")
    print(f"{'='*60}")
    print(f" cmd: {' '.join(cmd)}\n")

    if dry_run:
        return True

    try:
        proc = subprocess.run(cmd, timeout=600)
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        print("[!] Download timed out after 10 minutes.")
        return False
    except Exception as e:
        print(f"[!] Error: {e}")
        return False


# ---------------------------------------------------------------------------
# History — remember URLs we already processed
# ---------------------------------------------------------------------------

HISTORY_FILE = "processed_urls.json"


def load_history(out_dir: Path) -> set[str]:
    p = out_dir / HISTORY_FILE
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            return set()
    return set()


def save_history(out_dir: Path, history: set[str]):
    p = out_dir / HISTORY_FILE
    p.write_text(json.dumps(sorted(history), indent=2))


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


def watch(url_file: Path, out_dir: Path, audio_only: bool, dry_run: bool,
          browser: str | None = None, cookie_file: Path | None = None):
    out_dir.mkdir(parents=True, exist_ok=True)
    history = load_history(out_dir)
    stats = {"detected": 0, "downloaded": 0, "failed": 0}
    last_mtime = 0.0

    # Create the URL file if it doesn't exist, with instructions
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
    print(f"  URL file : {url_file.resolve()}")
    print(f"  Output   : {out_dir.resolve()}")
    print(f"  Mode     : {'Audio only' if audio_only else 'H.264 video + audio'}")
    print(f"  Dry-run  : {dry_run}")
    cookie_label = str(cookie_file) if cookie_file else (browser or "none (no login)")
    print(f"  Cookies  : {cookie_label}")
    print(f"  History  : {len(history)} previously processed URLs")
    print()

    try:
        while True:
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
                    if url in history:
                        print(f"[{ts}] Skipped (already done): {url}")
                        continue

                    known = is_known_domain(url)
                    label = "known-site" if known else "unknown-site"
                    print(f"[{ts}] New URL ({label}): {url}")

                    stats["detected"] += 1

                    ok = run_download(url, out_dir, audio_only, dry_run, browser, cookie_file)
                    if ok:
                        stats["downloaded"] += 1
                        history.add(url)
                        save_history(out_dir, history)
                    else:
                        stats["failed"] += 1
                        print(f"[{ts}] Failed — URL will be retried next time.")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n\n  Shutting down.")
        print(f"  Session stats: {stats}")
        print(f"  Total history: {len(history)} URLs\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    base = Path(__file__).parent
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
        "--dry-run",
        action="store_true",
        help="Detect URLs and log them, but don't download",
    )
    parser.add_argument(
        "-b", "--browser",
        default=None,
        choices=["chrome", "firefox", "edge", "brave", "opera", "vivaldi"],
        help="Use cookies from this browser for logged-in downloads",
    )
    parser.add_argument(
        "-c", "--cookies",
        default=None,
        help="Path to a cookies.txt file (Netscape format) for logged-in downloads",
    )
    args = parser.parse_args()
    cfile = Path(args.cookies) if args.cookies else None
    watch(Path(args.file), Path(args.output), args.audio_only, args.dry_run,
          args.browser, cfile)


if __name__ == "__main__":
    main()
