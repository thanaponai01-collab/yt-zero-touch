"""
Gallery-dl Engine Adapter.
==========================
Handles photo posts, multi-image carousels, and embedded video from
Instagram, Twitter/X, Reddit, Pinterest, Flickr, Tumblr, etc.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from yt_zero_touch.core.models import is_image_host
from yt_zero_touch.engines.base import BaseEngine, LogFn

try:
    import gallery_dl as _gallery_dl  # noqa: F401
    GALLERY_DL_OK = True
except ImportError:
    GALLERY_DL_OK = False

_LOGIN_WALLED_HOSTS = ("instagram.com", "facebook.com", "threads.net")
_BROWSER_COOKIE_ORDER = ("chrome", "edge", "brave", "firefox", "opera", "vivaldi")
_GALLERY_LOGIN_SIGNS = (
    "login", "redirect", "403", "401", "not logged in",
    "no valid session", "checkpoint", "challenge",
)


def is_login_walled(url: str) -> bool:
    return any(h in url for h in _LOGIN_WALLED_HOSTS)


def detect_browsers() -> list[str]:
    """Return installed browsers in preference order for cookie extraction."""
    candidates: dict[str, list[Path]] = {}
    if sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        roaming = Path(os.environ.get("APPDATA", ""))
        candidates = {
            "chrome":  [local / "Google/Chrome/User Data"],
            "edge":    [local / "Microsoft/Edge/User Data"],
            "brave":   [local / "BraveSoftware/Brave-Browser/User Data"],
            "vivaldi": [local / "Vivaldi/User Data"],
            "opera":   [roaming / "Opera Software/Opera Stable"],
            "firefox": [roaming / "Mozilla/Firefox/Profiles"],
        }
    else:
        home = Path.home()
        candidates = {
            "chrome":  [home / ".config/google-chrome"],
            "edge":    [home / ".config/microsoft-edge"],
            "brave":   [home / ".config/BraveSoftware/Brave-Browser"],
            "firefox": [home / ".mozilla/firefox"],
        }
    found = []
    for name in _BROWSER_COOKIE_ORDER:
        for p in candidates.get(name, []):
            try:
                if p.exists():
                    found.append(name)
                    break
            except Exception:
                pass
    return found


def _gallery_config_args(url: str) -> list[str]:
    args: list[str] = []
    if "instagram.com" in url:
        args += [
            "-o", "instagram.api=rest",
            "-o", "instagram.include=posts",
            "-o", "sleep-request=2.0-4.0",
        ]
    return args


def _run_gallery_dl(
    url: str,
    out_dir: Path,
    cookie_kind: str,
    cookie_value: str | None,
    force: bool,
    log: LogFn,
    *,
    quiet_errors: bool = False,
) -> tuple[bool, bool]:
    """Run gallery-dl once. Returns (success, hit_login_wall)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "--dest", str(out_dir),
        *(["--no-skip"] if force else []),
        *_gallery_config_args(url),
    ]
    if cookie_kind == "file" and cookie_value:
        cmd += ["--cookies", cookie_value]
    elif cookie_kind == "browser" and cookie_value:
        cmd += ["--cookies-from-browser", cookie_value]
        log(f"Downloading images with gallery-dl (cookies: {cookie_value})…", "info")
    if cookie_kind != "browser":
        log("Downloading images with gallery-dl…", "info")
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        log("  gallery-dl timed out after 600s", "error")
        return False, False
    except Exception as exc:
        log(f"  gallery-dl error: {exc}", "error")
        return False, False

    for line in (proc.stdout or "").splitlines():
        log(f"  {line}", "muted")

    if proc.returncode == 0 and (proc.stdout or "").strip():
        log("  gallery-dl finished.", "success")
        return True, False

    err = (proc.stderr or "") + (proc.stdout or "")
    login_wall = any(s in err.lower() for s in _GALLERY_LOGIN_SIGNS)
    if proc.returncode == 0 and not (proc.stdout or "").strip():
        login_wall = login_wall or is_login_walled(url)

    tail = err.strip().splitlines()[-5:]
    err_tag = "muted" if quiet_errors else "error"
    for line in tail:
        log(f"  {line}", err_tag)
    if not tail:
        log(f"  gallery-dl exited with code {proc.returncode}", err_tag)
    return False, login_wall


def download_gallery(
    url: str,
    out_dir: Path,
    cookie_file: Path | None = None,
    browser_cookie: str | None = None,
    force: bool = False,
    log: LogFn = lambda m, t: None,
    *,
    auto_cookie: bool = True,
) -> bool:
    """Download images or carousels using gallery-dl."""
    if not GALLERY_DL_OK:
        log("gallery-dl not installed — run: pip install gallery-dl", "error")
        return False

    cookie_sources: list[tuple[str, str | None]] = []
    if cookie_file and cookie_file.exists():
        cookie_sources.append(("file", str(cookie_file)))
    elif browser_cookie:
        cookie_sources.append(("browser", browser_cookie))
    elif auto_cookie and is_login_walled(url):
        detected = detect_browsers()
        if detected:
            log(f"No cookies given — auto-trying logged-in browser session ({', '.join(detected)})…", "info")
            cookie_sources = [("browser", b) for b in detected]
        else:
            cookie_sources.append(("none", None))
    else:
        cookie_sources.append(("none", None))

    last_login_wall = False
    for kind, value in cookie_sources:
        ok, login_wall = _run_gallery_dl(
            url, out_dir, kind, value, force, log,
            quiet_errors=(len(cookie_sources) > 1),
        )
        if ok:
            return True
        last_login_wall = login_wall
        if not login_wall:
            break

    if last_login_wall and is_login_walled(url):
        log("Instagram/Facebook needs you to be logged in. Fix once, works forever:", "warn")
        log("  1) Open instagram.com in Chrome/Edge/Firefox and log in.", "warn")
        log("  2) Keep that browser installed — the app borrows its session automatically.", "warn")
        log("  (Or pick your browser in the cookie dropdown / supply a cookies.txt.)", "warn")
    return False


class GalleryEngine(BaseEngine):
    def can_handle(self, url: str, **kwargs: Any) -> bool:
        return kwargs.get("gallery", False) or is_image_host(url)

    def download(self, url: str, out_dir: Path, log: LogFn, **kwargs: Any) -> bool:
        cookie_file = kwargs.get("cookie_file")
        browser_cookie = kwargs.get("browser_cookie")
        force = kwargs.get("force", False)
        return download_gallery(
            url,
            out_dir,
            cookie_file=Path(cookie_file) if cookie_file else None,
            browser_cookie=browser_cookie,
            force=force,
            log=log,
        )
