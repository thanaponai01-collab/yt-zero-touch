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
    classify_failure,
    download_with_retry,
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

    def test_bare_http_codes_are_permanent(self):
        # A bare code with no "HTTP Error " prefix must still classify as
        # permanent (403/401 → needs login, 404 → removed).
        self.assertTrue(is_permanent_error(["ERROR: server returned 403"]))
        self.assertTrue(is_permanent_error(["ERROR: got 404 for fragment 1"]))
        self.assertTrue(is_permanent_error(["ERROR: unauthorized (401)"]))

    def test_lookalike_numbers_do_not_trip_bare_code_match(self):
        # Word-boundary match — "4040" / "503" / a number glued to text must not
        # be read as a 403/404/401.
        self.assertFalse(is_permanent_error(["downloaded 4040 bytes, retrying"]))
        self.assertFalse(is_permanent_error(["HTTP Error 503: Service Unavailable… retrying"]))
        self.assertFalse(is_permanent_error(["timeout after 4030ms"]))


class TestClassifyFailure(unittest.TestCase):
    def test_bare_403_maps_to_cookies_404_to_removed(self):
        self.assertEqual(classify_failure(["got 403 back"]).reason, "needs_cookies")
        self.assertEqual(classify_failure(["got 404 back"]).reason, "removed")

    def test_phrase_rule_wins_over_bare_code(self):
        # A geo phrase next to a stray 403 still classifies as geo, because the
        # phrase rules run before the bare-code fallback.
        fc = classify_failure(["not available in your country (was 403 earlier)"])
        self.assertEqual(fc.reason, "geo_blocked")


    def test_login_required_maps_to_cookies(self):
        for msg in ["ERROR: Sign in to confirm your age",
                    "Private video. Sign in if you've been granted access",
                    "HTTP Error 403: Forbidden"]:
            fc = classify_failure([msg])
            self.assertIsNotNone(fc, msg)
            self.assertEqual(fc.reason, "needs_cookies", msg)
            self.assertTrue(fc.permanent)
            self.assertIn("cookie", fc.remedy.lower())

    def test_geo_block_maps_to_geo(self):
        fc = classify_failure(["This video is not available in your country"])
        self.assertEqual(fc.reason, "geo_blocked")

    def test_no_formats_suggests_update(self):
        fc = classify_failure(["ERROR: No video formats found"])
        self.assertEqual(fc.reason, "needs_update")

    def test_removed_video(self):
        fc = classify_failure(["ERROR: Video unavailable. This video has been removed"])
        self.assertEqual(fc.reason, "removed")

    def test_transient_is_unclassified(self):
        self.assertIsNone(classify_failure(["Connection reset by peer, retrying"]))
        self.assertIsNone(classify_failure([]))


class TestDownloadWithRetry(unittest.TestCase):
    def _policy(self, **kw):
        return BatchPolicy(out_dir=Path("."), retry_delays=(0, 0, 0), **kw)

    def test_success_returns_truthy_outcome(self):
        outcome = download_with_retry(
            lambda log, hook: True, policy=self._policy(), url="x", sleep=lambda *_: None,
        )
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome)          # __bool__ keeps old callers working
        self.assertIsNone(outcome.failure)

    def test_permanent_failure_does_not_retry_and_carries_reason(self):
        calls = []
        def dl(log, hook):
            calls.append(1)
            log("ERROR: Private video", "error")
            return False
        outcome = download_with_retry(
            dl, policy=self._policy(retry_max=3), url="x", sleep=lambda *_: None,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(len(calls), 1)   # short-circuited, no retries
        self.assertEqual(outcome.failure.reason, "needs_cookies")

    def test_transient_failure_retries_then_gives_up_unclassified(self):
        calls = []
        def dl(log, hook):
            calls.append(1)
            log("ERROR: connection reset by peer", "error")
            return False
        outcome = download_with_retry(
            dl, policy=self._policy(retry_max=2), url="x", sleep=lambda *_: None,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(len(calls), 3)   # initial + 2 retries
        self.assertIsNone(outcome.failure)


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

    def test_permanent_failure_classified_recorded_and_not_in_history(self):
        # Seam coverage: run_batch → real download_with_retry → real
        # classify_failure → BatchResult.failures, mocking only the leaf
        # downloader. A permanent failure must not retry, must stay out of
        # history, and must carry an actionable cause to the caller.
        class _FailingDownloader:
            def __init__(self):
                self.calls = 0

            def download(self, resolved, **kwargs):
                self.calls += 1
                kwargs["log"]("ERROR: Private video. Sign in to confirm", "error")
                return False

        history = set()
        dl = _FailingDownloader()
        result = self._run(["http://a/1"], history, dl)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.succeeded, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual(dl.calls, 1)                # permanent → no retries
        self.assertNotIn("http://a/1", history)      # failures never recorded
        self.assertEqual(len(result.failures), 1)
        _idx, _url, failure = result.failures[0]
        self.assertEqual(failure.reason, "needs_cookies")


if __name__ == "__main__":
    unittest.main()
