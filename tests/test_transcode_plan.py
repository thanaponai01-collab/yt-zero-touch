"""
Tests for transcode_plan — the single owner of the copy-vs-transcode,
container, gate, and verification decisions for a downloaded file.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import transcode_plan  # noqa: E402


class TestTranscodeToH264Default(unittest.TestCase):
    def test_transcode_to_h264_is_on_by_default(self):
        # The single place the shipped default is asserted. Other tests
        # patch TRANSCODE_TO_H264 explicitly rather than leaning on the
        # module value, so flipping this flag breaks exactly one test (this
        # one) instead of silently invalidating a path test's premise.
        self.assertTrue(transcode_plan.TRANSCODE_TO_H264)


class TestContainerFor(unittest.TestCase):
    def test_audio_only_is_opus(self):
        self.assertEqual(transcode_plan.container_for(audio_only=True), "opus")

    def test_forces_mp4_when_transcode_on(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            self.assertEqual(transcode_plan.container_for(audio_only=False), "mp4")

    def test_falls_back_to_mp4_or_mkv_when_transcode_off(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", False):
            self.assertEqual(transcode_plan.container_for(audio_only=False), "mp4/mkv")


class GateFreeAfterTest:
    """Fails the test that leaked the process-wide transcode gate, by name,
    then frees it so the rest of the suite still runs.

    Deleting this guard outright would not surface a leak as a failure — the
    gate is a non-reentrant Lock, so the next test to take it would block
    forever and the suite would hang with no culprit named."""

    def tearDown(self):
        super().tearDown()
        leaked = transcode_plan._TRANSCODE_GATE.locked()
        if leaked:
            transcode_plan._TRANSCODE_GATE.release()
        self.assertFalse(leaked, "test leaked the process-wide transcode gate")


class TestPlanTranscode(GateFreeAfterTest, unittest.TestCase):
    """The merge step must never re-encode video unless TRANSCODE_TO_H264 is
    on, and must never re-encode AAC→AAC."""

    def setUp(self):
        # Pin the H.264 fallback to libx264 so results don't depend on
        # whether the test machine happens to have a working NVENC GPU.
        self._saved_encoder_cache = transcode_plan._h264_encoder_cache
        transcode_plan._h264_encoder_cache = (transcode_plan._H264_TRANSCODE_ARGS, "libx264")

    def tearDown(self):
        transcode_plan._h264_encoder_cache = self._saved_encoder_cache
        super().tearDown()

    def test_h264_source_always_copies(self):
        for flag in (False, True):
            with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", flag):
                plan = transcode_plan.plan_transcode("avc1.640028", "mp4a.40.2")
                self.assertEqual(plan.merge_args, ["-c:v", "copy", "-movflags", "+faststart"])
                self.assertFalse(plan.did_transcode)
                self.assertFalse(plan.needs_gate)

    def test_vp9_copies_when_transcode_off(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", False):
            plan = transcode_plan.plan_transcode("vp09.00.50.08", "opus")
            self.assertEqual(plan.merge_args[:2], ["-c:v", "copy"])
            self.assertIn("aac", plan.merge_args)  # opus still gets a Premiere-safe track
            self.assertFalse(plan.did_transcode)
            self.assertFalse(plan.needs_gate)

    def test_vp9_transcodes_when_flag_on(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True), \
             mock.patch.object(transcode_plan, "_h264_transcode_args",
                               return_value=(["-c:v", "libx264"], "libx264")):
            plan = transcode_plan.plan_transcode("av01.0.12M.08", "opus")
            self.assertEqual(plan.merge_args[:2], ["-c:v", "libx264"])
            self.assertTrue(plan.did_transcode)

    def test_merge_full_copy_for_h264_plus_aac(self):
        plan = transcode_plan.plan_transcode("avc1.640028", "mp4a.40.2")
        self.assertEqual(plan.merge_args, transcode_plan.PREMIERE_MERGE_ARGS_COPY_AUDIO)

    def test_merge_transcodes_audio_only_for_h264_plus_opus(self):
        plan = transcode_plan.plan_transcode("avc1.640028", "opus")
        self.assertEqual(plan.merge_args, transcode_plan.PREMIERE_MERGE_ARGS)

    def test_merge_copies_vp9_when_transcode_disabled(self):
        # Flag off (Premiere 2023+ decodes VP9/AV1 natively): >1080p VP9
        # passes through untouched — no re-encode, no generation loss.
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", False):
            plan = transcode_plan.plan_transcode("vp9", "mp4a.40.2")
        self.assertEqual(plan.merge_args, transcode_plan.PREMIERE_MERGE_ARGS_COPY_AUDIO)

    def test_merge_transcodes_video_only_for_vp9_plus_aac(self):
        # With the flag on (pre-2023 Premiere): video needs the H.264
        # fallback, audio is already AAC so it can still be copied.
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            plan = transcode_plan.plan_transcode("vp9", "mp4a.40.2")
        self.assertEqual(
            plan.merge_args, [*transcode_plan._H264_TRANSCODE_ARGS, "-movflags", "+faststart"]
        )

    def test_merge_transcodes_both_for_av1_plus_opus(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            plan = transcode_plan.plan_transcode("av01.0.05M.08", "opus")
        self.assertEqual(
            plan.merge_args,
            [*transcode_plan._H264_TRANSCODE_ARGS, "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart"],
        )

    def test_needs_gate_only_for_libx264_transcode(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            plan = transcode_plan.plan_transcode("vp9", "mp4a.40.2")
        self.assertTrue(plan.needs_gate)

    def test_no_gate_for_nvenc_transcode(self):
        transcode_plan._h264_encoder_cache = (transcode_plan._H264_NVENC_ARGS, "nvenc")
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            plan = transcode_plan.plan_transcode("vp9", "mp4a.40.2")
        self.assertTrue(plan.did_transcode)
        self.assertFalse(plan.needs_gate)

    def test_no_gate_for_stream_copy(self):
        plan = transcode_plan.plan_transcode("avc1.640028", "opus")
        self.assertFalse(plan.needs_gate)

    def test_log_message_when_copying_non_h264(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", False):
            plan = transcode_plan.plan_transcode("vp9", "mp4a.40.2")
        self.assertIsNotNone(plan.log_message)
        self.assertIn("untouched", plan.log_message)

    def test_log_message_when_transcoding(self):
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True):
            plan = transcode_plan.plan_transcode("vp9", "mp4a.40.2")
        self.assertIsNotNone(plan.log_message)
        self.assertIn("transcoding", plan.log_message)

    def test_no_log_message_for_h264_source(self):
        plan = transcode_plan.plan_transcode("avc1.640028", "mp4a.40.2")
        self.assertIsNone(plan.log_message)


class TestMergeSessionGate(GateFreeAfterTest, unittest.TestCase):
    """Unit-level gate behaviour. The lifecycle sequences that matter — a
    crashed merge, a playlist's second merge — are driven through the real
    yt-dlp callback protocol in test_ytdlp_skill.py, because a green unit test
    here cannot prove that protocol is unable to wedge the session."""

    def setUp(self):
        self.messages = []
        self.session = transcode_plan.merge_session(
            lambda msg, tag="info": self.messages.append(msg), container="mp4")

    def _plan(self, needs_gate):
        return transcode_plan.TranscodePlan(
            merge_args=[], did_transcode=needs_gate, needs_gate=needs_gate,
            log_message=None,
        )

    def test_gated_merge_holds_then_frees(self):
        with self.session as session:
            session.merge_started(self._plan(needs_gate=True), "out.mp4")
            self.assertTrue(transcode_plan._TRANSCODE_GATE.locked())
            session.merge_finished("out.mp4")
            self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())

    def test_ungated_merge_never_takes_it(self):
        with self.session as session:
            session.merge_started(self._plan(needs_gate=False), "out.mp4")
            self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())

    def test_scope_exit_frees_a_merge_that_never_finished(self):
        with self.session as session:
            session.merge_started(self._plan(needs_gate=True), "out.mp4")
        self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())

    def test_uncontended_acquire_is_silent(self):
        with self.session as session:
            session.merge_started(self._plan(needs_gate=True), "out.mp4")
            session.merge_finished("out.mp4")
        self.assertEqual(self.messages, [])


class TestH264EncoderSelection(unittest.TestCase):
    def setUp(self):
        self._saved = transcode_plan._h264_encoder_cache
        transcode_plan._h264_encoder_cache = None

    def tearDown(self):
        transcode_plan._h264_encoder_cache = self._saved

    def test_prefers_nvenc_when_available(self):
        with mock.patch.object(transcode_plan, "_nvenc_available", return_value=True):
            self.assertEqual(
                transcode_plan._h264_transcode_args(),
                (transcode_plan._H264_NVENC_ARGS, "nvenc"),
            )

    def test_falls_back_to_libx264_slow(self):
        with mock.patch.object(transcode_plan, "_nvenc_available", return_value=False):
            self.assertEqual(
                transcode_plan._h264_transcode_args(),
                (transcode_plan._H264_TRANSCODE_ARGS, "libx264"),
            )

    def test_detection_runs_once_and_is_cached(self):
        with mock.patch.object(
            transcode_plan, "_nvenc_available", return_value=False
        ) as probe:
            transcode_plan._h264_transcode_args()
            transcode_plan._h264_transcode_args()
            self.assertEqual(probe.call_count, 1)


class TestVerifyH264Output(unittest.TestCase):
    def _fake_run(self, returncode, stdout):
        completed = mock.Mock(returncode=returncode, stdout=stdout)
        return mock.patch.object(
            transcode_plan.subprocess, "run", return_value=completed
        )

    def test_passes_for_h264_stream(self):
        with self._fake_run(0, "h264\n"):
            self.assertTrue(
                transcode_plan.verify_h264_output("out.mp4", lambda *a, **k: None)
            )

    def test_fails_for_wrong_or_unreadable_codec(self):
        with self._fake_run(0, "vp9\n"):
            self.assertFalse(
                transcode_plan.verify_h264_output("out.mp4", lambda *a, **k: None)
            )
        with self._fake_run(1, ""):
            self.assertFalse(
                transcode_plan.verify_h264_output("out.mp4", lambda *a, **k: None)
            )

    def test_missing_ffprobe_skips_verification(self):
        with mock.patch.object(
            transcode_plan.subprocess, "run", side_effect=FileNotFoundError
        ):
            self.assertTrue(
                transcode_plan.verify_h264_output("out.mp4", lambda *a, **k: None)
            )


if __name__ == "__main__":
    unittest.main()
