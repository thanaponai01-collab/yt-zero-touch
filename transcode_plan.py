"""
Transcode Plan — single owner for "what happens to a downloaded file".
========================================================================
Given the video/audio codecs yt-dlp actually selected, decides whether the
merge step copies or re-encodes to H.264, which ffmpeg args that takes, and
the gate/verification behaviour around a heavy transcode. `ytdlp_skill.py`
calls into this module instead of deciding any of it itself.

Two entry points, not one, because yt-dlp reads `merge_output_format` at
`YoutubeDL()` construction — before any codec is known — while the merge
step's ffmpeg args are read live, right before the merger postprocessor
runs, once the real codecs are known:

    container_for(audio_only)        -> call early, building ydl_opts
    plan_transcode(vcodec, acodec)   -> call late, once codecs are known
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from resolver import LogFn

# ---------------------------------------------------------------------------
# Master switch
# ---------------------------------------------------------------------------

# Premiere 2023+ decodes VP9 and AV1 natively, so a >1080p source can be
# muxed through untouched: the merge becomes a pure stream copy (seconds
# instead of minutes) *and* the output is bit-identical to what YouTube
# served — no H.264 generation loss. Flip to True only if the footage has to
# open in a pre-2023 Premiere, which needs the transcode below.
# ponytail: module-level switch, not a UI setting — one editor, one machine.
TRANSCODE_TO_H264 = True

# ---------------------------------------------------------------------------
# Merge args
# ---------------------------------------------------------------------------

# FFmpeg args applied during the video+audio merge step. Video and audio are
# each decided independently at merge time (see plan_transcode below) based
# on the actual codecs yt-dlp picked, so a single download can land on any
# of the four copy/transcode combinations:
# -c:v copy            → source is already H.264 (always true at ≤1080p,
#                         since format_sort prefers it there) — no re-encode.
# -c:v libx264 ...      → source is VP9/AV1 (i.e. >1080p, since format_sort
#                         only reaches for those above the H.264 ceiling) —
#                         transcoded to H.264 so the file opens in *any*
#                         Premiere Pro version, not just 2023+'s native
#                         VP9/AV1 decode. Slower, but that's the trade for
#                         "safe" playback everywhere.
# -c:a aac / -b:a 192k  → source audio isn't AAC (plain "bestaudio" means
#                         YouTube usually hands back Opus 251) — transcode.
# -c:a copy             → source audio is already AAC/m4a — skip the
#                         wasteful AAC→AAC re-encode.
# -movflags +faststart  → move MP4 index to front for instant Premiere import
#
# The merger's ffmpeg args always start with "-c copy" for both streams, so
# omitting -c:v/-c:a entirely (rather than spelling out "copy") also works —
# kept explicit here for readability.
PREMIERE_MERGE_ARGS = [
    "-c:v", "copy",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
]
PREMIERE_MERGE_ARGS_COPY_AUDIO = [
    "-c:v", "copy",
    "-movflags", "+faststart",
]

# H.264 encode used to transcode a >1080p VP9/AV1 source down to something
# every Premiere Pro version can decode. -crf 16 -preset slow aims for
# visually-lossless output (close to the high-bitrate VP9/AV1 source) at the
# cost of encode speed — tune down (e.g. -preset medium/faster, -crf 18-20)
# if turnaround time matters more than matching source quality exactly.
# -pix_fmt yuv420p forces 8-bit 4:2:0, since some Premiere builds choke on
# the 10-bit HDR pixel formats 4K VP9/AV1 sources can carry.
_H264_TRANSCODE_ARGS = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
]

# Hardware-accelerated equivalent for machines with an NVIDIA GPU. At these
# settings (p7 = highest-quality NVENC preset, CQ 19) output is visually on
# par with libx264 slow for editing footage, but encodes roughly 5-10x faster
# — a ~16-minute 4K60 software encode drops to a couple of minutes. Detected
# once at first use (see _h264_transcode_args) with a real 3-frame test
# encode, because h264_nvenc can be *listed* by ffmpeg builds that still fail
# at runtime when no NVIDIA GPU/driver is present.
_H264_NVENC_ARGS = [
    "-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq",
    "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p",
]

_h264_encoder_cache: "list[str] | None" = None
_h264_encoder_cache_lock = threading.Lock()


def _nvenc_available() -> bool:
    """True if this machine can actually encode with h264_nvenc."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
             "-frames:v", "3", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _h264_transcode_args() -> "list[str]":
    """H.264 encode args for the >1080p fallback — NVENC when the GPU
    supports it, libx264 slow otherwise. Detection result is cached for the
    process lifetime."""
    global _h264_encoder_cache
    with _h264_encoder_cache_lock:
        if _h264_encoder_cache is None:
            _h264_encoder_cache = (
                _H264_NVENC_ARGS if _nvenc_available() else _H264_TRANSCODE_ARGS
            )
        return _h264_encoder_cache


# Audio codec prefixes yt-dlp reports that are already AAC — safe to copy
# straight through instead of re-encoding AAC → AAC (generation loss for
# nothing, since Premiere accepts AAC natively either way).
_AAC_ACODEC_PREFIXES = ("mp4a", "aac")

# Video codec prefixes yt-dlp reports that are already H.264 — safe to copy
# straight through; anything else (vp9, av01, ...) gets the H.264 transcode
# above so the merged file is guaranteed to open in any Premiere version.
_H264_VCODEC_PREFIXES = ("avc1", "h264")

# ---------------------------------------------------------------------------
# Container — decided early, before codecs are known
# ---------------------------------------------------------------------------


def container_for(audio_only: bool) -> str:
    """yt-dlp's merge_output_format, decided at ydl_opts build time —
    before any codec is known, since YoutubeDL() reads this at construction.

    "mp4/mkv" = mp4 when the selected codecs are actually mp4-legal, mkv
    otherwise. Matters when VP9/AV1 pass through untouched: AV1 is standard
    in mp4, but VP9-in-mp4 is a container yt-dlp rejects and Premiere reads
    unreliably — those land in mkv, which Premiere 2023+ opens fine. When
    TRANSCODE_TO_H264 is on, the merged video is always re-encoded to H.264
    (mp4-legal), so force "mp4" outright — otherwise yt-dlp picks the
    container from the *source* codec before the transcode decision runs,
    and a VP9 source still lands in mkv even after its video stream gets
    re-encoded to H.264.
    """
    if audio_only:
        return "opus"
    return "mp4" if TRANSCODE_TO_H264 else "mp4/mkv"

# ---------------------------------------------------------------------------
# Merge decision — decided late, once codecs are known
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranscodePlan:
    merge_args: "list[str]"
    did_transcode: bool
    needs_gate: bool
    log_message: "str | None"
    log_level: str = "info"


def plan_transcode(vcodec: str, acodec: str) -> TranscodePlan:
    """Pick ffmpeg merge args based on the codecs yt-dlp actually selected.
    Pure — no I/O, no logging, no locking. The caller applies log_message /
    needs_gate itself."""
    vcodec = vcodec.lower()
    acodec = acodec.lower()

    is_h264 = vcodec.startswith(_H264_VCODEC_PREFIXES)
    will_transcode = TRANSCODE_TO_H264 and not is_h264

    log_message = None
    if not is_h264 and not TRANSCODE_TO_H264:
        log_message = (
            f"  Keeping {vcodec or 'source'} video untouched (stream copy) — "
            f"Premiere 2023+ decodes it natively. Set TRANSCODE_TO_H264=True "
            f"for older Premiere."
        )
    elif not is_h264 and TRANSCODE_TO_H264:
        encoder = _h264_transcode_args()[1]
        log_message = (
            f"  >1080p source is {vcodec or 'non-H.264'} — transcoding to "
            f"H.264 ({encoder}) for Premiere compatibility (this takes longer)…"
        )

    video_args = _h264_transcode_args() if will_transcode else ["-c:v", "copy"]
    audio_args = (
        [] if acodec.startswith(_AAC_ACODEC_PREFIXES)
        else ["-c:a", "aac", "-b:a", "192k"]
    )
    merge_args = [*video_args, *audio_args, "-movflags", "+faststart"]

    # Serialize heavy video encodes across all download threads — but only
    # the RAM-hungry libx264 path (concurrent 4K software encodes ≈ 6GB+ and
    # can OOM the machine). NVENC buffers on the GPU, so concurrent NVENC
    # encodes are cheap on system RAM — don't gate them, or a 4K batch
    # needlessly encodes one-at-a-time.
    needs_gate = will_transcode and _h264_transcode_args() is _H264_TRANSCODE_ARGS

    return TranscodePlan(
        merge_args=merge_args,
        did_transcode=will_transcode,
        needs_gate=needs_gate,
        log_message=log_message,
    )

# ---------------------------------------------------------------------------
# Gate — only one heavy H.264 video transcode may run at a time, process-wide
# ---------------------------------------------------------------------------

# The orchestrator runs up to 3 download threads; if several of them hit the
# >1080p transcode path simultaneously (e.g. a pasted batch of 4K links),
# concurrent libx264 4K encodes stack multi-GB RAM allocations and can OOM
# the machine (observed: two concurrent 4K encodes ≈ 6GB+). Downloads still
# run in parallel — only the ffmpeg merge/transcode step is serialized, and
# only when it actually transcodes video (pure stream copies don't take the
# gate).
_TRANSCODE_GATE = threading.Lock()


def acquire_gate(log: LogFn) -> None:
    """Acquire the process-wide transcode gate, logging if this call has to
    wait behind another in-flight transcode. Always blocks until acquired —
    there is no non-blocking "give up" path."""
    if _TRANSCODE_GATE.acquire(blocking=False):
        return
    log("  Waiting for another transcode to finish (one heavy encode at a time)…",
        "info")
    _TRANSCODE_GATE.acquire()


def release_gate() -> None:
    _TRANSCODE_GATE.release()

# ---------------------------------------------------------------------------
# Post-transcode verification
# ---------------------------------------------------------------------------


def verify_h264_output(path: "Path | str", log: LogFn) -> bool:
    """ffprobe the final file after a transcode to confirm it really is
    decodable H.264 — protects against a silently-truncated/corrupt output
    (crashed encoder, full disk, OOM-killed ffmpeg) that would otherwise
    only be discovered when the file fails to open in Premiere later."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        log("  ffprobe not found — skipping post-transcode verification.", "warn")
        return True
    except Exception as exc:
        log(f"  Post-transcode verification errored ({exc}) — treating as failed.", "error")
        return False
    codec = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
    if proc.returncode == 0 and codec == "h264":
        log("  Verified: output is clean H.264 — safe for any Premiere version.", "info")
        return True
    log(f"  Post-transcode verification FAILED (codec={codec or 'unreadable'}) — "
        f"the output file may be corrupt. Marking this download failed.", "error")
    return False
