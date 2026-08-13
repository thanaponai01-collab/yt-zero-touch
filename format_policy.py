"""
Format Sort Policy — single owner for yt-dlp's `format_sort` list.
========================================================================
`format_sort` ranks candidate formats with one flat, order-sensitive list —
but it actually encodes three independent concerns that happen to share a
list. Editing the list for one concern (e.g. resolution) can silently change
the outcome of another (e.g. language/dub selection), which is exactly what
happened in 9390530 (dub-track regression) after 38601b7/0751d86 (resolution
fixes) touched the same list.

Each concern below is its own named constant so it can be reasoned about
and tested in isolation. FORMAT_SORT composes them back into the single list
yt-dlp actually wants, in the exact order this repo has shipped with since
9390530 — this module is a pure refactor of that list, not a behavior change.
"""

from __future__ import annotations

# yt-dlp *prepends* format_sort fields to its own defaults rather than
# replacing them — so anything ranked ahead of "lang" can decide between two
# audio tracks before language is ever consulted. Without this, the
# effective order ends up "... channels, abr, lang, ...": for two audio-only
# tracks res/fps/vcodec are all null and channels usually ties at 2, leaving
# "abr" to decide — and a dub encoded at a higher bitrate than the original
# (or in 5.1 against a stereo original) wins. Ranking language first
# restores yt-dlp's default behaviour of preferring the track the uploader
# marked original. No-op on single-audio videos.
PREFER_ORIGINAL_AUDIO_TRACK = ["lang"]

# Plain height-capped selectors (see ytdlp_skill.FORMAT_VIDEO/QUALITY_PRESETS)
# carry no codec filter, so codec preference lives entirely here instead —
# an avc1-first filter in the format selector would cap "Best"/"4K" at
# 1080p, since YouTube only serves H.264 up to 1080p and a valid avc1 match
# would win before the real 4K/VP9/AV1 streams are ever considered. Ranking
# "res"/"fps" ahead of the codec preference below lets 1440p/4K actually
# pick the higher-res VP9/AV1 stream instead of being capped at a 1080p
# avc1 match.
DONT_CAP_RESOLUTION = ["res", "fps"]

# Within a resolution tier, prefer H.264 — keeps <=1080p output
# Premiere-native (H.264) without affecting which resolution tier gets
# picked (that's already decided by DONT_CAP_RESOLUTION above).
PREFER_H264_WITHIN_TIER = ["vcodec:h264"]

# Same concern as PREFER_ORIGINAL_AUDIO_TRACK — once "lang" has picked
# original vs. dub, these tiebreak between remaining candidates at that
# language (e.g. two original-language audio-only tracks: higher channels/
# bitrate wins). Kept as a separate constant rather than folded into
# PREFER_ORIGINAL_AUDIO_TRACK's list so FORMAT_SORT's composed order below
# stays byte-identical to the list this module replaces — moving them
# adjacent to "lang" would likely be behaviorally equivalent (res/fps/
# vcodec:h264 are null/tied on audio-only candidates) but that equivalence
# would then be assumed rather than proven, which is the same kind of
# silent-order-dependency risk this module exists to remove.
AUDIO_TRACK_QUALITY_TIEBREAKERS = ["channels", "abr"]

# The actual yt-dlp `format_sort` value — ytdlp_skill.py wires this straight
# into ydl_opts.
FORMAT_SORT = [
    *PREFER_ORIGINAL_AUDIO_TRACK,
    *DONT_CAP_RESOLUTION,
    *PREFER_H264_WITHIN_TIER,
    *AUDIO_TRACK_QUALITY_TIEBREAKERS,
]
