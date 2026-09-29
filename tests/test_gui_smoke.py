"""Drive the real Tk window (hidden) for the GUI features in FEATURES.md.

Skipped when no display is available. update_tools is stubbed so the app's
startup auto-update can never touch the installed packages.
"""

import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import tkinter as tk  # noqa: E402

from yt_zero_touch.ui import app as app_mod  # noqa: E402


def _display_ok() -> bool:
    # Not probed by creating a Tk root: a throwaway root before the real one is
    # what made Windows runs flake with a missing tk.tcl.
    return sys.platform == "win32" or bool(os.environ.get("DISPLAY"))


def _new_app(base):
    # Tk startup occasionally fails on Windows with a spurious "can't find tk.tcl"; retry it.
    for attempt in range(4):
        try:
            return app_mod.App(base_dir=base)
        except tk.TclError:
            if attempt == 3:
                raise
            time.sleep(0.3)


@unittest.skipUnless(_display_ok(), "no display for Tk")
class TestGuiSmoke(unittest.TestCase):
    # One window for the class: repeatedly creating Tk roots is flaky on Windows.
    @classmethod
    def setUpClass(cls):
        cls._orig_update = app_mod.update_tools
        app_mod.update_tools = lambda *a, **k: False
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        cls.app = _new_app(cls.base)
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        app_mod.update_tools = cls._orig_update
        cls.tmp.cleanup()

    def setUp(self):
        self.app.url_box.delete("1.0", "end")

    def test_link_count_counts_urls_in_the_box(self):
        self.app.url_box.insert("end", "https://a.com/v1\nnot a url\nhttps://b.com/v2")
        self.app._update_link_count()
        self.assertEqual(self.app.link_counter_lbl.cget("text"), "2 links ready")

    def test_load_urls_txt_adds_only_new_links(self):
        (self.base / "urls.txt").write_text("https://a.com/v1\nhttps://b.com/v2\n", encoding="utf-8")
        self.app.url_box.insert("end", "https://a.com/v1")
        self.app._load_from_urls_file()
        text = self.app.url_box.get("1.0", "end")
        self.assertEqual(text.count("https://a.com/v1"), 1)
        self.assertIn("https://b.com/v2", text)

    def test_clear_finished_keeps_only_unfinished_rows(self):
        self.app._reset_queue(["https://a.com/1", "https://a.com/2", "https://a.com/3"])
        self.app._on_item(1, "https://a.com/1", "done", None)
        self.app._on_item(2, "https://a.com/2", "failed", None)
        self.app.update()  # _on_item applies via after()
        self.app._clear_finished_rows()
        self.assertEqual(len(self.app.queue.get_children()), 1)

    def test_settings_survive_a_restart(self):
        self.app.quality.set("720p")
        self.app.sub_th.set(True)
        self.app._save_settings()
        self.app.quality.set("Best")
        self.app.sub_th.set(False)
        self.app._load_settings()  # what App.__init__ runs on the next launch
        self.assertEqual(self.app.quality.get(), "720p")
        self.assertTrue(self.app.sub_th.get())

    def test_clipboard_watcher_inserts_a_copied_link(self):
        self.app.watch_clip.set(True)
        self.app._clip_last = ""
        self.app.clipboard_clear()
        self.app.clipboard_append("https://c.com/v3")
        self.app._poll_clipboard()
        self.assertIn("https://c.com/v3", self.app.url_box.get("1.0", "end"))


    def test_start_button_hands_the_urls_and_options_to_run_batch(self):
        calls = []

        def fake_run_batch(urls, policy, downloader, **kw):
            calls.append((urls, policy))
            return SimpleNamespace(total=0)

        self.app.quality.set("Audio only")
        self.app.url_box.insert("end", "https://a.com/v1\nhttps://b.com/v2")
        with mock.patch.object(app_mod, "run_batch", fake_run_batch):
            self.app.dl_btn.invoke()
            # The worker thread reads Tk variables, which needs a running mainloop.
            deadline = time.time() + 5
            while (self.app.downloading or not calls) and time.time() < deadline:
                self.app.after(50, self.app.quit)
                self.app.mainloop()
            self.app.update()
        self.assertEqual(len(calls), 1)
        urls, policy = calls[0]
        self.assertEqual(urls, ["https://a.com/v1", "https://b.com/v2"])
        self.assertTrue(policy.audio_only)
        self.assertEqual(str(self.app.dl_btn.cget("state")), "normal")

    def test_start_with_nothing_startable_does_not_start_a_batch(self):
        for text in ("", "just words, no link"):
            self.app.url_box.delete("1.0", "end")
            self.app.url_box.insert("end", text)
            with mock.patch.object(app_mod, "run_batch") as rb:
                self.app.dl_btn.invoke()
                self.app.update()
            rb.assert_not_called()
            self.assertFalse(self.app.downloading)


    def test_queue_grows_a_row_for_a_video_beyond_the_pre_populated_ones(self):
        # A page that embeds several videos fans out to more work items than URLs pasted.
        self.app._reset_queue(["https://a.com/1"])
        self.app._on_item(2, "https://a.com/1", "queued", None)
        self.app.update()
        self.assertEqual(len(self.app.queue.get_children()), 2)
        self.app._on_item(2, "https://a.com/1", "done", None)
        self.app.update()
        self.assertEqual(len(self.app.queue.get_children()), 2)

if __name__ == "__main__":
    unittest.main()
