# BRIEF — YT-DLP Zero-Touch

Zero-touch video and image downloader for Windows and Premiere Pro.

## Goal
Provide a seamless, zero-touch media downloading pipeline on Windows for video editors.
Links pasted into a text file or GUI queue produce Premiere Pro-ready files (native H.264/AAC MP4 or ProRes 422 Proxy MOV) without manual transcoding or remuxing.

## Constraints
- **Platform**: Windows 10/11 with Python 3.10+, ffmpeg/ffprobe, and Playwright Chromium.
- **Premiere Pro Invariant**: Every downloaded video must open directly in Adobe Premiere Pro. Format must be valid H.264/AAC in MP4 or ProRes 422 Proxy in MOV with faststart flags.
- **Transcode Gate**: Software encodes (`libx264`, ProRes Proxy) are strictly serialized through `_TRANSCODE_GATE` to prevent multi-GB OOM crashes on concurrent 4K footage. Hardware NVENC encodes bypass the gate.
- **Container Commitment**: Output container (`mp4` or `mov`) is committed upfront; post-download `ffprobe` verification checks every file and fails immediately if codecs mismatch.
- **Ponytail Constants**: Deliberate module-level defaults tuned for a single editor on a dedicated workstation (not multi-tenant or multi-platform).

## Decisions in Force
- **D001 / D004**: Modular architecture split into `src/yt_zero_touch` with thin backward-compatible entrypoint forwarding shims (`app.py`, `watcher.py`).
- **D002**: Atomic thread-safe URL history persistence via `HistoryStore` (`processed_urls.json`).
- **D003**: Strongly typed configuration via `AppSettings` (`settings.json`).
- **D005**: Eliminated unnecessary abstract `BaseEngine` hierarchy; dispatch uses direct URL pattern branches in `download_ytdlp`.
- **D006**: Unified URL history file shared across GUI and CLI watcher frontends.
- **ADR-0001 to ADR-0006**: Documented architectural decision records in `docs/adr/`.

## Observable Acceptance Criteria
1. CLI Watcher polls `urls.txt` and processes incoming URLs automatically.
2. Desktop GUI provides Fluent Dark controls, link queue, clipboard watcher, and profile switches.
3. Supported sources (YouTube, Instagram, X/Twitter, Google Drive, Brightcove embeds) download or fall back to image extractors cleanly.
4. Downloaded video files verify as H.264 or ProRes via `ffprobe` before marking complete.
5. All 134 regression tests pass via `python -m unittest discover tests`.

## Open Questions & Unknowns
- Upstream anti-bot measures (YouTube PO Token, Instagram session requirements) require occasional manual cookie refreshes (`cookies.txt`).
- Playwright browser binary updates are decoupled from pip package updates.
