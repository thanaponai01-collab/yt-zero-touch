# VERIFY

Each feature lists the commands that prove it. A check passes when its command exits 0.
Run them all with `verify.py run`.

## Download batch
- path: src/yt_zero_touch/services/orchestrator.py, src/yt_zero_touch/services/resolver.py, src/yt_zero_touch/core/history.py, src/yt_zero_touch/core/failures.py, src/yt_zero_touch/core/transcode.py, src/yt_zero_touch/core/models.py, src/yt_zero_touch/core/__init__.py, src/yt_zero_touch/engines/ytdlp_engine.py
- fail-signal: test_already_downloaded_urls_are_skipped
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

## Link detection
- path: src/yt_zero_touch/core/models.py, src/yt_zero_touch/ui/cli/watcher.py
- fail-signal: test_long_tlds_are_links
- test: `python -m pytest tests/test_url_re.py -q`
- fail-proof: TLD cap at 6 characters (`{1,6}`) in URL_RE, re-caught by `verify.py challenge` on 2026-11-09; (src/yt_zero_touch/core/models.py) is the original bug; test_url_re.py was red against it before the fix

## Real-app runs
- path: src/yt_zero_touch/ui/app.py, src/yt_zero_touch/ui/layout.py
- test: `python .claude/skills/verify-yt-zero-touch/scripts/drive.py run smoke`
- fail-signal: [FAIL] window title
- fail-proof: window title changed to "YT-DLP" in src/yt_zero_touch/ui/app.py; `verify.py challenge` caught it (smoke printed [FAIL] window title), scratch copy
`smoke` needs a desktop session (no network). The other scenarios (`download`, `watcher`, `preset`, `load-urls`, `clipboard`, `settings-restart`) take real time and `download`/`watcher` need network, so they stay out of `verify.py run`: run them by hand for GUI or pipeline changes; evidence lands in `.claude/verify-evidence/<run-id>/`

## GUI
- path: src/yt_zero_touch/ui/app.py, src/yt_zero_touch/ui/layout.py
- fail-signal: test_retry_failed_mid_batch_must_not_clobber_input
- test: `python -m pytest tests/test_gui_smoke.py tests/test_retry_while_running.py -q`
- fail-proof: [start button] audio flag ignored, and the no-URL guard removed: test_start_button / test_start_with_nothing red; [link count] wrong count text; [load urls.txt] dedupe removed; [clear finished] filter disabled; [settings] quality not restored; [clipboard] poll disabled: each turned test_gui_smoke red in src/yt_zero_touch/ui/app.py, reverted (git diff empty)

## Update tools
- path: src/yt_zero_touch/services/updater.py, src/yt_zero_touch/services/system.py
- fail-signal: test_find_deno
- test: `python -m pytest tests/test_services.py tests/test_system.py tests/test_updater.py -q`
- fail-proof: [updater] version-change check forced true, pip-failure branch disabled, weekly scheduler always False; [system] disk check always True, check_ffmpeg always True, deno home path misspelled: each turned test_services red in src/yt_zero_touch/services/, reverted (git diff empty)

## Engines
- path: src/yt_zero_touch/engines/gallery_engine.py, src/yt_zero_touch/engines/gdrive_engine.py, src/yt_zero_touch/engines/base.py
- fail-signal: test_success_uses_the_uc_url_and_creates_the_folder
- test: `python -m pytest tests/test_engines.py -q`
- fail-proof: [gdrive] id regex, uc url, no-output branch, exception handler; [gallery] login hosts, instagram args, --no-skip, empty-success rule, login-sign list, plain-failure stop, browser auto-try, browser order: 12 breaks in src/yt_zero_touch/engines/, each turned test_engines red, reverted (git diff empty). Four first survived (weak assertions); tests were tightened and all 12 then went red

## Config
- path: src/yt_zero_touch/core/config.py
- fail-signal: 'Worst' != 'Best'
- test: `python -m pytest tests/test_config.py -q`
- fail-proof: default quality Best -> Worst in src/yt_zero_touch/core/config.py; test_config.py went red, reverted (git diff empty)

## Format Policy
- path: src/yt_zero_touch/core/format_policy.py
- fail-signal: test_res_and_fps_are_the_fields
- test: `python -m pytest tests/test_format_policy.py -q`
- fail-proof: emptied DONT_CAP_RESOLUTION in src/yt_zero_touch/core/format_policy.py; test_format_policy.py went red, reverted (git diff empty)

## Watcher
- path: src/yt_zero_touch/ui/cli/watcher.py
- fail-signal: test_history_is_persisted_so_the_url_is_not_downloaded_again
- test: `python -m pytest tests/test_watcher.py -q`
- fail-proof: _harvest_completed stopped recording history in src/yt_zero_touch/ui/cli/watcher.py; test_watcher.py went red, reverted (git diff empty)

## Cookies and login vault
- path: src/yt_zero_touch/core/cookies.py, src/yt_zero_touch/services/cookie_vault.py
- fail-signal: test_inspect_expired_and_active_cookies
- test: `python -m pytest tests/test_cookies.py tests/test_cookie_vault.py tests/test_improvements.py -q`
- fail-proof: expired-cookie test flipped (`r.expires > current_time`) in src/yt_zero_touch/core/cookies.py; `verify.py challenge` caught it (test_inspect_expired_and_active_cookies red), scratch copy

## Formal conformance
- path: src/yt_zero_touch/services/orchestrator.py, src/yt_zero_touch/core/transcode.py, src/yt_zero_touch/core/history.py
- test: `python tools/formal/retry_loop/conformance.py`
- test: `python tools/formal/transcode_gate/conformance.py`
- test: `python tools/formal/batch_history/conformance.py`
- oracle: tools/formal/retry_loop/RetryLoop.tla, tools/formal/transcode_gate/MergeGate.tla, tools/formal/batch_history/BatchPipeline.tla
- fail-signal: script=
- fail-proof: retry loop shortened by one attempt (`range(1, retry_max + 1)`) in src/yt_zero_touch/services/orchestrator.py; `verify.py challenge` caught it (retry_loop conformance printed the mismatching script=), scratch copy

## Blind spots
- Real runs cover only yt-dlp + ffmpeg, through the verify skill (`download`, `watcher`). gallery-dl, gdown and Playwright are never run end to end. update_tools is tested with subprocess faked, never against real pip.
- The GUI smoke drives 7 handlers on a hidden real window (run_batch stubbed for the start button); it does not check layout or a real download. The Tk window is created once per run, with retries for a spurious Windows 'tk.tcl' startup error (0 failures in 12 consecutive runs after the retry was added; it flaked about 1 in 3 before).
- Engines: only the yt-dlp engine is exercised (through `tests/test_ytdlp_skill.py`, with yt-dlp faked); `gallery_engine.py` and `gdrive_engine.py` are tested with subprocess and gdown faked; neither tool is ever run for real. `ui/state.py` is not imported by anything.
- `tools/formal/tlc.py` (the TLC model-checker wrapper) and `tools/formal/flows/` (diagram viewers) run only through the verify-retry-loop, verify-transcode-gate and verify-batch-history skills, not `verify.py run`.
- `src/yt_zero_touch/ui/state.py` is not imported by anything.
