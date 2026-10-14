"""
Tests for cookie_vault service.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.services import cookie_vault


class TestCookieVault(unittest.TestCase):
    def test_vault_targets_declared(self):
        self.assertIn("youtube", cookie_vault.VAULT_TARGETS)
        self.assertIn("instagram", cookie_vault.VAULT_TARGETS)
        self.assertIn("twitter", cookie_vault.VAULT_TARGETS)
        self.assertIn("facebook", cookie_vault.VAULT_TARGETS)

    def test_vault_missing_playwright_handles_gracefully(self):
        with mock.patch.object(cookie_vault, "PLAYWRIGHT_VAULT_OK", False):
            logs = []
            done_called = []
            ok = cookie_vault.launch_login_vault(
                "youtube",
                Path("dummy.txt"),
                log=lambda m, t: logs.append((m, t)),
                on_done=lambda s, m: done_called.append((s, m)),
            )
            self.assertFalse(ok)
            self.assertTrue(any("playwright is not installed" in m.lower() for m, _ in logs))
            self.assertEqual(len(done_called), 1)
            self.assertFalse(done_called[0][0])

    def test_vault_captures_and_exports_cookies(self):
        fake_cookies = [
            {"name": "sessionid", "value": "xyz", "domain": ".instagram.com", "path": "/", "expires": 1800000000, "secure": True}
        ]

        class FakePage:
            def goto(self, url): pass
            def is_closed(self): return True

        class FakeContext:
            def __init__(self):
                self.pages = [FakePage()]
            def cookies(self):
                return fake_cookies
            def close(self): pass

        class FakeChromium:
            def launch_persistent_context(self, *args, **kwargs):
                return FakeContext()

        class FakePlaywright:
            chromium = FakeChromium()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "vault.txt"
            with mock.patch.object(cookie_vault, "PLAYWRIGHT_VAULT_OK", True), \
                 mock.patch.object(cookie_vault, "sync_playwright", lambda: FakePlaywright()):
                logs = []
                done_called = []
                ok = cookie_vault.launch_login_vault(
                    "instagram",
                    out_file,
                    log=lambda m, t: logs.append((m, t)),
                    on_done=lambda s, m: done_called.append((s, m)),
                )
                self.assertTrue(ok)
                self.assertTrue(out_file.exists())
                self.assertEqual(len(done_called), 1)
                self.assertTrue(done_called[0][0])
                self.assertIn("Instagram", done_called[0][1])


if __name__ == "__main__":
    unittest.main()
