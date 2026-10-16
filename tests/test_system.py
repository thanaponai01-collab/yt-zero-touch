"""
Unit tests for system & environment utilities in yt_zero_touch.services.system.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.services import system


class TestSystemUtils(unittest.TestCase):
    def test_check_disk_space_threshold(self):
        fake_usage = mock.Mock(free=1024 ** 3)  # exactly 1.0 GB free
        with mock.patch("shutil.disk_usage", return_value=fake_usage):
            ok, free = system.check_disk_space("C:/", min_free_gb=1.0)
            self.assertTrue(ok)
            self.assertAlmostEqual(free, 1.0)

            # When threshold is strictly greater than available
            ok_higher, _ = system.check_disk_space("C:/", min_free_gb=1.5)
            self.assertFalse(ok_higher)

    def test_check_disk_space_exception_returns_true_inf(self):
        with mock.patch("shutil.disk_usage", side_effect=OSError("Drive unmounted")):
            ok, free = system.check_disk_space("Z:/")
            self.assertTrue(ok)
            self.assertEqual(free, float("inf"))

    def test_check_ffmpeg_success_and_failure(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
            self.assertTrue(system.check_ffmpeg())

        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(system.check_ffmpeg())

    def test_find_deno(self):
        # Found on PATH
        with mock.patch("shutil.which", return_value="C:/bin/deno.exe"):
            self.assertEqual(system.find_deno(), "C:/bin/deno.exe")

    def test_check_dependencies(self):
        # Default parameters with ffmpeg available
        with mock.patch("yt_zero_touch.services.system.check_ffmpeg", return_value=True):
            self.assertTrue(system.check_dependencies())

        # When yt-dlp python import is not ok, BUT CLI exists on PATH
        with mock.patch("yt_zero_touch.services.system.check_ffmpeg", return_value=True), \
             mock.patch("shutil.which", return_value="C:/bin/yt-dlp.exe"):
            self.assertTrue(system.check_dependencies(yt_dlp_ok=False))

        # When yt-dlp is missing and not on PATH
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(system.check_dependencies(yt_dlp_ok=False, gallery_dl_ok=False))


if __name__ == "__main__":
    unittest.main()

