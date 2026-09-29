"""Tests for the updater and system services. No test touches pip, ffmpeg or the network:
subprocess is faked, and disk/deno lookups run against temp dirs."""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.services import system, updater  # noqa: E402


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


class TestUpdateTools(unittest.TestCase):
    def _run(self, versions, run_result, **kw):
        """versions: successive get_pkg_version answers; run_result: what pip returns."""
        logs = []
        installs = []

        def fake_run(cmd, **_):
            installs.append(cmd)
            if isinstance(run_result, Exception):
                raise run_result
            return run_result

        with mock.patch.object(updater, "get_pkg_version", side_effect=list(versions)), \
             mock.patch.object(updater.subprocess, "run", side_effect=fake_run):
            changed = updater.update_tools(log=lambda m, t="info": logs.append((t, m)), **kw)
        return changed, logs, installs

    def test_version_change_returns_true_and_updates_both_packages(self):
        changed, logs, installs = self._run(["1", "2", "3", "4"], _proc())
        self.assertTrue(changed)
        self.assertEqual(len(installs), 2)
        self.assertTrue(any("1 → 2" in m for _t, m in logs))

    def test_same_version_returns_false(self):
        changed, logs, _ = self._run(["1", "1", "3", "3"], _proc())
        self.assertFalse(changed)
        self.assertTrue(any("already current" in m for _t, m in logs))

    def test_gallery_can_be_skipped(self):
        _, _, installs = self._run(["1", "2"], _proc(), gallery_ok=False)
        self.assertEqual(len(installs), 1)
        self.assertIn(updater.YTDLP_NIGHTLY, installs[0])

    def test_pip_failure_is_logged_and_not_a_change(self):
        changed, logs, _ = self._run(["1", "3"], _proc(rc=1, err="boom"))
        self.assertFalse(changed)
        self.assertTrue(any(t == "error" and "boom" in m for t, m in logs))

    def test_locked_files_get_a_specific_message(self):
        changed, logs, _ = self._run(["1", "3"], _proc(rc=1, err="WinError 32 in use"))
        self.assertFalse(changed)
        self.assertTrue(any("locked" in m for _t, m in logs))

    def test_subprocess_exception_is_survived(self):
        changed, logs, _ = self._run(["1", "3"], subprocess.TimeoutExpired("pip", 1))
        self.assertFalse(changed)
        self.assertTrue(any("update failed" in m for _t, m in logs))


class TestGetPkgVersion(unittest.TestCase):
    def test_parses_pip_show_output(self):
        with mock.patch.object(updater.subprocess, "run", return_value=_proc(out="Name: x\nVersion: 9.9.1\n")):
            self.assertEqual(updater.get_pkg_version("x"), "9.9.1")

    def test_unknown_when_pip_fails(self):
        with mock.patch.object(updater.subprocess, "run", side_effect=OSError):
            self.assertEqual(updater.get_pkg_version("x"), "unknown")


class TestToolUpdateScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stamp = Path(self.tmp.name) / "stamp"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_stamp_means_check(self):
        self.assertTrue(updater.ToolUpdateScheduler(self.stamp).should_check())

    def test_fresh_stamp_means_no_check(self):
        s = updater.ToolUpdateScheduler(self.stamp)
        s.stamp()
        self.assertFalse(s.should_check())

    def test_old_stamp_means_check(self):
        self.stamp.write_text(str(int(time.time()) - 8 * 86400))
        self.assertTrue(updater.ToolUpdateScheduler(self.stamp).should_check())


class TestSystem(unittest.TestCase):
    def test_disk_space_reports_enough_and_not_enough(self):
        ok, free = system.check_disk_space(tempfile.gettempdir(), min_free_gb=0.0)
        self.assertTrue(ok)
        self.assertGreater(free, 0)
        ok, _ = system.check_disk_space(tempfile.gettempdir(), min_free_gb=10 ** 9)
        self.assertFalse(ok)

    def test_disk_space_unreadable_path_does_not_block(self):
        ok, free = system.check_disk_space(Path(tempfile.gettempdir()) / "no" / "such" / "dir")
        self.assertTrue(ok)
        self.assertEqual(free, float("inf"))

    def test_check_ffmpeg_true_when_it_runs_false_when_missing(self):
        with mock.patch.object(system.subprocess, "run", return_value=_proc()):
            self.assertTrue(system.check_ffmpeg())
        with mock.patch.object(system.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(system.check_ffmpeg())

    def test_check_dependencies_fails_only_when_ytdlp_is_missing(self):
        with mock.patch.object(system.shutil, "which", return_value=None), \
             mock.patch.object(system, "check_ffmpeg", return_value=False):
            self.assertFalse(system.check_dependencies(yt_dlp_ok=False))
            self.assertTrue(system.check_dependencies(yt_dlp_ok=True))

    def test_find_deno_prefers_path_then_home(self):
        with mock.patch.object(system.shutil, "which", return_value="/x/deno"):
            self.assertEqual(system.find_deno(), "/x/deno")
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(system.shutil, "which", return_value=None), \
             mock.patch.object(system.Path, "home", return_value=Path(home)):
            self.assertIsNone(system.find_deno())
            d = Path(home) / ".deno" / "bin"
            d.mkdir(parents=True)
            exe = d / ("deno.exe" if sys.platform == "win32" else "deno")
            exe.write_text("")
            self.assertEqual(system.find_deno(), str(exe))


if __name__ == "__main__":
    unittest.main()
