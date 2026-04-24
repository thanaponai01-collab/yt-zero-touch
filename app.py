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
import json
import http.cookiejar
import urllib.request
from pathlib import Path
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

try:
    import yt_dlp as _yt_dlp
    YT_DLP_API_OK = True
except ImportError:
    YT_DLP_API_OK = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR    = Path(__file__).parent
DEFAULT_OUT = BASE_DIR / "downloads"
HISTORY_F   = BASE_DIR / "processed_urls.json"

FORMAT_VIDEO = "bestvideo[vcodec^=avc1]+bestaudio/bestvideo+bestaudio/best[acodec!=none]"
FORMAT_AUDIO = "bestaudio/best"
MAX_WORKERS  = 3  # concurrent download threads

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

URL_RE     = re.compile(r'https?://[^\s"<>\']+')
F1_RE      = re.compile(r'formula1\.com/en/video/.*?\.(\d{10,})')
BC_ACCT_RE = re.compile(r'BRIGHTCOVE[_\s]*ACCOUNTID["\s:]+(\d+)', re.IGNORECASE)
BC_VID_RE  = re.compile(r'videoId["\s:=]+["\']?(\d{10,})')
STREAM_RE  = re.compile(
    r'https?://[^\s"\'<>]+(?:\.m3u8|\.mp4|\.mpd)[^\s"\'<>]*', re.IGNORECASE
)

KNOWN_DOMAINS = [
    "youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "dailymotion.com",
    "soundcloud.com", "twitter.com", "x.com", "instagram.com", "tiktok.com",
    "facebook.com", "bilibili.com", "reddit.com",
]
IGNORE_STREAM_DOMAINS = [
    "doubleclick", "googlevideo.com", "googlesyndication",
    "thumbnail", "preview", "poster", "image",
]

_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu", "--disable-software-rasterizer", "--disable-dev-shm-usage",
    "--disable-extensions", "--disable-background-networking",
    "--no-first-run", "--mute-audio",
]
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_BLOCK_RESOURCES = {"image", "font", "stylesheet"}

# ---------------------------------------------------------------------------
# Playwright Manager — one browser instance for the whole session
# ---------------------------------------------------------------------------

class PlaywrightManager:
    """Keeps one Chromium instance alive across all URL resolutions.

    All page operations are serialized through a lock so the sync API is
    never called concurrently from multiple download threads.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._pw      = None
        self._browser = None

    def _ensure_started(self):
        """Lazy-start the browser. Caller must hold self._lock."""
        if self._browser is not None or not PLAYWRIGHT_OK:
            return
        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True, args=_BROWSER_ARGS)

    def intercept(self, url: str, cookie_file: "Path | None", log) -> "str | None":
        with self._lock:
            self._ensure_started()
            if self._browser is None:
                return None
            return _do_intercept(self._browser, url, cookie_file, log)

    def stop(self):
        with self._lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw:
                try:
                    self._pw.stop()
                except Exception:
                    pass
                self._pw = None


_pw_manager = PlaywrightManager()

# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def resolve_url(url: str, cookie_file: "Path | None", log) -> str:
    # 1. Formula1.com → Brightcove
    m = F1_RE.search(url)
    if m:
        bc = (f"https://players.brightcove.net/6057949432001"
              f"/default_default/index.html?videoId={m.group(1)}")
        log("  Resolved F1 → Brightcove player", "info")
        return bc

    # 2. Already a known yt-dlp site — pass through unchanged
    if any(d in url for d in KNOWN_DOMAINS):
        return url

    # 3. Try static HTML for Brightcove embed (fast, no browser)
    try:
        bc = _brightcove_from_page(url, cookie_file)
        if bc:
            log("  Found Brightcove embed in page", "info")
            return bc
    except Exception:
        pass

    # 4. Headless browser intercept (reuses existing browser instance)
    if PLAYWRIGHT_OK:
        stream = _pw_manager.intercept(url, cookie_file, log)
        if stream:
            return stream
    else:
        log("  playwright not installed — trying URL directly", "warn")

    return url


def _brightcove_from_page(url: str, cookie_file: "Path | None") -> "str | None":
    opener = urllib.request.build_opener()
    if cookie_file and cookie_file.exists():
        cj = http.cookiejar.MozillaCookieJar(str(cookie_file))
        cj.load(ignore_discard=True, ignore_expires=True)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", _USER_AGENT)]
    resp = opener.open(url, timeout=10)
    html = resp.read().decode("utf-8", errors="replace")
    acct = BC_ACCT_RE.search(html)
    vid  = BC_VID_RE.search(html)
    if acct and vid:
        return (f"https://players.brightcove.net/{acct.group(1)}"
                f"/default_default/index.html?videoId={vid.group(1)}")
    return None


def _do_intercept(browser, url: str, cookie_file: "Path | None", log) -> "str | None":
    """Intercept a video stream URL using an existing browser instance."""
    log("  Launching headless browser to intercept video stream…", "muted")
    captured = []

    ctx = browser.new_context(user_agent=_USER_AGENT)
    if cookie_file and cookie_file.exists():
        raw = _parse_netscape_cookies(cookie_file)
        if raw:
            ctx.add_cookies(raw)

    page = ctx.new_page()
    page.route(
        "**/*",
        lambda r: r.abort() if r.request.resource_type in _BLOCK_RESOURCES else r.continue_(),
    )
    page.add_init_script(_outseta_mock_js(cookie_file))
    page.on(
        "request",
        lambda req: captured.append(req.url)
        if STREAM_RE.search(req.url) and not any(x in req.url for x in IGNORE_STREAM_DOMAINS)
        else None,
    )

    log(f"  Loading page: {url}", "muted")
    try:
        page.goto(url, wait_until="load", timeout=30_000)
    except Exception:
        pass

    # Poll up to 10 s for a stream URL to appear
    elapsed, limit, step = 0, 10_000, 500
    while not captured and elapsed < limit:
        page.wait_for_timeout(step)
        elapsed += step

    page.close()
    ctx.close()

    if not captured:
        log("  No stream URL intercepted by browser", "warn")
        return None

    # Prefer master m3u8 over segment files
    for u in captured:
        if ".m3u8" in u and not any(x in u for x in ["segment", "/ts/", "fmp4"]):
            log(f"  Intercepted: {u[:80]}…", "success")
            return u
    log(f"  Intercepted: {captured[0][:80]}…", "success")
    return captured[0]


def _outseta_mock_js(cookie_file: "Path | None") -> str:
    token = ""
    if cookie_file and cookie_file.exists():
        for line in cookie_file.read_text(encoding="utf-8").splitlines():
            if "accessToken" in line:
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    token = parts[-1]
                    break
    token_json = json.dumps(token)
    return f"""
(function() {{
    var TOKEN = {token_json};
    var rawUser = {{
        Uid: "mock-uid", Email: "user@example.com",
        Account: {{Uid: "mock-account",
                   CurrentSubscription: {{Plan: {{Uid: "mock-plan", Name: "Gold"}}}}}},
        HasGoldPlan: true, HasMotorsportsPlan: true, HasPlatinumPlan: true,
        HasMRCPlan: true, HasRCCPlan: true, HasFreePlan: true,
        HasAnyPlan: true, HasAnyPaidPlan: true
    }};
    function buildMod() {{
        return {{
            getUser: function() {{ return rawUser; }},
            subscribe: function(cb) {{
                setTimeout(function() {{ cb(rawUser); }}, 50);
                return function() {{}};
            }},
            on: function(evs, cb) {{
                (Array.isArray(evs) ? evs : [evs]).forEach(function(e) {{
                    if (e === 'initial' || e.indexOf('auth') >= 0 ||
                        e.indexOf('token') >= 0)
                        setTimeout(function() {{ cb(rawUser); }}, 100);
                }});
                return function() {{}};
            }},
            off: function() {{}},
            getAccessTokenAsync: function() {{ return Promise.resolve(TOKEN); }}
        }};
    }}
    var mod = buildMod();
    Object.defineProperty(window, '__outsetaFramerModule',
        {{get: function() {{ return mod; }}, set: function() {{}}, configurable: false}});
    Object.defineProperty(window, 'Outseta',
        {{get: function() {{ return mod; }}, set: function() {{}}, configurable: false}});
}})();
"""


def _parse_netscape_cookies(cookie_file: Path) -> list:
    cookies = []
    try:
        for line in cookie_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _, path, secure, expires, name, value = parts[:7]
            cookies.append({
                "name":     name,
                "value":    value,
                "domain":   domain.lstrip("."),
                "path":     path,
                "secure":   secure.upper() == "TRUE",
                "sameSite": "None",
            })
    except Exception:
        pass
    return cookies

# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def load_history() -> set:
    if HISTORY_F.exists():
        try:
            return set(json.loads(HISTORY_F.read_text()))
        except Exception:
            pass
    return set()


def save_history(h: set):
    DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
    HISTORY_F.write_text(json.dumps(sorted(h), indent=2))

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

        self.history       = load_history()
        self._history_lock = threading.Lock()
        self.cookie_file   = tk.StringVar()
        self.out_dir       = tk.StringVar(value=str(DEFAULT_OUT))
        self.audio_only    = tk.BooleanVar(value=False)
        self.sub_en        = tk.BooleanVar(value=False)
        self.sub_th        = tk.BooleanVar(value=False)
        self.force_redl    = tk.BooleanVar(value=False)
        self.downloading   = False

        self._build_ui()
        self._log("Ready. Paste a URL and click Download.", "muted")
        if YT_DLP_API_OK:
            self._log("yt-dlp Python API active — native progress callbacks enabled.", "muted")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        _pw_manager.stop()
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
        tk.Label(hdr, text="Paste a link — get the best quality MP4",
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
        tk.Label(ctrl, text="Cookies file  (optional — for login-required sites)",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).grid(row=4, column=0,
                 columnspan=2, sticky="w", pady=(0, 2))
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

        _ck(opts, "Audio only",  self.audio_only).grid(row=0, column=0, sticky="w", padx=(0, 12))
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
        audio_only  = self.audio_only.get()
        force_redl  = self.force_redl.get()
        ck_path_str = self.cookie_file.get().strip()
        cookie_file = Path(ck_path_str) if ck_path_str else None
        sub_langs   = [lang for lang, var in (("en", self.sub_en), ("th", self.sub_th))
                       if var.get()]

        out_dir.mkdir(parents=True, exist_ok=True)
        pad = len(str(len(urls)))

        # ── Phase 1: Resolve all URLs sequentially (Playwright stays warm) ──
        work_items: list[tuple[int, str, str, str]] = []
        for idx, url in enumerate(urls, 1):
            ts = datetime.now().strftime("%H:%M:%S")
            if url in self.history and not force_redl:
                self._log(f"[{ts}] Skipping (already downloaded): {url[:80]}", "muted")
                continue

            self._log(f"\n[{ts}] Resolving {idx}/{len(urls)}: {url[:80]}", "accent")
            resolved = resolve_url(url, cookie_file, self._log)

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
                    idx, url, resolved, tpl, out_dir, audio_only, sub_langs, cookie_file,
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
                        save_history(self.history)
                    done[0] += 1
                    self.after(0, lambda d=done[0]: self.status_var.set(f"{d} / {total} done"))
                else:
                    self._log(f"  [#{idx}] Download failed.", "error")

        self.downloading = False
        self.after(0, self._reset_btn)

    def _download_one(
        self,
        idx: int,
        url: str,
        resolved: str,
        tpl: str,
        out_dir: Path,
        audio_only: bool,
        sub_langs: list[str],
        cookie_file: "Path | None",
    ) -> bool:
        prefix = f"[#{idx}]"

        def log(msg: str, tag: str = "info"):
            self._log(f"{prefix} {msg}", tag)

        fmt = FORMAT_AUDIO if audio_only else FORMAT_VIDEO
        log(f"Starting: {url[:80]}", "accent")

        if YT_DLP_API_OK:
            return self._download_via_api(
                resolved, out_dir / tpl, fmt, audio_only, sub_langs, cookie_file, log
            )
        return self._download_via_subprocess(
            resolved, out_dir, tpl, fmt, audio_only, sub_langs, cookie_file, log
        )

    def _download_via_api(
        self,
        resolved: str,
        outtmpl: Path,
        fmt: str,
        audio_only: bool,
        sub_langs: list[str],
        cookie_file: "Path | None",
        log,
    ) -> bool:
        """Download using the yt_dlp Python API — no subprocess, native progress."""

        class _Logger:
            def __init__(self, fn):
                self._fn = fn
            def debug(self, msg):
                if not msg.startswith("[debug]"):
                    self._fn(f"  {msg}", "muted")
            def info(self, msg):
                self._fn(f"  {msg}", "muted")
            def warning(self, msg):
                self._fn(f"  {msg}", "warn")
            def error(self, msg):
                self._fn(f"  {msg}", "error")

        last_milestone = [-1]

        def _progress(d: dict):
            if d["status"] == "downloading":
                pct_str = d.get("_percent_str", "").strip().rstrip("%")
                speed   = d.get("_speed_str", "?").strip()
                eta     = d.get("_eta_str", "?").strip()
                try:
                    milestone = (int(float(pct_str)) // 10) * 10
                except (ValueError, TypeError):
                    return
                # Update status bar with live speed on every tick
                self.after(0, lambda s=speed, e=eta, p=pct_str:
                    self.status_var.set(f"Downloading  {p}%  •  {s}  •  ETA {e}"))
                if milestone != last_milestone[0]:
                    last_milestone[0] = milestone
                    log(f"  {milestone}%  {speed}  ETA {eta}", "success")
            elif d["status"] == "finished":
                name = Path(d.get("filename", "")).name
                log(f"  Finished: {name}", "success")
                self.after(0, lambda: self.status_var.set("Merging…"))

        postprocessors = [
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
            {"key": "EmbedThumbnail", "already_have_thumbnail": False},
        ]
        if sub_langs:
            postprocessors.append(
                {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"}
            )
        if audio_only:
            postprocessors.insert(
                0,
                {"key": "FFmpegExtractAudio", "preferredcodec": "best", "preferredquality": "0"},
            )

        ydl_opts: dict = {
            "format":                        fmt,
            "outtmpl":                       str(outtmpl),
            "noplaylist":                    True,
            "merge_output_format":           "opus" if audio_only else "mp4",
            "overwrites":                    False,
            "addmetadata":                   True,
            "writethumbnail":                True,
            "sponsorblock_mark":             "all",
            "restrictfilenames":             True,
            "windowsfilenames":              True,
            "ignoreerrors":                  True,
            "quiet":                         True,
            "logger":                        _Logger(log),
            "progress_hooks":                [_progress],
            "postprocessors":                postprocessors,
            "socket_timeout":                60,
            "concurrent_fragment_downloads": 4,
            "retries":                       10,
            "fragment_retries":              10,
        }
        if sub_langs:
            ydl_opts.update({
                "writesubtitles":    True,
                "writeautomaticsub": True,
                "subtitleslangs":    sub_langs,
                "subtitlesformat":   "srt",
            })
        if cookie_file and cookie_file.exists():
            ydl_opts["cookiefile"] = str(cookie_file)

        try:
            with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ret = ydl.download([resolved])
            return ret == 0
        except Exception as exc:
            log(f"  yt-dlp API error: {exc}", "error")
            return False

    def _download_via_subprocess(
        self,
        resolved: str,
        out_dir: Path,
        tpl: str,
        fmt: str,
        audio_only: bool,
        sub_langs: list[str],
        cookie_file: "Path | None",
        log,
    ) -> bool:
        """Fallback: shell out to yt-dlp CLI (used when yt_dlp package not installed)."""
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", fmt,
            "--merge-output-format", "opus" if audio_only else "mp4",
            "-o", str(out_dir / tpl),
            "--no-overwrites",
            "--embed-metadata",
            "--embed-thumbnail",
            "--sponsorblock-mark", "all",
            "--restrict-filenames",
            "--windows-filenames",
            "--ignore-errors",
            "--newline",
            "--socket-timeout", "60",
            "--concurrent-fragments", "4",
            "--retries", "10",
            "--fragment-retries", "10",
        ]
        if sub_langs:
            cmd += [
                "--write-subs", "--write-auto-subs",
                "--sub-langs", ",".join(sub_langs),
                "--sub-format", "srt",
                "--convert-subs", "srt",
            ]
        if audio_only:
            cmd.insert(cmd.index("--merge-output-format"), "--extract-audio")
        if cookie_file and cookie_file.exists():
            cmd.extend(["--cookies", str(cookie_file)])
        cmd.append(resolved)

        log(f"  cmd: {' '.join(cmd)}", "cmd")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tag = "info"
                if line.startswith("[download]"):
                    tag = "success"
                elif "ERROR" in line or "error" in line.lower():
                    tag = "error"
                elif "WARNING" in line:
                    tag = "warn"
                elif line.startswith("["):
                    tag = "muted"
                log(f"  {line}", tag)
            proc.wait()
            return proc.returncode == 0
        except Exception as exc:
            log(f"  Error: {exc}", "error")
            return False

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
