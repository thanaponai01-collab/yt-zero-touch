import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.core.models import URL_RE  # noqa: E402
from yt_zero_touch.ui.cli import watcher  # noqa: E402


class TestUrlRe(unittest.TestCase):
    def test_long_tlds_are_links(self):
        for url in ("https://x.example/v1",
                    "https://studio.photography/p/123",
                    "https://news.technology/watch?v=1"):
            self.assertEqual(URL_RE.findall(url), [url], url)

    def test_common_links_still_match_whole(self):
        for url in ("https://www.youtube.com/watch?v=jNQXAC9IVRw",
                    "https://youtu.be/jNQXAC9IVRw",
                    "https://x.com/user/status/12345",
                    "http://a.com/v1"):
            self.assertEqual(URL_RE.findall(url), [url], url)

    def test_links_inside_text_and_non_links(self):
        text = "see https://a.com/v1 and https://b.example/v2, not www.c.com or plain words"
        self.assertEqual(URL_RE.findall(text), ["https://a.com/v1", "https://b.example/v2"])
        self.assertEqual(URL_RE.findall("just words, no link"), [])

    def test_long_tld_links_survive_the_urls_file_reader(self):
        # The watcher reads urls.txt through URL_RE; a long-TLD link must come
        # back whole, not cut at the TLD.
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "urls.txt"
            f.write_text("https://studio.photography/p/123\n"
                         "https://news.technology/watch?v=1\n", encoding="utf-8")
            self.assertEqual(watcher.read_urls_from_file(f),
                             ["https://studio.photography/p/123",
                              "https://news.technology/watch?v=1"])


if __name__ == "__main__":
    unittest.main()
