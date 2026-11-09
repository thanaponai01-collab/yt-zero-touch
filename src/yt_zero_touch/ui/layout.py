"""Tk layout builders for the main window (mixed into ui.app.App)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk
from typing import Callable

from yt_zero_touch.core.transcode import nvenc_available
from yt_zero_touch.ui.theme import COLORS, STATUS_STYLE

PRESET_OPTIONS = [
    ("Best", "Best"),
    ("4K", "4K / 2160p"),
    ("1440p", "1440p QHD"),
    ("1080p", "1080p FHD"),
    ("720p", "720p HD"),
    ("Audio only", "Audio Only"),
    ("Photos", "Photos / dl"),
]


class LayoutMixin:
    """Widget construction; relies on App for vars and handlers."""

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

        self._build_header()
        # ── Main Container ─────────────────────────────────────────────
        container = tk.Frame(self, bg=COLORS["bg"], padx=14, pady=8)
        container.grid(row=1, column=0, sticky="ew")
        container.columnconfigure(0, weight=1)

        self._build_links_card(container)
        self._build_controls_card(container)
        self._build_actions_card(container)
        self._build_queue_card(container)
        self._build_log_card()
        self._build_status_bar()

    def _build_header(self):
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

        has_nvenc = nvenc_available()
        hw_text = "● NVENC HW Ready" if has_nvenc else "● FFmpeg (CPU)"
        hw_fg = COLORS["success"] if has_nvenc else COLORS["muted"]

        hw_pill = tk.Label(
            right_hdr, text=f" {hw_text} ",
            bg=COLORS["input_bg"], fg=hw_fg,
            font=("Consolas", 8, "bold"), padx=8, pady=3,
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        hw_pill.pack(side="right")

    def _build_links_card(self, container):
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

        self._build_links_input(url_card)
        self._build_links_actions(url_card)

    def _build_links_input(self, url_card):
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

    def _build_links_actions(self, url_card):
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

    def _build_controls_card(self, container):
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

        self._build_trim_cookies_row(controls_card)
        self._build_summary_banner(controls_card)

    def _build_trim_cookies_row(self, controls_card):
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

        self._build_cookie_widgets(trim_cookie_row)
        self._build_folder_button(trim_cookie_row)

    def _build_cookie_widgets(self, trim_cookie_row):
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
        ).pack(side="left", padx=(4, 6))

        tk.Button(
            trim_cookie_row, text="🔐 Login Vault…", command=self._open_login_vault,
            bg=COLORS["input_bg"], fg=COLORS["accent"],
            activebackground=COLORS["accent"], activeforeground="white",
            relief="flat", font=("Segoe UI", 8, "bold"), cursor="hand2", padx=6, pady=1,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left", padx=(0, 6))

        self.cookie_status_btn = tk.Button(
            trim_cookie_row, text="○ No cookies", command=self._show_cookie_details,
            bg=COLORS["card"], fg=COLORS["muted"],
            activebackground=COLORS["card"], activeforeground=COLORS["text"],
            relief="flat", font=("Segoe UI", 8), cursor="hand2", bd=0, padx=2,
        )
        self.cookie_status_btn.pack(side="left", padx=(0, 10))

    def _build_folder_button(self, trim_cookie_row):
        tk.Label(trim_cookie_row, text="Folder:", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        tk.Button(
            trim_cookie_row, text="Change folder…", command=self._browse_out,
            bg=COLORS["input_bg"], fg=COLORS["muted"],
            activebackground=COLORS["input_bg"], activeforeground=COLORS["text"],
            relief="flat", font=("Segoe UI", 8), cursor="hand2", padx=6, pady=1,
            highlightthickness=1, highlightbackground=COLORS["border"],
        ).pack(side="left")

    def _build_summary_banner(self, controls_card):
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


    def _build_actions_card(self, container):
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

    def _build_queue_card(self, container):
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

        self.retry_failed_btn = tk.Button(
            qhdr, text="🔁 Retry Failed (0)", command=self._retry_failed,
            bg=COLORS["card_alt"], fg=COLORS["muted"],
            activebackground=COLORS["card_alt"], activeforeground=COLORS["accent"],
            relief="flat", cursor="hand2", bd=0, font=("Segoe UI", 8, "bold"),
            state="disabled", padx=8,
        )
        self.retry_failed_btn.pack(side="right", padx=(6, 0))

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

    def _build_log_card(self):
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

    def _build_status_bar(self):
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
