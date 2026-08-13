"""
Tests for the download-engine routing logic in ytdlp_skill.

These lock in the gallery-dl (Photos) routing: which hosts are image-first,
that Photos mode bypasses yt-dlp and stream resolution entirely, and that a
video-mode download on an image host falls back to gallery-dl only when
yt-dlp finds nothing.
"""

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ytdlp_skill  # noqa: E402
import transcode_plan  # noqa: E402
import format_policy  # noqa: E402
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


class DownloadApiHarness(GateFreeAfterTest, unittest.TestCase):
    """Drives _download_api against a yt-dlp fake that speaks the real
    postprocessor-hook protocol, so merge-lifecycle scenarios can be written
    as a script of callbacks rather than by poking the hook directly."""

    def setUp(self):
        # Pin the H.264 fallback to libx264 so results don't depend on
        # whether the test machine happens to have a working NVENC GPU.
        self._saved_encoder_cache = transcode_plan._h264_encoder_cache
        transcode_plan._h264_encoder_cache = (transcode_plan._H264_TRANSCODE_ARGS, "libx264")
        self.tmp = Path(__file__).resolve().parent / "_tmp_download_api"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil
        transcode_plan._h264_encoder_cache = self._saved_encoder_cache
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def merged_file(self, name):
        """A real file on disk, so the exists() check before verification is
        exercised rather than stubbed."""
        path = self.tmp / name
        path.write_bytes(b"not really an mp4")
        return str(path)

    def merge_event(self, status, vcodec="vp9", acodec="opus", filepath=None):
        return ("Merger", status, {
            "filepath": filepath,
            "requested_formats": [
                {"vcodec": vcodec, "acodec": "none"},
                {"vcodec": "none", "acodec": acodec},
            ],
        })

    def run_download(self, events=(), retcode=0, raises=None,
                     audio_only=False, probe_codec="h264"):
        """Replay `events` through the registered postprocessor hooks during
        download(), then return `retcode` (or raise `raises`).

        Returns a result carrying only what a caller can observe: whether the
        attempt succeeded, the captured ydl_opts, the merger args as they
        stood at each merge, and the files ffprobe was pointed at."""
        captured = {}
        merger_args_at_merge = []
        probed = []
        logged = []

        class _FakeYDL:
            def __init__(self, opts):
                captured.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                for pp, status, info in events:
                    for hook in captured.get("postprocessor_hooks", []):
                        hook({"postprocessor": pp, "status": status, "info_dict": info})
                    if pp == "Merger" and status == "started":
                        # Snapshot now: the production code mutates this dict
                        # in place, so by the end of a playlist it holds only
                        # the last entry's args.
                        merger_args_at_merge.append(
                            list(captured["postprocessor_args"]["merger"]))
                if raises is not None:
                    raise raises
                return retcode

        def _fake_run(cmd, **kwargs):
            probed.append(list(cmd))
            return mock.Mock(returncode=0, stdout=f"{probe_codec}\n")

        with mock.patch.object(ytdlp_skill._yt_dlp, "YoutubeDL", _FakeYDL), \
             mock.patch.object(transcode_plan.subprocess, "run", _fake_run):
            ok = ytdlp_skill._download_api(
                "https://youtube.com/watch?v=abc",
                Path("out") / "%(title)s.%(ext)s",
                ytdlp_skill.FORMAT_AUDIO if audio_only else ytdlp_skill.FORMAT_VIDEO,
                audio_only, False, False, [], None, None,
                log=lambda msg, tag="info": logged.append((tag, msg)),
            )
        return _Attempt(ok, captured, merger_args_at_merge, probed, logged)


class _Attempt:
    def __init__(self, ok, opts, merger_args_at_merge, probed, logged):
        self.ok = ok
        self.opts = opts
        self.merger_args_at_merge = merger_args_at_merge
        self.logged = logged
        # ffprobe argv is "ffprobe ... <path>", so the target is the last arg.
        self.verified = [cmd[-1] for cmd in probed]

    def log_text(self):
        return "\n".join(msg for _, msg in self.logged)


class TestDownloadApiOptions(DownloadApiHarness):
    """Locks in the format/merge-tuning ydl_opts built by _download_api."""

    def _captured_opts(self, audio_only=False):
        return self.run_download(audio_only=audio_only).opts

    def test_no_codec_filters_in_default_format(self):
        self.assertEqual(ytdlp_skill.FORMAT_VIDEO, "bestvideo+bestaudio/best")
        for preset in ytdlp_skill.QUALITY_PRESETS.values():
            self.assertNotIn("vcodec", preset)
            self.assertNotIn("ext=m4a", preset)

    def test_video_download_tunes_concurrency_and_format_sort(self):
        opts = self._captured_opts(audio_only=False)
        self.assertEqual(opts["concurrent_fragment_downloads"], 8)
        self.assertEqual(opts["http_chunk_size"], 10485760)
        # Ordering/scenario coverage for format_sort itself lives in
        # test_format_policy.py — this only checks the wiring didn't drift.
        self.assertIs(opts["format_sort"], format_policy.FORMAT_SORT)
        self.assertEqual(opts["postprocessor_args"]["merger"], transcode_plan.PREMIERE_MERGE_ARGS)
        self.assertEqual(len(opts["postprocessor_hooks"]), 1)

    def test_audio_only_skips_merger_args(self):
        opts = self._captured_opts(audio_only=True)
        self.assertNotIn("postprocessor_args", opts)
        self.assertNotIn("postprocessor_hooks", opts)

    def test_merge_hook_ignores_other_postprocessors(self):
        run = self.run_download(events=[("Metadata", "started", {})])
        self.assertEqual(
            run.opts["postprocessor_args"]["merger"], transcode_plan.PREMIERE_MERGE_ARGS
        )
        self.assertTrue(run.ok)


class TestMergeLifecycle(DownloadApiHarness):
    """The merge lifecycle as yt-dlp actually drives it — including the
    sequences where it never reports back.

    yt-dlp only promises the "finished" callback when the merge succeeds. A
    crashed merge is therefore modelled as: "started" fires, "finished" never
    does, and download() returns nonzero — faithful, because run_pp catches
    the merger's PostProcessingError and ignoreerrors turns it into a retcode,
    so no exception ever reaches the hook."""

    def setUp(self):
        super().setUp()
        self._flag = mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True)
        self._flag.start()
        self.addCleanup(self._flag.stop)

    def test_merge_that_starts_and_finishes(self):
        merged = self.merged_file("clip.mp4")
        run = self.run_download(events=[
            self.merge_event("started", filepath=merged),
            self.merge_event("finished", filepath=merged),
        ])
        self.assertTrue(run.ok)
        self.assertEqual(run.merger_args_at_merge,
                         [transcode_plan.plan_transcode("vp9", "opus").merge_args])
        self.assertEqual(run.verified, [merged])

    def test_crashed_merge_fails_the_download_and_frees_the_gate(self):
        # "started" with no "finished" — the gate must not survive the call.
        run = self.run_download(
            events=[self.merge_event("started", filepath=self.merged_file("clip.mp4"))],
            retcode=1,
        )
        self.assertFalse(run.ok)
        self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())
        self.assertEqual(run.verified, [])

    def test_second_merge_does_not_block_on_a_dead_first_one(self):
        # The shipped hang: one ydl.download() call serves a whole playlist,
        # so entry 2's merge asks for a non-reentrant gate its own thread
        # still holds from entry 1's crashed merge. Run it on a thread and
        # bound the wait, so a regression fails in five seconds instead of
        # hanging the suite forever.
        first, second = self.merged_file("one.mp4"), self.merged_file("two.mp4")
        result = {}

        def _go():
            result["run"] = self.run_download(events=[
                self.merge_event("started", filepath=first),    # dies here
                self.merge_event("started", filepath=second),
                self.merge_event("finished", filepath=second),
            ], retcode=1)

        worker = threading.Thread(target=_go, daemon=True)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(),
                         "second merge deadlocked on the gate held by the first")
        run = result["run"]
        self.assertFalse(run.ok)          # entry 1 still failed the retcode
        self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())
        self.assertEqual(len(run.merger_args_at_merge), 2)
        self.assertIn("freeing the transcode gate", run.log_text())

    def test_gate_is_freed_when_the_download_call_raises(self):
        # The session's second release path: ignoreerrors doesn't swallow
        # everything, and a raise must not strand the gate either.
        run = self.run_download(
            events=[self.merge_event("started", filepath=self.merged_file("clip.mp4"))],
            raises=RuntimeError("yt-dlp exploded mid-merge"),
        )
        self.assertFalse(run.ok)
        self.assertFalse(transcode_plan._TRANSCODE_GATE.locked())

    def test_stream_copy_never_takes_the_gate(self):
        merged = self.merged_file("clip.mp4")
        run = self.run_download(events=[
            self.merge_event("started", vcodec="avc1.640028", acodec="mp4a.40.2",
                             filepath=merged),
            self.merge_event("finished", vcodec="avc1.640028", acodec="mp4a.40.2",
                             filepath=merged),
        ])
        self.assertTrue(run.ok)
        self.assertEqual(run.merger_args_at_merge[0][:2], ["-c:v", "copy"])


class TestOutputVerification(DownloadApiHarness):
    """mp4 is forced before any codec is known, on the promise that a
    transcode will make it legal. Collecting on that promise is ffprobe's job,
    not a bookkeeping flag's."""

    def setUp(self):
        super().setUp()
        self._flag = mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", True)
        self._flag.start()
        self.addCleanup(self._flag.stop)

    def _merged(self, name, **kw):
        path = self.merged_file(name)
        return path, [self.merge_event("started", filepath=path, **kw),
                      self.merge_event("finished", filepath=path, **kw)]

    def test_h264_stream_copy_is_still_verified_and_passes(self):
        # The guard against reading "the commitment was not honoured" as "no
        # transcode was recorded": this download legitimately never
        # transcodes, and must still be verified and must still succeed.
        merged, events = self._merged("clip.mp4", vcodec="avc1.640028",
                                      acodec="mp4a.40.2")
        run = self.run_download(events=events, probe_codec="h264")
        self.assertTrue(run.ok)
        self.assertEqual(run.merger_args_at_merge[0][:2], ["-c:v", "copy"])
        self.assertEqual(run.verified, [merged])

    def test_output_that_is_not_h264_fails_loudly(self):
        # A transcode that was silently skipped reads back as vp9. Nothing
        # about the download reported an error, so only the probe can catch it.
        _, events = self._merged("clip.mp4")
        run = self.run_download(events=events, probe_codec="vp9")
        self.assertFalse(run.ok)
        self.assertIn("Output verification FAILED", run.log_text())
        self.assertIn("codec=vp9", run.log_text())

    def test_every_playlist_entry_is_verified(self):
        one, two, three = (self.merged_file(n) for n in
                           ("one.mp4", "two.mp4", "three.mp4"))
        events = []
        for path in (one, two, three):
            events.append(self.merge_event("started", filepath=path))
            events.append(self.merge_event("finished", filepath=path))
        run = self.run_download(events=events)
        self.assertTrue(run.ok)
        self.assertEqual(run.verified, [one, two, three])

    def test_a_failed_entry_short_circuits_before_verification(self):
        # yt-dlp's nonzero retcode already condemns the download, so there is
        # nothing for verification to add — and a crashed merge leaves no
        # finished file to probe in the first place.
        one, two = self.merged_file("one.mp4"), self.merged_file("two.mp4")
        run = self.run_download(events=[
            self.merge_event("started", filepath=one),     # dies, no finish
            self.merge_event("started", filepath=two),
            self.merge_event("finished", filepath=two),
        ], retcode=1)
        self.assertFalse(run.ok)
        self.assertEqual(run.verified, [])

    def test_audio_only_download_is_never_verified(self):
        run = self.run_download(audio_only=True)
        self.assertTrue(run.ok)
        self.assertEqual(run.verified, [])

    def test_no_verification_when_the_container_was_not_forced(self):
        # Flag off: container_for returns "mp4/mkv", nothing was promised, so
        # a VP9 stream copy is a legitimate output and must not be probed.
        _, events = self._merged("clip.mkv")
        with mock.patch.object(transcode_plan, "TRANSCODE_TO_H264", False):
            run = self.run_download(events=events, probe_codec="vp9")
        self.assertTrue(run.ok)
        self.assertEqual(run.verified, [])


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
