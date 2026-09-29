# VERIFY

Each feature lists the commands that prove it. A check passes when its command exits 0.
Run them all with `verify.py run`.

## Download batch
- test: `python -m pytest tests/test_orchestrator.py -q`
- fail-proof: [Orchestrator] is_permanent_error always False in src/yt_zero_touch/core/failures.py, and the already-downloaded skip disabled in src/.../services/orchestrator.py; test_orchestrator.py went red, reverted (git diff empty)
- test: `python -m pytest tests/test_history_store.py -q`
- fail-proof: [History Store] contains() always False in src/yt_zero_touch/core/history.py; test_history_store.py went red, reverted (git diff empty)
- test: `python -m pytest tests/test_resolver.py -q`
- fail-proof: [Resolver] all-videos helper always None, and id scan limited to the first video, in src/yt_zero_touch/services/resolver.py; [Orchestrator fan-out] only the first resolved video queued, in services/orchestrator.py; [GUI queue] no row created for an extra video, in ui/app.py: each turned its test red, reverted (git diff empty)
- test: `python -m pytest tests/test_transcode_plan.py -q`
- fail-proof: [Transcode Plan] _codec_case returned non_h264 for h264 in src/yt_zero_touch/core/transcode.py; test_transcode_plan.py went red, reverted (git diff empty)
- test: `python -m pytest tests/test_ytdlp_skill.py -q`
- fail-proof: [Ytdlp Skill] is_image_host inverted in src/yt_zero_touch/core/models.py; test_ytdlp_skill.py went red, reverted (git diff empty)
- test: `python -m pytest tests/test_package_imports.py -q`
- fail-proof: [Package Imports] misspelled a re-exported import in src/yt_zero_touch/core/__init__.py; test_package_imports.py went red, reverted (git diff empty)

## GUI
- test: `python -m pytest tests/test_gui_smoke.py -q`
- fail-proof: [start button] audio flag ignored, and the no-URL guard removed: test_start_button / test_start_with_nothing red; [link count] wrong count text; [load urls.txt] dedupe removed; [clear finished] filter disabled; [settings] quality not restored; [clipboard] poll disabled: each turned test_gui_smoke red in src/yt_zero_touch/ui/app.py, reverted (git diff empty)

## Update tools
- test: `python -m pytest tests/test_services.py -q`
- fail-proof: [updater] version-change check forced true, pip-failure branch disabled, weekly scheduler always False; [system] disk check always True, check_ffmpeg always True, deno home path misspelled: each turned test_services red in src/yt_zero_touch/services/, reverted (git diff empty)

## Config
- test: `python -m pytest tests/test_config.py -q`
- fail-proof: default quality Best -> Worst in src/yt_zero_touch/core/config.py; test_config.py went red, reverted (git diff empty)

## Format Policy
- test: `python -m pytest tests/test_format_policy.py -q`
- fail-proof: emptied DONT_CAP_RESOLUTION in src/yt_zero_touch/core/format_policy.py; test_format_policy.py went red, reverted (git diff empty)

## Watcher
- test: `python -m pytest tests/test_watcher.py -q`
- fail-proof: _harvest_completed stopped recording history in src/yt_zero_touch/ui/cli/watcher.py; test_watcher.py went red, reverted (git diff empty)

## Blind spots
- No real-run check: nothing downloads a real URL (yt-dlp, gallery-dl, gdown, Playwright and ffmpeg are not exercised end to end). update_tools is tested with subprocess faked, never against real pip.
- The GUI smoke drives 7 handlers on a hidden real window (run_batch stubbed for the start button); it does not check layout or a real download. The Tk window is created once per run, with retries for a spurious Windows 'tk.tcl' startup error (0 failures in 12 consecutive runs after the retry was added; it flaked about 1 in 3 before).
- Engines: only the yt-dlp engine is exercised (through `tests/test_ytdlp_skill.py`, with yt-dlp faked); `gallery_engine.py` and `gdrive_engine.py` have no test beyond the import check. `ui/state.py` is not imported by anything.
