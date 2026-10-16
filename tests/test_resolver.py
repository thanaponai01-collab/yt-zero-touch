"""Tests for the site-specific URL resolver's page-scraping layer.

These exercise the pure HTML → Brightcove-player-URL step only; the network
fetch and the headless-browser fallback are deliberately not touched.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest import mock  # noqa: E402

from yt_zero_touch.services import resolver  # noqa: E402
from yt_zero_touch.services.resolver import (  # noqa: E402
    resolve_url,
    resolve_urls,  # noqa: E402
    _brightcove_from_html,
    _brightcove_all_from_html,
)

F1_ACCOUNT = "6057949432001"
VIDEO_ID = "1709982240646065581"
OTHER_VIDEO_ID = "1709984821439983524"

# The two shapes formula1.com emits for the same embed: a lowercase HTML data
# attribute in the server-rendered markup, and a backslash-escaped JSON copy in
# the React payload further down the document.
ATTR_EMBED = f'<div class="f1-video" data-videoid="{VIDEO_ID}"></div>'
JSON_EMBED = f'{{\\"contentType\\":\\"atomVideo\\",\\"videoId\\":\\"{VIDEO_ID}\\"}}'
ACCOUNT_CONFIG = f'{{\\"BRIGHTCOVE_ACCOUNTID\\":\\"{F1_ACCOUNT}\\"}}'


def _player(video_id=VIDEO_ID, account=F1_ACCOUNT):
    return (f"https://players.brightcove.net/{account}"
            f"/default_default/index.html?videoId={video_id}")


def test_reads_lowercase_data_attribute_embed():
    assert _brightcove_from_html(ACCOUNT_CONFIG + ATTR_EMBED) == _player()


def test_reads_escaped_json_embed():
    assert _brightcove_from_html(ACCOUNT_CONFIG + JSON_EMBED) == _player()


def test_reads_plain_json_embed():
    html = ACCOUNT_CONFIG + f'{{"videoId": "{VIDEO_ID}"}}'
    assert _brightcove_from_html(html) == _player()


def test_article_page_picks_the_first_video_not_the_related_rail():
    """An F1 article carries its own video first, then a related-videos rail.

    Both ids appear twice (attribute markup, then JSON payload) — the article's
    own video must win.
    """
    html = (ACCOUNT_CONFIG
            + ATTR_EMBED
            + f'<div data-videoid="{OTHER_VIDEO_ID}"></div>'
            + JSON_EMBED
            + f'{{\\"videoId\\":\\"{OTHER_VIDEO_ID}\\"}}')
    assert _brightcove_from_html(html) == _player()


def test_no_video_on_the_page_is_not_a_match():
    assert _brightcove_from_html(ACCOUNT_CONFIG + "<p>text only</p>") is None


def test_no_brightcove_account_is_not_a_match():
    assert _brightcove_from_html(ATTR_EMBED) is None


def test_short_numbers_are_not_mistaken_for_video_ids():
    """Guards the id pattern against unrelated markup like videoIdx="3"."""
    assert _brightcove_from_html(ACCOUNT_CONFIG + '<div data-videoid="42"></div>') is None


def test_all_from_html_collects_every_distinct_video_in_order():
    """An article with two of its own videos (e.g. a recap plus an interview)
    must yield both, in the order they first appear on the page."""
    html = (ACCOUNT_CONFIG
            + f'<div data-videoid="{VIDEO_ID}"></div>'
            + f'<div data-videoid="{OTHER_VIDEO_ID}"></div>')
    assert _brightcove_all_from_html(html) == [_player(), _player(OTHER_VIDEO_ID)]


def test_all_from_html_dedupes_repeated_ids():
    """The same id shows up twice on the page (attribute markup, then the
    escaped JSON payload) — it must only be returned once."""
    html = ACCOUNT_CONFIG + ATTR_EMBED + JSON_EMBED
    assert _brightcove_all_from_html(html) == [_player()]


def test_all_from_html_empty_without_account():
    assert _brightcove_all_from_html(ATTR_EMBED) == []


class TestResolveUrls(unittest.TestCase):
    """resolve_urls() fans a page out to every video it embeds; resolve_url()
    stays the single-result wrapper. The HTML fetch is stubbed."""

    PAGE = (ACCOUNT_CONFIG + ATTR_EMBED + f'<div data-videoid="{OTHER_VIDEO_ID}"></div>')

    def _resolve(self, fn, page):
        with mock.patch.object(resolver, "_fetch_page_html", return_value=page), \
             mock.patch.object(resolver, "_PLAYWRIGHT_OK", False):
            return fn("https://news.example.com/article", log=lambda *a, **k: None)

    def test_every_distinct_video_on_the_page_is_returned(self):
        self.assertEqual(
            self._resolve(resolve_urls, self.PAGE),
            [_player(VIDEO_ID), _player(OTHER_VIDEO_ID)],
        )

    def test_resolve_url_returns_only_the_first(self):
        self.assertEqual(self._resolve(resolve_url, self.PAGE), _player(VIDEO_ID))

    def test_page_with_no_embed_falls_back_to_the_url_itself(self):
        self.assertEqual(
            self._resolve(resolve_urls, "<html>nothing here</html>"),
            ["https://news.example.com/article"],
        )

    def test_formula1_url_resolves_to_a_single_player(self):
        out = resolve_urls("https://www.formula1.com/en/video/recap." + VIDEO_ID,
                           log=lambda *a, **k: None)
        self.assertEqual(out, [_player(VIDEO_ID)])

    def test_known_ytdlp_site_passes_through(self):
        self.assertEqual(resolve_urls("https://www.youtube.com/watch?v=abc", log=lambda *a, **k: None),
                         ["https://www.youtube.com/watch?v=abc"])


def test_resolve_urls_f1():
    from yt_zero_touch.services.resolver import resolve_urls
    # 1. /en/latest/video.<title>.<id>.html format
    f1_latest = "https://www.formula1.com/en/latest/video.highlights-2024-monaco.1709982240646065581.html"
    res1 = resolve_urls(f1_latest)
    assert len(res1) == 1
    assert "players.brightcove.net/6057949432001" in res1[0]
    assert "1709982240646065581" in res1[0]

    # 2. /en/video/<title>.<id>.html format
    f1_video = "https://www.formula1.com/en/video/highlights-2024-monaco.1709982240646065581.html"
    res2 = resolve_urls(f1_video)
    assert len(res2) == 1
    assert "players.brightcove.net/6057949432001" in res2[0]
    assert "1709982240646065581" in res2[0]


def test_resolve_urls_known_domains_pass_through():
    from yt_zero_touch.services.resolver import resolve_urls, resolve_url
    yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert resolve_urls(yt_url) == [yt_url]
    assert resolve_url(yt_url) == yt_url

    reddit_url = "https://reddit.com/r/videos/comments/12345"
    assert resolve_urls(reddit_url) == [reddit_url]


def test_parse_netscape_cookies(tmp_path):
    from yt_zero_touch.services.resolver import _parse_netscape_cookies
    cookie_file = tmp_path / "cookies.txt"
    content = (
        "# Netscape HTTP Cookie File\n"
        "# Comment line to skip\n"
        "\n"  # empty line to skip
        "too\tfew\tparts\n"  # malformed line to skip (< 7 parts)
        ".example.com\tTRUE\t/\tTRUE\t1735689600\tsession_id\tabc123\n"
        "sub.example.com\tFALSE\t/path\tFALSE\t1735689600\tpref\tdark\n"
    )
    cookie_file.write_text(content, encoding="utf-8")

    cookies = _parse_netscape_cookies(cookie_file)
    assert len(cookies) == 2

    # First cookie: .example.com domain stripped leading dot, secure=True
    assert cookies[0] == {
        "name": "session_id",
        "value": "abc123",
        "domain": "example.com",
        "path": "/",
        "secure": True,
        "sameSite": "None",
    }

    # Second cookie: secure=False
    assert cookies[1] == {
        "name": "pref",
        "value": "dark",
        "domain": "sub.example.com",
        "path": "/path",
        "secure": False,
        "sameSite": "None",
    }


def test_stream_regex_and_ignore_stream_rules():
    from yt_zero_touch.services.resolver import _STREAM_RE, _IGNORE_STREAM

    # Matching stream extensions
    assert _STREAM_RE.search("https://cdn.site.com/video/master.m3u8?token=xyz")
    assert _STREAM_RE.search("https://cdn.site.com/video/track.mpd")
    assert _STREAM_RE.search("https://cdn.site.com/video/1080p.mp4")

    # Non-streams
    assert _STREAM_RE.search("https://site.com/watch?v=123") is None
    assert _STREAM_RE.search("https://site.com/image.jpg") is None

    # Ignore streams list filtering
    ignored_urls = [
        "https://googleads.doubleclick.net/pagead/ads",
        "https://rr1---sn-4g5ednls.googlevideo.com/videoplayback",
        "https://cdn.site.com/preview_clip.m3u8",
        "https://cdn.site.com/thumbnail.mp4",
        "https://cdn.site.com/poster.jpg",
    ]
    for u in ignored_urls:
        assert any(x in u.lower() for x in _IGNORE_STREAM)
