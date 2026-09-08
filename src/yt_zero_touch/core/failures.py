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


def classify_failure(messages: list[str]) -> FailureClass | None:
    """Classify captured error messages into a typed cause.

    Returns the matching FailureClass, or None when nothing matches — an
    unclassified failure is treated as transient (retryable).
    """
    combined = " ".join(messages).lower()
    for failure, keywords in _FAILURE_RULES:
        if any(kw in combined for kw in keywords):
            return failure
    m = _HTTP_CODE_RE.search(combined)
    if m:
        return _HTTP_CODE_CAUSE[m.group(1)]
    return None


def is_permanent_error(messages: list[str]) -> bool:
    """True if the captured error names a permanent (non-retryable) failure."""
    failure = classify_failure(messages)
    return failure is not None and failure.permanent
