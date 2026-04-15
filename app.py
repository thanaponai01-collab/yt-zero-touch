"""
YT-DLP Zero-Touch — Desktop App
================================
Paste a URL, click Download. The app finds the best video+audio
automatically, handles F1/Brightcove sites, downloads subtitles,
and saves to MP4 ready for Premiere Pro.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import threading
import subprocess
import re
import json
import http.cookiejar
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR    = Path(__file__).parent
DEFAULT_OUT = BASE_DIR / "downloads"
HISTORY_F   = BASE_DIR / "processed_urls.json"

FORMAT_VIDEO = "bestvideo[vcodec^=avc1]+bestaudio/bestvideo+bestaudio/best"
FORMAT_AUDIO = "bestaudio/best"
OUTPUT_TPL   = "%(title).100B - [%(id)s].%(ext)s"

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

URL_RE       = re.compile(r'https?://[^\s"<>\']+')
F1_RE        = re.compile(r'formula1\.com/en/video/.*?\.(\d{10,})')
BC_ACCT_RE   = re.compile(r'BRIGHTCOVE[_\s]*ACCOUNTID["\s:]+(\d+)', re.IGNORECASE)
BC_VID_RE    = re.compile(r'videoId["\s:=]+["\']?(\d{10,})')

# ---------------------------------------------------------------------------
# URL resolver
# ---------------------------------------------------------------------------

# Video stream URL patterns to intercept in network requests
STREAM_RE = re.compile(
    r'https?://[^\s"\'<>]+'
    r'(?:\.m3u8|\.mp4|\.mpd)'
    r'[^\s"\'<>]*',
    re.IGNORECASE
)

KNOWN_DOMAINS = [
    "youtube.com","youtu.be","twitch.tv","vimeo.com","dailymotion.com",
    "soundcloud.com","twitter.com","x.com","instagram.com","tiktok.com",
    "facebook.com","bilibili.com","reddit.com",
]

# Domains whose stream URLs we don't want to intercept (ads/trackers/thumbnails)
IGNORE_STREAM_DOMAINS = [
    "doubleclick", "googlevideo.com", "googlesyndication",
    "thumbnail", "preview", "poster", "image",
]


def resolve_url(url: str, cookie_file: Path | None, log) -> str:
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

    # 3. Unknown site — try static HTML for Brightcove embed first (fast)
    try:
        bc = _brightcove_from_page(url, cookie_file)
        if bc:
            log("  Found Brightcove embed in page", "info")
            return bc
    except Exception:
        pass

    # 4. Unknown site — launch headless browser, intercept video stream URLs
    if PLAYWRIGHT_OK:
        try:
            stream = _playwright_intercept(url, cookie_file, log)
            if stream:
                return stream
        except Exception as e:
            log(f"  Browser intercept failed ({e})", "warn")
    else:
        log("  playwright not installed — trying URL directly", "warn")

    return url


def _brightcove_from_page(url: str, cookie_file: Path | None) -> str | None:
    opener = urllib.request.build_opener()
    if cookie_file and cookie_file.exists():
        cj = http.cookiejar.MozillaCookieJar(str(cookie_file))
        cj.load(ignore_discard=True, ignore_expires=True)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")]
    resp = opener.open(url, timeout=10)
    html = resp.read().decode("utf-8", errors="replace")
    acct = BC_ACCT_RE.search(html)
    vid  = BC_VID_RE.search(html)
    if acct and vid:
        return (f"https://players.brightcove.net/{acct.group(1)}"
                f"/default_default/index.html?videoId={vid.group(1)}")
    return None


def _outseta_mock_js(cookie_file: Path | None) -> str:
    """Build a JS mock of window.Outseta / window.__outsetaFramerModule.

    Reads the JWT from cookies so the signer endpoint accepts the request.
    Sets HasGoldPlan/HasAnyPlan etc. so any plan-gated VideoPlayer renders.
    """
    token = ""
    if cookie_file and cookie_file.exists():
        for line in cookie_file.read_text(encoding="utf-8").splitlines():
            if "accessToken" in line:
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    token = parts[-1]
                    break
    import json as _json
    return f"""
(function() {{
    var TOKEN = {_json.dumps(token)};
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


def _playwright_intercept(url: str, cookie_file: Path | None, log) -> str | None:
    """Open page in headless Chromium, inject auth mocks, intercept video stream URLs."""
    log("  Launching headless browser to intercept video stream…", "muted")
    captured = []

    def _on_request(req):
        u = req.url
        if STREAM_RE.search(u) and not any(x in u for x in IGNORE_STREAM_DOMAINS):
            captured.append(u)

    # These resource types are never stream URLs and just waste CPU/bandwidth
    _BLOCK = {"image", "font", "stylesheet"}

    def _handle_route(route):
        if route.request.resource_type in _BLOCK:
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-background-networking",
                "--no-first-run",
                "--mute-audio",
            ],
        )
        ctx = browser.new_context(user_agent=
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

        if cookie_file and cookie_file.exists():
            raw_cookies = _parse_netscape_cookies(cookie_file)
            if raw_cookies:
                ctx.add_cookies(raw_cookies)

        page = ctx.new_page()
        page.route("**/*", _handle_route)
        # Inject auth mock before any page scripts run
        page.add_init_script(_outseta_mock_js(cookie_file))
        page.on("request", _on_request)

        log(f"  Loading page: {url}", "muted")
        try:
            page.goto(url, wait_until="load", timeout=30000)
        except Exception:
            pass

        # Poll every 500 ms — exit as soon as a stream URL is captured, cap at 10 s
        elapsed, limit, step = 0, 10_000, 500
        while not captured and elapsed < limit:
            page.wait_for_timeout(step)
            elapsed += step

        browser.close()

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


def _parse_netscape_cookies(cookie_file: Path) -> list[dict]:
    """Parse a Netscape cookies.txt into Playwright cookie dicts."""
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
                "name":    name,
                "value":   value,
                "domain":  domain.lstrip("."),
                "path":    path,
                "secure":  secure.upper() == "TRUE",
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

        self.history     = load_history()
        self.cookie_file = tk.StringVar()
        self.out_dir     = tk.StringVar(value=str(DEFAULT_OUT))
        self.audio_only  = tk.BooleanVar(value=False)
        self.sub_en      = tk.BooleanVar(value=True)
        self.sub_th      = tk.BooleanVar(value=True)
        self.downloading = False

        self._build_ui()
        self._log("Ready. Paste a URL and click Download.", "muted")

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

        # URL input — multi-line
        lbl_row = tk.Frame(ctrl, bg=COLORS["panel"])
        lbl_row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0,2))
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
        url_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0,10))
        url_frame.columnconfigure(0, weight=1)
        self.url_box = tk.Text(url_frame,
                               bg=COLORS["input_bg"], fg=COLORS["text"],
                               insertbackground=COLORS["text"],
                               relief="flat", font=("Segoe UI", 10),
                               bd=8, height=4, wrap="none",
                               selectbackground=COLORS["accent2"])
        self.url_box.grid(row=0, column=0, sticky="ew")
        # Ctrl+Enter triggers download; plain Enter just adds a new line
        self.url_box.bind("<Control-Return>", lambda _: self._start_download())

        # Row 2: Output dir
        tk.Label(ctrl, text="Output folder", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).grid(
                 row=2, column=0, sticky="w", pady=(0,2))
        out_frame = tk.Frame(ctrl, bg=COLORS["input_bg"],
                             highlightbackground=COLORS["accent2"],
                             highlightthickness=1)
        out_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0,10))
        out_frame.columnconfigure(0, weight=1)
        tk.Entry(out_frame, textvariable=self.out_dir,
                 bg=COLORS["input_bg"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 relief="flat", font=("Segoe UI", 9), bd=6
                 ).grid(row=0, column=0, sticky="ew")
        self._small_btn(out_frame, "Browse", self._browse_out).grid(
            row=0, column=1, padx=4, pady=2)

        # Row 4: Cookies
        tk.Label(ctrl, text="Cookies file  (optional — for login-required sites)",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).grid(row=4, column=0,
                 columnspan=2, sticky="w", pady=(0,2))
        ck_frame = tk.Frame(ctrl, bg=COLORS["input_bg"],
                            highlightbackground=COLORS["accent2"],
                            highlightthickness=1)
        ck_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0,12))
        ck_frame.columnconfigure(0, weight=1)
        tk.Entry(ck_frame, textvariable=self.cookie_file,
                 bg=COLORS["input_bg"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 relief="flat", font=("Segoe UI", 9), bd=6
                 ).grid(row=0, column=0, sticky="ew")
        self._small_btn(ck_frame, "Browse", self._browse_cookies).grid(
            row=0, column=1, padx=4, pady=2)

        # Row 6: Options + Download button
        opts = tk.Frame(ctrl, bg=COLORS["panel"])
        opts.grid(row=6, column=0, columnspan=3, sticky="ew")
        opts.columnconfigure(4, weight=1)

        def _ck(parent, text, var, col):
            return tk.Checkbutton(parent, text=text, variable=var,
                                  bg=COLORS["panel"], fg=COLORS["text"],
                                  selectcolor=COLORS["accent2"],
                                  activebackground=COLORS["panel"],
                                  font=("Segoe UI", 9), cursor="hand2")

        _ck(opts, "Audio only",      self.audio_only, 0).grid(row=0, column=0, sticky="w", padx=(0,12))
        tk.Label(opts, text="Subtitles:", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w")
        _ck(opts, "English",         self.sub_en,     2).grid(row=0, column=2, sticky="w", padx=(4,4))
        _ck(opts, "Thai",            self.sub_th,     3).grid(row=0, column=3, sticky="w", padx=(0,8))

        self.dl_btn = tk.Button(opts, text="  ▶  DOWNLOAD  ",
                                command=self._start_download,
                                bg=COLORS["accent"], fg="white",
                                activebackground=COLORS["btn_hover"],
                                activeforeground="white",
                                relief="flat", font=("Segoe UI", 10, "bold"),
                                cursor="hand2", padx=18, pady=6)
        self.dl_btn.grid(row=0, column=6, sticky="e")

        self.open_btn = self._small_btn(opts, "Open folder", self._open_folder)
        self.open_btn.grid(row=0, column=5, sticky="e", padx=(0, 10))

        # ── Log ─────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=COLORS["bg"])
        log_frame.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        tk.Label(log_frame, text="LOG", bg=COLORS["bg"],
                 fg=COLORS["muted"], font=("Segoe UI", 8),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=16, pady=(8,2))

        self.log_box = scrolledtext.ScrolledText(
            log_frame, bg=COLORS["input_bg"], fg=COLORS["text"],
            font=("Consolas", 9), relief="flat", bd=0,
            state="disabled", wrap="word",
            selectbackground=COLORS["accent2"])
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=0)

        # Tag colours
        self.log_box.tag_config("info",    foreground=COLORS["text"])
        self.log_box.tag_config("muted",   foreground=COLORS["muted"])
        self.log_box.tag_config("success", foreground=COLORS["success"])
        self.log_box.tag_config("warn",    foreground=COLORS["warning"])
        self.log_box.tag_config("error",   foreground=COLORS["error"])
        self.log_box.tag_config("accent",  foreground=COLORS["accent"])
        self.log_box.tag_config("cmd",     foreground="#aaaaff")

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
        self.status_var.set("Downloading…")

        threading.Thread(target=self._download_worker,
                         args=(urls,), daemon=True).start()

    def _download_worker(self, urls):
        out_dir     = Path(self.out_dir.get())
        audio_only  = self.audio_only.get()
        ck_path_str = self.cookie_file.get().strip()
        cookie_file = Path(ck_path_str) if ck_path_str else None

        # Build subtitle language list from checkboxes
        sub_langs = []
        if self.sub_en.get():
            sub_langs.append("en")
        if self.sub_th.get():
            sub_langs.append("th")

        out_dir.mkdir(parents=True, exist_ok=True)

        pad = len(str(len(urls)))  # e.g. 3 urls → pad=1, 12 urls → pad=2

        for idx, url in enumerate(urls, start=1):
            ts = datetime.now().strftime("%H:%M:%S")

            if url in self.history:
                self._log(f"[{ts}] Already downloaded — skipping", "muted")
                self._log(f"  {url}", "muted")
                continue

            self._log(f"\n[{ts}] Processing URL", "accent")
            self._log(f"  {url}", "info")

            # Resolve URL (handles F1, Brightcove, etc.)
            self._log("  Detecting best download method…", "muted")
            resolved = resolve_url(url, cookie_file, self._log)

            # Build yt-dlp command
            fmt = FORMAT_AUDIO if audio_only else FORMAT_VIDEO
            num_prefix = f"{idx:0{pad}d} - " if len(urls) > 1 else ""

            # For intercepted stream URLs (m3u8/mp4 with tokens), derive a
            # clean filename from the original page URL slug instead of the
            # stream URL which contains JWT tokens and is too long for Windows.
            is_stream = resolved != url and (
                ".m3u8" in resolved or (".mp4" in resolved and "?" in resolved)
            )
            if is_stream:
                slug = re.sub(r"[^\w\s-]", "", url.rstrip("/").split("/")[-1])
                slug = re.sub(r"\s+", "-", slug)[:80] or "video"
                tpl = f"{num_prefix}{slug}.%(ext)s"
            else:
                tpl = f"{num_prefix}%(title).100B - [%(id)s].%(ext)s"
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
            ]
            if sub_langs:
                cmd += [
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-langs", ",".join(sub_langs),
                    "--sub-format", "srt",
                    "--convert-subs", "srt",
                ]
            if audio_only:
                cmd.insert(cmd.index("--merge-output-format"), "--extract-audio")
            if cookie_file and cookie_file.exists():
                cmd.extend(["--cookies", str(cookie_file)])
            cmd.append(resolved)

            self._log(f"  cmd: {' '.join(cmd)}", "cmd")
            self._log("", "info")

            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    bufsize=1
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
                    self._log(f"  {line}", tag)
                proc.wait()

                if proc.returncode == 0:
                    self._log(f"\n  Done!", "success")
                    self.history.add(url)
                    save_history(self.history)
                    self.after(0, lambda: self.status_var.set("Done"))
                else:
                    self._log(f"\n  Failed (exit {proc.returncode})", "error")
                    self.after(0, lambda: self.status_var.set("Failed"))

            except Exception as e:
                self._log(f"  Error: {e}", "error")

        self.downloading = False
        self.after(0, self._reset_btn)

    def _reset_btn(self):
        self.dl_btn.config(state="normal", text="  ▶  DOWNLOAD  ")
        if self.status_var.get() == "Downloading…":
            self.status_var.set("Idle")

    # ------------------------------------------------------------------
    # Log helper (thread-safe)
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
