"""Tests for the gallery-dl and gdown engine adapters. gallery-dl and gdown themselves
are never run: subprocess and gdown are faked, and browser detection uses a temp home."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.engines import gallery_engine as gal  # noqa: E402
from yt_zero_touch.engines import gdrive_engine as gd  # noqa: E402

FILE_ID = "1aBcD_eFg-HiJkLmNoPqRsTuVwXyZ0123"


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


class TestGdriveId(unittest.TestCase):
    def test_id_from_each_share_link_shape(self):
        for url in (
            f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
            f"https://drive.google.com/open?id={FILE_ID}",
            f"https://drive.google.com/uc?export=download&id={FILE_ID}",
        ):
            self.assertEqual(gd.extract_gdrive_id(url), FILE_ID, url)

    def test_non_drive_url_has_no_id(self):
        self.assertIsNone(gd.extract_gdrive_id("https://youtube.com/watch?v=abc"))


class TestDownloadGdrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "new" / "dir"
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **gdown_kw):
        fake = mock.Mock(**gdown_kw)
        with mock.patch.object(gd, "GDOWN_OK", True), mock.patch.object(gd, "_gdown", fake):
            ok = gd.download_gdrive(FILE_ID, self.out, lambda m, t: self.logs.append((t, m)))
        return ok, fake

    def test_success_uses_the_uc_url_and_creates_the_folder(self):
        ok, fake = self._run(download=mock.Mock(return_value=str(self.out / "clip.mp4")))
        self.assertTrue(ok)
        self.assertTrue(self.out.is_dir())
        self.assertEqual(fake.download.call_args.args[0], f"https://drive.google.com/uc?id={FILE_ID}")
        self.assertTrue(any("Saved: clip.mp4" in m for _t, m in self.logs))

    def test_no_output_path_is_a_failure(self):
        ok, _ = self._run(download=mock.Mock(return_value=None))
        self.assertFalse(ok)
        self.assertTrue(any("no output path" in m for t, m in self.logs if t == "error"))

    def test_gdown_exception_is_a_failure_not_a_crash(self):
        ok, _ = self._run(download=mock.Mock(side_effect=RuntimeError("quota")))
        self.assertFalse(ok)
        self.assertTrue(any("quota" in m for _t, m in self.logs))

    def test_missing_gdown_reports_how_to_install(self):
        with mock.patch.object(gd, "GDOWN_OK", False):
            ok = gd.download_gdrive(FILE_ID, self.out, lambda m, t: self.logs.append((t, m)))
        self.assertFalse(ok)
        self.assertTrue(any("pip install gdown" in m for _t, m in self.logs))


class TestGalleryHelpers(unittest.TestCase):
    def test_login_walled_hosts(self):
        self.assertTrue(gal.is_login_walled("https://www.instagram.com/p/abc/"))
        self.assertTrue(gal.is_login_walled("https://www.facebook.com/photo/1"))
        self.assertTrue(gal.is_login_walled("https://www.threads.net/@a/post/1"))
        self.assertFalse(gal.is_login_walled("https://imgur.com/a/abc"))

    def test_instagram_gets_extra_args_others_do_not(self):
        self.assertIn("instagram.api=rest", gal._gallery_config_args("https://instagram.com/p/x"))
        self.assertEqual(gal._gallery_config_args("https://imgur.com/a/x"), [])

    def test_detect_browsers_finds_only_installed_ones_in_order(self):
        with tempfile.TemporaryDirectory() as home:
            local, roaming = Path(home, "local"), Path(home, "roaming")
            (local / "Microsoft/Edge/User Data").mkdir(parents=True)
            (roaming / "Mozilla/Firefox/Profiles").mkdir(parents=True)
            (Path(home) / ".config/microsoft-edge").mkdir(parents=True)
            (Path(home) / ".mozilla/firefox").mkdir(parents=True)
            with mock.patch.dict(gal.os.environ, {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}), \
                 mock.patch.object(gal.Path, "home", return_value=Path(home)):
                self.assertEqual(gal.detect_browsers(), ["edge", "firefox"])
                (local / "Google/Chrome/User Data").mkdir(parents=True)
                self.assertEqual(gal.detect_browsers(), ["chrome", "edge", "firefox"])


class TestRunGalleryDl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "imgs"
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, result, url="https://imgur.com/a/x", kind="none", value=None, force=False):
        seen = []

        def fake_run(cmd, **_):
            seen.append(cmd)
            if isinstance(result, Exception):
                raise result
            return result

        with mock.patch.object(gal.subprocess, "run", side_effect=fake_run):
            res = gal._run_gallery_dl(url, self.out, kind, value, force,
                                      lambda m, t: self.logs.append((t, m)))
        return res, seen[0]

    def test_success_needs_zero_exit_and_output(self):
        (ok, wall), cmd = self._run(_proc(out="./imgs/a.jpg\n"))
        self.assertEqual((ok, wall), (True, False))
        self.assertIn("--dest", cmd)
        self.assertNotIn("--no-skip", cmd)

    def test_force_adds_no_skip(self):
        _, cmd = self._run(_proc(out="x\n"), force=True)
        self.assertIn("--no-skip", cmd)

    def test_cookie_file_and_browser_flags(self):
        _, cmd = self._run(_proc(out="x\n"), kind="file", value="c.txt")
        self.assertEqual(cmd[cmd.index("--cookies") + 1], "c.txt")
        _, cmd = self._run(_proc(out="x\n"), kind="browser", value="chrome")
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "chrome")

    def test_login_wording_in_stderr_flags_a_login_wall(self):
        (ok, wall), _ = self._run(_proc(rc=1, err="HTTP 403 Forbidden"))
        self.assertEqual((ok, wall), (False, True))

    def test_empty_success_on_instagram_counts_as_login_wall(self):
        (ok, wall), _ = self._run(_proc(rc=0, out=""), url="https://instagram.com/p/x")
        self.assertEqual((ok, wall), (False, True))

    def test_plain_failure_is_not_a_login_wall(self):
        (ok, wall), _ = self._run(_proc(rc=1, err="unsupported url"))
        self.assertEqual((ok, wall), (False, False))

    def test_timeout_and_crash_are_failures(self):
        for exc in (subprocess.TimeoutExpired("gallery_dl", 600), OSError("boom")):
            (ok, wall), _ = self._run(exc)
            self.assertEqual((ok, wall), (False, False))


class TestDownloadGallery(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.log = lambda m, t: self.logs.append((t, m))
        self.out = Path(tempfile.gettempdir())
        p = mock.patch.object(gal, "GALLERY_DL_OK", True)
        p.start()
        self.addCleanup(p.stop)

    def _download(self, url, results, **kw):
        with mock.patch.object(gal, "_run_gallery_dl", side_effect=results) as run:
            ok = gal.download_gallery(url, self.out, log=self.log, **kw)
        return ok, run

    def test_missing_gallery_dl_reports_how_to_install(self):
        with mock.patch.object(gal, "GALLERY_DL_OK", False):
            self.assertFalse(gal.download_gallery("https://imgur.com/a/x", self.out, log=self.log))
        self.assertTrue(any("pip install gallery-dl" in m for _t, m in self.logs))

    def test_public_site_runs_once_without_cookies(self):
        ok, run = self._download("https://imgur.com/a/x", [(True, False)])
        self.assertTrue(ok)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[2], "none")

    def test_plain_failure_stops_after_one_attempt(self):
        ok, run = self._download("https://imgur.com/a/x", [(False, False)])
        self.assertFalse(ok)
        self.assertEqual(run.call_count, 1)

    def test_login_walled_url_tries_each_detected_browser_until_one_works(self):
        with mock.patch.object(gal, "detect_browsers", return_value=["chrome", "edge"]):
            ok, run = self._download("https://instagram.com/p/x", [(False, True), (True, False)])
        self.assertTrue(ok)
        self.assertEqual([c.args[2:4] for c in run.call_args_list],
                         [("browser", "chrome"), ("browser", "edge")])

    def test_non_login_failure_stops_the_browser_loop(self):
        with mock.patch.object(gal, "detect_browsers", return_value=["chrome", "edge"]):
            ok, run = self._download("https://instagram.com/p/x", [(False, False), (True, False)])
        self.assertFalse(ok)
        self.assertEqual(run.call_count, 1)

    def test_all_browsers_walled_shows_the_login_help(self):
        with mock.patch.object(gal, "detect_browsers", return_value=["chrome"]):
            ok, _ = self._download("https://instagram.com/p/x", [(False, True)])
        self.assertFalse(ok)
        self.assertTrue(any("needs you to be logged in" in m for t, m in self.logs if t == "warn"))

    def test_explicit_browser_cookie_beats_auto_detection(self):
        with mock.patch.object(gal, "detect_browsers") as det:
            _, run = self._download("https://instagram.com/p/x", [(True, False)], browser_cookie="brave")
        det.assert_not_called()
        self.assertEqual(run.call_args.args[2:4], ("browser", "brave"))

    def test_existing_cookie_file_is_used(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            _, run = self._download("https://instagram.com/p/x", [(True, False)], cookie_file=Path(f.name))
        self.assertEqual(run.call_args.args[2:4], ("file", f.name))


if __name__ == "__main__":
    unittest.main()
