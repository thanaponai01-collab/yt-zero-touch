"""
Unit tests for HistoryStore in yt_zero_touch.core.history.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.core.history import HistoryStore


class TestHistoryStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()

    def test_empty_store_on_new_file(self):
        self.path.unlink()
        store = HistoryStore(self.path)
        self.assertEqual(len(store), 0)
        self.assertFalse(store.contains("https://youtube.com/watch?v=123"))

    def test_add_and_contains(self):
        store = HistoryStore(self.path)
        url1 = "https://youtube.com/watch?v=abc"
        url2 = "https://youtube.com/watch?v=def"

        store.add(url1)
        self.assertTrue(store.contains(url1))
        self.assertTrue(url1 in store)
        self.assertFalse(url2 in store)
        self.assertEqual(len(store), 1)

        # Re-load in a new store instance to test disk persistence
        store2 = HistoryStore(self.path)
        self.assertTrue(store2.contains(url1))
        self.assertEqual(len(store2), 1)

    def test_persisted_json_is_sorted_list(self):
        store = HistoryStore(self.path)
        store.add("https://b.com")
        store.add("https://a.com")

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw, ["https://a.com", "https://b.com"])


if __name__ == "__main__":
    unittest.main()
