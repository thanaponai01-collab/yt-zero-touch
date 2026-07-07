"""
YT-DLP Zero-Touch — Desktop App
================================
Paste a URL, click Download. The app finds the best video+audio
automatically, handles F1/Brightcove sites, downloads subtitles,
and saves to MP4 ready for Premiere Pro.

Zero-touch niceties:
  • Clipboard watcher — copy a link anywhere, it drops into the box.
  • Live queue table — one row per URL with status + progress.
  • Remembers your last settings (folder, quality, cookies, …).
  • Section trim — grab just a clip with a "10:00-20:00" time range.
"""

import json
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk
import threading
import subprocess
from pathlib import Path

from ytdlp_skill import load_history, Downloader, QUALITY_PRESETS, update_tools, URL_RE
from orchestrator import run_batch, BatchPolicy

try:
    import yt_dlp as _yt_dlp
    YT_DLP_API_OK = True
except ImportError:
    YT_DLP_API_OK = False

try:
    from plyer import notification as _plyer_notification
    _NOTIFY_OK = True
except ImportError:
    _NOTIFY_OK = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR    = Path(__file__).parent
DEFAULT_OUT = BASE_DIR / "downloads"
HISTORY_F   = BASE_DIR / "processed_urls.json"
SETTINGS_F  = BASE_DIR / "settings.json"

MAX_WORKERS = 3  # concurrent download threads

CLIP_POLL_MS = 1000  # clipboard watcher poll interval

COLORS = {
    "bg":        "#1a1a2e",
    "panel":     "#16213e",
    "accent":    "#e94560",
    "accent2":   "#0f3460",
    "text":      "#eaeaea",
    "muted":     "#888888",
    "success":   "#4caf50",
    "warning":   "#ff9800",
    "error":     "#f44336",
    "input_bg":  "#0d1b2a",
    "btn_hover": "#c73652",
}

# Per-status label + colour for the queue table.
_STATUS_STYLE = {
    "resolving":   ("Resolving…",  COLORS["muted"]),
    "queued":      ("Queued",      COLORS["muted"]),
    "skipped":     ("Skipped",     COLORS["muted"]),
    "downloading": ("Downloading", COLORS["text"]),
    "merging":     ("Merging…",    COLORS["warning"]),
    "retrying":    ("Retrying…",   COLORS["warning"]),
    "done":        ("Done",        COLORS["success"]),
    "failed":      ("Failed",      COLORS["error"]),
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT-DLP Zero-Touch")
        self.geometry("860x760")
        self.minsize(720, 560)
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)

        self._downloader   = Downloader()
        self.history       = load_history(HISTORY_F)
        self._history_lock = threading.Lock()

        # ── Tk variables (defaults; overwritten by saved settings below) ──
        self.cookie_file      = tk.StringVar()
        self.browser_cookies  = tk.StringVar(value="none")
        self.out_dir          = tk.StringVar(value=str(DEFAULT_OUT))
        self.quality          = tk.StringVar(value="Best")
        self.sub_en           = tk.BooleanVar(value=False)
        self.sub_th           = tk.BooleanVar(value=False)
        self.force_redl       = tk.BooleanVar(value=False)
        self.sections         = tk.StringVar(value="")
        self.watch_clip       = tk.BooleanVar(value=False)

        self.downloading   = False
        self._updating     = False
        self._clip_last    = ""            # last clipboard value we acted on
        self._queue_rows   = {}            # idx -> treeview item id

        self._load_settings()
        self._build_ui()

        # Seed the clipboard baseline so we don't auto-insert whatever was
        # already on the clipboard when the app launched.
        try:
            self._clip_last = self.clipboard_get()
        except Exception:
            self._clip_last = ""

        self._log("Ready. Paste a URL and click Download.", "muted")
        if YT_DLP_API_OK:
            self._log("yt-dlp Python API active — native progress callbacks enabled.", "muted")
        if not self._check_ffmpeg():
            self._log(
                "WARNING: FFmpeg not found in PATH. Video+audio merging will fail — "
                "install FFmpeg and ensure it is on your PATH.",
                "warn",
            )
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Keep extractors fresh (throttled to once per week, runs in background).
        self._maybe_auto_update()
        # Start the clipboard watcher loop (it early-returns while toggled off).
        self.after(CLIP_POLL_MS, self._poll_clipboard)

    def _check_ffmpeg(self) -> bool:
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
            return True
        except Exception:
            return False

    def _on_close(self):
        self._save_settings()
        self._downloader.__exit__(None, None, None)
        self.destroy()

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _load_settings(self):
        """Restore the last-used settings from settings.json (best-effort)."""
        try:
            data = json.loads(SETTINGS_F.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        setters = {
            "out_dir":         self.out_dir.set,
            "quality":         self.quality.set,
            "cookie_file":     self.cookie_file.set,
            "browser_cookies": self.browser_cookies.set,
            "sub_en":          self.sub_en.set,
            "sub_th":          self.sub_th.set,
            "sections":        self.sections.set,
            "watch_clip":      self.watch_clip.set,
        }
        for key, setter in setters.items():
            if key in data and data[key] is not None:
                try:
                    setter(data[key])
                except Exception:
                    pass

    def _save_settings(self):
        """Persist current settings so the next launch starts where we left off."""
        data = {
            "out_dir":         self.out_dir.get(),
            "quality":         self.quality.get(),
            "cookie_file":     self.cookie_file.get(),
            "browser_cookies": self.browser_cookies.get(),
            "sub_en":          self.sub_en.get(),
            "sub_th":          self.sub_th.get(),
            "sections":        self.sections.get(),
            "watch_clip":      self.watch_clip.get(),
        }
        try:
            SETTINGS_F.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)   # log row stretches

        # ── Header ──────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=COLORS["accent2"], pady=12)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(0, weight=1)
        tk.Label(hdr, text="YT-DLP  ZERO-TOUCH",
                 bg=COLORS["accent2"], fg=COLORS["accent"],
                 font=("Segoe UI", 18, "bold")).grid(row=0, column=0)
        _ver = getattr(_yt_dlp, "__version__", "?") if YT_DLP_API_OK else "CLI"
        tk.Label(hdr, text=f"Paste a link — choose quality — get a Premiere-ready MP4  |  yt-dlp {_ver}",
                 bg=COLORS["accent2"], fg=COLORS["muted"],
                 font=("Segoe UI", 9)).grid(row=1, column=0)

        # ── Controls ────────────────────────────────────────────────────
        ctrl = tk.Frame(self, bg=COLORS["panel"], padx=18, pady=14)
        ctrl.grid(row=1, column=0, sticky="ew", padx=0)
        ctrl.columnconfigure(1, weight=1)

        # URL input
        lbl_row = tk.Frame(ctrl, bg=COLORS["panel"])
        lbl_row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 2))
        lbl_row.columnconfigure(0, weight=1)
        tk.Label(lbl_row, text="Video URLs  (one per line, or paste multiple)",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        tk.Button(lbl_row, text="Clear", command=self._clear_url,
                  bg=COLORS["panel"], fg=COLORS["muted"],
                  activebackground=COLORS["panel"], activeforeground=COLORS["accent"],
                  relief="flat", cursor="hand2", bd=0,
                  font=("Segoe UI", 8)).grid(row=0, column=1, sticky="e")

        url_frame = tk.Frame(ctrl, bg=COLORS["input_bg"],
                             highlightbackground=COLORS["accent2"],
                             highlightthickness=1)
        url_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        url_frame.columnconfigure(0, weight=1)
        self.url_box = tk.Text(url_frame,
                               bg=COLORS["input_bg"], fg=COLORS["text"],
                               insertbackground=COLORS["text"],
                               relief="flat", font=("Segoe UI", 10),
                               bd=8, height=4, wrap="none",
                               selectbackground=COLORS["accent2"])
        self.url_box.grid(row=0, column=0, sticky="ew")
        self.url_box.bind("<Control-Return>", lambda _: self._start_download())

        # Output dir
        tk.Label(ctrl, text="Output folder", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).grid(
                 row=2, column=0, sticky="w", pady=(0, 2))
        out_frame = tk.Frame(ctrl, bg=COLORS["input_bg"],
                             highlightbackground=COLORS["accent2"],
                             highlightthickness=1)
        out_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        out_frame.columnconfigure(0, weight=1)
        tk.Entry(out_frame, textvariable=self.out_dir,
                 bg=COLORS["input_bg"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 relief="flat", font=("Segoe UI", 9), bd=6
                 ).grid(row=0, column=0, sticky="ew")
        self._small_btn(out_frame, "Browse", self._browse_out).grid(
            row=0, column=1, padx=4, pady=2)

        # Cookies
        ck_label_row = tk.Frame(ctrl, bg=COLORS["panel"])
        ck_label_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        ck_label_row.columnconfigure(0, weight=1)
        tk.Label(ck_label_row, text="Cookies  (optional — fixes PO token / login-required sites)",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")

        ck_frame = tk.Frame(ctrl, bg=COLORS["input_bg"],
                            highlightbackground=COLORS["accent2"],
                            highlightthickness=1)
        ck_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ck_frame.columnconfigure(0, weight=1)
        tk.Entry(ck_frame, textvariable=self.cookie_file,
                 bg=COLORS["input_bg"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 relief="flat", font=("Segoe UI", 9), bd=6
                 ).grid(row=0, column=0, sticky="ew")
        self._small_btn(ck_frame, "Browse", self._browse_cookies).grid(
            row=0, column=1, padx=4, pady=2)

        # Browser cookie extraction
        browser_row = tk.Frame(ctrl, bg=COLORS["panel"])
        browser_row.grid(row=5, column=2, sticky="e", padx=(8, 0), pady=(0, 12))
        tk.Label(browser_row, text="or extract from:",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).grid(row=0, column=0, padx=(0, 4))
        browser_menu = tk.OptionMenu(browser_row, self.browser_cookies,
                                     "none", "chrome", "firefox", "edge", "brave")
        browser_menu.config(bg=COLORS["accent2"], fg=COLORS["text"],
                            activebackground=COLORS["accent"],
                            activeforeground="white",
                            relief="flat", font=("Segoe UI", 8),
                            highlightthickness=0, bd=0)
        browser_menu["menu"].config(bg=COLORS["accent2"], fg=COLORS["text"])
        browser_menu.grid(row=0, column=1)

        # ── Trim + clipboard row ────────────────────────────────────────
        trim_row = tk.Frame(ctrl, bg=COLORS["panel"])
        trim_row.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        trim_row.columnconfigure(1, weight=1)

        tk.Label(trim_row, text="Trim clip:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).grid(
                 row=0, column=0, sticky="w", padx=(0, 6))
        trim_entry_frame = tk.Frame(trim_row, bg=COLORS["input_bg"],
                                    highlightbackground=COLORS["accent2"],
                                    highlightthickness=1)
        trim_entry_frame.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        trim_entry_frame.columnconfigure(0, weight=1)
        tk.Entry(trim_entry_frame, textvariable=self.sections,
                 bg=COLORS["input_bg"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 relief="flat", font=("Segoe UI", 9), bd=6
                 ).grid(row=0, column=0, sticky="ew")
        tk.Label(trim_row, text="e.g. 10:00-20:00  (blank = whole video)",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w", padx=(0, 12))

        tk.Checkbutton(trim_row, text="Watch clipboard", variable=self.watch_clip,
                       command=self._on_clip_toggle,
                       bg=COLORS["panel"], fg=COLORS["text"],
                       selectcolor=COLORS["accent2"],
                       activebackground=COLORS["panel"],
                       font=("Segoe UI", 9), cursor="hand2").grid(
                       row=0, column=3, sticky="e")

        # Options + Download button
        opts = tk.Frame(ctrl, bg=COLORS["panel"])
        opts.grid(row=7, column=0, columnspan=3, sticky="ew")
        opts.columnconfigure(5, weight=1)

        def _ck(parent, text, var):
            return tk.Checkbutton(parent, text=text, variable=var,
                                  bg=COLORS["panel"], fg=COLORS["text"],
                                  selectcolor=COLORS["accent2"],
                                  activebackground=COLORS["panel"],
                                  font=("Segoe UI", 9), cursor="hand2")

        # Quality dropdown
        q_frame = tk.Frame(opts, bg=COLORS["panel"])
        q_frame.grid(row=0, column=0, sticky="w", padx=(0, 12))
        tk.Label(q_frame, text="Quality:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        _quality_values = list(QUALITY_PRESETS.keys()) + ["Audio only", "Photos"]
        q_menu = tk.OptionMenu(q_frame, self.quality, *_quality_values)
        q_menu.config(bg=COLORS["accent2"], fg=COLORS["text"],
                      activebackground=COLORS["accent"], activeforeground="white",
                      relief="flat", font=("Segoe UI", 8),
                      highlightthickness=0, bd=0)
        q_menu["menu"].config(bg=COLORS["accent2"], fg=COLORS["text"])
        q_menu.pack(side="left")

        tk.Label(opts, text="Subtitles:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w")
        _ck(opts, "English", self.sub_en).grid(row=0, column=2, sticky="w", padx=(4, 4))
        _ck(opts, "Thai",    self.sub_th).grid(row=0, column=3, sticky="w", padx=(0, 8))
        _ck(opts, "Re-download", self.force_redl).grid(row=0, column=4, sticky="w", padx=(12, 8))

        self.dl_btn = tk.Button(opts, text="  ▶  DOWNLOAD  ",
                                command=self._start_download,
                                bg=COLORS["accent"], fg="white",
                                activebackground=COLORS["btn_hover"],
                                activeforeground="white",
                                relief="flat", font=("Segoe UI", 10, "bold"),
                                cursor="hand2", padx=18, pady=6)
        self.dl_btn.grid(row=0, column=7, sticky="e")

        self.open_btn = self._small_btn(opts, "Open folder", self._open_folder)
        self.open_btn.grid(row=0, column=6, sticky="e", padx=(0, 10))

        self._small_btn(opts, "Update tools", self._update_ytdlp).grid(
            row=0, column=5, sticky="e", padx=(0, 6))

        # ── Queue table ─────────────────────────────────────────────────
        queue_frame = tk.Frame(self, bg=COLORS["bg"])
        queue_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 0))
        queue_frame.columnconfigure(0, weight=1)

        qhdr = tk.Frame(queue_frame, bg=COLORS["bg"])
        qhdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        qhdr.columnconfigure(0, weight=1)
        tk.Label(qhdr, text="QUEUE", bg=COLORS["bg"],
                 fg=COLORS["muted"], font=("Segoe UI", 8),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 2))
        tk.Button(qhdr, text="Clear finished", command=self._clear_finished_rows,
                  bg=COLORS["bg"], fg=COLORS["muted"],
                  activebackground=COLORS["bg"], activeforeground=COLORS["accent"],
                  relief="flat", cursor="hand2", bd=0,
                  font=("Segoe UI", 8)).grid(row=0, column=1, sticky="e")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Queue.Treeview",
                        background=COLORS["input_bg"],
                        fieldbackground=COLORS["input_bg"],
                        foreground=COLORS["text"],
                        rowheight=22, borderwidth=0)
        style.configure("Queue.Treeview.Heading",
                        background=COLORS["accent2"], foreground=COLORS["text"],
                        relief="flat", font=("Segoe UI", 8, "bold"))
        style.map("Queue.Treeview.Heading",
                  background=[("active", COLORS["accent2"])])

        self.queue = ttk.Treeview(
            queue_frame, style="Queue.Treeview",
            columns=("num", "url", "status", "progress"),
            show="headings", height=6, selectmode="none",
        )
        self.queue.heading("num", text="#")
        self.queue.heading("url", text="URL")
        self.queue.heading("status", text="Status")
        self.queue.heading("progress", text="Progress")
        self.queue.column("num", width=36, anchor="center", stretch=False)
        self.queue.column("url", width=440, anchor="w")
        self.queue.column("status", width=110, anchor="w", stretch=False)
        self.queue.column("progress", width=90, anchor="w", stretch=False)
        for status, (_lbl, color) in _STATUS_STYLE.items():
            self.queue.tag_configure(status, foreground=color)
        qscroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.queue.yview)
        self.queue.configure(yscrollcommand=qscroll.set)
        self.queue.grid(row=1, column=0, sticky="ew")
        qscroll.grid(row=1, column=1, sticky="ns")

        # ── Log ─────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=COLORS["bg"])
        log_frame.grid(row=3, column=0, sticky="nsew", padx=0, pady=0)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        tk.Label(log_frame, text="LOG", bg=COLORS["bg"],
                 fg=COLORS["muted"], font=("Segoe UI", 8),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=16, pady=(8, 2))

        self.log_box = scrolledtext.ScrolledText(
            log_frame, bg=COLORS["input_bg"], fg=COLORS["text"],
            font=("Consolas", 9), relief="flat", bd=0,
            state="disabled", wrap="word",
            selectbackground=COLORS["accent2"])
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=0)

        for tag, color in [
            ("info",    COLORS["text"]),
            ("muted",   COLORS["muted"]),
            ("success", COLORS["success"]),
            ("warn",    COLORS["warning"]),
            ("error",   COLORS["error"]),
            ("accent",  COLORS["accent"]),
            ("cmd",     "#aaaaff"),
        ]:
            self.log_box.tag_config(tag, foreground=color)

        # ── Status bar ──────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Idle")
        tk.Label(self, textvariable=self.status_var,
                 bg=COLORS["accent2"], fg=COLORS["muted"],
                 font=("Segoe UI", 8), anchor="w", padx=10
                 ).grid(row=4, column=0, sticky="ew")

    def _small_btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd,
                         bg=COLORS["accent2"], fg=COLORS["text"],
                         activebackground=COLORS["accent"],
                         activeforeground="white",
                         relief="flat", font=("Segoe UI", 8),
                         cursor="hand2", padx=8, pady=3)

    # ------------------------------------------------------------------
    # Clipboard watcher
    # ------------------------------------------------------------------

    def _on_clip_toggle(self):
        """When switching the watcher on, re-baseline so we don't grab stale text."""
        if self.watch_clip.get():
            try:
                self._clip_last = self.clipboard_get()
            except Exception:
                self._clip_last = ""
            self._log("Clipboard watch on — copy a link and it drops into the box.",
                      "muted")

    def _poll_clipboard(self):
        """Poll the clipboard; append any newly-copied URL(s) to the URL box."""
        if self.watch_clip.get():
            try:
                clip = self.clipboard_get()
            except Exception:
                clip = ""
            if clip and clip != self._clip_last:
                self._clip_last = clip
                found = URL_RE.findall(clip)
                if found:
                    existing = self.url_box.get("1.0", "end")
                    added = 0
                    for u in found:
                        if u not in existing:
                            if existing.strip() and not existing.endswith("\n"):
                                self.url_box.insert("end", "\n")
                                existing += "\n"
                            self.url_box.insert("end", u + "\n")
                            existing += u + "\n"
                            added += 1
                    if added:
                        self._log(f"Clipboard: added {added} link(s).", "accent")
        self.after(CLIP_POLL_MS, self._poll_clipboard)

    # ------------------------------------------------------------------
    # Queue table (thread-safe via self.after)
    # ------------------------------------------------------------------

    def _reset_queue(self, urls):
        """Pre-populate the queue table with one row per URL, all 'queued'."""
        def _do():
            for iid in self.queue.get_children():
                self.queue.delete(iid)
            self._queue_rows.clear()
            for i, url in enumerate(urls, 1):
                short = url if len(url) <= 70 else url[:67] + "…"
                iid = self.queue.insert(
                    "", "end", values=(i, short, "Queued", ""), tags=("queued",))
                self._queue_rows[i] = iid
        self.after(0, _do)

    def _on_item(self, idx, url, status, pct):
        """orchestrator callback — update one queue row. Runs off-thread."""
        def _do():
            iid = self._queue_rows.get(idx)
            if not iid:
                return
            label, _color = _STATUS_STYLE.get(status, (status.title(), COLORS["text"]))
            if status == "downloading" and pct is not None:
                prog = f"{pct:.0f}%"
            elif status == "done":
                prog = "100%"
            elif status == "merging":
                prog = "…"
            else:
                prog = ""
            vals = self.queue.item(iid, "values")
            self.queue.item(iid, values=(vals[0], vals[1], label, prog),
                            tags=(status,))
        self.after(0, _do)

    def _clear_finished_rows(self):
        for iid in list(self.queue.get_children()):
            tags = self.queue.item(iid, "tags")
            if tags and tags[0] in ("done", "skipped"):
                self.queue.delete(iid)
        live = set(self.queue.get_children())
        self._queue_rows = {i: iid for i, iid in self._queue_rows.items()
                            if iid in live}

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _clear_url(self):
        self.url_box.delete("1.0", "end")
        self.url_box.focus()

    def _browse_out(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get())
        if d:
            self.out_dir.set(d)

    def _browse_cookies(self):
        f = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if f:
            self.cookie_file.set(f)

    def _open_folder(self):
        import os
        path = self.out_dir.get()
        Path(path).mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _update_ytdlp(self, *, quiet: bool = False):
        """Update yt-dlp (nightly) + gallery-dl in a background thread."""
        if self._updating:
            if not quiet:
                self._log("Update already in progress…", "warn")
            return

        def _run():
            self._updating = True
            try:
                changed = update_tools(log=self._log if not quiet else (lambda *a, **k: None))
                if changed:
                    self._log("Tools updated — restart the app to use the new version.", "warn")
                elif not quiet:
                    self._log("Tools already up to date.", "success")
            except Exception as exc:
                if not quiet:
                    self._log(f"Update failed: {exc}", "error")
            finally:
                self._updating = False
                self._stamp_update_check()
        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Throttled startup auto-update — keeps extractors fresh without nagging
    # ------------------------------------------------------------------

    _UPDATE_STAMP = BASE_DIR / ".last_update_check"
    _UPDATE_INTERVAL_DAYS = 7

    def _stamp_update_check(self):
        import time
        try:
            self._UPDATE_STAMP.write_text(str(int(time.time())))
        except Exception:
            pass

    def _maybe_auto_update(self):
        """Run a quiet update at most once per _UPDATE_INTERVAL_DAYS."""
        import time
        try:
            last = float(self._UPDATE_STAMP.read_text().strip())
        except Exception:
            last = 0.0
        if time.time() - last < self._UPDATE_INTERVAL_DAYS * 86400:
            return
        self._log("Checking for yt-dlp / gallery-dl updates in the background…", "muted")
        self._update_ytdlp(quiet=True)

    def _start_download(self):
        if self.downloading:
            return
        raw = self.url_box.get("1.0", "end").strip()
        if not raw:
            self._log("Paste at least one URL first.", "warn")
            return
        urls = URL_RE.findall(raw)
        if not urls:
            self._log("No valid URLs detected.", "error")
            return

        # Persist settings the moment a run starts (so a crash mid-download
        # doesn't lose the user's configuration).
        self._save_settings()

        self._reset_queue(urls)
        self.downloading = True
        self.dl_btn.config(state="disabled", text="  ⏳  Downloading…  ")
        self.status_var.set("Resolving URLs…")
        threading.Thread(target=self._download_worker, args=(urls,), daemon=True).start()

    # ------------------------------------------------------------------
    # Download worker — Phase 1: resolve, Phase 2: concurrent download
    # ------------------------------------------------------------------

    def _download_worker(self, urls):
        quality    = self.quality.get()
        audio_only = (quality == "Audio only")
        gallery    = (quality == "Photos")
        ck_path_str    = self.cookie_file.get().strip()
        browser_cookie = self.browser_cookies.get()
        sections   = self.sections.get().strip() or None

        policy = BatchPolicy(
            out_dir=Path(self.out_dir.get()),
            audio_only=audio_only,
            gallery=gallery,
            fmt=None if (audio_only or gallery) else QUALITY_PRESETS.get(quality),
            sub_langs=[lang for lang, var in (("en", self.sub_en), ("th", self.sub_th))
                       if var.get()],
            cookie_file=Path(ck_path_str) if ck_path_str else None,
            browser_cookie=None if browser_cookie == "none" else browser_cookie,
            force=self.force_redl.get(),
            write_metadata=False,
            sections=None if gallery else sections,
            max_workers=MAX_WORKERS,
        )
        if sections and gallery:
            self._log("Trim clip is ignored in Photos mode.", "warn")

        try:
            result = run_batch(
                urls, policy, self._downloader,
                history=self.history,
                history_lock=self._history_lock,
                history_path=HISTORY_F,
                log=self._log,
                set_status=lambda t: self.after(0, self.status_var.set, t),
                on_item=self._on_item,
            )
            if result.total == 0:
                return
            if result.failed == 0:
                self._notify("Download complete",
                             f"{result.succeeded} file{'s' if result.succeeded != 1 else ''} "
                             f"saved to {policy.out_dir.name}")
            else:
                remedies = []
                for _idx, _url, failure in result.failures:
                    if failure and failure.remedy not in remedies:
                        remedies.append(failure.remedy)
                if remedies:
                    self._log("How to fix the failures:", "accent")
                    for remedy in remedies:
                        self._log(f"  → {remedy}", "warn")
                top = next((f for _i, _u, f in result.failures if f), None)
                detail = f" — {top.label}" if top else " — check the log"
                self._notify("Download finished with errors",
                             f"{result.succeeded} succeeded, {result.failed} failed{detail}")
        except Exception as exc:
            self._log(f"Unexpected error: {exc}", "error")
        finally:
            self.downloading = False
            self.after(0, self._reset_btn)

    def _notify(self, title, message):
        if not _NOTIFY_OK:
            return
        try:
            _plyer_notification.notify(
                title=title,
                message=message,
                app_name="YT-DLP Zero-Touch",
                timeout=6,
            )
        except Exception:
            pass

    def _reset_btn(self):
        self.dl_btn.config(state="normal", text="  ▶  DOWNLOAD  ")
        status = self.status_var.get()
        if status in ("Downloading…", "Resolving URLs…"):
            self.status_var.set("Idle")

    # ------------------------------------------------------------------
    # Log helper — thread-safe via self.after, with a bounded line count
    # ------------------------------------------------------------------

    _LOG_MAX_LINES = 5000

    def _log(self, msg, tag="info"):
        def _write():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n", tag)
            line_count = int(self.log_box.index("end-1c").split(".")[0])
            if line_count > self._LOG_MAX_LINES:
                self.log_box.delete("1.0", f"{line_count - self._LOG_MAX_LINES}.0")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _write)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
