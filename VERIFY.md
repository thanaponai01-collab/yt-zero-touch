# VERIFY

Each feature lists the commands that prove it. A check passes when its command exits 0.
Run them all with `verify.py run`.

## Config
- test: `python -m unittest discover -s tests -p test_config.py`
- oracle: tests/test_config.py
- fail-signal: AssertionError: AppSettings load/save mismatch
- fail-proof: Corrupted JSON or unmapped fields cause test_config.py to fail assertion on default or persisted values

## Format Policy
- test: `python -m unittest discover -s tests -p test_format_policy.py`
- oracle: tests/test_format_policy.py
- fail-signal: AssertionError: FORMAT_SORT does not match expected ordering
- fail-proof: Reordering language or resolution fields ahead of format preferences fails test_format_policy.py

## History Store
- test: `python -m unittest discover -s tests -p test_history_store.py`
- oracle: tests/test_history_store.py
- fail-signal: AssertionError: HistoryStore URL persistence failed
- fail-proof: Non-atomic writes or missing lock synchronization fails thread-safety and round-trip assertions in test_history_store.py

## Orchestrator
- test: `python -m unittest discover -s tests -p test_orchestrator.py`
- oracle: tests/test_orchestrator.py
- fail-signal: AssertionError: Orchestrator retry or failure classification mismatch
- fail-proof: Misclassifying permanent errors as transient or omitting alternate player fallback fails test_orchestrator.py

## Package Imports
- test: `python -m unittest discover -s tests -p test_package_imports.py`
- oracle: tests/test_package_imports.py
- fail-signal: ModuleNotFoundError: No module named 'yt_zero_touch'
- fail-proof: Removing __init__.py or misconfiguring pyproject.toml package find causes test_package_imports.py to fail

## Resolver
- test: `python -m unittest discover -s tests -p test_resolver.py`
- oracle: tests/test_resolver.py
- fail-signal: AssertionError: Failed to extract stream URL or Brightcove ID
- fail-proof: Breaking Brightcove regex or stream sniffer fallback fails test_resolver.py assertions

## Transcode Plan
- test: `python -m unittest discover -s tests -p test_transcode_plan.py`
- oracle: tests/test_transcode_plan.py
- fail-signal: AssertionError: Transcode plan codec or gate mismatch
- fail-proof: Allowing concurrent software transcodes or emitting non-Premiere codec arguments fails test_transcode_plan.py

## Watcher
- test: `python -m unittest discover -s tests -p test_watcher.py`
- oracle: tests/test_watcher.py
- fail-signal: AssertionError: Watcher file polling or URL queue error
- fail-proof: Breaking url file parsing or history coordination causes test_watcher.py to fail

## Ytdlp Skill
- test: `python -m unittest discover -s tests -p test_ytdlp_skill.py`
- oracle: tests/test_ytdlp_skill.py
- fail-signal: AssertionError: Engine routing or output container verification failed
- fail-proof: Bypassing gallery-dl on image hosts or silently skipping post-merge verification fails test_ytdlp_skill.py

## Blind spots
- Live external streaming sites (YouTube, Instagram, Google Drive, X/Twitter) are mocked in tests; real downloads depend on external upstream network availability and valid session cookies.
- Hardware NVENC encoding requires a physical NVIDIA GPU with supported drivers; environments without NVENC fall back to software transcoding via CPU.
- Headless browser stream extraction requires Playwright Chromium binaries installed on the host.
