"""
YT-DLP Zero-Touch — Desktop App
================================
Paste a URL, click Download. The app finds the best video+audio
automatically, handles F1/Brightcove sites, downloads subtitles,
and saves to MP4 ready for Premiere Pro.
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import re
import time
from pathlib import Path
from datetime import datetime

from ytdlp_skill import (
    resolve_url,
    load_history, save_history,
    Downloader,
    QUALITY_PRESETS,
    _launch_temp_browser, _PLAYWRIGHT_OK,
)

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

MAX_WORKERS = 3  # concurrent download threads

# Error recovery — retry on transient failures with exponential backoff
RETRY_MAX    = 3           # max retry attempts after first failure
RETRY_DELAYS = [5, 15, 30] # seconds to wait before each retry

# Keywords in yt-dlp error output that indicate a permanent, non-retryable failure.
_PERMANENT_ERR_KEYWORDS = [
    "video unavailable", "has been removed", "private video",
    "this video is not available", "geo",  # geo-restricted
    "age", "sign in to confirm",           # age/login gate
    "404", "not found", "403",             # HTTP perm failures
    "no video formats", "no formats found",
]

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

URL_RE = re.compile(r'https?://[^\s"<>\']+')

# URL resolution, download engine, and history are provided by ytdlp_skill.

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT-DLP Zero-Touch")
        self.geometry("820x680")
        self.minsize(680, 500)
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)

        self._downloader   = Downloader()
        self.history       = load_history(HISTORY_F)
        self._history_lock = threading.Lock()
        self.cookie_file      = tk.StringVar()
        self.browser_cookies  = tk.StringVar(value="none")
        self.out_dir          = tk.StringVar(value=str(DEFAULT_OUT))
        self.quality          = tk.StringVar(value="Best")
        self.sub_en           = tk.BooleanVar(value=False)
        self.sub_th           = tk.BooleanVar(value=False)
        self.force_redl       = tk.BooleanVar(value=False)
        self.downloading   = False
        self._updating     = False

        self._build_ui()
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
        self._downloader.__exit__(None, None, None)
        self.destroy()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

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

        # Options + Download button
        opts = tk.Frame(ctrl, bg=COLORS["panel"])
        opts.grid(row=6, column=0, columnspan=3, sticky="ew")
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
        _quality_values = list(QUALITY_PRESETS.keys()) + ["Audio only"]
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

        self._small_btn(opts, "Update yt-dlp", self._update_ytdlp).grid(
            row=0, column=5, sticky="e", padx=(0, 6))

        # ── Log ─────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=COLORS["bg"])
        log_frame.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
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
                 ).grid(row=3, column=0, sticky="ew")

    def _small_btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd,
                         bg=COLORS["accent2"], fg=COLORS["text"],
                         activebackground=COLORS["accent"],
                         activeforeground="white",
                         relief="flat", font=("Segoe UI", 8),
                         cursor="hand2", padx=8, pady=3)

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

    def _update_ytdlp(self):
        if self._updating:
            self._log("Update already in progress…", "warn")
            return
        import subprocess, threading, sys
        self._updating = True
        self._log("Updating yt-dlp (nightly channel)…", "info")
        NIGHTLY = ("yt-dlp @ https://github.com/yt-dlp/yt-dlp-nightly-builds"
                   "/releases/latest/download/yt-dlp.tar.gz")
        def _version():
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "show", "yt-dlp"],
                    capture_output=True, text=True, timeout=15,
                )
                for ln in r.stdout.splitlines():
                    if ln.lower().startswith("version:"):
                        return ln.split(":", 1)[1].strip()
            except Exception:
                pass
            return "unknown"
        def _run():
            before = _version()
            self.after(0, self._log, f"Before: yt-dlp {before}", "muted")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", "--force-reinstall",
                     "--no-deps", NIGHTLY],
                    capture_output=True, text=True, timeout=180,
                )
                if result.returncode != 0:
                    out = (result.stdout + result.stderr).strip()
                    if "WinError 32" in out or "being used by another process" in out:
                        self.after(0, self._log,
                            "Update failed: yt-dlp files are locked. "
                            "Close the app, run the update from a terminal, then reopen.", "error")
                    else:
                        for line in out.splitlines()[-15:]:
                            self.after(0, self._log, line, "error")
                    return
                after = _version()
                if after != before:
                    self.after(0, self._log, f"Updated: {before} → {after}", "success")
                    self.after(0, self._log, "Restart the app to use the new version.", "warn")
                else:
                    self.after(0, self._log, f"Already at latest nightly ({after}).", "success")
            except Exception as exc:
                self.after(0, self._log, f"Update failed: {exc}", "error")
            finally:
                self._updating = False
        threading.Thread(target=_run, daemon=True).start()

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

        self.downloading = True
        self.dl_btn.config(state="disabled", text="  ⏳  Downloading…  ")
        self.status_var.set("Resolving URLs…")
        threading.Thread(target=self._download_worker, args=(urls,), daemon=True).start()

    # ------------------------------------------------------------------
    # Download worker — Phase 1: resolve, Phase 2: concurrent download
    # ------------------------------------------------------------------

    def _download_worker(self, urls: list[str]):
        out_dir     = Path(self.out_dir.get())
        quality     = self.quality.get()
        audio_only  = (quality == "Audio only")
        fmt         = None if audio_only else QUALITY_PRESETS.get(quality)
        force_redl  = self.force_redl.get()
        ck_path_str    = self.cookie_file.get().strip()
        cookie_file    = Path(ck_path_str) if ck_path_str else None
        browser_cookie = self.browser_cookies.get()
        if browser_cookie == "none":
            browser_cookie = None
        sub_langs   = [lang for lang, var in (("en", self.sub_en), ("th", self.sub_th))
                       if var.get()]

        out_dir.mkdir(parents=True, exist_ok=True)
        pad = len(str(len(urls)))

        # ── Phase 1: Resolve all URLs sequentially (Playwright stays warm) ──
        # Browser is created here, in the worker thread — Playwright's sync API
        # binds its greenlet dispatcher to the creating thread, so passing a
        # browser from the main thread causes "Cannot switch to a different thread".
        _worker_browser = _launch_temp_browser() if _PLAYWRIGHT_OK else None
        work_items: list[tuple[int, str, str, str]] = []
        try:
            for idx, url in enumerate(urls, 1):
                ts = datetime.now().strftime("%H:%M:%S")
                if url in self.history and not force_redl:
                    self._log(f"[{ts}] Skipping (already downloaded): {url[:80]}", "muted")
                    continue

                self._log(f"\n[{ts}] Resolving {idx}/{len(urls)}: {url[:80]}", "accent")
                resolved = resolve_url(
                    url, cookie_file=cookie_file, log=self._log,
                    _browser=_worker_browser,
                )

                is_stream = resolved != url and (
                    ".m3u8" in resolved or (".mp4" in resolved and "?" in resolved)
                )
                num_prefix = f"{idx:0{pad}d} - " if len(urls) > 1 else ""
                if is_stream:
                    slug = re.sub(r"[^\w\s-]", "", url.rstrip("/").split("/")[-1])
                    slug = re.sub(r"\s+", "-", slug)[:80] or "video"
                    tpl = f"{num_prefix}{slug}.%(ext)s"
                else:
                    tpl = f"{num_prefix}%(title).100B - [%(id)s].%(ext)s"

                work_items.append((idx, url, resolved, tpl))
        finally:
            if _worker_browser:
                try:
                    _worker_browser.close()
                except Exception:
                    pass

        if not work_items:
            self.downloading = False
            self.after(0, self._reset_btn)
            return

        total     = len(work_items)
        workers   = min(MAX_WORKERS, total)
        done      = [0]  # mutable for closure across threads
        self._log(
            f"\nStarting {total} download(s) with up to {workers} concurrent thread(s)…",
            "info",
        )
        self.after(0, lambda: self.status_var.set(f"0 / {total} done"))

        # ── Phase 2: Concurrent downloads ──────────────────────────────────
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._download_one,
                    idx, url, resolved, tpl, out_dir, audio_only, fmt, sub_langs, cookie_file, browser_cookie,
                ): (idx, url)
                for idx, url, resolved, tpl in work_items
            }
            for future in as_completed(futures):
                idx, url = futures[future]
                try:
                    ok = future.result()
                except Exception as exc:
                    self._log(f"  [#{idx}] Unexpected error: {exc}", "error")
                    ok = False

                if ok:
                    with self._history_lock:
                        self.history.add(url)
                        save_history(HISTORY_F, self.history)
                    done[0] += 1
                    self.after(0, lambda d=done[0]: self.status_var.set(f"{d} / {total} done"))
                else:
                    self._log(f"  [#{idx}] Download failed.", "error")

        self.downloading = False
        failed = total - done[0]
        if failed == 0:
            self._notify("Download complete",
                         f"{done[0]} file{'s' if done[0] != 1 else ''} saved to {out_dir.name}")
        else:
            self._notify("Download finished with errors",
                         f"{done[0]} succeeded, {failed} failed — check the log")
        self.after(0, self._reset_btn)

    def _is_permanent_error(self, messages: list[str]) -> bool:
        """Check if error messages indicate a permanent failure (not retryable)."""
        combined = " ".join(messages).lower()
        return any(kw in combined for kw in _PERMANENT_ERR_KEYWORDS)

    def _download_one(
        self,
        idx: int,
        url: str,
        resolved: str,
        tpl: str,
        out_dir: Path,
        audio_only: bool,
        fmt: "str | None",
        sub_langs: list[str],
        cookie_file: "Path | None",
        browser_cookie: "str | None" = None,
    ) -> bool:
        prefix = f"[#{idx}]"

        def base_log(msg: str, tag: str = "info"):
            self._log(f"{prefix} {msg}", tag)

        def progress_hook(d: dict):
            if d["status"] == "downloading":
                pct   = d.get("_percent_str", "").strip()
                speed = d.get("_speed_str", "?").strip()
                eta   = d.get("_eta_str", "?").strip()
                self.after(0, lambda p=pct, s=speed, e=eta:
                    self.status_var.set(f"Downloading  {p}  •  {s}  •  ETA {e}"))
            elif d["status"] == "finished":
                self.after(0, lambda: self.status_var.set("Merging…"))

        base_log(f"Starting: {url[:80]}", "accent")

        # Retry loop with exponential backoff
        for attempt in range(1, RETRY_MAX + 2):
            captured_errors = []

            def log(msg: str, tag: str = "info"):
                base_log(msg, tag)
                if tag == "error":
                    captured_errors.append(msg)

            ok = self._downloader.download(
                resolved,
                out_dir=out_dir,
                audio_only=audio_only,
                fmt=fmt,
                write_metadata=False,
                sub_langs=sub_langs,
                cookie_file=cookie_file,
                browser_cookie=browser_cookie,
                out_template=tpl,
                log=log,
                progress_hook=progress_hook,
                pre_resolved=True,
            )

            if ok:
                return True

            if self._is_permanent_error(captured_errors):
                base_log("  Permanent error — not retrying", "error")
                return False

            if attempt <= RETRY_MAX:
                delay = RETRY_DELAYS[attempt - 1]
                base_log(f"  Attempt {attempt} failed — retrying in {delay}s…", "warn")
                for i in range(delay, 0, -1):
                    self.after(0, lambda s=i, a=attempt, idx_val=idx:
                        self.status_var.set(f"Retry #{a} for #{idx_val} in {s}s…"))
                    time.sleep(1)

        base_log(f"  All {RETRY_MAX + 1} attempts failed.", "error")
        return False

    def _notify(self, title: str, message: str):
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
    # Log helper — thread-safe via self.after
    # ------------------------------------------------------------------

    def _log(self, msg: str, tag: str = "info"):
        def _write():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n", tag)
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _write)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
