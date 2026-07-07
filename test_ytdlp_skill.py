"""
Tests for the download-engine routing logic in ytdlp_skill.

These lock in the gallery-dl (Photos) routing: which hosts are image-first,
that Photos mode bypasses yt-dlp and stream resolution entirely, and that a
video-mode download on an image host falls back to gallery-dl only when
yt-dlp finds nothing.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ytdlp_skill  # noqa: E402
from ytdlp_skill import is_image_host  # noqa: E402


class TestIsImageHost(unittest.TestCase):
    def test_image_first_hosts_match(self):
        for url in [
            "https://www.instagram.com/p/Cabc123/",
            "https://instagram.com/reel/xyz/",
            "https://twitter.com/user/status/1",
            "https://x.com/user/status/1",
            "https://www.reddit.com/r/pics/comments/1/title/",
            "https://imgur.com/gallery/abc",
        ]:
            self.assertTrue(is_image_host(url), url)

    def test_video_hosts_do_not_match(self):
        for url in [
            "https://www.youtube.com/watch?v=abc",
            "https://youtu.be/abc",
            "https://vimeo.com/123",
            "https://example.com/video/1",
        ]:
            self.assertFalse(is_image_host(url), url)


class TestGalleryRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_tmp_ytdlp_skill"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_photos_mode_uses_gallery_dl_and_skips_resolve(self):
        # gallery=True must hand the raw URL to gallery-dl without resolving a
        # stream (no browser) and without touching yt-dlp.
        with mock.patch.object(ytdlp_skill, "_download_gallery", return_value=True) as mg, \
             mock.patch.object(ytdlp_skill, "resolve_url",
                               side_effect=AssertionError("must not resolve in Photos mode")), \
             mock.patch.object(ytdlp_skill, "_download_api",
                               side_effect=AssertionError("must not call yt-dlp in Photos mode")):
            ok = ytdlp_skill.download(
                "https://instagram.com/p/abc", out_dir=self.tmp, gallery=True,
            )
        self.assertTrue(ok)
        mg.assert_called_once()

    def test_image_host_falls_back_to_gallery_when_ytdlp_finds_nothing(self):
        with mock.patch.object(ytdlp_skill, "_YT_DLP_API_OK", True), \
             mock.patch.object(ytdlp_skill, "_GALLERY_DL_OK", True), \
             mock.patch.object(ytdlp_skill, "resolve_url",
                               return_value="https://instagram.com/p/abc"), \
             mock.patch.object(ytdlp_skill, "_download_api", return_value=False), \
             mock.patch.object(ytdlp_skill, "_download_gallery", return_value=True) as mg:
            ok = ytdlp_skill.download("https://instagram.com/p/abc", out_dir=self.tmp)
        self.assertTrue(ok)
        mg.assert_called_once()

    def test_no_gallery_fallback_for_video_host(self):
        with mock.patch.object(ytdlp_skill, "_YT_DLP_API_OK", True), \
             mock.patch.object(ytdlp_skill, "_GALLERY_DL_OK", True), \
             mock.patch.object(ytdlp_skill, "resolve_url",
                               return_value="https://youtube.com/watch?v=abc"), \
             mock.patch.object(ytdlp_skill, "_download_api", return_value=False), \
             mock.patch.object(ytdlp_skill, "_download_gallery") as mg:
            ok = ytdlp_skill.download("https://youtube.com/watch?v=abc", out_dir=self.tmp)
        self.assertFalse(ok)
        mg.assert_not_called()

    def test_no_gallery_fallback_for_audio_only(self):
        # Audio-only on an image host should not fall back to gallery-dl —
        # there's no audio in a photo.
        with mock.patch.object(ytdlp_skill, "_YT_DLP_API_OK", True), \
             mock.patch.object(ytdlp_skill, "_GALLERY_DL_OK", True), \
             mock.patch.object(ytdlp_skill, "resolve_url",
                               return_value="https://instagram.com/p/abc"), \
             mock.patch.object(ytdlp_skill, "_download_api", return_value=False), \
             mock.patch.object(ytdlp_skill, "_download_gallery") as mg:
            ok = ytdlp_skill.download(
                "https://instagram.com/p/abc", out_dir=self.tmp, audio_only=True,
            )
        self.assertFalse(ok)
        mg.assert_not_called()


class TestParseSections(unittest.TestCase):
    def test_basic_range(self):
        from ytdlp_skill import parse_sections
        self.assertEqual(parse_sections("10:00-20:00"), [(600.0, 1200.0)])

    def test_leading_star_and_seconds(self):
        from ytdlp_skill import parse_sections
        self.assertEqual(parse_sections("*00:10-01:30"), [(10.0, 90.0)])
        self.assertEqual(parse_sections("90-120"), [(90.0, 120.0)])

    def test_hms_and_multiple(self):
        from ytdlp_skill import parse_sections
        self.assertEqual(parse_sections("1:02:03-1:02:10"), [(3723.0, 3730.0)])
        self.assertEqual(
            parse_sections("0:30-1:00, 2:00-2:30"),
            [(30.0, 60.0), (120.0, 150.0)],
        )

    def test_invalid_returns_none(self):
        from ytdlp_skill import parse_sections
        for bad in ("", None, "bad", "20:00-10:00", "5-5", "nope-nope"):
            self.assertIsNone(parse_sections(bad), bad)


if __name__ == "__main__":
    unittest.main()
