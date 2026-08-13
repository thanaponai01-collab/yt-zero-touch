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

Applying that decision is a lifecycle, not a call, because yt-dlp reports the
merge starting and finishing through separate callbacks and only promises the
second one on success. `merge_session()` owns that lifecycle for one download.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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

_h264_encoder_cache: "tuple[list[str], Literal['nvenc', 'libx264']] | None" = None
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


def _h264_transcode_args() -> "tuple[list[str], Literal['nvenc', 'libx264']]":
    """H.264 encode args for the >1080p fallback — NVENC when the GPU
    supports it, libx264 slow otherwise — paired with which encoder that is,
    so callers can branch on the explicit kind instead of comparing object
    identity against a module constant. Detection result is cached for the
    process lifetime."""
    global _h264_encoder_cache
    with _h264_encoder_cache_lock:
        if _h264_encoder_cache is None:
            _h264_encoder_cache = (
                (_H264_NVENC_ARGS, "nvenc") if _nvenc_available()
                else (_H264_TRANSCODE_ARGS, "libx264")
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

    # Only called when a transcode is actually needed — keeps the NVENC
    # detection subprocess probe (see _h264_transcode_args) off the path for
    # downloads that never transcode.
    encoder_kind = None
    if will_transcode:
        video_args, encoder_kind = _h264_transcode_args()
    else:
        video_args = ["-c:v", "copy"]

    log_message = None
    if not is_h264 and not TRANSCODE_TO_H264:
        log_message = (
            f"  Keeping {vcodec or 'source'} video untouched (stream copy) — "
            f"Premiere 2023+ decodes it natively. Set TRANSCODE_TO_H264=True "
            f"for older Premiere."
        )
    elif will_transcode:
        encoder = video_args[1]
        log_message = (
            f"  >1080p source is {vcodec or 'non-H.264'} — transcoding to "
            f"H.264 ({encoder}) for Premiere compatibility (this takes longer)…"
        )

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
    needs_gate = will_transcode and encoder_kind == "libx264"

    return TranscodePlan(
        merge_args=merge_args,
        did_transcode=will_transcode,
        needs_gate=needs_gate,
        log_message=log_message,
    )

# ---------------------------------------------------------------------------
# Merge session — owns one download's merge lifecycle
# ---------------------------------------------------------------------------

# The orchestrator runs up to 3 download threads; if several of them hit the
# >1080p transcode path simultaneously (e.g. a pasted batch of 4K links),
# concurrent libx264 4K encodes stack multi-GB RAM allocations and can OOM
# the machine (observed: two concurrent 4K encodes ≈ 6GB+). Downloads still
# run in parallel — only the ffmpeg merge/transcode step is serialized, and
# only when it actually transcodes video (pure stream copies don't take the
# gate).
#
# Private to this file on purpose: only the merge session below may touch it.
# There is no acquire/release pair to call from outside, because a caller that
# can acquire is a caller that can forget to release.
_TRANSCODE_GATE = threading.Lock()


class _MergeSession:
    """Owns the merge lifecycle for one download: the transcode gate, and
    where the merged file landed.

    Scoped to the *download*, not to one merge, because the gate has to be
    held across two separate yt-dlp callbacks — `started` returns before
    ffmpeg runs and `finished` arrives after it, so no single `with` block can
    bracket one merge. The pairing moves in here instead of dissolving.

    Ordering contract, as yt-dlp speaks it:

        merge_started(plan, filepath)   <- "started" callback, before ffmpeg
        merge_finished(filepath)        <- "finished" callback, after ffmpeg
        __exit__                        <- the enclosing download ended

    yt-dlp promises `finished` only when the merge *succeeds*: its hook
    wrapper emits it on the statement after the merge call, with no
    try/finally (postprocessor/common.py). A crashed merge therefore skips it,
    so the gate is freed on two independent paths — see merge_started and
    __exit__.
    """

    def __init__(self, log: LogFn, container: str):
        self._log = log
        self._holding_gate = False
        # The container commitment, taken straight from the value that went
        # into ydl_opts so there is no second source of truth. "mp4" means we
        # forced an mp4 before any codec was known, on the promise that a
        # transcode would make it legal — a promise verify() collects on.
        self._committed_to_mp4 = container == "mp4"
        # Merged outputs, in the order yt-dlp produced them. A playlist runs
        # several merges inside one download call, so this cannot be a single
        # slot without silently verifying only the last entry.
        self._merged: "list[str]" = []
        self._finished: "list[str]" = []

    def __enter__(self) -> "_MergeSession":
        return self

    def __exit__(self, *exc_info) -> bool:
        self._free_gate()
        return False

    def merge_started(self, plan: "TranscodePlan", filepath: "str | None") -> None:
        """A merge is about to run with `plan`'s args, producing `filepath`."""
        # Still holding the gate from a previous merge means that merge died
        # without reporting back. Free it rather than blocking: this is the
        # same thread, and the gate is not reentrant, so blocking here is an
        # unbreakable self-deadlock. It is reachable whenever one
        # ydl.download() call serves several entries — i.e. any playlist,
        # since ignoreerrors lets it carry on past a failed merge.
        if self._holding_gate:
            self._log("  Previous merge ended without reporting back — freeing "
                      "the transcode gate for this one.", "warn")
            self._free_gate()
        if filepath:
            self._merged.append(filepath)
        if plan.needs_gate:
            self._take_gate()

    def merge_finished(self, filepath: "str | None") -> None:
        """The merge completed and ffmpeg has renamed its output into place."""
        # Prefer the path recorded at "started": yt-dlp hands the "finished"
        # callback the same pre-run infodict copy, so this adds nothing, but a
        # future payload change that drops it must not lose the file.
        landed = filepath or (self._merged[-1] if self._merged else None)
        if landed:
            self._finished.append(landed)
        self._free_gate()

    def verify(self) -> bool:
        """Collect on the container commitment, by measurement.

        mp4 was forced before any codec was known, on the promise that a
        transcode would follow. Rather than ask whether that transcode was
        recorded — the bookkeeping that lied in the first place — ffprobe every
        file that merged successfully. An H.264 stream copy reads back as h264
        and passes; a transcode that was silently skipped reads back as vp9 and
        fails. Nothing this consults is capable of lying.

        Runs after the download call rather than at each "finished", because
        FFmpegMetadata and EmbedThumbnail rewrite the file after the merger.
        """
        if not self._committed_to_mp4:
            return True
        ok = True
        for path in self._finished:
            if not Path(path).exists():
                self._log(f"  Could not locate merged output for verification "
                          f"({Path(path).name}) — check the file manually "
                          f"before importing.", "warn")
                continue
            if not verify_h264_output(path, self._log):
                ok = False
        return ok

    def _take_gate(self) -> None:
        if not _TRANSCODE_GATE.acquire(blocking=False):
            self._log("  Waiting for another transcode to finish (one heavy "
                      "encode at a time)…", "info")
            _TRANSCODE_GATE.acquire()
        self._holding_gate = True

    def _free_gate(self) -> None:
        if self._holding_gate:
            self._holding_gate = False
            _TRANSCODE_GATE.release()


def merge_session(log: LogFn, container: str) -> _MergeSession:
    """Open a merge session for one download. Use as a context manager around
    the yt-dlp download call, and feed it the merger's callbacks. `container`
    is the merge_output_format that went into ydl_opts — see container_for."""
    return _MergeSession(log, container)

# ---------------------------------------------------------------------------
# Output verification
# ---------------------------------------------------------------------------

# ffprobe missing is a property of the machine, not of the download, so say so
# once rather than on every merged file for the rest of the session.
_ffprobe_missing_reported = False


def verify_h264_output(path: "Path | str", log: LogFn) -> bool:
    """ffprobe a merged file to confirm its video stream really is decodable
    H.264 — catching both a silently-truncated/corrupt output (crashed
    encoder, full disk, OOM-killed ffmpeg) and a transcode that should have
    run and didn't, either of which would otherwise only be discovered when
    the file fails to open in Premiere later."""
    global _ffprobe_missing_reported
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        if not _ffprobe_missing_reported:
            _ffprobe_missing_reported = True
            log("  ffprobe not found — skipping output verification for this "
                "session.", "warn")
        return True
    except Exception as exc:
        log(f"  Output verification errored ({exc}) — treating as failed.", "error")
        return False
    codec = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
    if proc.returncode == 0 and codec == "h264":
        log("  Verified: output is clean H.264 — safe for any Premiere version.", "info")
        return True
    log(f"  Output verification FAILED (codec={codec or 'unreadable'}, expected "
        f"h264) — {Path(path).name} is corrupt or was never transcoded. Marking "
        f"this download failed.", "error")
    return False
