"""
Tests for cookie inspection, validation, and Netscape export utilities.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_zero_touch.core.cookies import (
    CookieRecord,
    CookieStatus,
    export_playwright_cookies,
    inspect_cookie_file,
    parse_netscape_lines,
)


class TestCookieParsing(unittest.TestCase):
    def test_parse_standard_netscape_lines(self):
        lines = [
            "# Netscape HTTP Cookie File",
            ".youtube.com\tTRUE\t/\tTRUE\t1900000000\tPREF\tf6=40000000",
            "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1900000000\t__Secure-3PSID\tsecret123",
            ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tig_secret",
            "# Comment line to ignore",
            "",
        ]
        records = parse_netscape_lines(lines)
        self.assertEqual(len(records), 3)

        pref = records[0]
        self.assertEqual(pref.domain, ".youtube.com")
        self.assertEqual(pref.name, "PREF")
        self.assertFalse(pref.http_only)
        self.assertFalse(pref.is_session)

        sec = records[1]
        self.assertEqual(sec.name, "__Secure-3PSID")
        self.assertTrue(sec.http_only)

        ig = records[2]
        self.assertEqual(ig.name, "sessionid")
        self.assertTrue(ig.is_session)

    def test_inspect_missing_and_empty_file(self):
        st = inspect_cookie_file(None)
        self.assertFalse(st.valid)
        self.assertEqual(st.status, "none")

        st_missing = inspect_cookie_file(Path("nonexistent_cookies.txt"))
        self.assertFalse(st_missing.valid)
        self.assertEqual(st_missing.status, "missing")

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write("# empty file\n\n")
            f_path = Path(f.name)
        try:
            st_empty = inspect_cookie_file(f_path)
            self.assertFalse(st_empty.valid)
            self.assertEqual(st_empty.status, "empty")
        finally:
            f_path.unlink()

    def test_inspect_expired_and_active_cookies(self):
        now = 1700000000.0

        # Expired
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write(f".youtube.com\tTRUE\t/\tTRUE\t{int(now - 3600)}\t__Secure-3PSID\told_token\n")
            f_path = Path(f.name)
        try:
            st = inspect_cookie_file(f_path, now=now)
            self.assertFalse(st.valid)
            self.assertEqual(st.status, "expired")
            self.assertIn("YouTube", st.domains)
        finally:
            f_path.unlink()

        # Active with 10 days left
        ten_days = int(now + 86400 * 10)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write(f".youtube.com\tTRUE\t/\tTRUE\t{ten_days}\t__Secure-3PSID\tvalid_token\n")
            f_path = Path(f.name)
        try:
            st = inspect_cookie_file(f_path, now=now)
            self.assertTrue(st.valid)
            self.assertEqual(st.status, "active")
            self.assertAlmostEqual(st.days_left, 10.0, places=0)
            self.assertIn("10d left", st.summary)
        finally:
            f_path.unlink()

    def test_export_playwright_cookies_roundtrip(self):
        pw_cookies = [
            {
                "name": "sessionid",
                "value": "12345abc",
                "domain": ".instagram.com",
                "path": "/",
                "expires": 1800000000,
                "httpOnly": True,
                "secure": True,
            },
            {
                "name": "csrftoken",
                "value": "token999",
                "domain": "instagram.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": False,
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "vault_cookies.txt"
            count = export_playwright_cookies(pw_cookies, out_file)
            self.assertEqual(count, 2)
            self.assertTrue(out_file.exists())

            content = out_file.read_text(encoding="utf-8")
            self.assertIn("#HttpOnly_.instagram.com", content)
            self.assertIn("sessionid", content)

            records = parse_netscape_lines(content.splitlines())
            self.assertEqual(len(records), 2)
            self.assertTrue(records[0].http_only)
            self.assertTrue(records[1].is_session)


if __name__ == "__main__":
    unittest.main()
