"""Regression: Retry Failed while a batch is running must not clobber input.

The button enables as soon as one row fails; clicking it mid-batch used to
overwrite the URL box and turn Force Re-download on, then do nothing because
_start_download returns early while a pipeline is active."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gui_smoke import app_mod, _new_app  # noqa: E402


class RetryWhileRunning(unittest.TestCase):
    def test_retry_failed_mid_batch_must_not_clobber_input(self):
        app_mod.update_tools = lambda *a, **k: False
        with tempfile.TemporaryDirectory() as d:
            app = _new_app(Path(d))
            app.withdraw()
            try:
                app.url_box.insert("end", "https://a.com/keep-me")
                app._reset_queue(["https://a.com/x"])
                app._on_item(1, "https://a.com/x", "failed", None)
                app.update()
                app.downloading = True          # batch still running
                app.force_redl.set(False)
                app._retry_failed()
                text = app.url_box.get("1.0", "end")
                self.assertIn("https://a.com/keep-me", text)
                self.assertFalse(app.force_redl.get())
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
