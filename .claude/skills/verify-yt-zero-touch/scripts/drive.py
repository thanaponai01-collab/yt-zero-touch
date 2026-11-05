"""Drive the real YT-DLP Zero-Touch Tk window and capture evidence.

Usage (from the repo root):
    python .claude/skills/verify-yt-zero-touch/scripts/drive.py doctor
    python .claude/skills/verify-yt-zero-touch/scripts/drive.py run <scenario> [options]
    python .claude/skills/verify-yt-zero-touch/scripts/drive.py cleanup

Each `run` launches its own App(base_dir=<fresh instance dir>) in this process,
drives it through the real widgets (Button.invoke, key events), writes evidence
to .claude/verify-evidence/<run-id>/, destroys the window, and deletes the
instance dir unless --keep. Exit code 0 = every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
EVIDENCE_ROOT = REPO / ".claude" / "verify-evidence"
RUNS_ROOT = REPO / ".claude" / "verify-runs"
DEFAULT_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".jpg", ".png", ".webp"}

sys.path.insert(0, str(REPO / "src"))
# Button labels carry emoji/arrows; a cp1252 console would crash on print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def doctor() -> int:
    ok = True

    def line(good: bool, name: str, detail: str) -> None:
        nonlocal ok
        ok &= good
        print(f"[{'ok' if good else 'FAIL'}] {name}: {detail}")

    line(sys.version_info >= (3, 10), "python", sys.version.split()[0])
    try:
        import tkinter  # noqa: F401
        line(True, "tkinter", "importable")
    except Exception as exc:
        line(False, "tkinter", str(exc))
    try:
        from yt_zero_touch.ui import app as app_mod  # noqa: F401
        line(True, "yt_zero_touch", f"imports from {REPO / 'src'}")
    except Exception as exc:
        line(False, "yt_zero_touch", repr(exc))
    try:
        import yt_dlp
        line(True, "yt-dlp", yt_dlp.version.__version__)
    except Exception as exc:
        line(False, "yt-dlp", repr(exc))
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        line(bool(path), tool, path or "not on PATH")
    gdl = shutil.which("gallery-dl")
    print(f"[{'ok' if gdl else 'warn'}] gallery-dl: {gdl or 'not on PATH (Photos only)'}")
    try:
        from PIL import ImageGrab  # noqa: F401
        line(True, "Pillow", "ImageGrab available (screenshots)")
    except Exception as exc:
        line(False, "Pillow", repr(exc))
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "src"],
                           capture_output=True, text=True).stdout.strip()
    print(f"[info] build: HEAD {head}{' + uncommitted src changes' if dirty else ''}")
    live = _live_runs()
    print(f"[info] driver runs still alive: {live or 'none'}")
    return 0 if ok else 1


class Harness:
    def __init__(self, run_id: str, keep: bool, visible: bool):
        self.run_id = run_id
        self.keep = keep
        self.visible = visible
        self.base = RUNS_ROOT / run_id
        self.evidence = EVIDENCE_ROOT / run_id
        self.base.mkdir(parents=True, exist_ok=True)
        self.evidence.mkdir(parents=True, exist_ok=True)
        (self.base / "driver.pid").write_text(str(os.getpid()))
        # A fresh stamp makes the app decide no update is due, so launch never pip-upgrades yt-dlp.
        (self.base / ".last_update_check").write_text(str(int(time.time())))
        self.checks: list[dict] = []
        self.app = None
        self.shots = 0

    def launch(self):
        import tkinter as tk
        from yt_zero_touch.ui import app as app_mod
        for attempt in range(4):  # Tk on Windows sometimes fails first with a spurious missing tk.tcl
            try:
                self.app = app_mod.App(base_dir=self.base)
                break
            except tk.TclError:
                if attempt == 3:
                    raise
                time.sleep(0.3)
        self.app.geometry("+40+40")
        self.app.deiconify()
        self.app.lift()
        self.app.attributes("-topmost", True)
        self.pump(lambda: "System initialized" in self.log_text(), 10, "app ready")
        return self.app

    def close(self):
        if self.app is not None:
            try:
                self.app._on_close()
            except Exception:
                pass
            self.app = None

    def pump(self, until, timeout: float, what: str) -> bool:
        # Short real mainloop slices, not update(): the app's worker thread reads
        # Tk variables, which raises "main thread is not in main loop" otherwise.
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.after(50, self.app.quit)
            self.app.mainloop()
            if until():
                return True
        self.app.update()
        print(f"  timeout after {timeout}s waiting for: {what}")
        return bool(until())

    def widgets(self, root=None):
        root = root or self.app
        for child in root.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, text: str):
        for w in self.widgets():
            if w.winfo_class() == "Button" and text in str(w.cget("text")):
                return w
        raise LookupError(f"no button containing {text!r}")

    def click(self, text: str):
        btn = self.button(text)
        print(f"  click: {btn.cget('text').strip()!r}")
        btn.invoke()
        self.app.update()

    def type_urls(self, text: str):
        box = self.app.url_box
        box.focus_force()
        box.insert("end", text)
        box.event_generate("<KeyRelease>")
        self.app.update()

    def press_ctrl_enter(self):
        self.app.url_box.focus_force()
        self.app.update()
        self.app.url_box.event_generate("<Control-Return>")
        self.app.update()

    def log_text(self) -> str:
        return self.app.log_box.get("1.0", "end")

    def queue_rows(self) -> list[list[str]]:
        q = self.app.queue
        return [list(q.item(i, "values")) for i in q.get_children()]

    def snapshot(self, label: str):
        self.shots += 1
        name = f"{self.shots:02d}-{label}.png"
        self.app.update()
        time.sleep(0.2)
        self.app.update()
        try:
            from PIL import ImageGrab
            hwnd = int(self.app.wm_frame(), 16)
            try:
                img = ImageGrab.grab(window=hwnd)
            except TypeError:
                x, y = self.app.winfo_rootx(), self.app.winfo_rooty()
                img = ImageGrab.grab(bbox=(x, y, x + self.app.winfo_width(), y + self.app.winfo_height()),
                                     all_screens=True)
            img.save(self.evidence / name)
        except Exception as exc:
            print(f"  screenshot failed: {exc!r}")
        state = {
            "status": self.app.status_var.get(),
            "link_count": self.app.link_counter_lbl.cget("text"),
            "quality": self.app.quality.get(),
            "summary": self.app.summary_lbl.cget("text"),
            "start_button": [self.app.dl_btn.cget("text").strip(), str(self.app.dl_btn.cget("state"))],
            "url_box": self.app.url_box.get("1.0", "end").strip(),
            "queue": self.queue_rows(),
        }
        (self.evidence / name.replace(".png", ".state.json")).write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  evidence: {name}")

    def check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}{' — ' + detail if detail else ''}")

    def finish(self, scenario: str, args: dict) -> int:
        if self.app is not None:
            (self.evidence / "app-log.txt").write_text(self.log_text(), encoding="utf-8")
        self.close()
        files = sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*") if p.is_file())
        result = {
            "scenario": scenario, "args": args, "run_id": self.run_id,
            "instance_dir": str(self.base), "instance_files": files,
            "passed": all(c["passed"] for c in self.checks) and bool(self.checks),
            "checks": self.checks,
        }
        (self.evidence / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        if not self.keep:
            shutil.rmtree(self.base, ignore_errors=True)
        print(f"\n{'PASSED' if result['passed'] else 'FAILED'} — evidence in {self.evidence}")
        return 0 if result["passed"] else 1


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
         "-of", "json", str(path)], capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except Exception:
        return {"error": out.stderr}


def sc_smoke(h: Harness, a):
    h.launch()
    h.snapshot("launched")
    h.check("window title", h.app.title() == "YT-DLP Zero-Touch", h.app.title())
    h.check("start button enabled", str(h.app.dl_btn.cget("state")) == "normal")
    h.check("no ffmpeg warning", "FFmpeg not detected" not in h.log_text())


def sc_download(h: Harness, a):
    h.launch()
    h.click(a.preset)
    h.type_urls(a.url)
    h.check("link counter", h.app.link_counter_lbl.cget("text") == "1 link ready",
            h.app.link_counter_lbl.cget("text"))
    h.snapshot("before-start")
    if a.via == "shortcut":
        h.press_ctrl_enter()
    else:
        h.click("START ZERO-TOUCH PIPELINE")
    h.check("pipeline started", h.pump(lambda: h.app.downloading, 5, "downloading=True"))
    h.snapshot("running")
    h.pump(lambda: not h.app.downloading, a.timeout, "pipeline finished")
    h.pump(lambda: str(h.app.dl_btn.cget("state")) == "normal", 5, "button reset")
    h.snapshot("finished")
    rows = h.queue_rows()
    h.check("queue row Done", bool(rows) and all("Done" in r[2] for r in rows), json.dumps(rows, ensure_ascii=False))
    out_dir = Path(h.app.out_dir.get())
    media = [p for p in out_dir.rglob("*") if p.suffix.lower() in VIDEO_EXTS]
    h.check("media file written", bool(media), ", ".join(p.name for p in media))
    probes = {p.name: ffprobe(p) for p in media}
    (h.evidence / "ffprobe.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")
    if a.preset != "Audio Only" and media:
        streams = next(iter(probes.values())).get("streams", [])
        vcodecs = [s["codec_name"] for s in streams if s.get("codec_type") == "video"]
        acodecs = [s["codec_name"] for s in streams if s.get("codec_type") == "audio"]
        want = "prores" if h.app.prores_proxy.get() else "h264"
        h.check(f"video codec {want}", want in vcodecs, f"video={vcodecs}")
        h.check("has audio stream", bool(acodecs), f"audio={acodecs}")
    hist = h.base / "processed_urls.json"
    h.check("history records URL", hist.exists() and a.url in hist.read_text(encoding="utf-8"))


def sc_preset(h: Harness, a):
    h.launch()
    for label, key in (("720p HD", "720p"), ("Audio Only", "Audio only"), ("Photos / dl", "Photos")):
        h.click(label)
        h.check(f"quality={key}", h.app.quality.get() == key, h.app.quality.get())
        h.snapshot(f"preset-{key.replace(' ', '_')}")
    h.click("ProRes 422 Proxy")
    h.check("prores toggled on", h.app.prores_proxy.get() is True)
    h.snapshot("prores-on")
    saved = json.loads((h.base / "settings.json").read_text(encoding="utf-8"))
    h.check("settings.json saved toggle", saved.get("prores_proxy") is True, json.dumps(saved))


def sc_load_urls(h: Harness, a):
    (h.base / "urls.txt").write_text("# test\nhttps://a.com/v1\nhttps://b.com/v2\nhttps://c.example/v3\n", encoding="utf-8")
    h.launch()
    h.type_urls("https://a.com/v1")
    h.click("Load urls.txt")
    box = h.app.url_box.get("1.0", "end")
    h.check("dedupe kept one a.com link", box.count("https://a.com/v1") == 1)
    h.check("new links appended", "https://b.com/v2" in box and "https://c.example/v3" in box)
    h.check("counter", h.app.link_counter_lbl.cget("text") == "3 links ready", h.app.link_counter_lbl.cget("text"))
    h.snapshot("after-load")


def sc_clipboard(h: Harness, a):
    h.launch()
    try:
        saved_clip = h.app.clipboard_get()
    except Exception:
        saved_clip = None
    try:
        h.click("Clipboard Watcher")
        h.check("watcher on", h.app.watch_clip.get() is True)
        h.app.clipboard_clear()
        h.app.clipboard_append("https://clip-test.com/v3")
        h.check("link auto-inserted",
                h.pump(lambda: "https://clip-test.com/v3" in h.app.url_box.get("1.0", "end"), 5, "clipboard poll"))
        h.snapshot("after-copy")
    finally:
        h.app.clipboard_clear()
        if saved_clip is not None:
            h.app.clipboard_append(saved_clip)
        h.app.update()


def sc_settings_restart(h: Harness, a):
    h.launch()
    h.click("720p HD")
    h.click("Thai (th)")
    h.close()  # real close path saves settings
    h.launch()
    h.snapshot("relaunched")
    h.check("quality restored", h.app.quality.get() == "720p", h.app.quality.get())
    h.check("TH subs restored", h.app.sub_th.get() is True)


def _wait_for(cond, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.5)
    return bool(cond())


def sc_watcher(h: Harness, a):
    urls_txt = h.base / "urls.txt"
    out_dir = h.base / "downloads"
    history = h.base / "processed_urls.json"
    repo_history = REPO / "processed_urls.json"
    repo_history_before = repo_history.read_bytes() if repo_history.exists() else None
    transcript = h.evidence / "watcher-stdout.txt"
    cmd = [sys.executable, str(REPO / "watcher.py"), "-f", str(urls_txt), "-o", str(out_dir),
           "--history", str(history), "--max-workers", "1"]
    (h.evidence / "watcher-cmd.txt").write_text(" ".join(f'"{c}"' for c in cmd), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with open(transcript, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=out, stderr=subprocess.STDOUT, env=env,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        (h.base / "child.pid").write_text(str(proc.pid))
        read = lambda: transcript.read_text(encoding="utf-8", errors="replace")  # noqa: E731
        try:
            h.check("watcher banner", _wait_for(lambda: "Concurrency" in read(), 20),
                    read().strip().splitlines()[-1] if read().strip() else "no output")
            h.check("watching private history", str(history) in read() or "0 previously processed" in read())
            time.sleep(1.5)  # the watcher records the file's mtime on its first poll; save after that
            with open(urls_txt, "a", encoding="utf-8") as f:
                f.write(a.url + "\n")
            h.check("URL queued", _wait_for(lambda: "Queued" in read() and a.url in read(), 15))
            h.check("history records URL",
                    _wait_for(lambda: history.exists() and a.url in history.read_text(encoding="utf-8"), a.timeout))
            h.check("transcript says Done", f"Done: {a.url}" in read())
        finally:
            # Ctrl+C, the watcher's clean exit, cannot reach a detached child on Windows.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            proc.wait(timeout=10)
    media = [p for p in out_dir.rglob("*") if p.suffix.lower() in VIDEO_EXTS]
    h.check("media file written", bool(media), ", ".join(p.name for p in media))
    probes = {p.name: ffprobe(p) for p in media}
    (h.evidence / "ffprobe.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")
    if media:
        streams = next(iter(probes.values())).get("streams", [])
        h.check("video codec h264", "h264" in [s["codec_name"] for s in streams if s.get("codec_type") == "video"])
        h.check("has audio stream", any(s.get("codec_type") == "audio" for s in streams))
    after = repo_history.read_bytes() if repo_history.exists() else None
    h.check("repo-root processed_urls.json untouched", after == repo_history_before)


SCENARIOS = {
    "smoke": sc_smoke,
    "watcher": sc_watcher,
    "download": sc_download,
    "preset": sc_preset,
    "load-urls": sc_load_urls,
    "clipboard": sc_clipboard,
    "settings-restart": sc_settings_restart,
}


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def _live_runs() -> list[str]:
    live = []
    for pidf in RUNS_ROOT.glob("*/*.pid"):
        pid = int(pidf.read_text().strip() or 0)
        if pid and pid != os.getpid() and _pid_alive(pid):
            live.append(f"{pidf.parent.name} (pid {pid})")
    return live


def cleanup() -> int:
    if not RUNS_ROOT.exists():
        print("nothing to clean")
        return 0
    for run in RUNS_ROOT.iterdir():
        for pidf in run.glob("*.pid"):
            pid = int(pidf.read_text().strip() or 0)
            if pid and pid != os.getpid() and _pid_alive(pid):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                print(f"killed {pidf.stem} pid {pid} ({run.name})")
        shutil.rmtree(run, ignore_errors=True)
        print(f"removed {run}")
    print(f"evidence kept in {EVIDENCE_ROOT}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("cleanup")
    r = sub.add_parser("run")
    r.add_argument("scenario", choices=sorted(SCENARIOS))
    r.add_argument("--url", default=DEFAULT_VIDEO, help="download: URL to fetch")
    r.add_argument("--preset", default="720p HD", help="download: preset chip label to click")
    r.add_argument("--via", choices=["button", "shortcut"], default="button", help="download: Start button or Ctrl+Enter")
    r.add_argument("--timeout", type=float, default=300, help="download: seconds to wait for the pipeline")
    r.add_argument("--keep", action="store_true", help="keep the instance dir for inspection")
    a = p.parse_args()

    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "cleanup":
        return cleanup()

    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{a.scenario}"
    h = Harness(run_id, keep=a.keep, visible=True)
    print(f"run {run_id}\n  instance: {h.base}\n  evidence: {h.evidence}")
    try:
        SCENARIOS[a.scenario](h, a)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        h.check("scenario raised no exception", False, repr(exc))
    return h.finish(a.scenario, {k: v for k, v in vars(a).items() if k != "cmd"})


if __name__ == "__main__":
    sys.exit(main())
