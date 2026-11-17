"""
YT-DLP Zero-Touch — windowless launcher
=======================================
Double-click this file (or "YT-DLP Zero-Touch.vbs") to open the app with no
terminal window. Run under pythonw there is no console, so everything the app
prints goes to app.log next to this file. Use run.bat to see a live console.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_LOG = _ROOT / "app.log"

if sys.stdout is None or sys.stderr is None:
    _stream = open(_LOG, "w", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = sys.stdout or _stream
    sys.stderr = sys.stderr or _stream

_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from yt_zero_touch.ui.app import main
    main()
except Exception:
    traceback.print_exc()
    try:
        from tkinter import messagebox
        messagebox.showerror(
            "YT-DLP Zero-Touch",
            f"The app could not start. Details are in:\n{_LOG}\n\n"
            "Run install.bat if you have not already, or run.bat to see the error.",
        )
    except Exception:
        pass
    raise SystemExit(1)
