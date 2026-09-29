"""
Tests for the watcher's completed-download harvest.

These exist for one reason: a directory-scoped `.part` check used to sit here
and fail finished downloads because *some other* attempt had left debris in the
output folder (issue #10, ADR-0005). The tests below pin the rule that replaced
it — a truthy DownloadOutcome is recorded as done, whatever else is on disk.

Run with:  python -m pytest tests/ -q     (or: python -m unittest -v)
"""

import contextlib
import inspect
import io
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.ui.cli import watcher  # noqa: E402
from yt_zero_touch.core.failures import FailureClass  # noqa: E402
from yt_zero_touch.core.models import DownloadOutcome  # noqa: E402


def _settled(value) -> Future:
    """A Future that has already completed with `value`."""
    f: Future = Future()
    f.set_result(value)
    return f


def _raised(exc: Exception) -> Future:
    f: Future = Future()
    f.set_exception(exc)
    return f


class HarvestTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name)
        self.history_file = self.out_dir / "processed_urls.json"
        self.history: "set[str]" = set()
        self.stats = {"detected": 0, "downloaded": 0, "failed": 0}
        self.addCleanup(self._tmp.cleanup)

    def harvest(self, in_flight):
        watcher._harvest_completed(
            in_flight,
            history=self.history,
            history_lock=threading.Lock(),
            history_file=self.history_file,
            stats=self.stats,
        )

    def leave_stale_part(self, name="Some Video - [abc123].f315.webm.part"):
        (self.out_dir / name).write_bytes(b"partial")


class TestStalePartFilesDoNotFailADownload(HarvestTestCase):
    """The regression. Both files below carry the same video id, which is why
    scoping the old guard's glob to the id would not have fixed it either."""

    def test_success_is_recorded_despite_a_stale_part_file(self):
        self.leave_stale_part()
        (self.out_dir / "Some Video - [abc123].mp4").write_bytes(b"complete")

        self.harvest({"https://x/watch?v=abc123": _settled(DownloadOutcome(ok=True))})

        self.assertIn("https://x/watch?v=abc123", self.history)
        self.assertEqual(self.stats, {"detected": 0, "downloaded": 1, "failed": 0})

    def test_success_is_recorded_despite_another_worker_downloading(self):
        # A concurrent worker's in-flight .part — the live race, not leftovers.
        self.leave_stale_part("Other Video - [zzz999].f299.mp4.part")

        self.harvest({"https://x/watch?v=abc123": _settled(DownloadOutcome(ok=True))})

        self.assertIn("https://x/watch?v=abc123", self.history)
        self.assertEqual(self.stats["downloaded"], 1)

    def test_history_is_persisted_so_the_url_is_not_downloaded_again(self):
        self.leave_stale_part()

        self.harvest({"https://x/watch?v=abc123": _settled(DownloadOutcome(ok=True))})

        self.assertEqual(
            json.loads(self.history_file.read_text()), ["https://x/watch?v=abc123"]
        )


class TestFailuresAreStillFailures(HarvestTestCase):
    def test_failed_outcome_is_not_recorded(self):
        failure = FailureClass("needs_cookies", "Login required", "Supply cookies.", True)
        self.harvest({"https://x/1": _settled(DownloadOutcome(ok=False, failure=failure))})

        self.assertEqual(self.history, set())
        self.assertEqual(self.stats["failed"], 1)
        self.assertFalse(self.history_file.exists())

    def test_worker_exception_is_a_failure_not_a_crash(self):
        self.harvest({"https://x/1": _raised(RuntimeError("boom"))})

        self.assertEqual(self.history, set())
        self.assertEqual(self.stats["failed"], 1)


class TestHarvestBookkeeping(HarvestTestCase):
    def test_only_finished_downloads_are_harvested(self):
        pending: Future = Future()
        in_flight = {
            "https://x/done": _settled(DownloadOutcome(ok=True)),
            "https://x/pending": pending,
        }

        self.harvest(in_flight)

        self.assertEqual(list(in_flight), ["https://x/pending"])
        self.assertEqual(self.history, {"https://x/done"})

    def test_nothing_finished_is_a_no_op(self):
        in_flight = {"https://x/pending": Future()}

        self.harvest(in_flight)

        self.assertEqual(list(in_flight), ["https://x/pending"])
        self.assertEqual(self.stats, {"detected": 0, "downloaded": 0, "failed": 0})


class TestWatcherDefaultPaths(unittest.TestCase):
    """The CLI's defaults used to resolve one directory short, landing on
    src/urls.txt and src/downloads/ instead of the repo root the README and
    run.bat both mean - so the watcher silently watched an empty file."""

    def test_base_dir_resolves_to_the_repo_root(self):
        base = Path(watcher.__file__).resolve().parents[4]
        self.assertTrue((base / "pyproject.toml").exists(),
                        f"watcher base resolved to {base}, not the repo root")
        self.assertNotEqual(base.name, "src")

    def test_history_file_is_shared_with_the_gui_by_default(self):
        # Both front ends must skip the same URLs; two rival history files
        # means the first watcher run re-downloads everything the GUI has.
        base = Path(watcher.__file__).resolve().parents[4]
        src = inspect.getsource(watcher.main)
        self.assertIn('history_file=base / "processed_urls.json"', src)
        self.assertEqual((base / "processed_urls.json").name,
                         "processed_urls.json")

    def test_watch_honours_an_explicit_history_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            shared = Path(tmp) / "processed_urls.json"
            shared.write_text(json.dumps(["https://x/already"]), encoding="utf-8")
            captured = {}

            def _fake_load(path):
                captured["path"] = Path(path)
                return {"https://x/already"}

            # watch() prints a box-drawing banner; a cp1252 test console
            # can't encode it and that is not what this test is about.
            with contextlib.redirect_stdout(io.StringIO()), \
                 mock.patch.object(watcher, "load_history", _fake_load), \
                 mock.patch.object(watcher, "Downloader", _NullDownloader), \
                 mock.patch.object(watcher.time, "sleep", _StopAfterFirstPoll()):
                try:
                    watcher.watch(
                        url_file=Path(tmp) / "urls.txt", out_dir=out,
                        audio_only=False, dry_run=True, history_file=shared,
                    )
                except KeyboardInterrupt:
                    pass

            self.assertEqual(captured["path"], shared)
            self.assertNotEqual(captured["path"], out / "processed_urls.json")


class _NullDownloader:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _StopAfterFirstPoll:
    """watch() loops forever; let it complete exactly one pass."""

    def __call__(self, _seconds):
        raise KeyboardInterrupt


if __name__ == "__main__":
    unittest.main()
