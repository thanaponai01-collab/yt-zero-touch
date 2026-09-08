"""
Unit tests for AppSettings in yt_zero_touch.core.config.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.core.config import AppSettings


class TestAppSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()

    def test_default_values(self):
        self.path.unlink()
        settings = AppSettings.load(self.path, default_out_dir=Path("D:/Downloads"))
        self.assertEqual(settings.quality, "Best")
        self.assertEqual(settings.out_dir, "D:\\Downloads")
        self.assertFalse(settings.prores_proxy)

    def test_save_and_reload(self):
        settings = AppSettings(
            out_dir="D:/Custom/Dir",
            quality="4K",
            prores_proxy=True,
            sub_en=True,
            sections="10:00-15:00",
        )
        settings.save(self.path)

        loaded = AppSettings.load(self.path)
        self.assertEqual(loaded.out_dir, "D:/Custom/Dir")
        self.assertEqual(loaded.quality, "4K")
        self.assertTrue(loaded.prores_proxy)
        self.assertTrue(loaded.sub_en)
        self.assertEqual(loaded.sections, "10:00-15:00")


if __name__ == "__main__":
    unittest.main()
