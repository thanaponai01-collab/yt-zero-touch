"""
Unit tests for ToolUpdateScheduler in yt_zero_touch.services.updater.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.services.updater import ToolUpdateScheduler


class TestToolUpdateScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".stamp", delete=False)
        self.tmp.close()
        self.stamp_path = Path(self.tmp.name)
        if self.stamp_path.exists():
            self.stamp_path.unlink()

    def tearDown(self):
        if self.stamp_path.exists():
            self.stamp_path.unlink()

    def test_should_check_when_file_missing(self):
        scheduler = ToolUpdateScheduler(self.stamp_path, interval_days=7)
        self.assertTrue(scheduler.should_check())

    def test_should_check_when_file_corrupt(self):
        self.stamp_path.write_text("not-a-number", encoding="utf-8")
        scheduler = ToolUpdateScheduler(self.stamp_path, interval_days=7)
        self.assertTrue(scheduler.should_check())

    def test_should_check_when_recently_updated(self):
        recent_time = time.time() - 3600  # 1 hour ago
        self.stamp_path.write_text(str(int(recent_time)), encoding="utf-8")
        scheduler = ToolUpdateScheduler(self.stamp_path, interval_days=7)
        self.assertFalse(scheduler.should_check())

    def test_should_check_when_interval_elapsed(self):
        old_time = time.time() - (8 * 86400)  # 8 days ago
        self.stamp_path.write_text(str(int(old_time)), encoding="utf-8")
        scheduler = ToolUpdateScheduler(self.stamp_path, interval_days=7)
        self.assertTrue(scheduler.should_check())

    def test_stamp_records_and_resets_check(self):
        scheduler = ToolUpdateScheduler(self.stamp_path, interval_days=7)
        scheduler.stamp()
        self.assertTrue(self.stamp_path.exists())
        self.assertFalse(scheduler.should_check())


if __name__ == "__main__":
    unittest.main()
