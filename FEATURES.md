# FEATURES

What the system has and how each feature is reached. `features.py check` tests every entry
point against the code.

## Watcher
- what: Automated background CLI daemon monitoring a text file for URLs to download.
- cli: `python watcher.py` @ watcher.py :: main
- trace: `main` @ watcher.py > `watch` @ src/yt_zero_touch/ui/cli/watcher.py > `read_urls_from_file` @ src/yt_zero_touch/ui/cli/watcher.py
- verify: Watcher
- status: proven @ 31641f1: test_watcher.py verifies file polling, url extraction, and history coordination

## Package Imports
- what: Modular Python package structure with clean entry points and scripts.
- cli: `python app.py` @ app.py :: main
- trace: `main` @ app.py > `App` @ src/yt_zero_touch/ui/app.py > `main` @ src/yt_zero_touch/ui/app.py
- verify: Package Imports
- status: proven @ 31641f1: test_package_imports.py verifies package discoverability and clean module imports

## Config
- what: Strongly typed application settings persistence with JSON serialization.
- trace: `App` @ src/yt_zero_touch/ui/app.py > `AppSettings` @ src/yt_zero_touch/core/config.py
- verify: Config
- status: proven @ 31641f1: test_config.py verifies JSON load/save round-trip persistence

## History Store
- what: Atomic thread-safe tracking of downloaded URLs to skip duplicates.
- trace: `HistoryStore` @ src/yt_zero_touch/core/history.py > `load` @ src/yt_zero_touch/core/history.py > `save` @ src/yt_zero_touch/core/history.py
- verify: History Store
- status: proven @ 31641f1: test_history_store.py verifies atomic disk serialization and deduplication

## Format Policy
- what: Intelligent format selection, language preservation, and video/audio sorting.
- trace: `FORMAT_SORT` @ src/yt_zero_touch/core/format_policy.py > `PREFER_ORIGINAL_AUDIO_TRACK` @ src/yt_zero_touch/core/format_policy.py > `DONT_CAP_RESOLUTION` @ src/yt_zero_touch/core/format_policy.py
- verify: Format Policy
- status: proven @ 31641f1: test_format_policy.py verifies codec prioritization and resolution tiebreaking

## Transcode Plan
- what: Ffmpeg transcode planning, NVENC hardware check, transcode gate, and container commitments.
- trace: `plan_transcode` @ src/yt_zero_touch/core/transcode.py > `_h264_encoder` @ src/yt_zero_touch/core/transcode.py > `_nvenc_available` @ src/yt_zero_touch/core/transcode.py
- verify: Transcode Plan
- status: proven @ 31641f1: test_transcode_plan.py verifies gate locking, NVENC routing, and Premiere-safe codecs

## Resolver
- what: Headless browser stream extraction and Brightcove scraping for obscure video players.
- trace: `resolve_url` @ src/yt_zero_touch/services/resolver.py > `resolve_urls` @ src/yt_zero_touch/services/resolver.py > `_intercept` @ src/yt_zero_touch/services/resolver.py
- verify: Resolver
- status: proven @ 31641f1: test_resolver.py verifies domain matching and sniffing fallbacks

## Orchestrator
- what: Multi-worker concurrent download pool with exponential backoff retry and failure classification.
- trace: `run_batch` @ src/yt_zero_touch/services/orchestrator.py > `download_with_retry` @ src/yt_zero_touch/services/orchestrator.py > `classify_failure` @ src/yt_zero_touch/core/failures.py
- verify: Orchestrator
- status: proven @ 31641f1: test_orchestrator.py verifies retry loop, alternate player fallback, and failure classifier

## Ytdlp Skill
- what: Engine adapter for yt-dlp, gallery-dl image host routing, and post-merge verification.
- trace: `download_ytdlp` @ src/yt_zero_touch/engines/ytdlp_engine.py > `merge_session` @ src/yt_zero_touch/core/transcode.py > `_MergeSession` @ src/yt_zero_touch/core/transcode.py
- verify: Ytdlp Skill
- status: proven @ 31641f1: test_ytdlp_skill.py verifies engine dispatch, photo fallbacks, and output codec enforcement
