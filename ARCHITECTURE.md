# Architecture & System Design — YT-DLP Zero-Touch v2.0

Zero-touch video/photo downloading pipeline for Windows editors producing Premiere-ready files.

---

## 1. System Sketch

```
[UI Layer]
  ├── Desktop GUI (yt_zero_touch.ui.app) <── Tkinter Fluent Dark Theme
  └── CLI Watcher (yt_zero_touch.ui.cli.watcher) <── urls.txt File Poller
        │
        ▼
[Service & Orchestration Layer]
  ├── BatchRunner (yt_zero_touch.services.orchestrator)
  │     ├── Phase 1: Stream Sniffer (yt_zero_touch.services.resolver)
  │     │     └── Headless Playwright / Brightcove Scraper
  │     └── Phase 2: Concurrent Download Pool & Retry Loop
  ├── Tool Auto-Updater (yt_zero_touch.services.updater)
  └── Environment Prober (yt_zero_touch.services.system)
        │
        ▼
[Engine Adapters]  — plain functions, routed by inline branches in download_ytdlp
  ├── download_ytdlp   (yt_zero_touch.engines.ytdlp_engine)  — the default path
  ├── download_gallery (yt_zero_touch.engines.gallery_engine) — gallery/image hosts
  └── download_gdrive  (yt_zero_touch.engines.gdrive_engine)  — Drive share links
        │
        ▼
[Core Domain & Invariants]
  ├── Transcode & Gate (yt_zero_touch.core.transcode) — ADR-0001, ADR-0002, ADR-0003, ADR-0006
  ├── Format Sort Policy (yt_zero_touch.core.format_policy)
  ├── Failure Classifier (yt_zero_touch.core.failures)
  ├── History Store (yt_zero_touch.core.history)
  ├── Configuration Store (yt_zero_touch.core.config)
  └── Domain Models (yt_zero_touch.core.models)
```

---

## 2. Module Boundaries & Forbidden Knowledge

| Module | One-Sentence Responsibility | What It Owns | Forbidden Knowledge (Must Never Know) |
|---|---|---|---|
| `yt_zero_touch.core.transcode` | Governs ffmpeg merge arguments, container commitments, hardware NVENC detection, and transcode gate locking. | `MergeSession`, `TranscodePlan`, `TargetCodec`, `verify_h264_output`, `_TRANSCODE_GATE`. | Knows nothing about Tkinter, UI widgets, network protocols, or batch concurrency. |
| `yt_zero_touch.core.history` | Atomic, thread-safe persistence of downloaded URLs to skip duplicates. | `HistoryStore`, JSON load/save serialization, synchronization locks. | Knows nothing about yt-dlp, downloading status, or ffmpeg. |
| `yt_zero_touch.core.config` | Strongly typed application settings persistence. | `AppSettings` dataclass, JSON mapping, default directory resolution. | Knows nothing about downloading processes or active futures. |
| `yt_zero_touch.core.failures` | Classifies stderr messages into human-remediable causes. | `FailureClass`, failure regex rules, retry eligibility rules. | Knows nothing about the UI or network socket states. |
| `yt_zero_touch.engines.*` | Concrete adapters wrapping third-party tools (yt-dlp, gallery-dl, gdown), plus the branches that choose between them. | Subprocess execution, CLI flag translation, native API hooks, `Downloader` and its browser's thread affinity. | Knows nothing about UI state or history persistence. |
| `yt_zero_touch.services.orchestrator` | Coordinates the 2-phase resolve-then-download pipeline with concurrency and retry. | `run_batch`, `download_with_retry`, worker thread pools. | Knows nothing about Tkinter widget handles or UI layout. |
| `yt_zero_touch.ui.app` | Presentation window for user interaction. | Tkinter layout, user input bindings, clipboard watch loop. | Knows nothing about low-level ffmpeg arguments or yt-dlp internals. |

---

## 3. Contracts & Invariants

1. **Delete Test**: A front end (GUI, CLI watcher) can be deleted by reading only `BatchPolicy` and `run_batch`. Engines are *not* behind an abstraction — routing between `download_ytdlp`, `download_gallery` and `download_gdrive` is a handful of explicit branches inside `download_ytdlp`, driven by facts about the URL and the request. Removing an engine means editing those branches. This is deliberate: an ABC over three adapters nothing dispatched through was documentation pretending to be code.
2. **Transcode Gate**: Software encodes (libx264, ProRes Proxy) are strictly serialized through `_TRANSCODE_GATE` to prevent multi-GB OOM crashes on 4K footage. NVENC is hardware-accelerated and passes without gating.
3. **Container Commitment**: Whenever a container is committed (`mp4` or `mov`), the file that lands is verified with `ffprobe` and the download is marked failed if its codec doesn't match — on **every** path, not only after a merge. The trigger is the `MoveFiles` postprocessor (yt-dlp's last), so a single pre-muxed format that never merges is checked too; the merge signal remains as a fallback. See ADR-0003.
4. **Machine-Parseable Diagnostics**: Errors are classified into typed `FailureClass` objects containing actionable user remedies, preventing useless retry churn on permanent errors (e.g. login wall, deleted video). A one-shot alternate-client fallback is classified on *its own* errors, never on the buffer the first attempt left behind.
5. **Browser Thread Affinity**: Playwright's sync API belongs to the thread that started it. `Downloader` hands its shared browser only to that thread; any other caller gets `None` and `resolve_urls` opens a short-lived one. `run_batch` resolves before it fans out, so it keeps the shared browser.
