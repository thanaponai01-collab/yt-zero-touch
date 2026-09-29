# FEATURES

Windows desktop app (Tk) and a CLI watcher that download video/photos and prepare Premiere-ready files.
Start the GUI: `run.bat` or `python app.py`. Start the watcher: `python watcher.py`.

## Download batch (GUI)
- what: Paste URLs, choose quality, run the resolve → download → merge pipeline with a live queue table.
- click: `START ZERO-TOUCH PIPELINE` @ src/yt_zero_touch/ui/app.py :: _start_download
- shortcut: `Ctrl+Enter` @ src/yt_zero_touch/ui/app.py :: <Control-Return>
- trace: `_start_download` @ src/yt_zero_touch/ui/app.py > `_download_worker` @ src/yt_zero_touch/ui/app.py > `run_batch` @ src/yt_zero_touch/services/orchestrator.py > `download_with_retry` @ src/yt_zero_touch/services/orchestrator.py
- verify: Download batch
- status: traced: read the chain; GUI not launched

## Quality and encoding options (GUI)
- what: Pick Best/4K/1080p/720p/480p/Audio only/Photos, optional ProRes 422 Proxy MOV, subtitles, trim range.
- click: `_set_preset` @ src/yt_zero_touch/ui/app.py
- click: `○ ProRes 422 Proxy [MOV]` @ src/yt_zero_touch/ui/app.py :: label_off
- trace: `_set_preset` @ src/yt_zero_touch/ui/app.py > `_update_profile_summary` @ src/yt_zero_touch/ui/app.py
- verify: Format Policy
- status: traced: read the chain; GUI not launched

## Load urls.txt (GUI)
- what: Append new links from urls.txt into the URL box.
- click: `Load urls.txt` @ src/yt_zero_touch/ui/app.py :: _load_from_urls_file
- trace: `_load_from_urls_file` @ src/yt_zero_touch/ui/app.py > `_update_link_count` @ src/yt_zero_touch/ui/app.py
- verify: GUI
- status: traced: read the chain; GUI not launched

## Clipboard watcher (GUI)
- what: While on, any link copied anywhere is added to the URL box.
- click: `○ Clipboard Watcher: OFF` @ src/yt_zero_touch/ui/app.py :: label_off
- trace: `_on_clip_toggled` @ src/yt_zero_touch/ui/app.py > `_poll_clipboard` @ src/yt_zero_touch/ui/app.py
- verify: GUI
- status: traced: read the chain; GUI not launched

## Update tools (GUI)
- what: Upgrade yt-dlp and gallery-dl on demand, and quietly once a week.
- click: `Update Tools` @ src/yt_zero_touch/ui/app.py :: _update_ytdlp
- trace: `_update_ytdlp` @ src/yt_zero_touch/ui/app.py > `update_tools` @ src/yt_zero_touch/services/updater.py
- effect: pip upgrades of yt-dlp / gallery-dl
- verify: Update tools
- status: traced: read the chain; tested with subprocess faked, never run against real pip

## Settings memory (GUI)
- what: Output folder, quality, cookies, subtitles, trim and toggles restored on next launch (automatic at startup, no entry point).
- trace: `_load_settings` @ src/yt_zero_touch/ui/app.py > `load` @ src/yt_zero_touch/core/config.py
- verify: Config
- status: traced: read the chain; GUI not launched

## Output folder and queue housekeeping (GUI)
- what: Open the download folder; clear finished queue rows.
- click: `Open Output Folder` @ src/yt_zero_touch/ui/app.py :: _open_folder
- click: `Clear finished` @ src/yt_zero_touch/ui/app.py :: _clear_finished_rows
- trace: `_clear_finished_rows` @ src/yt_zero_touch/ui/app.py > `_queue_rows` @ src/yt_zero_touch/ui/app.py
- effect: `_open_folder` runs `explorer` on the output folder, creating it if missing
- verify: GUI
- status: traced: read both handlers; GUI not launched

## URL file watcher (CLI)
- what: Watch urls.txt, download each new URL concurrently, record finished ones in history.
- cli: `python watcher.py` @ src/yt_zero_touch/ui/cli/watcher.py :: add_argument("-f"
- cli: `--dry-run` @ src/yt_zero_touch/ui/cli/watcher.py :: --dry-run
- trace: `main` @ src/yt_zero_touch/ui/cli/watcher.py > `watch` @ src/yt_zero_touch/ui/cli/watcher.py > `_harvest_completed` @ src/yt_zero_touch/ui/cli/watcher.py
- verify: Watcher
- status: proven @ e66b47f: `python watcher.py --help` prints usage (re-run after the flatten/wip merge); the watch loop itself was not run
