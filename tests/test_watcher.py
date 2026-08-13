"""
Tests for the watcher's completed-download harvest.

These exist for one reason: a directory-scoped `.part` check used to sit here
and fail finished downloads because *some other* attempt had left debris in the
output folder (issue #10, ADR-0004). The tests below pin the rule that replaced
it — a truthy DownloadOutcome is recorded as done, whatever else is on disk.

Run with:  python -m pytest tests/ -q     (or: python -m unittest -v)
"""

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import watcher  # noqa: E402
from orchestrator import DownloadOutcome, FailureClass  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
