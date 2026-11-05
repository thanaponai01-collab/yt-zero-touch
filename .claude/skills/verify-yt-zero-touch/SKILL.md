---
name: verify-yt-zero-touch
description: Drive the real YT-DLP Zero-Touch Tk desktop window (the GUI an editor uses) on Windows, click its actual buttons, run a real download, and capture screenshots, widget state, ffprobe output and the app log as proof. Use when you need to show a GUI change works in the running app, not just in unit tests, or when VERIFY.md says "GUI not launched".
---

# Verify YT-DLP Zero-Touch (desktop GUI)

The primary surface is the Tk window that `run.bat` / `python app.py` opens (`src/yt_zero_touch/ui/app.py`, class `App`). The second surface is the CLI watcher (`python watcher.py`), which the `watcher` scenario drives as a subprocess. Everything goes through one helper, `scripts/drive.py`. Run it from the repo root:

```
python .claude/skills/verify-yt-zero-touch/scripts/drive.py doctor
python .claude/skills/verify-yt-zero-touch/scripts/drive.py run <scenario> [--url URL] [--preset LABEL] [--via button|shortcut] [--timeout SEC] [--keep]
python .claude/skills/verify-yt-zero-touch/scripts/drive.py cleanup
```

Scenarios: `smoke`, `download`, `preset`, `load-urls`, `clipboard`, `settings-restart`, `watcher`. Exit code 0 means every check passed.

## Launch

There's no server. Each `run` is a single short-lived Python process. It:

1. Creates a fresh instance dir at `.claude/verify-runs/<run-id>/`. This becomes the app's `base_dir`, so `settings.json`, `processed_urls.json`, `urls.txt` and `downloads/` all live there instead of in the user's repo-root copies.
2. Writes a current `.last_update_check` stamp there. The app's own weekly check then decides no update is due, so a launch never runs `pip install --upgrade yt-dlp gallery-dl`.
3. Constructs `App(base_dir=...)`, retrying up to 4 times on the spurious Windows `tk.tcl` TclError, and shows the window topmost at +40+40.
4. Treats the app as **ready** once the diagnostics log contains `System initialized`.

Because every run has its own `base_dir`, two runs can go side by side. They do share the system clipboard and the screen, though, so never run `clipboard` alongside anything else. Never drive the user's own `run.bat` window. It uses the repo-root settings, history and downloads.

Teardown happens inside the run. The helper calls `App._on_close()` (what the window's X button does), saves the evidence, then deletes the instance dir. Pass `--keep` to inspect it afterward, and run `cleanup` when you're done.

## Doctor

Run `drive.py doctor` first, and again whenever anything looks off. It's read-only. It checks Python ≥3.10, tkinter, that `yt_zero_touch` imports from this checkout's `src/`, the yt-dlp version, ffmpeg and ffprobe on PATH (a missing ffmpeg fails muxing), gallery-dl (only the Photos preset needs it), and Pillow ImageGrab (needed for screenshots). It also prints the git HEAD with a note if `src/` has uncommitted changes, plus any driver processes from earlier runs that are still alive. Any `[FAIL]` line means the instance isn't worth driving.

## Drive

The helper drives the window the way a user does, through the widgets' own handlers:

- **Clicks** use `Harness.click(text)`. It finds the first `Button` whose label *contains* `text` and calls `.invoke()`, which runs the same command a mouse click runs. Stable label handles from `ui/app.py`:
  - Preset chips: `Best`, `4K / 2160p`, `1440p QHD`, `1080p FHD`, `720p HD`, `Audio Only`, `Photos / dl`
  - Toggle pills (the label flips ○/● when toggled, so match on the stable part): `Clipboard Watcher`, `ProRes 422 Proxy`, `English (en)`, `Thai (th)`, `Skip History` (becomes `Force Re-download` when on)
  - Actions: `START ZERO-TOUCH PIPELINE`, `Load urls.txt`, `Clear`, `Clear finished`, `Retry Failed`, `Open Output Folder`, `Update Tools`, `Cookie file…`, `Login Vault…`, `Change folder…`
- **Typing** uses `Harness.type_urls(text)`. It inserts into `url_box` and fires `<KeyRelease>`, which is what refreshes the `N links ready` counter.
- **The shortcut** is `Harness.press_ctrl_enter()`. It fires `<Control-Return>` on the URL box, which is the documented Ctrl+Enter start.
- **Waiting** uses `Harness.pump(cond, timeout, what)`. It runs real `mainloop()` slices. Don't replace it with `update()`. The download worker thread reads Tk variables, and without a running mainloop it dies with `RuntimeError: main thread is not in main loop` while the queue sits at `Queued`.

To add a journey, write a `sc_<name>(h, a)` function in `drive.py` and register it in `SCENARIOS`. Keep to `click`, `type_urls`, `press_ctrl_enter` and `pump`. Calling `App` internals such as `_start_download` or `quality.set` skips the user path. Don't do it, except to stage preconditions the user would have staged themselves, like a `urls.txt` on disk.

The feature recipes live in [features/README.md](features/README.md).

## Evidence

Every run writes to `.claude/verify-evidence/<run-id>/`, which is gitignored and survives cleanup:

- `NN-<label>.png`: a screenshot of the app window, captured by HWND
- `NN-<label>.state.json`: widget state at the same moment (status bar, link counter, quality, profile summary, Start button text and state, URL box, queue rows)
- `app-log.txt`: the full diagnostics log panel
- `ffprobe.json`: streams of every media file written (`download` only)
- `result.json`: the scenario, its args, every check with pass/fail, and the files the instance dir held before deletion

Proof standards:

- Drive the real user path: button invoke, key events, real yt-dlp, real ffmpeg. No `run_batch` stub. The unit suite (`tests/test_gui_smoke.py`) already covers stubbed paths, and this skill exists to cover what it can't.
- Capture before, during and after, not just the final screen. `download` snapshots `before-start`, `running` and `finished`.
- Check side effects next to what's visible. For a download, that means the media file exists, ffprobe shows h264 (or prores) video plus an audio stream, the URL is in the instance's `processed_urls.json`, and the queue row shows `Done`.
- A run that times out or throws is a failure. Report it with its evidence dir. Don't re-run with weaker checks.

## Cleanup

`drive.py cleanup` kills only PIDs recorded in `.claude/verify-runs/*/*.pid` (`driver.pid`, plus `child.pid` for the watcher subprocess), using `taskkill /PID <pid> /T`, never by process name. Then it deletes `.claude/verify-runs/`. It never touches `.claude/verify-evidence/`. Run it after every failed or interrupted iteration, and after any `--keep` run.

## Gotchas

- `URL_RE` (`core/models.py`) used to cap the TLD at 6 characters, so `.example` and `.photography` links were invisible. That's fixed, and `load-urls` keeps a `c.example` link in its fixture to guard it. If that check fails, the regex has regressed.
- `download` needs network access and takes about 45 s for the default 19 s clip (`jNQXAC9IVRw`). The MP4 also carries an embedded PNG thumbnail as a second "video" stream. Assert that h264 is *among* the video codecs, not that it's the only one.
- A successful batch raises a Windows toast through plyer. That's expected, not a stray window.
- `Open Output Folder` launches Explorer, and `Update Tools` really pip-upgrades packages. Neither is scripted. Don't click either unless that's the change under test, and say so in the report if you do.
- A screenshot can fail with `OSError('screen grab failed')` when the session is locked or the window is off-screen. The `.state.json` is still written. Report the missing image rather than skipping it silently.
