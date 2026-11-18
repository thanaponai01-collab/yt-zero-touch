# Project Commands

Key developer, operational, and verification commands for `yt-zero-touch`.

| Command | Working Directory | Prerequisites | Purpose | Observed Status |
|---|---|---|---|---|
| `YT-DLP Zero-Touch.vbs` (double-click) | `<repo>` | Python 3.10+ on PATH, dependencies | Launch the GUI with no terminal window (`app.pyw` under pythonw); output goes to `app.log` | Ran: window opens on PATH's Python 3.13, no console |
| `python app.py` | `<repo>` | Python 3.10+, Tkinter, dependencies | Launch desktop Fluent dark GUI window | Observed / Available (`run-console.bat`; `run.bat` now launches the .vbs, no console) |
| `python watcher.py` | `<repo>` | Python 3.10+, ffmpeg | Start CLI watcher monitoring `urls.txt` | Observed / Available (`--help` verified) |
| `python -m unittest discover tests` | `<repo>` | Python 3.10+, dependencies | Run complete 134-test regression suite | Ran: 134 passed in 0.14s |
| `python <verify-loop>/scripts/verify.py run` | `<repo>` | Python 3.10+, `verify-loop` | Run feature check recipe in `VERIFY.md` | Ran: 9 checks pass, 0 fail |
| `python <feature-map>/scripts/features.py check . --strict` | `<repo>` | Python 3.10+, `feature-map` | Validate feature map entry points and traces | Ran: 0 stale, 0 broken, 0 unmapped |
| `python <project-foundation>/scripts/foundation.py --repo . check` | `<repo>` | Python 3.10+, `project-foundation` | Check foundation document integrity | Ran: validates setup categories |
| `python -m pip install -r requirements.txt` | `<repo>` | Python 3.10+, pip | Install runtime package dependencies | Documented in `install.bat` |
| `python -m playwright install chromium` | `<repo>` | Playwright package installed | Install headless browser for stream scraping | Documented in `install.bat` |
