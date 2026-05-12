# Session Log

---

## 2026-05-07

**Summary:** Fixed YouTube Shorts download failure, added Google Drive support, Thai filename fix, and major watcher/skill robustness overhaul.

**Done:**
- `ytdlp_skill.py` — Fixed YouTube Shorts "not available" error by adding `extractor_args: youtube:player_client=ios,web` to both API and subprocess paths
- `ytdlp_skill.py` — Added Google Drive download support via `gdown` library with yt-dlp fallback; added `_gdrive_file_id()`, `_download_gdrive()`, `_GDRIVE_RE` regex
- `ytdlp_skill.py` — Fixed Thai/Unicode filenames being stripped: changed `restrictfilenames=True` → `False` (kept `windowsfilenames=True`)
- `ytdlp_skill.py` — Added `playlist: bool = False` param to `download()`, `_download_api()`, `_download_subprocess()`, `Downloader.download()`; playlist-aware output template
- `ytdlp_skill.py` — Added `write_metadata: bool = True` param; enables `writeinfojson`/`--write-info-json` for `.info.json` sidecar per download
- `ytdlp_skill.py` — Fixed `load_history()` corruption: bad JSON now backs up to `.bak.json` and warns instead of silently resetting
- `ytdlp_skill.py` — Added public helpers: `check_disk_space()`, `has_partial_files()`, `check_dependencies()`
- `watcher.py` — Replaced sequential download loop with `ThreadPoolExecutor` (default 3 workers, `--max-workers` flag)
- `watcher.py` — Reused single Chromium instance via `Downloader` context manager (was launching a new browser per URL)
- `watcher.py` — Added dependency check at startup (`check_dependencies()`) for yt-dlp and ffmpeg
- `watcher.py` — Added disk space warning (<1 GB free) before each queued download
- `watcher.py` — Added partial download detection: scans for `.part` files after each "successful" future; keeps URL out of history if found
- `watcher.py` — Added `--playlist` and `--max-workers` CLI flags; removed unused `--browser` flag
- Committed and pushed to GitHub (`dd24e36` on `master`)

**Decisions:**
- Used `ios` player client for YouTube (not `web`) because it doesn't require a JS runtime/Deno and works natively with Shorts
- Used `gdown` for Google Drive (not raw `requests`) because it handles the virus-scan bypass for large files
- Kept `watchdog` library out — polling at 1s is sufficient for a local file; the dependency isn't worth it
- Skipped quality/resolution selector and desktop notifications (user explicitly excluded items 4 and 6)
- `write_metadata=True` by default so all downloads get `.info.json` sidecars automatically

**Errors/Fixes:**
- YouTube Shorts `ERROR: This video is not available` — caused by fallback to `android_vr` client when no JS runtime found; fixed with `extractor_args ios,web`
- Thai characters in filenames replaced with `_` — caused by `restrictfilenames=True` (ASCII-only); fixed by setting to `False`

**Left to do / Follow-up:**
- Quality/resolution selector (480p / 720p / 1080p / 4K) — skipped this session
- Desktop notification on finish/fail (Windows toast) — skipped this session
- `app.py` not updated to match new `download()` signature (`playlist`, `write_metadata` params)

---

## 2026-05-13

**Summary:** Fixed YouTube download failures caused by new PO-token / JS-challenge anti-bot wall; switched to nightly yt-dlp and PO-token-free player clients; restored Thai filenames in `app.py`.

**Done:**
- `ytdlp_skill.py` + `app.py` — Replaced YouTube `player_client` from `mweb,web` → `tv_simply,android_vr,tv,web` (no PO token, avoids tv DRM experiment)
- `ytdlp_skill.py` + `app.py` — Added `--remote-components ejs:github` / `remote_components: ["ejs:github"]` so yt-dlp auto-fetches the JS challenge solver
- `app.py:334 _update_ytdlp()` — Rewrote update button to use nightly channel (`yt-dlp-nightly-builds` tarball), uses `sys.executable -m pip`, shows before→after version
- `app.py` — Set `restrictfilenames: False` and removed `--restrict-filenames` so Thai/Unicode characters are preserved in filenames (kept `windows-filenames`)
- Installed yt-dlp nightly `2026.5.5.233942` locally (replaced 2-month-old PyPI stable `2026.3.17`)

**Decisions:**
- Use nightly yt-dlp by default — PyPI stable lags YouTube extractor fixes by weeks; the user hit a 2-month-old release while YouTube had rolled out PO tokens
- Picked `tv_simply` + `android_vr` as primary clients — currently the only two that need neither PO token nor JS challenge solving
- Kept `web` as last fallback (works once `ejs:github` auto-fetches the JS solver) instead of recommending manual deno install up front
- Did NOT refactor the duplicated yt-dlp logic in `app.py` (mirrors `ytdlp_skill.py`) — flagged as cleanup but out of scope

**Errors/Fixes:**
- `mweb` PO-token error + JS challenge failure → switched clients away from mweb/ios
- `tv` client DRM-protected via session experiment → added `tv_simply` (different code path) and `android_vr` ahead of it
- After first edit, error persisted → discovered `app.py` has its own duplicated `extractor_args` (lines 609, 662) overriding the skill module
- After update, still old version → root cause: yt-dlp PyPI stable is too old; switched to nightly tarball install
- Thai title stripped from filename → `restrictfilenames=True` was forcing ASCII-only

**Left to do / Follow-up:**
- Refactor `app.py` to call `ytdlp_skill.download()` instead of maintaining a duplicate yt-dlp pipeline (current duplication caused today's "edit didn't take effect" bug)
- If `tv_simply`/`android_vr` get blocked later, document the deno install path (`winget install denoland.deno`) for the `web` client JS fallback
- Update `_update_ytdlp` could optionally check GitHub releases API to surface "new nightly available" without forcing reinstall

---
