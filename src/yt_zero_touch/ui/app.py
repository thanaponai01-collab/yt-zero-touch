"""
YT-DLP Zero-Touch — Modernized Desktop GUI Window.
===================================================
Windows 11 Fluent dark-theme design with zero checkboxes:
  - Interactive click-to-activate color toggle chips for all options
  - Live Profile Summary banner updating on every selection
  - Real-time link counter and clipboard watcher badge
  - ProRes 422 Proxy MOV, Clip Trim Range, and Subtitle pills
  - Modernized Treeview queue with progress, speed, and ETA
  - Syntax-highlighted diagnostics terminal
"""

from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk
from typing import Callable

from yt_zero_touch.core.config import AppSettings
from yt_zero_touch.core.history import HistoryStore
from yt_zero_touch.core.models import QUALITY_PRESETS, URL_RE, BatchPolicy
from yt_zero_touch.core.transcode import _nvenc_available
from yt_zero_touch.engines.ytdlp_engine import Downloader, YT_DLP_API_OK
from yt_zero_touch.services.orchestrator import run_batch
from yt_zero_touch.services.system import check_ffmpeg
from yt_zero_touch.services.updater import ToolUpdateScheduler, update_tools
from yt_zero_touch.ui.theme import COLORS, STATUS_STYLE

try:
    from plyer import notification as _plyer_notification
    _NOTIFY_OK = True
except ImportError:
    _NOTIFY_OK = False

MAX_WORKERS = 3
CLIP_POLL_MS = 1000

PRESET_OPTIONS = [
    ("Best", "Best"),
    ("4K", "4K / 2160p"),
    ("1080p", "1080p FHD"),
    ("720p", "720p HD"),
    ("Audio only", "Audio Only"),
    ("Photos", "Photos / dl"),
]


class App(tk.Tk):
    """Modern desktop application window with interactive chip controls."""

    def __init__(self, base_dir: Path | str | None = None):
        super().__init__()
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
        self.default_out = self.base_dir / "downloads"
        self.history_f = self.base_dir / "processed_urls.json"
        self.settings_f = self.base_dir / "settings.json"
        self.update_stamp = self.base_dir / ".last_update_check"
        self.urls_txt = self.base_dir / "urls.txt"

        self.title("YT-DLP Zero-Touch")
        self.geometry("940x890")
        self.minsize(800, 700)
        self.configure(bg=COLORS["bg"])

        self._downloader = Downloader()
        self.history = HistoryStore(self.history_f)
        self.scheduler = ToolUpdateScheduler(self.update_stamp)

        # Reactive State Variables
        self.out_dir = tk.StringVar(value=str(self.default_out))
        self.quality = tk.StringVar(value="Best")
        self.cookie_file = tk.StringVar()
        self.browser_cookies = tk.StringVar(value="none")
        self.sub_en = tk.BooleanVar(value=False)
        self.sub_th = tk.BooleanVar(value=False)
        self.force_redl = tk.BooleanVar(value=False)
        self.sections = tk.StringVar(value="")
        self.watch_clip = tk.BooleanVar(value=False)
        self.prores_proxy = tk.BooleanVar(value=False)

        self.downloading = False
        self._updating = False
        self._clip_last = ""
        self._queue_rows: dict[int, str] = {}
        self._preset_buttons: dict[str, tk.Button] = {}
        self._toggle_buttons: list[tuple[tk.Button, tk.BooleanVar, str, str, str, str]] = []

        self._load_settings()
        self._build_ui()

        try:
            self._clip_last = self.clipboard_get()
        except Exception:
            self._clip_last = ""

        self._log("System initialized. Paste a URL or click clipboard watcher.", "muted")
        if YT_DLP_API_OK:
            self._log("yt-dlp Python engine active — native stream callbacks connected.", "muted")
        if not check_ffmpeg():
            self._log(
                "WARNING: FFmpeg not detected in PATH. Video muxing will fail — install FFmpeg.",
                "warn",
            )
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._maybe_auto_update()
        self.after(CLIP_POLL_MS, self._poll_clipboard)

    def _on_close(self):
        self._save_settings()
        self._downloader.__exit__(None, None, None)
        self.destroy()

    def _load_settings(self):
        settings = AppSettings.load(self.settings_f, default_out_dir=self.default_out)
        self.out_dir.set(settings.out_dir or str(self.default_out))
        self.quality.set(settings.quality)
        self.cookie_file.set(settings.cookie_file)
        self.browser_cookies.set(settings.browser_cookies)
        self.sub_en.set(settings.sub_en)
        self.sub_th.set(settings.sub_th)
        self.sections.set(settings.sections)
        self.watch_clip.set(settings.watch_clip)
        self.prores_proxy.set(settings.prores_proxy)

    def _save_settings(self):
        settings = AppSettings(
            out_dir=self.out_dir.get(),
            quality=self.quality.get(),
            cookie_file=self.cookie_file.get(),
            browser_cookies=self.browser_cookies.get(),
            sub_en=self.sub_en.get(),
            sub_th=self.sub_th.get(),
            sections=self.sections.get(),
            watch_clip=self.watch_clip.get(),
            prores_proxy=self.prores_proxy.get(),
        )
        settings.save(self.settings_f)

    # ------------------------------------------------------------------
    # Modern UI Construction (Zero Checkboxes — All Interactive Chips)
    # ------------------------------------------------------------------

    def _create_toggle_pill(
        self,
        parent: tk.Widget,
        var: tk.BooleanVar,
        label_off: str,
        label_on: str,
        active_bg: str = COLORS["accent"],
        active_border: str = COLORS["accent"],
        active_fg: str = "white",
        on_toggle: Callable[[], None] | None = None,
    ) -> tk.Button:
        """Create an interactive clickable toggle pill that lights up with color when active."""
        btn = tk.Button(
            parent,
            text="",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=3,
            highlightthickness=1,
        )

        def _refresh():
            is_active = var.get()
            if is_active:
                btn.config(
                    text=label_on,
                    bg=active_bg,
                    fg=active_fg,
                    activebackground=active_bg,
                    activeforeground=active_fg,
                    highlightbackground=active_border,
                )
            else:
                btn.config(
                    text=label_off,
                    bg=COLORS["pill_off"],
                    fg=COLORS["muted"],
                    activebackground=COLORS["card_alt"],
                    activeforeground=COLORS["text"],
                    highlightbackground=COLORS["border"],
                )

        def _clicked():
            var.set(not var.get())
            _refresh()
            self._save_settings()
            self._update_profile_summary()
            if on_toggle:
                on_toggle()

        btn.config(command=_clicked)
        _refresh()
        self._toggle_buttons.append((btn, var, label_off, label_on, active_bg, active_border))
        return btn

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # ── 1. Top Header Bar ──────────────────────────────────────────
        header = tk.Frame(self, bg=COLORS["card"], padx=18, pady=10, highlightthickness=1, highlightbackground=COLORS["border"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        left_hdr = tk.Frame(header, bg=COLORS["card"])
        left_hdr.grid(row=0, column=0, sticky="w")

        title_lbl = tk.Label(
            left_hdr, text="YT-DLP ZERO-TOUCH",
            bg=COLORS["card"], fg=COLORS["text_bright"],
            font=("Segoe UI", 15, "bold"),
        )
        title_lbl.pack(side="left")

        sub_lbl = tk.Label(
            header, text="Zero-touch video pipeline designed for Premiere Pro & creators",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8),
        )
        sub_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))

        right_hdr = tk.Frame(header, bg=COLORS["card"])
        right_hdr.grid(row=0, column=1, rowspan=2, sticky="e")

        has_nvenc = _nvenc_available()
        hw_text = "● NVENC HW Ready" if has_nvenc else "● FFmpeg (CPU)"
        hw_fg = COLORS["success"] if has_nvenc else COLORS["muted"]

        hw_pill = tk.Label(
            right_hdr, text=f" {hw_text} ",
            bg=COLORS["input_bg"], fg=hw_fg,
            font=("Consolas", 8, "bold"), padx=8, pady=3,
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        hw_pill.pack(side="right")

        # ── Main Container ─────────────────────────────────────────────
        container = tk.Frame(self, bg=COLORS["bg"], padx=14, pady=8)
        container.grid(row=1, column=0, sticky="ew")
        container.columnconfigure(0, weight=1)

        # ── Card 1: Target Links ───────────────────────────────────────
        url_card = tk.Frame(container, bg=COLORS["card"], padx=14, pady=10, highlightthickness=1, highlightbackground=COLORS["border"])
        url_card.pack(fill="x", pady=(0, 8))
        url_card.columnconfigure(0, weight=1)

        url_top = tk.Frame(url_card, bg=COLORS["card"])
        url_top.pack(fill="x", pady=(0, 6))

        tk.Label(
            url_top, text="TARGET LINKS (VIDEO, PLAYLIST, IMAGE CAROUSEL)",
            bg=COLORS["card"], fg=COLORS["accent"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        # Clipboard Watcher pill
        self.clip_pill = self._create_toggle_pill(
            parent=url_top,
            var=self.watch_clip,
            label_off="○ Clipboard Watcher: OFF",
            label_on="● Clipboard Watcher: ON",
            active_bg=COLORS["success"],
            active_border=COLORS["success"],
            on_toggle=self._on_clip_toggled,
        )
        self.clip_pill.pack(side="right")

        text_frame = tk.Frame(url_card, bg=COLORS["input_bg"], highlightthickness=1, highlightbackground=COLORS["border"])
        text_frame.pack(fill="x")
        text_frame.columnconfigure(0, weight=1)

        self.url_box = tk.Text(
            text_frame, bg=COLORS["input_bg"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat",
            font=("Consolas", 9), bd=6, height=3, wrap="none",
            selectbackground=COLORS["accent_subtle"],
        )
        self.url_box.grid(row=0, column=0, sticky="ew")
        self.url_box.bind("<KeyRelease>", lambda _: self._update_link_count())
        self.url_box.bind("<Control-Return>", lambda _: self._start_download())

        action_bar = tk.Frame(url_card, bg=COLORS["card"])
        action_bar.pack(fill="x", pady=(6, 0))

        tk.Button(
            action_bar, text="📂 Load urls.txt", command=self._load_from_urls_file,
            bg=COLORS["input_bg"], fg=COLORS["text"],
            activebackground=COLORS["accent_subtle"], activeforeground="white",
            relief="flat", font=("Segoe UI", 8), cursor="hand2", padx=8, pady=2,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            action_bar, text="Clear", command=self._clear_url,
            bg=COLORS["input_bg"], fg=COLORS["muted"],
            activebackground=COLORS["input_bg"], activeforeground=COLORS["accent"],
            relief="flat", font=("Segoe UI", 8), cursor="hand2", padx=8, pady=2,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left")

        self.link_counter_lbl = tk.Label(
            action_bar, text="0 links ready",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8),
        )
        self.link_counter_lbl.pack(side="left", padx=(12, 0))

        tk.Label(
            action_bar, text="Ctrl+Enter to Download",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8),
        ).pack(side="right")

        # ── Card 2: Interactive Chips & Encoding Controls ──────────────
        controls_card = tk.Frame(container, bg=COLORS["card"], padx=14, pady=10, highlightthickness=1, highlightbackground=COLORS["border"])
        controls_card.pack(fill="x", pady=(0, 8))

        # Preset Chips Row
        tk.Label(
            controls_card, text="ENCODING PRESET & QUALITY",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        presets_frame = tk.Frame(controls_card, bg=COLORS["card"])
        presets_frame.pack(fill="x", pady=(0, 8))

        for key, label in PRESET_OPTIONS:
            btn = tk.Button(
                presets_frame, text=label,
                command=lambda k=key: self._set_preset(k),
                bg=COLORS["input_bg"], fg=COLORS["text"],
                font=("Segoe UI", 8, "bold"), relief="flat",
                cursor="hand2", padx=10, pady=4,
                highlightthickness=1, highlightbackground=COLORS["border"],
            )
            btn.pack(side="left", expand=True, fill="x", padx=2)
            self._preset_buttons[key] = btn

        self._refresh_preset_buttons()

        # Format Target & Options Row (All Clickable Pills — Zero Checkboxes)
        pills_row = tk.Frame(controls_card, bg=COLORS["card"])
        pills_row.pack(fill="x", pady=(2, 6))

        # ProRes Pill Button
        self._create_toggle_pill(
            parent=pills_row,
            var=self.prores_proxy,
            label_off="○ ProRes 422 Proxy [MOV]",
            label_on="● ProRes 422 Proxy [MOV]",
            active_bg=COLORS["amber"],
            active_border=COLORS["amber_border"],
        ).pack(side="left", padx=(0, 6))

        # Subtitle Pills
        tk.Label(pills_row, text="Subtitles:", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(6, 4))

        self._create_toggle_pill(
            parent=pills_row,
            var=self.sub_en,
            label_off="○ English (en)",
            label_on="● English (en)",
            active_bg=COLORS["cyan"],
            active_border=COLORS["cyan_border"],
        ).pack(side="left", padx=2)

        self._create_toggle_pill(
            parent=pills_row,
            var=self.sub_th,
            label_off="○ Thai (th)",
            label_on="● Thai (th)",
            active_bg=COLORS["cyan"],
            active_border=COLORS["cyan_border"],
        ).pack(side="left", padx=2)

        # Force Redownload Pill
        self._create_toggle_pill(
            parent=pills_row,
            var=self.force_redl,
            label_off="○ Skip History",
            label_on="● Force Re-download",
            active_bg=COLORS["error"],
            active_border=COLORS["error"],
        ).pack(side="left", padx=(10, 0))

        # Trim & Cookies Row
        trim_cookie_row = tk.Frame(controls_card, bg=COLORS["card"])
        trim_cookie_row.pack(fill="x", pady=(4, 6))

        # Trim range
        tk.Label(trim_cookie_row, text="Trim clip [Sec]:", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self.trim_entry = tk.Entry(
            trim_cookie_row, textvariable=self.sections, bg=COLORS["input_bg"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", font=("Consolas", 8),
            highlightthickness=1, highlightbackground=COLORS["border"], width=16,
        )
        self.trim_entry.pack(side="left", padx=(0, 12))
        self.trim_entry.bind("<KeyRelease>", lambda _: self._update_profile_summary())

        # Cookies
        tk.Label(trim_cookie_row, text="Cookies:", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        browser_menu = tk.OptionMenu(
            trim_cookie_row, self.browser_cookies, "none", "chrome", "firefox", "edge", "brave",
            command=lambda _: (self._save_settings(), self._update_profile_summary()),
        )
        browser_menu.config(
            bg=COLORS["input_bg"], fg=COLORS["text"],
            activebackground=COLORS["accent"], activeforeground="white",
            relief="flat", font=("Segoe UI", 8), highlightthickness=1, highlightbackground=COLORS["border"], bd=0,
        )
        browser_menu["menu"].config(bg=COLORS["input_bg"], fg=COLORS["text"])
        browser_menu.pack(side="left")

        tk.Button(
            trim_cookie_row, text="Cookie file…", command=self._browse_cookies,
            bg=COLORS["input_bg"], fg=COLORS["muted"],
            activebackground=COLORS["input_bg"], activeforeground=COLORS["text"],
            relief="flat", font=("Segoe UI", 8), cursor="hand2", padx=6, pady=1,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left", padx=(4, 12))

        # Folder location
        tk.Label(trim_cookie_row, text="Folder:", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        tk.Button(
            trim_cookie_row, text="Change folder…", command=self._browse_out,
            bg=COLORS["input_bg"], fg=COLORS["muted"],
            activebackground=COLORS["input_bg"], activeforeground=COLORS["text"],
            relief="flat", font=("Segoe UI", 8), cursor="hand2", padx=6, pady=1,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left")

        # ── Live Profile Summary Banner ────────────────────────────────
        self.summary_card = tk.Frame(controls_card, bg=COLORS["card_alt"], padx=10, pady=5, highlightthickness=1, highlightbackground=COLORS["border"])
        self.summary_card.pack(fill="x", pady=(4, 0))

        self.summary_lbl = tk.Label(
            self.summary_card, text="",
            bg=COLORS["card_alt"], fg=COLORS["text"],
            font=("Segoe UI", 8), anchor="w",
        )
        self.summary_lbl.pack(side="left", fill="x", expand=True)
        self._update_profile_summary()

        # ── Primary Download & Actions ─────────────────────────────────
        action_row = tk.Frame(container, bg=COLORS["bg"])
        action_row.pack(fill="x", pady=(4, 8))

        self.dl_btn = tk.Button(
            action_row, text="  ▶  START ZERO-TOUCH PIPELINE  ",
            command=self._start_download,
            bg=COLORS["accent"], fg="white",
            activebackground=COLORS["accent_hover"], activeforeground="white",
            relief="flat", font=("Segoe UI", 10, "bold"),
            cursor="hand2", padx=20, pady=7,
        )
        self.dl_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Button(
            action_row, text="📂 Open Output Folder", command=self._open_folder,
            bg=COLORS["card"], fg=COLORS["text"],
            activebackground=COLORS["card_alt"], activeforeground="white",
            relief="flat", font=("Segoe UI", 9, "bold"),
            cursor="hand2", padx=12, pady=7,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            action_row, text="🔄 Update Tools", command=self._update_ytdlp,
            bg=COLORS["card"], fg=COLORS["muted"],
            activebackground=COLORS["card_alt"], activeforeground=COLORS["accent"],
            relief="flat", font=("Segoe UI", 8),
            cursor="hand2", padx=10, pady=7,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="right")

        # ── Card 3: Live Pipeline Queue Table ──────────────────────────
        queue_card = tk.Frame(container, bg=COLORS["card"], padx=14, pady=8, highlightthickness=1, highlightbackground=COLORS["border"])
        queue_card.pack(fill="x", pady=(0, 8))
        queue_card.columnconfigure(0, weight=1)

        qhdr = tk.Frame(queue_card, bg=COLORS["card"])
        qhdr.pack(fill="x", pady=(0, 4))
        tk.Label(
            qhdr, text="ACTIVE PIPELINE QUEUE",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        tk.Label(qhdr, text="Max Threads: 3", bg=COLORS["card"], fg=COLORS["muted"], font=("Consolas", 7)).pack(side="left", padx=10)

        tk.Button(
            qhdr, text="Clear finished", command=self._clear_finished_rows,
            bg=COLORS["card"], fg=COLORS["muted"],
            activebackground=COLORS["card"], activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", bd=0, font=("Segoe UI", 8),
        ).pack(side="right")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Queue.Treeview",
            background=COLORS["input_bg"],
            fieldbackground=COLORS["input_bg"],
            foreground=COLORS["text"],
            rowheight=24, borderwidth=0,
            font=("Segoe UI", 8),
        )
        style.configure(
            "Queue.Treeview.Heading",
            background=COLORS["card_alt"],
            foreground=COLORS["text"],
            relief="flat", font=("Segoe UI", 8, "bold"),
        )
        style.map("Queue.Treeview.Heading", background=[("active", COLORS["card_alt"])])

        self.queue = ttk.Treeview(
            queue_card, style="Queue.Treeview",
            columns=("num", "url", "status", "progress"),
            show="headings", height=5, selectmode="none",
        )
        self.queue.heading("num", text="#")
        self.queue.heading("url", text="Stream / URL")
        self.queue.heading("status", text="Status")
        self.queue.heading("progress", text="Progress / ETA")
        self.queue.column("num", width=36, anchor="center", stretch=False)
        self.queue.column("url", width=420, anchor="w")
        self.queue.column("status", width=120, anchor="w", stretch=False)
        self.queue.column("progress", width=220, anchor="w", stretch=False)

        for status, (_lbl, color) in STATUS_STYLE.items():
            self.queue.tag_configure(status, foreground=color)

        qscroll = ttk.Scrollbar(queue_card, orient="vertical", command=self.queue.yview)
        self.queue.configure(yscrollcommand=qscroll.set)
        self.queue.pack(side="left", fill="x", expand=True)
        qscroll.pack(side="right", fill="y")

        # ── Card 4: Diagnostics Log Drawer ─────────────────────────────
        log_card = tk.Frame(self, bg=COLORS["card"], padx=14, pady=6, highlightthickness=1, highlightbackground=COLORS["border"])
        log_card.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 4))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        tk.Label(
            log_card, text="ZERO-TOUCH DIAGNOSTICS LOG",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))

        self.log_box = scrolledtext.ScrolledText(
            log_card, bg=COLORS["input_bg"], fg=COLORS["text"],
            font=("Consolas", 8), relief="flat", bd=0,
            state="disabled", wrap="word", selectbackground=COLORS["accent_subtle"],
            height=6,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew")

        for tag, color in [
            ("info", COLORS["text"]),
            ("muted", COLORS["muted"]),
            ("success", COLORS["success"]),
            ("warn", COLORS["warning"]),
            ("error", COLORS["error"]),
            ("accent", COLORS["accent"]),
            ("cmd", "#aaaaff"),
        ]:
            self.log_box.tag_config(tag, foreground=color)

        # ── Status Bar ─────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Idle")
        status_bar = tk.Frame(self, bg=COLORS["card_alt"], padx=10, pady=3)
        status_bar.grid(row=4, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)

        tk.Label(
            status_bar, textvariable=self.status_var,
            bg=COLORS["card_alt"], fg=COLORS["muted"],
            font=("Segoe UI", 8), anchor="w",
        ).pack(side="left")

        self.footer_out_lbl = tk.Label(
            status_bar, text=f"Output: {Path(self.out_dir.get()).name}/",
            bg=COLORS["card_alt"], fg=COLORS["muted"],
            font=("Consolas", 8), anchor="e",
        )
        self.footer_out_lbl.pack(side="right")

    # ------------------------------------------------------------------
    # Dynamic Profile Summary UX
    # ------------------------------------------------------------------

    def _update_profile_summary(self):
        """Update the live profile summary badge so user has instant confidence in active settings."""
        parts = []
        quality = self.quality.get()
        parts.append(f"Quality: {quality}")

        if quality == "Photos":
            parts.append("Format: Image Carousels (gallery-dl)")
        elif quality == "Audio only":
            parts.append("Format: Audio Only (Opus/AAC)")
        elif self.prores_proxy.get():
            parts.append("Format: ProRes 422 Proxy (MOV)")
        else:
            parts.append("Format: H.264 / AAC (MP4)")

        subs = []
        if self.sub_en.get():
            subs.append("en")
        if self.sub_th.get():
            subs.append("th")
        if subs:
            parts.append(f"Subs: {', '.join(subs)}")

        trim = self.sections.get().strip()
        if trim and quality != "Photos":
            parts.append(f"Trim: {trim}")

        if self.force_redl.get():
            parts.append("Mode: Force Re-download")
        else:
            parts.append("Mode: Skip Duplicates")

        b_cookie = self.browser_cookies.get()
        if b_cookie != "none":
            parts.append(f"Cookies: {b_cookie.capitalize()}")
        elif self.cookie_file.get().strip():
            parts.append(f"Cookies: {Path(self.cookie_file.get().strip()).name}")

        self.summary_lbl.config(text="✨ Profile:  " + "   •   ".join(parts))

    # ------------------------------------------------------------------
    # Preset & Interaction Handlers
    # ------------------------------------------------------------------

    def _set_preset(self, preset_key: str):
        self.quality.set(preset_key)
        self._refresh_preset_buttons()
        self._save_settings()
        self._update_profile_summary()

    def _refresh_preset_buttons(self):
        active = self.quality.get()
        for key, btn in self._preset_buttons.items():
            if key == active:
                btn.config(
                    bg=COLORS["accent"], fg="white",
                    activebackground=COLORS["accent_hover"],
                    highlightbackground=COLORS["accent"],
                )
            else:
                btn.config(
                    bg=COLORS["input_bg"], fg=COLORS["text"],
                    activebackground=COLORS["card_alt"],
                    highlightbackground=COLORS["border"],
                )

    def _on_clip_toggled(self):
        if self.watch_clip.get():
            try:
                self._clip_last = self.clipboard_get()
            except Exception:
                self._clip_last = ""
            self._log("Clipboard watcher ON — copy any link to auto-insert.", "accent")
        else:
            self._log("Clipboard watcher paused.", "muted")

    def _update_link_count(self):
        raw = self.url_box.get("1.0", "end").strip()
        urls = URL_RE.findall(raw)
        count = len(urls)
        self.link_counter_lbl.config(
            text=f"{count} link{'s' if count != 1 else ''} ready",
            fg=COLORS["success"] if count > 0 else COLORS["muted"],
        )

    def _load_from_urls_file(self):
        if self.urls_txt.exists():
            try:
                content = self.urls_txt.read_text(encoding="utf-8")
                links = URL_RE.findall(content)
                if links:
                    current = self.url_box.get("1.0", "end").strip()
                    existing = set(URL_RE.findall(current))
                    to_add = [u for u in links if u not in existing]
                    if to_add:
                        sep = "\n" if current else ""
                        self.url_box.insert("end", sep + "\n".join(to_add))
                        self._log(f"Loaded {len(to_add)} link(s) from urls.txt", "success")
                        self._update_link_count()
                        return
                self._log("urls.txt contains no new valid links.", "warn")
            except Exception as exc:
                self._log(f"Error reading urls.txt: {exc}", "error")
        else:
            self._log("urls.txt does not exist yet.", "warn")

    def _poll_clipboard(self):
        if self.watch_clip.get():
            try:
                clip = self.clipboard_get()
            except Exception:
                clip = ""
            if clip and clip != self._clip_last:
                self._clip_last = clip
                links = URL_RE.findall(clip)
                if links:
                    current = self.url_box.get("1.0", "end").strip()
                    existing = set(URL_RE.findall(current))
                    new_links = [l for l in links if l not in existing]
                    if new_links:
                        sep = "\n" if current else ""
                        self.url_box.insert("end", sep + "\n".join(new_links))
                        self.url_box.see("end")
                        self._log(f"Clipboard auto-added {len(new_links)} URL(s).", "accent")
                        self._update_link_count()
        self.after(CLIP_POLL_MS, self._poll_clipboard)

    def _clear_url(self):
        self.url_box.delete("1.0", "end")
        self._update_link_count()

    def _browse_out(self):
        d = filedialog.askdirectory(title="Choose download folder", initialdir=self.out_dir.get())
        if d:
            self.out_dir.set(d)
            self._save_settings()
            self.footer_out_lbl.config(text=f"Output: {Path(d).name}/")
            self._log(f"Destination folder updated: {d}", "info")

    def _browse_cookies(self):
        f = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if f:
            self.cookie_file.set(f)
            self._save_settings()
            self._update_profile_summary()
            self._log(f"Loaded cookies file: {Path(f).name}", "info")

    def _open_folder(self):
        p = Path(self.out_dir.get())
        p.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["explorer", str(p)])
        except Exception as exc:
            self._log(f"Could not open folder: {exc}", "error")

    def _clear_finished_rows(self):
        for iid in list(self.queue.get_children()):
            tags = self.queue.item(iid, "tags") or ()
            if any(t in tags for t in ("done", "failed", "skipped")):
                self.queue.delete(iid)
                for k, v in list(self._queue_rows.items()):
                    if v == iid:
                        del self._queue_rows[k]

    def _reset_queue(self, urls: list[str]):
        for iid in self.queue.get_children():
            self.queue.delete(iid)
        self._queue_rows.clear()
        for idx, url in enumerate(urls, 1):
            iid = self.queue.insert("", "end", values=(str(idx), url, "Queued", "-"), tags=("queued",))
            self._queue_rows[idx] = iid

    def _on_item(self, idx: int, url: str, status: str, pct: float | None):
        def _apply():
            iid = self._queue_rows.get(idx)
            if not iid:
                return
            lbl, _ = STATUS_STYLE.get(status, (status.capitalize(), COLORS["text"]))
            pct_str = f"{pct:.1f}%" if pct is not None else "-"
            self.queue.item(iid, values=(str(idx), url, lbl, pct_str), tags=(status,))
        self.after(0, _apply)

    def _update_ytdlp(self, quiet: bool = False):
        if self._updating:
            return
        self._updating = True

        def _run():
            try:
                changed = update_tools(log=self._log)
                if changed:
                    self._log("Tools updated — restart the app to use the new version.", "warn")
                elif not quiet:
                    self._log("Tools already up to date.", "success")
            except Exception as exc:
                if not quiet:
                    self._log(f"Update failed: {exc}", "error")
            finally:
                self._updating = False
                self.scheduler.stamp()

        threading.Thread(target=_run, daemon=True).start()

    def _maybe_auto_update(self):
        if not self.scheduler.should_check():
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

        self._save_settings()
        self._reset_queue(urls)
        self.downloading = True
        self.dl_btn.config(state="disabled", text="  ⏳  PIPELINE ACTIVE…  ", bg=COLORS["accent_subtle"])
        self.status_var.set("Resolving URLs…")
        threading.Thread(target=self._download_worker, args=(urls,), daemon=True).start()

    def _download_worker(self, urls: list[str]):
        quality = self.quality.get()
        audio_only = (quality == "Audio only")
        gallery = (quality == "Photos")
        ck_path_str = self.cookie_file.get().strip()
        browser_cookie = self.browser_cookies.get()
        sections = self.sections.get().strip() or None

        policy = BatchPolicy(
            out_dir=Path(self.out_dir.get()),
            audio_only=audio_only,
            gallery=gallery,
            fmt=None if (audio_only or gallery) else QUALITY_PRESETS.get(quality),
            sub_langs=[lang for lang, var in (("en", self.sub_en), ("th", self.sub_th)) if var.get()],
            cookie_file=Path(ck_path_str) if ck_path_str else None,
            browser_cookie=None if browser_cookie == "none" else browser_cookie,
            force=self.force_redl.get(),
            write_metadata=False,
            sections=None if gallery else sections,
            target_codec="prores" if self.prores_proxy.get() else "h264",
            max_workers=MAX_WORKERS,
        )

        try:
            result = run_batch(
                urls, policy, self._downloader,
                history=self.history,
                log=self._log,
                set_status=lambda t: self.after(0, self.status_var.set, t),
                on_item=self._on_item,
            )
            if result.total == 0:
                return
            if result.failed == 0:
                self._notify(
                    "Download complete",
                    f"{result.succeeded} file{'s' if result.succeeded != 1 else ''} saved to {policy.out_dir.name}",
                )
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
                self._notify(
                    "Download finished with errors",
                    f"{result.succeeded} succeeded, {result.failed} failed{detail}",
                )
        except Exception as exc:
            self._log(f"Unexpected error: {exc}", "error")
        finally:
            self.downloading = False
            self.after(0, self._reset_btn)

    def _notify(self, title: str, message: str):
        if not _NOTIFY_OK:
            return
        try:
            _plyer_notification.notify(title=title, message=message, app_name="YT-DLP Zero-Touch", timeout=6)
        except Exception:
            pass

    def _reset_btn(self):
        self.dl_btn.config(state="normal", text="  ▶  START ZERO-TOUCH PIPELINE  ", bg=COLORS["accent"])
        status = self.status_var.get()
        if status in ("Downloading…", "Resolving URLs…"):
            self.status_var.set("Idle")

    _LOG_MAX_LINES = 5000

    def _log(self, msg: str, tag: str = "info"):
        def _write():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n", tag)
            line_count = int(self.log_box.index("end-1c").split(".")[0])
            if line_count > self._LOG_MAX_LINES:
                self.log_box.delete("1.0", f"{line_count - self._LOG_MAX_LINES}.0")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _write)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
