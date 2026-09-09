"""
Failure classification — what went wrong, and what the user can do about it.
=============================================================================
A download failure carries a *cause* the user can usually act on (supply
cookies, update yt-dlp, etc.). We classify the captured error text into a
typed FailureClass so every front-end can show the remedy instead of throwing
the diagnosis away with a bare boolean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FailureClass:
    reason: str       # short stable id, e.g. "needs_cookies"
    label: str        # human-readable headline
    remedy: str       # one-line, actionable next step
    permanent: bool   # True -> don't retry (cause won't change on its own)


_LOGIN = FailureClass(
    "needs_cookies", "Login required",
    "Supply a cookies.txt or pick your browser in the cookie dropdown, then retry.",
    permanent=True)

_GEO = FailureClass(
    "geo_blocked", "Geo-restricted",
    "Use cookies from a region where it's available, or a VPN, then retry.",
    permanent=True)

_UPDATE = FailureClass(
    "needs_update", "yt-dlp may be out of date",
    "Click 'Update yt-dlp' in the app, then retry.",
    permanent=True)

_REMOVED = FailureClass(
    "removed", "Video removed or unavailable",
    "The video was deleted or made private at the source — nothing to do.",
    permanent=True)

_UNVERIFIED = FailureClass(
    "output_unverified", "Output failed its H.264 check",
    "The merged file isn't clean H.264 — check free disk space and that ffmpeg "
    "works, then retry this URL on its own.",
    permanent=True)

# ffmpeg (used as external downloader for --download-sections cuts) reports a
# CDN rejection (e.g. HTTP 403 on a stale/erratic-client URL) only as a raw
# process exit code; its own stderr with the real reason inherits the console
# directly and never reaches this app's logger. A normal ffmpeg failure exits
# 0-255; anything larger is Windows reporting an abnormal termination, which
# in practice here means "the URL this client picked didn't work" — the same
# shape as _LOGIN's bot-check case, so it gets the same one-shot
# alternate-client retry. Not permanent (unlike _LOGIN): a fresh extraction,
# even on the same client, often lands a working edge/URL next attempt.
_CLIENT_RETRY = FailureClass(
    "client_served_bad_url", "Player client served an unreachable URL",
    "Retrying with an alternate player client…",
    permanent=False)


_FAILURE_RULES: list[tuple[FailureClass, list[str]]] = [
    (_UNVERIFIED,
     ["output verification failed", "output verification errored"]),

    (_LOGIN,
     ["sign in to confirm", "private video", "http error 403", "http error 401",
      "age-restricted", "age restricted", "login required", "members-only",
      "join this channel", "this video is only available"]),

    (_GEO,
     ["geo-restricted", "geo restricted", "not available in your country",
      "this video is not available"]),

    (_UPDATE,
     ["no video formats", "no formats found", "unable to extract",
      "unsupported url"]),

    (_REMOVED,
     ["video unavailable", "has been removed", "http error 404", "not found"]),
]

_HTTP_CODE_CAUSE = {"401": _LOGIN, "403": _LOGIN, "404": _REMOVED}
_HTTP_CODE_RE = re.compile(r"\b(401|403|404)\b")

# See _CLIENT_RETRY above: a normal ffmpeg exit is 0-255, so a larger reported
# code is Windows' abnormal-termination value, not a real ffmpeg status.
_FFMPEG_EXIT_RE = re.compile(r"ffmpeg exited with code (\d+)")

# ffmpeg's own CDN-rejection text for a section-trim's external downloader
# ("Error opening input: Server returned 403 Forbidden") contains a bare 403,
# which the generic phrase rule below reads as a login wall — a permanent
# failure that stops retries dead. It isn't one: the player client's URL was
# rejected by the CDN, not the account. Must be checked before _FAILURE_RULES
# so the generic "http error 403" phrase can't win first.
_FFMPEG_INPUT_ERROR_RE = re.compile(r"error opening input")


def classify_failure(messages: list[str]) -> FailureClass | None:
    """Classify captured error messages into a typed cause.

    Returns the matching FailureClass, or None when nothing matches — an
    unclassified failure is treated as transient (retryable).
    """
    combined = " ".join(messages).lower()
    if _FFMPEG_INPUT_ERROR_RE.search(combined) and _HTTP_CODE_RE.search(combined):
        return _CLIENT_RETRY
    for failure, keywords in _FAILURE_RULES:
        if any(kw in combined for kw in keywords):
            return failure
    m = _HTTP_CODE_RE.search(combined)
    if m:
        return _HTTP_CODE_CAUSE[m.group(1)]
    m = _FFMPEG_EXIT_RE.search(combined)
    if m and int(m.group(1)) > 255:
        return _CLIENT_RETRY
    return None


def is_permanent_error(messages: list[str]) -> bool:
    """True if the captured error names a permanent (non-retryable) failure."""
    failure = classify_failure(messages)
    return failure is not None and failure.permanent
