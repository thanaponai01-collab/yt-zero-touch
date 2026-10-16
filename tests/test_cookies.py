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

    def test_cookie_record_methods_and_immutability(self):
        from dataclasses import FrozenInstanceError
        # Session cookie
        rec_session = CookieRecord(
            domain=".example.com", include_subdomains=True, path="/",
            secure=True, expires=0, name="sess", value="val"
        )
        self.assertTrue(rec_session.is_session)
        self.assertFalse(rec_session.is_expired(now=1700000000.0))
        self.assertFalse(rec_session.http_only)

        # Boundary: expires exactly at current time is not yet expired
        rec_boundary = CookieRecord(
            domain=".example.com", include_subdomains=True, path="/",
            secure=True, expires=1700000000, name="b", value="v"
        )
        self.assertFalse(rec_boundary.is_expired(now=1700000000.0))
        self.assertTrue(rec_boundary.is_expired(now=1700000001.0))

        # Frozen immutability
        with self.assertRaises(FrozenInstanceError):
            rec_session.name = "mutated"  # type: ignore

    def test_inspect_expiring_soon_and_multi_domain_summary(self):
        now = 1700000000.0
        twelve_hours = int(now + 43200)

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            f.write(
                f".youtube.com\tTRUE\t/\tTRUE\t{twelve_hours}\t__Secure-3PSID\tyt_token\n"
                f".instagram.com\tTRUE\t/\tTRUE\t{twelve_hours}\tsessionid\tig_token\n"
                f".reddit.com\tTRUE\t/\tTRUE\t{twelve_hours}\ttoken\trd_token\n"
            )
            f_path = Path(f.name)
        try:
            st = inspect_cookie_file(f_path, now=now)
            self.assertTrue(st.valid)
            self.assertEqual(st.status, "expiring_soon")
            self.assertIn("12h left", st.summary)
            # More than 2 domains adds "+1"
            self.assertIn("+1", st.summary)
        finally:
            f_path.unlink()

    def test_export_playwright_cookies_subdomain_rules(self):
        cookies = [
            # sub.example.com has 2 dots -> TRUE
            {"name": "a", "value": "1", "domain": "sub.example.com", "path": "/", "expires": 0},
            # example.com has 1 dot -> FALSE
            {"name": "b", "value": "2", "domain": "example.com", "path": "/", "expires": -5},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_sub.txt"
            export_playwright_cookies(cookies, out_file)
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("sub.example.com\tTRUE\t/\tFALSE\t0\ta\t1", content)
            self.assertIn("example.com\tFALSE\t/\tFALSE\t0\tb\t2", content)


if __name__ == "__main__":
    unittest.main()

