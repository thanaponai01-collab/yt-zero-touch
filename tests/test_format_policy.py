"""
Tests for format_policy — the single owner of yt-dlp's `format_sort` list,
decomposed into its three independent concerns (see format_policy.py).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import format_policy  # noqa: E402


class TestFormatSortComposition(unittest.TestCase):
    def test_composes_to_the_shipped_list_byte_identical(self):
        # This module is a pure refactor of the list this repo has shipped
        # with since 9390530 — pinning the exact composed value here means
        # any future edit to a concern's contents shows up as an intentional
        # change to *this* assertion, not a silent drift.
        self.assertEqual(
            format_policy.FORMAT_SORT,
            ["lang", "res", "fps", "vcodec:h264", "channels", "abr"],
        )

    def test_composed_from_the_four_named_constants_in_order(self):
        self.assertEqual(
            format_policy.FORMAT_SORT,
            [
                *format_policy.PREFER_ORIGINAL_AUDIO_TRACK,
                *format_policy.DONT_CAP_RESOLUTION,
                *format_policy.PREFER_H264_WITHIN_TIER,
                *format_policy.AUDIO_TRACK_QUALITY_TIEBREAKERS,
            ],
        )


class TestPreferOriginalAudioTrack(unittest.TestCase):
    """Regression: multi-audio videos (YouTube auto-dubs) must keep the
    uploader's original track. yt-dlp prepends format_sort fields to its own
    defaults, so any field ahead of "lang" can decide between two audio
    tracks before language is consulted — a dub encoded at a higher abr (or
    in 5.1 against a stereo original) would then win."""

    def test_lang_is_the_field(self):
        self.assertEqual(format_policy.PREFER_ORIGINAL_AUDIO_TRACK, ["lang"])

    def test_lang_outranks_every_other_field_in_the_composed_list(self):
        sort = format_policy.FORMAT_SORT
        lang_rank = sort.index("lang")
        for field in sort:
            if field == "lang":
                continue
            self.assertLess(
                lang_rank, sort.index(field),
                f"{field!r} outranks 'lang' — a dub can beat the original",
            )


class TestDontCapResolution(unittest.TestCase):
    def test_res_and_fps_are_the_fields(self):
        self.assertEqual(format_policy.DONT_CAP_RESOLUTION, ["res", "fps"])

    def test_res_outranks_the_h264_codec_preference(self):
        # A resolution tier must be picked before codec preference narrows
        # candidates within it — otherwise an avc1-first tiebreak could cap
        # "Best"/"4K" at 1080p the same way FORMAT_VIDEO's selector avoids
        # doing (see ytdlp_skill.FORMAT_VIDEO).
        sort = format_policy.FORMAT_SORT
        self.assertLess(sort.index("res"), sort.index("vcodec:h264"))


class TestPreferH264WithinTier(unittest.TestCase):
    def test_vcodec_h264_is_the_field(self):
        self.assertEqual(format_policy.PREFER_H264_WITHIN_TIER, ["vcodec:h264"])


class TestAudioTrackQualityTiebreakers(unittest.TestCase):
    def test_channels_and_abr_are_the_fields(self):
        self.assertEqual(format_policy.AUDIO_TRACK_QUALITY_TIEBREAKERS, ["channels", "abr"])

    def test_stay_at_the_tail_behind_resolution_and_codec_fields(self):
        # Kept behind res/fps/vcodec:h264 in the composed list — see
        # format_policy.py's comment on AUDIO_TRACK_QUALITY_TIEBREAKERS for
        # why this refactor preserves that position rather than moving them
        # next to "lang".
        sort = format_policy.FORMAT_SORT
        for field in format_policy.AUDIO_TRACK_QUALITY_TIEBREAKERS:
            for earlier in ("res", "fps", "vcodec:h264"):
                self.assertLess(sort.index(earlier), sort.index(field))


if __name__ == "__main__":
    unittest.main()
