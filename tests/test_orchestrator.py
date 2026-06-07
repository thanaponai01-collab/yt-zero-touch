"""
Tests for the UI-free orchestrator.

These exist to lock in the logic that used to be trapped inside the Tk App
class — most importantly the permanent-error classifier, whose old substring
form silently disabled the retry path.

Run with:  python -m pytest tests/ -q     (or: python -m unittest -v)
"""

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import (  # noqa: E402
    is_permanent_error,
    build_output_template,
    run_batch,
    BatchPolicy,
)


class TestIsPermanentError(unittest.TestCase):
    def test_named_permanent_failures_are_permanent(self):
        self.assertTrue(is_permanent_error(["ERROR: Video unavailable"]))
        self.assertTrue(is_permanent_error(["This video is not available in your country"]))
        self.assertTrue(is_permanent_error(["HTTP Error 403: Forbidden"]))
        self.assertTrue(is_permanent_error(["Sign in to confirm your age"]))

    def test_transient_failures_are_not_permanent(self):
        self.assertFalse(is_permanent_error(["Connection reset by peer, retrying"]))
        self.assertFalse(is_permanent_error(["Temporary failure in name resolution"]))
        self.assertFalse(is_permanent_error([]))

    def test_message_word_is_not_mistaken_for_age(self):
        # Regression: the old code used bare "age" as a keyword, and "message"
        # contains "age" — so a transient error mentioning "message" was wrongly
        # classified permanent and never retried.
        self.assertFalse(is_permanent_error(["received message too short, will retry"]))
        self.assertFalse(is_permanent_error(["unexpected end of stream package"]))


class TestBuildOutputTemplate(unittest.TestCase):
    def test_single_known_url_uses_title_id(self):
        url = "https://youtube.com/watch?v=abc"
        tpl = build_output_template(1, url, url, total=1, pad=1)
        self.assertEqual(tpl, "%(title).100B - [%(id)s].%(ext)s")

    def test_multi_url_gets_numeric_prefix(self):
        url = "https://youtube.com/watch?v=abc"
        tpl = build_output_template(2, url, url, total=12, pad=2)
        self.assertTrue(tpl.startswith("02 - "))

    def test_resolved_stream_is_slugified_from_page_url(self):
        url = "https://example.com/cool/My Race Highlights/"
        resolved = "https://cdn.example.com/x.m3u8?token=1"
        tpl = build_output_template(1, url, resolved, total=1, pad=1)
        self.assertEqual(tpl, "My-Race-Highlights.%(ext)s")


class _FakeDownloader:
    """Records calls; returns a scripted ok/fail per resolved URL."""

    def __init__(self, results):
        self.results = results          # dict resolved -> bool
        self.calls = []

    def download(self, resolved, **kwargs):
        self.calls.append((resolved, kwargs))
        kwargs["log"]("downloading…", "info")
        return self.results.get(resolved, True)


class TestRunBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_tmp_run_batch"
        self.tmp.mkdir(exist_ok=True)
        self.history_path = self.tmp / "history.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, urls, history, downloader, force=False):
        policy = BatchPolicy(out_dir=self.tmp, force=force)
        return run_batch(
            urls, policy, downloader,
            history=history,
            history_lock=threading.Lock(),
            history_path=self.history_path,
            log=lambda *a, **k: None,
            resolve_fn=lambda url, **kw: url,   # identity resolver
            playwright_ok=False,                # no browser in tests
        )

    def test_successful_downloads_recorded_to_history(self):
        history = set()
        dl = _FakeDownloader({})
        result = self._run(["http://a/1", "http://a/2"], history, dl)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.succeeded, 2)
        self.assertEqual(result.failed, 0)
        self.assertEqual(history, {"http://a/1", "http://a/2"})

    def test_already_downloaded_urls_are_skipped(self):
        history = {"http://a/1"}
        dl = _FakeDownloader({})
        result = self._run(["http://a/1", "http://a/2"], history, dl)
        self.assertEqual(result.total, 1)            # only the new one
        self.assertEqual([c[0] for c in dl.calls], ["http://a/2"])

    def test_force_redownloads_known_urls(self):
        history = {"http://a/1"}
        dl = _FakeDownloader({})
        result = self._run(["http://a/1"], history, dl, force=True)
        self.assertEqual(result.total, 1)
        self.assertTrue(dl.calls[0][1]["force"])     # force propagated to downloader


if __name__ == "__main__":
    unittest.main()
