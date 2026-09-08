# Architecture & System Design — YT-DLP Zero-Touch v2.0

Zero-touch video/photo downloading pipeline for Windows editors producing Premiere-ready files.

---

## 1. System Sketch

```
[UI Layer]
  ├── Desktop GUI (yt_zero_touch.ui.app) <── Tkinter Fluent Dark Theme
  ├── CLI Watcher (yt_zero_touch.ui.cli.watcher) <── urls.txt File Poller
  └── ViewModels & State (yt_zero_touch.ui.state)
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
[Engine Adapters]
  ├── BaseEngine (yt_zero_touch.engines.base)
  ├── YtdlpEngine (yt_zero_touch.engines.ytdlp_engine)
  ├── GalleryEngine (yt_zero_touch.engines.gallery_engine)
  └── GDriveEngine (yt_zero_touch.engines.gdrive_engine)
        │
        ▼
[Core Domain & Invariants]
  ├── Transcode & Gate (yt_zero_touch.core.transcode) — ADR-0001, ADR-0002, ADR-0003, ADR-0005
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
| `yt_zero_touch.engines.*` | Concrete adapters wrapping third-party tools (yt-dlp, gallery-dl, gdown). | Subprocess execution, CLI flag translation, native API hooks. | Knows nothing about UI state or history persistence. |
| `yt_zero_touch.services.orchestrator` | Coordinates the 2-phase resolve-then-download pipeline with concurrency and retry. | `run_batch`, `download_with_retry`, worker thread pools. | Knows nothing about Tkinter widget handles or UI layout. |
| `yt_zero_touch.ui.app` | Presentation window for user interaction. | Tkinter layout, user input bindings, clipboard watch loop. | Knows nothing about low-level ffmpeg arguments or yt-dlp internals. |

---

## 3. Contracts & Invariants

1. **Delete Test**: Any engine (`gallery-dl`, `gdown`) or the GUI presentation layer can be completely replaced or deleted by reading only the `BaseEngine` and `BatchPolicy` contracts.
2. **Transcode Gate**: Software encodes (libx264, ProRes Proxy) are strictly serialized through `_TRANSCODE_GATE` to prevent multi-GB OOM crashes on 4K footage. NVENC is hardware-accelerated and passes without gating.
3. **Container Commitment**: A forced container format (`mp4` or `mov`) is verified after merging via `ffprobe`. A download is marked failed if the output stream does not match the committed codec.
4. **Machine-Parseable Diagnostics**: Errors are classified into typed `FailureClass` objects containing actionable user remedies, preventing useless retry churn on permanent errors (e.g. login wall, deleted video).
