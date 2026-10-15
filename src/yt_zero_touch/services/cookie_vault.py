"""
Cookie Vault Service — Playwright-Powered In-App Authentication.
================================================================
Allows users to log in directly into YouTube, Instagram, X/Twitter, or Facebook
via a dedicated visible browser window. Extracts session cookies cleanly without
relying on browser extensions, locked SQLite databases, or App-Bound Encryption.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from yt_zero_touch.core.cookies import export_playwright_cookies, inspect_cookie_file

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_VAULT_OK = True
except ImportError:
    sync_playwright = None  # type: ignore
    PLAYWRIGHT_VAULT_OK = False


VAULT_TARGETS = {
    "youtube": {
        "label": "YouTube / Google",
        "url": "https://www.youtube.com/",
        "domain": "youtube.com",
    },
    "instagram": {
        "label": "Instagram",
        "url": "https://www.instagram.com/accounts/login/",
        "domain": "instagram.com",
    },
    "twitter": {
        "label": "Twitter / X",
        "url": "https://x.com/i/flow/login",
        "domain": "x.com",
    },
    "facebook": {
        "label": "Facebook",
        "url": "https://www.facebook.com/login/",
        "domain": "facebook.com",
    },
}

_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--password-store=basic",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def launch_login_vault(
    target_key: str,
    save_path: Path | str,
    *,
    log: Callable[[str, str], None] = lambda m, t: None,
    on_done: Callable[[bool, str], None] | None = None,
) -> bool:
    """Launch a visible browser for user login and capture cookies on close.

    Runs synchronously; callers should dispatch via threading.Thread.
    """
    if not PLAYWRIGHT_VAULT_OK or sync_playwright is None:
        msg = "Playwright is not installed. Run: pip install playwright && python -m playwright install chromium"
        log(msg, "error")
        if on_done:
            on_done(False, msg)
        return False

    target = VAULT_TARGETS.get(target_key, VAULT_TARGETS["youtube"])
    out_path = Path(save_path)
    profile_dir = out_path.parent / ".vault_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    log(f"Opening Login Vault for {target['label']}…", "accent")
    log("Log into your account in the browser window, then simply close the window when done.", "info")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                user_agent=_USER_AGENT,
                viewport={"width": 1100, "height": 850},
                args=_BROWSER_ARGS,
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.goto(target["url"])

            # Wait for user to close all pages in the context
            closed_event = threading.Event()

            def _check_pages():
                while not closed_event.is_set():
                    time.sleep(0.5)
                    try:
                        # If all pages are closed or context is disconnected
                        if not context.pages or all(p.is_closed() for p in context.pages):
                            closed_event.set()
                            break
                    except Exception:
                        closed_event.set()
                        break

            watcher_thread = threading.Thread(target=_check_pages, daemon=True)
            watcher_thread.start()

            closed_event.wait(timeout=600)  # 10 minute maximum login window

            # Extract all captured cookies before closing
            try:
                cookies = context.cookies()
            except Exception:
                cookies = []

            try:
                context.close()
            except Exception:
                pass

        if not cookies:
            msg = f"Login Vault closed with no cookies saved for {target['label']}."
            log(msg, "warn")
            if on_done:
                on_done(False, msg)
            return False

        saved_count = export_playwright_cookies(cookies, out_path)
        status = inspect_cookie_file(out_path)

        success_msg = f"Vault captured {saved_count} cookies ({status.summary}) into {out_path.name}!"
        log(success_msg, "success")
        if on_done:
            on_done(True, success_msg)
        return True

    except Exception as exc:
        err_msg = f"Login Vault failed: {exc}"
        log(err_msg, "error")
        if on_done:
            on_done(False, err_msg)
        return False
