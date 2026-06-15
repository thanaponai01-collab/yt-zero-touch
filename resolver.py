"""
YT-DLP Zero-Touch — URL Resolver (site-specific)
================================================
Turns a page URL into a direct, downloadable stream URL. This is the brittle,
site-specific layer — Formula1.com → Brightcove, generic Brightcove embeds,
and a headless-browser fallback that intercepts the stream a page requests.

It is deliberately kept OUT of the generic downloader so the downloader stays
reusable without dragging this scraping/auth-bypass code along with it.

Dependencies (optional — degrades gracefully if absent):
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.request
from pathlib import Path
from typing import Callable

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

# ---------------------------------------------------------------------------
# Logging contract — shared by the downloader too
# ---------------------------------------------------------------------------

LogFn = Callable[[str, str], None]  # (message, tag) where tag ∈ info/warn/error/success/muted


def _print_log(msg: str, tag: str = "info") -> None:
    prefix = {"warn": "[WARN]", "error": "[ERR ]", "success": "[OK  ]"}.get(tag, "[    ]")
    print(f"{prefix} {msg}")


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_BLOCK_RESOURCES = {"image", "font", "stylesheet"}
_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu", "--disable-software-rasterizer", "--disable-dev-shm-usage",
    "--disable-extensions", "--disable-background-networking",
    "--no-first-run", "--mute-audio",
]

_F1_RE      = re.compile(r"formula1\.com/en/video/.*?\.(\d{10,})")
_BC_ACCT_RE = re.compile(r"BRIGHTCOVE[_\s]*ACCOUNTID[\"\\s:]+(\d+)", re.IGNORECASE)
_BC_VID_RE  = re.compile(r'videoId["\s:=]+["\']?(\d{10,})')
_STREAM_RE  = re.compile(
    r'https?://[^\s"\'<>]+(?:\.m3u8|\.mp4|\.mpd)[^\s"\'<>]*', re.IGNORECASE
)
_KNOWN_DOMAINS = [
    "youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "dailymotion.com",
    "soundcloud.com", "twitter.com", "x.com", "instagram.com", "tiktok.com",
    "facebook.com", "bilibili.com", "reddit.com", "drive.google.com",
]
_IGNORE_STREAM = ["doubleclick", "googlevideo.com", "googlesyndication",
                  "thumbnail", "preview", "poster", "image"]

# Response bodies worth scanning for a stream URL embedded in the payload
# (many players fetch a small JSON/manifest that *contains* the real .m3u8).
_SCANNABLE_CTYPES = ("mpegurl", "dash+xml", "json", "text/", "javascript")
_MAX_SCAN_BYTES = 3_000_000

# Best-effort selectors to dismiss consent walls and start lazy-loaded players,
# so the player actually requests its stream within our wait window.
_CONSENT_SELECTORS = (
    "button#onetrust-accept-btn-handler",
    "button[aria-label*='accept' i]",
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button:has-text('Agree')",
    "button:has-text('Got it')",
)
_PLAY_SELECTORS = (
    "button[aria-label*='play' i]",
    ".vjs-big-play-button",
    ".ytp-large-play-button",
    "button.play",
    "[class*='play-button']",
)


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def resolve_url(
    url: str,
    cookie_file: "Path | str | None" = None,
    log: LogFn = _print_log,
    _browser=None,          # pass an open Playwright browser to reuse it
) -> str:
    """Convert any page URL to a direct downloadable URL.

    Handles:
    - Formula1.com → Brightcove player URL
    - Generic pages with Brightcove embed (static HTML scrape)
    - Unknown sites → headless browser stream interception (requires playwright)
    - Known yt-dlp sites → pass through unchanged
    """
    cookie_file = Path(cookie_file) if cookie_file else None

    # 1. Formula1.com
    m = _F1_RE.search(url)
    if m:
        bc = (f"https://players.brightcove.net/6057949432001"
              f"/default_default/index.html?videoId={m.group(1)}")
        log("Resolved F1 → Brightcove player", "info")
        return bc

    # 2. Known yt-dlp site — pass through
    if any(d in url for d in _KNOWN_DOMAINS):
        return url

    # 3. Static HTML Brightcove scrape (fast, no browser)
    try:
        bc = _brightcove_from_page(url, cookie_file)
        if bc:
            log("Found Brightcove embed in page HTML", "info")
            return bc
    except Exception:
        pass

    # 4. Headless browser interception
    if _PLAYWRIGHT_OK:
        browser = _browser or _launch_temp_browser()
        owned   = _browser is None
        try:
            stream = _intercept(browser, url, cookie_file, log)
            if stream:
                return stream
        finally:
            if owned:
                try:
                    browser.close()
                except Exception:
                    pass
    else:
        log("playwright not installed — trying URL directly", "warn")

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
    acct = _BC_ACCT_RE.search(html)
    vid  = _BC_VID_RE.search(html)
    if acct and vid:
        return (f"https://players.brightcove.net/{acct.group(1)}"
                f"/default_default/index.html?videoId={vid.group(1)}")
    return None


class _TempBrowser:
    """One-shot Playwright browser; close() shuts down both Chromium and the Playwright context."""

    def __init__(self):
        self._pw     = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True, args=_BROWSER_ARGS)

    def close(self):
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass

    def __getattr__(self, name: str):
        return getattr(self.browser, name)


def _launch_temp_browser() -> "_TempBrowser":
    return _TempBrowser()


def _nudge_player(page) -> None:
    """Best-effort: dismiss consent dialogs, scroll, and click a play button so
    a lazy-loaded player issues its stream request. All steps are optional and
    never raise — a site that needs none of them is unaffected."""
    for sel in _CONSENT_SELECTORS:
        try:
            page.click(sel, timeout=800)
            break
        except Exception:
            pass
    try:
        page.mouse.wheel(0, 1200)
    except Exception:
        pass
    for sel in _PLAY_SELECTORS:
        try:
            page.click(sel, timeout=800)
            break
        except Exception:
            pass


def _intercept(browser, url: str, cookie_file: "Path | None", log: LogFn) -> "str | None":
    log("Launching headless browser to intercept stream…", "muted")
    captured = []
    all_urls: list[str] = []

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
    page.add_init_script(_outseta_js(cookie_file))

    def _on_request(req):
        u = req.url
        all_urls.append(u)
        if _STREAM_RE.search(u) and not any(x in u for x in _IGNORE_STREAM):
            captured.append(u)

    def _on_response(resp):
        # Scan small text/JSON/manifest bodies for a stream URL the page never
        # requested directly (e.g. an API that returns the .m3u8 in its JSON).
        try:
            ctype = (resp.headers or {}).get("content-type", "").lower()
            if not any(t in ctype for t in _SCANNABLE_CTYPES):
                return
            body = resp.text()
        except Exception:
            return
        if not body or len(body) > _MAX_SCAN_BYTES:
            return
        for m in _STREAM_RE.findall(body):
            if not any(x in m for x in _IGNORE_STREAM):
                captured.append(m)

    page.on("request", _on_request)
    page.on("response", _on_response)

    try:
        page.goto(url, wait_until="load", timeout=30_000)
    except Exception:
        pass

    # Nudge the page into actually loading its player: dismiss consent walls,
    # scroll lazy content into view, and click an obvious play button.
    _nudge_player(page)

    elapsed, limit, step = 0, 20_000, 500
    while not captured and elapsed < limit:
        page.wait_for_timeout(step)
        elapsed += step
        # Re-scroll periodically — some players only initialise once visible.
        if elapsed % 5_000 == 0:
            try:
                page.mouse.wheel(0, 1500)
            except Exception:
                pass

    page.close()
    ctx.close()

    if not captured:
        # Log all seen domains to help diagnose what the page is requesting
        from urllib.parse import urlsplit as _urlsplit
        seen_hosts = sorted({_urlsplit(u).netloc for u in all_urls if u.startswith("http")} - {""})
        log(f"No stream URL intercepted. Hosts seen: {', '.join(seen_hosts) or '(none)'}", "warn")
        return None

    for u in captured:
        if ".m3u8" in u and not any(x in u for x in ["segment", "/ts/", "fmp4"]):
            log(f"Intercepted: {u[:80]}…", "success")
            return u
    log(f"Intercepted: {captured[0][:80]}…", "success")
    return captured[0]


def _outseta_js(cookie_file: "Path | None") -> str:
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
                "name": name, "value": value,
                "domain": domain.lstrip("."), "path": path,
                "secure": secure.upper() == "TRUE", "sameSite": "None",
            })
    except Exception:
        pass
    return cookies
