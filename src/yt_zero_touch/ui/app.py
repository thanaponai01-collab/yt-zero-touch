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

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from yt_zero_touch.core.cookies import CookieStatus, inspect_cookie_file
from yt_zero_touch.core.config import AppSettings
from yt_zero_touch.services.cookie_vault import VAULT_TARGETS, launch_login_vault
from yt_zero_touch.core.history import HistoryStore
from yt_zero_touch.core.models import QUALITY_PRESETS, URL_RE, BatchPolicy
from yt_zero_touch.engines.ytdlp_engine import Downloader, YT_DLP_API_OK
from yt_zero_touch.services.orchestrator import run_batch
from yt_zero_touch.services.system import check_ffmpeg
from yt_zero_touch.services.updater import ToolUpdateScheduler, update_tools
from yt_zero_touch.ui.layout import LayoutMixin
from yt_zero_touch.ui.theme import COLORS, STATUS_STYLE

try:
    from plyer import notification as _plyer_notification
    _NOTIFY_OK = True
except ImportError:
    _NOTIFY_OK = False

MAX_WORKERS = 3
CLIP_POLL_MS = 1000

class App(LayoutMixin, tk.Tk):
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
        self._retry_force = False   # one-run override set by Retry Failed
        self.sections = tk.StringVar(value="")
        self.watch_clip = tk.BooleanVar(value=False)
        self.prores_proxy = tk.BooleanVar(value=False)

        self.downloading = False
        self._updating = False
        self._clip_last = ""
        self._queue_rows: dict[int, str] = {}
        self._preset_buttons: dict[str, tk.Button] = {}
        self._toggle_buttons: list[tuple[tk.Button, tk.BooleanVar, str, str, str, str]] = []
        self._last_failed_urls: list[str] = []
        self._current_cookie_status: CookieStatus | None = None

        self._load_settings()
        self._build_ui()
        self._update_cookie_status()

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

    # Layout lives in ui/layout.py (LayoutMixin).

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
            status = getattr(self, "_current_cookie_status", None)
            stat_hint = f" [{status.summary}]" if status and status.valid else ""
            parts.append(f"Cookies: {Path(self.cookie_file.get().strip()).name}{stat_hint}")
        else:
            parts.append("Cookies: None")

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
            self._update_cookie_status()
            self._update_profile_summary()
            self._log(f"Loaded cookies file: {Path(f).name}", "info")

    def _update_cookie_status(self):
        ck_path = self.cookie_file.get().strip()
        status = inspect_cookie_file(ck_path if ck_path else None)
        self._current_cookie_status = status

        if status.status == "active":
            lbl_text = f"● {status.summary}"
            fg_col = COLORS["success"]
        elif status.status == "expiring_soon":
            lbl_text = f"⚠ {status.summary}"
            fg_col = COLORS["amber"]
        elif status.status == "expired":
            lbl_text = f"✖ {status.summary}"
            fg_col = COLORS["error"]
        elif status.status == "missing":
            lbl_text = f"⚠ {status.summary}"
            fg_col = COLORS["error"]
        else:
            lbl_text = "○ No cookies"
            fg_col = COLORS["muted"]

        if hasattr(self, "cookie_status_btn"):
            self.cookie_status_btn.config(text=lbl_text, fg=fg_col)

    def _show_cookie_details(self):
        status = getattr(self, "_current_cookie_status", None)
        if not status or status.status == "none":
            messagebox.showinfo(
                "Cookie Status",
                "No cookie file currently loaded.\n\nUse 'Cookie file…' to select a cookies.txt, "
                "or click '🔐 Login Vault…' to authenticate directly without browser extensions.",
            )
            return
        details_txt = "\n".join(status.details)
        messagebox.showinfo("Cookie Health & Expiration", f"Status: {status.summary}\n\n{details_txt}")

    def _open_login_vault(self):
        vault_win = tk.Toplevel(self)
        vault_win.title("🔐 Login Vault")
        vault_win.geometry("380x300")
        vault_win.configure(bg=COLORS["card"])
        vault_win.resizable(False, False)
        vault_win.transient(self)
        vault_win.grab_set()

        tk.Label(
            vault_win, text="🔐 Browser Login Vault",
            bg=COLORS["card"], fg=COLORS["text_bright"],
            font=("Segoe UI", 12, "bold"),
        ).pack(pady=(16, 4))

        tk.Label(
            vault_win,
            text="Opens a clean browser window to log in.\nCookies are automatically captured when you close the window.",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Segoe UI", 8), justify="center",
        ).pack(pady=(0, 14))

        btn_frame = tk.Frame(vault_win, bg=COLORS["card"])
        btn_frame.pack(fill="x", padx=24)

        for key, target in VAULT_TARGETS.items():
            btn = tk.Button(
                btn_frame,
                text=f"Log in to {target['label']}",
                command=lambda k=key: self._start_vault_login(k, vault_win),
                bg=COLORS["input_bg"], fg=COLORS["text"],
                activebackground=COLORS["accent"], activeforeground="white",
                relief="flat", font=("Segoe UI", 9, "bold"),
                cursor="hand2", pady=6,
                highlightthickness=1, highlightbackground=COLORS["border"],
            )
            btn.pack(fill="x", pady=3)

    def _start_vault_login(self, target_key: str, win: tk.Toplevel):
        win.destroy()
        vault_file = self.base_dir / "Cookies" / "vault_cookies.txt"
        self._log(f"Launching Login Vault for {target_key} in a clean browser window…", "accent")

        def _on_done(ok: bool, msg: str):
            def _apply():
                if ok:
                    self.cookie_file.set(str(vault_file))
                    self.browser_cookies.set("none")
                    self._save_settings()
                    self._update_cookie_status()
                    self._update_profile_summary()
                    self._log(f"Vault cookies activated: {vault_file.name}", "success")
                else:
                    self._log(msg, "warn")
            self.after(0, _apply)

        threading.Thread(
            target=launch_login_vault,
            args=(target_key, vault_file),
            kwargs={"log": self._log, "on_done": _on_done},
            daemon=True,
        ).start()

    def _retry_failed(self):
        if self.downloading:
            self._log("A pipeline is still running - retry the failed items when it finishes.", "warn")
            return
        failed_urls = list(self._last_failed_urls)
        for iid in self.queue.get_children():
            tags = self.queue.item(iid, "tags") or ()
            if "failed" in tags:
                vals = self.queue.item(iid, "values")
                if len(vals) >= 2 and vals[1] not in failed_urls:
                    failed_urls.append(vals[1])

        if not failed_urls:
            self._log("No failed URLs to retry.", "info")
            return

        self._log(f"Retrying {len(failed_urls)} failed download(s) with Force Re-download…", "accent")
        self.url_box.delete("1.0", "end")
        self.url_box.insert("end", "\n".join(failed_urls))
        self._retry_force = True
        self._update_link_count()
        self._update_profile_summary()
        self._start_download()

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

    def _set_retry_button(self, failed_cnt: int):
        """Show the Retry Failed button as active (amber) or idle (muted)."""
        if not hasattr(self, "retry_failed_btn"):
            return
        if failed_cnt > 0:
            self.retry_failed_btn.config(
                state="normal",
                text=f"🔁 Retry Failed ({failed_cnt})",
                bg=COLORS["amber"],
                fg="black",
                activebackground=COLORS["amber"],
                activeforeground="black",
            )
        else:
            self.retry_failed_btn.config(
                state="disabled",
                text="🔁 Retry Failed (0)",
                bg=COLORS["card_alt"],
                fg=COLORS["muted"],
            )

    def _reset_queue(self, urls: list[str]):
        for iid in self.queue.get_children():
            self.queue.delete(iid)
        self._queue_rows.clear()
        self._last_failed_urls.clear()
        self._set_retry_button(0)
        for idx, url in enumerate(urls, 1):
            iid = self.queue.insert("", "end", values=(str(idx), url, "Queued", "-"), tags=("queued",))
            self._queue_rows[idx] = iid

    def _on_item(self, idx: int, url: str, status: str, pct: float | None):
        """orchestrator callback - update one queue row. Runs off-thread.

        idx can exceed the row count _reset_queue pre-populated: a page URL
        that embeds several videos (see resolver.resolve_urls) fans out into
        one work item per video, so a row is created here on first sight.
        """
        def _apply():
            iid = self._queue_rows.get(idx)
            if not iid:
                iid = self.queue.insert(
                    "", "end", values=(str(idx), url, "Queued", "-"), tags=("queued",))
                self._queue_rows[idx] = iid
            lbl, _ = STATUS_STYLE.get(status, (status.capitalize(), COLORS["text"]))
            pct_str = f"{pct:.1f}%" if pct is not None else "-"
            self.queue.item(iid, values=(str(idx), url, lbl, pct_str), tags=(status,))

            if status == "failed":
                if url not in self._last_failed_urls:
                    self._last_failed_urls.append(url)
            elif status == "done":
                if url in self._last_failed_urls:
                    self._last_failed_urls.remove(url)

            self._set_retry_button(len(self._last_failed_urls))
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
            force=self.force_redl.get() or self._retry_force,
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
            self._retry_force = False
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
