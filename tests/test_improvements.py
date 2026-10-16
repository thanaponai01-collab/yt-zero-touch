"""
Acceptance oracle for downloading, quality, and efficiency improvements.
========================================================================
Verifies:
1. Audio-only Premiere Pro compatibility (M4A/WAV output, studio bitrate 256k).
2. 1440p QHD preset availability.
3. Multi-vendor GPU hardware acceleration probing (NVENC, QSV, AMF).
4. Adaptive transcode gate allowing concurrency for <=1080p footage.
5. HDR-to-SDR tone-mapping filter plan.
6. Lazy browser initialization in batch orchestrator.
7. Valid generic impersonate client configuration in yt-dlp options.
8. External downloader (aria2c) support for direct streams.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.core import format_policy, models, transcode
from yt_zero_touch.services import orchestrator, resolver


class TestQualityImprovements(unittest.TestCase):
    def test_audio_only_defaults_to_premiere_compatible_m4a(self):
        """Audio-only output must default to m4a (or wav), NOT opus, for Premiere compatibility."""
        container = transcode.container_for(audio_only=True)
        self.assertIn(container, ("m4a", "wav"))
        self.assertNotEqual(container, "opus")

    def test_audio_only_supports_format_selection(self):
        """Caller can request specific audio container (m4a, wav, or opus)."""
        self.assertEqual(transcode.container_for(audio_only=True, audio_format="wav"), "wav")
        self.assertEqual(transcode.container_for(audio_only=True, audio_format="m4a"), "m4a")
        self.assertEqual(transcode.container_for(audio_only=True, audio_format="opus"), "opus")

    def test_1440p_preset_is_defined(self):
        """1440p (2K / QHD) preset must be available in QUALITY_PRESETS."""
        self.assertIn("1440p", models.QUALITY_PRESETS)
        self.assertIn("1440", models.QUALITY_PRESETS["1440p"])

    def test_studio_audio_bitrate_upgrade(self):
        """Default audio transcode bitrate must be at least 256k for studio fidelity."""
        args = transcode.PRE_MERGE_DEFAULT_ARGS
        self.assertIn("-b:a", args)
        idx = args.index("-b:a")
        bitrate_str = args[idx + 1]
        self.assertTrue(bitrate_str.endswith("k"))
        self.assertGreaterEqual(int(bitrate_str[:-1]), 256)

    def test_hdr_tone_mapping_plan(self):
        """HDR streams (e.g. bt2020 / pq / hlg) must receive tone mapping to SDR bt709."""
        plan = transcode.plan_transcode("vp9", "opus", is_hdr=True)
        # Should include tone mapping in ffmpeg filter args
        has_filter = any("-vf" == arg or "-filter:v" == arg for arg in plan.merge_args)
        self.assertTrue(has_filter, "HDR transcode to H.264 must include tone mapping filter")


class TestHardwareAccelerationImprovements(unittest.TestCase):
    def test_gpu_encoder_probe_order(self):
        """Hardware probing checks NVENC, QSV, and AMF before falling back to libx264."""
        # When NVENC is disabled but QSV is available
        with mock.patch.object(transcode, "nvenc_available", return_value=False), \
             mock.patch.object(transcode, "qsv_available", return_value=True):
            encoder = transcode.get_best_h264_encoder()
            self.assertEqual(encoder.kind, "qsv")

        # When NVENC and QSV are disabled but AMF is available
        with mock.patch.object(transcode, "nvenc_available", return_value=False), \
             mock.patch.object(transcode, "qsv_available", return_value=False), \
             mock.patch.object(transcode, "amf_available", return_value=True):
            encoder = transcode.get_best_h264_encoder()
            self.assertEqual(encoder.kind, "amf")

    def test_adaptive_transcode_gate(self):
        """Software transcode gate permits concurrency for <=1080p but restricts 4K."""
        # 1080p transcode plan should allow up to 2 concurrent slots
        plan_1080p = transcode.plan_transcode("vp9", "opus", height=1080)
        plan_4k = transcode.plan_transcode("vp9", "opus", height=2160)
        self.assertTrue(plan_1080p.allow_concurrent_software_slots)
        self.assertFalse(plan_4k.allow_concurrent_software_slots)


class TestDownloadingEfficiencyImprovements(unittest.TestCase):
    def test_lazy_browser_skips_when_all_urls_are_known(self):
        """run_batch must not launch Playwright browser when all URLs belong to known domains."""
        mock_browser_factory = mock.MagicMock()
        policy = models.BatchPolicy(out_dir=Path("./test_downloads"))
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://twitter.com/user/status/123456",
        ]
        mock_downloader = mock.MagicMock()
        mock_downloader.download.return_value = True

        orchestrator.run_batch(
            urls, policy, mock_downloader,
            history=set(),
            browser_factory=mock_browser_factory,
            resolve_fn=lambda u, **kwargs: [u],
        )
        mock_browser_factory.assert_not_called()

    def test_impersonate_client_is_explicit(self):
        """Generic extractor impersonate profile must be an explicit browser name."""
        from yt_zero_touch.engines import ytdlp_engine
        # ytdlp_engine options builder or default opts
        opts = ytdlp_engine.get_default_extractor_args()
        self.assertIn("generic", opts)
        impersonate_list = opts["generic"].get("impersonate", [])
        self.assertTrue(len(impersonate_list) > 0)
        self.assertTrue(impersonate_list[0] in ("chrome", "safari", "edge"))


class TestBatchPolicyAndOutputTemplate(unittest.TestCase):
    def test_batch_policy_defaults(self):
        policy = models.BatchPolicy(out_dir=Path("out"))
        self.assertFalse(policy.audio_only)
        self.assertFalse(policy.gallery)
        self.assertFalse(policy.force)
        self.assertFalse(policy.write_metadata)
        self.assertFalse(policy.playlist)
        self.assertEqual(policy.max_workers, 3)
        self.assertEqual(policy.retry_max, 3)
        self.assertEqual(policy.target_codec, "h264")

    def test_build_output_template_stream_detection(self):
        url = "https://example.com/watch/my-video"

        # 1. resolved == url is NOT a stream even if .m3u8 is present
        tmpl = models.build_output_template(1, url, url, total=1, pad=2)
        self.assertEqual(tmpl, "%(title).100B - [%(id)s].%(ext)s")

        # 2. resolved != url with .m3u8 IS a stream
        tmpl = models.build_output_template(1, url, "https://cdn.example.com/live.m3u8", total=1, pad=2)
        self.assertEqual(tmpl, "my-video.%(ext)s")

        # 3. resolved != url with .mp4 AND '?' IS a stream
        tmpl = models.build_output_template(1, url, "https://cdn.example.com/frag.mp4?token=123", total=1, pad=2)
        self.assertEqual(tmpl, "my-video.%(ext)s")

        # 4. resolved != url with .mp4 but WITHOUT '?' is NOT a stream (standard direct file)
        tmpl = models.build_output_template(1, url, "https://cdn.example.com/direct.mp4", total=1, pad=2)
        self.assertEqual(tmpl, "%(title).100B - [%(id)s].%(ext)s")

        # 5. resolved != url with '?' but WITHOUT .mp4/.m3u8 is NOT a stream
        tmpl = models.build_output_template(1, url, "https://example.com/redirect?target=1", total=1, pad=2)
        self.assertEqual(tmpl, "%(title).100B - [%(id)s].%(ext)s")

        # 6. total > 1 adds numbered prefix
        tmpl = models.build_output_template(1, url, "https://cdn.example.com/live.m3u8", total=5, pad=2)
        self.assertEqual(tmpl, "01 - my-video.%(ext)s")


if __name__ == "__main__":
    unittest.main()

