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
import transcode_plan  # noqa: E402
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


class TestDownloadApiOptions(unittest.TestCase):
    """Locks in the format/merge-tuning ydl_opts built by _download_api."""

    def setUp(self):
        # Pin the H.264 fallback to libx264 so results don't depend on
        # whether the test machine happens to have a working NVENC GPU.
        self._saved_encoder_cache = transcode_plan._h264_encoder_cache
        transcode_plan._h264_encoder_cache = transcode_plan._H264_TRANSCODE_ARGS

    def tearDown(self):
        transcode_plan._h264_encoder_cache = self._saved_encoder_cache
        # Guard against a test leaving the global transcode gate held.
        if transcode_plan._TRANSCODE_GATE.locked():
            transcode_plan._TRANSCODE_GATE.release()

    def _captured_opts(self, audio_only=False):
        captured = {}

        class _FakeYDL:
            def __init__(self, opts):
                captured.update(opts)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def download(self, urls):
                return 0

        with mock.patch.object(ytdlp_skill._yt_dlp, "YoutubeDL", _FakeYDL):
            ytdlp_skill._download_api(
                "https://youtube.com/watch?v=abc",
                Path("out") / "%(title)s.%(ext)s",
                ytdlp_skill.FORMAT_AUDIO if audio_only else ytdlp_skill.FORMAT_VIDEO,
                audio_only, False, False, [], None, None,
            )
        return captured

    def test_no_codec_filters_in_default_format(self):
        self.assertEqual(ytdlp_skill.FORMAT_VIDEO, "bestvideo+bestaudio/best")
        for preset in ytdlp_skill.QUALITY_PRESETS.values():
            self.assertNotIn("vcodec", preset)
            self.assertNotIn("ext=m4a", preset)

    def test_video_download_tunes_concurrency_and_format_sort(self):
        opts = self._captured_opts(audio_only=False)
        self.assertEqual(opts["concurrent_fragment_downloads"], 8)
        self.assertEqual(opts["http_chunk_size"], 10485760)
        self.assertEqual(
            opts["format_sort"], ["lang", "res", "fps", "vcodec:h264", "channels", "abr"]
        )
        self.assertEqual(opts["postprocessor_args"]["merger"], transcode_plan.PREMIERE_MERGE_ARGS)
        self.assertEqual(len(opts["postprocessor_hooks"]), 1)

    def test_format_sort_ranks_language_above_bitrate(self):
        """Regression: multi-audio videos (YouTube auto-dubs) must keep the
        uploader's original track. yt-dlp prepends these fields to its own
        defaults, so any field ahead of "lang" can decide between two audio
        tracks before language is consulted — a dub encoded at a higher abr
        (or in 5.1 against a stereo original) would then win."""
        for audio_only in (False, True):
            with self.subTest(audio_only=audio_only):
                sort = self._captured_opts(audio_only=audio_only)["format_sort"]
                self.assertIn("lang", sort)
                for tiebreaker in ("abr", "channels", "asr", "br", "size"):
                    if tiebreaker in sort:
                        self.assertLess(
                            sort.index("lang"), sort.index(tiebreaker),
                            f"{tiebreaker!r} outranks 'lang' — a dub can beat the original",
                        )

    def test_audio_only_skips_merger_args(self):
        opts = self._captured_opts(audio_only=True)
        self.assertNotIn("postprocessor_args", opts)
        self.assertNotIn("postprocessor_hooks", opts)

    def test_hook_wires_plan_into_ydl_opts_and_manages_gate(self):
        # The closure's own job, not transcode_plan's: pull vcodec/acodec out
        # of yt-dlp's requested_formats shape, apply the resulting merge_args
        # to ydl_opts, and hold the transcode gate for the lifetime of the
        # merge. Scenario coverage for the decision itself (copy vs.
        # transcode, per codec pair) lives in test_transcode_plan.py.
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            opts = self._captured_opts(audio_only=False)
            hook = opts["postprocessor_hooks"][0]
            info_dict = {"requested_formats": [
                {"acodec": "none", "vcodec": "vp9"},
                {"acodec": "opus", "vcodec": "none"},
            ]}
            hook({"postprocessor": "Merger", "status": "started", "info_dict": info_dict})
            self.assertTrue(transcode_plan._TRANSCODE_GATE.locked())
            self.assertEqual(
                opts["postprocessor_args"]["merger"],
                transcode_plan.plan_transcode("vp9", "opus").merge_args,
            )
            hook({"postprocessor": "Merger", "status": "finished", "info_dict": info_dict})
        self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())

    def test_merge_hook_ignores_other_postprocessors(self):
        opts = self._captured_opts(audio_only=False)
        hook = opts["postprocessor_hooks"][0]
        hook({"postprocessor": "Metadata", "status": "started", "info_dict": {}})
        self.assertEqual(
            opts["postprocessor_args"]["merger"], transcode_plan.PREMIERE_MERGE_ARGS
        )


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
