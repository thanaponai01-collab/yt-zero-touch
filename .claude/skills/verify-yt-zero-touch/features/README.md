# YT-DLP Zero-Touch verification map

This directory is the maintained source for verifying what an editor can do in the Zero-Touch desktop window. Read this index before you drive the app, then use the matching feature file as the recipe. `drive.py` below means `python .claude/skills/verify-yt-zero-touch/scripts/drive.py`, run from the repo root.

## Baseline preconditions

- `drive.py doctor` prints no `[FAIL]` lines.
- Each run gets a fresh `base_dir` under `.claude/verify-runs/<run-id>/`: no settings, no history, `downloads/` empty, update stamp current.
- Never drive the user's own `run.bat` window or the repo-root `settings.json`, `processed_urls.json` or `downloads/`.

## Driving conventions

- Every action goes through `drive.py`, using `click(label)`, `type_urls`, `press_ctrl_enter` and `pump`. Never call `App` internals to perform the action under test.
- Match buttons by the stable part of the label. Toggle pills flip ○/● when toggled.
- Run `drive.py cleanup` after any failed, interrupted or `--keep` run.

## Proof and skip reporting

- Proof is a `result.json` with every check passing, plus before, during and after `.png` and `.state.json` files in `.claude/verify-evidence/<run-id>/`.
- For a change that touches downloading, also check the side effects: the media file, ffprobe codecs, and the history entry.
- If you couldn't reach an entry point, report the command you tried and the precondition that wasn't met. A pass through the Start button doesn't verify the Ctrl+Enter path.

## Feature entry contract

Each feature file has an H1, one paragraph, and then these four H2 sections in order: `Sub-features`, `How to get to it (user POV)`, `Driving it with drive.py`, `Gotchas`.

## Features

- [Download batch](./download-batch.md) pastes a link, starts the pipeline, and gets a Premiere-ready H.264 MP4 plus a history entry.
- [Quality presets and toggles](./quality-presets.md) covers the preset chips and the ProRes toggle, and that each one persists to settings.
- [Load urls.txt](./load-urls.md) appends new links from `urls.txt` and skips ones already in the box.
- [Clipboard watcher](./clipboard-watcher.md) auto-inserts any link copied while the watcher is on.
- [Settings memory](./settings-memory.md) restores choices after a close and relaunch.
- [CLI watcher](./cli-watcher.md) watches a `urls.txt`, downloads each newly saved link, and records it in history.

Not mapped yet:

- CLI watcher flags beyond the defaults: `--dry-run`, `--audio-only`, `--photos`, `--prores`, `--sections`, `--sub-langs`.
- `Clear finished` and `Retry Failed`.
- Login Vault and cookie status.
- Photos (gallery-dl) and Google Drive links.
- Trim range.
- `Open Output Folder` and `Update Tools`.
