# Decision Ledger — YT-DLP Zero-Touch

Consequential architectural decisions recorded with rationale, options considered, and reversibility class.

| ID | Date | Decision | Options Considered | Forces | Reversibility Class | Evidence Tag | Status |
|---|---|---|---|---|---|---|---|
| **D001** | 2026-09-08 | Package Restructuring into `src/yt_zero_touch/` | 1. Keep flat root directory.<br>2. Restructure into standard `src/yt_zero_touch` with core/engines/services/ui split. | Monolithic god file `ytdlp_skill.py` (1,106 lines) violated SRP; runtime files cluttered root; code duplication between watcher and app. | Two-way door | **(proven)** — 121 tests passing, backwards-compatible entrypoints preserved | **Active** |
| **D002** | 2026-09-08 | Encapsulate History in `HistoryStore` | 1. Pass `(history: set, lock, path)` tuples across modules.<br>2. Thread-safe `HistoryStore` repository. | Concurrency bugs from loose lock passing; duplicate file I/O code in watcher and GUI. | Two-way door | **(proven)** — `test_history_store.py` verifies atomic disk serialization | **Active** |
| **D003** | 2026-09-08 | Strong Typing for Configuration (`AppSettings`) | 1. Ad-hoc JSON dict parsing in Tkinter code.<br>2. Typed dataclass with default values and validation. | Silent bugs when setting keys drift or corrupt settings file causes crash. | Two-way door | **(proven)** — `test_config.py` verifies round-trip persistence | **Active** |
| **D004** | 2026-09-08 | Root-Level Forwarding Shims | 1. Force users to modify shortcuts to `python -m yt_zero_touch`.<br>2. Provide thin shims in root `app.py` and `watcher.py`. | Zero disruption to existing `run.bat`, user muscle memory, and automated workflows. | Two-way door | **(proven)** — `run.bat` and `watcher.py -h` execute seamlessly | **Active** |
