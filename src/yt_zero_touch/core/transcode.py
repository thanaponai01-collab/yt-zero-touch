"""
Transcode Plan — single owner for "what happens to a downloaded file".
========================================================================
Given the video/audio codecs yt-dlp actually selected, decides whether the
merge step copies or re-encodes to H.264, which ffmpeg args that takes, and
the gate/verification behaviour around a heavy transcode.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

LogFn = Callable[[str, str], None]

# ---------------------------------------------------------------------------
# Master switch
# ---------------------------------------------------------------------------

# Premiere 2023+ decodes VP9 and AV1 natively, so a >1080p source can be
# muxed through untouched: the merge becomes a pure stream copy (seconds
# instead of minutes) *and* the output is bit-identical to what YouTube
# served — no H.264 generation loss. Flip to True only if the footage has to
# open in a pre-2023 Premiere, which needs the transcode below.
TRANSCODE_TO_H264 = True

# ---------------------------------------------------------------------------
# Encoder args
# ---------------------------------------------------------------------------

PREMIERE_MERGE_ARGS_COPY_AUDIO = [
    "-c:v", "copy",
    "-movflags", "+faststart",
]

_H264_TRANSCODE_ARGS = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
]

_H264_NVENC_ARGS = [
    "-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq",
    "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p",
]

_PRORES_PROXY_ARGS = [
    "-c:v", "prores_ks", "-profile:v", "0", "-vendor", "apl0",
    "-pix_fmt", "yuv422p10le",
]


@dataclass(frozen=True)
class Encoder:
    """One H.264 encoder, in the two vocabularies that have to agree about it."""
    args: list[str]
    kind: Literal["nvenc", "libx264", "prores"]

    @property
    def name(self) -> str:
        return self.args[self.args.index("-c:v") + 1]


_h264_encoder_cache: Encoder | None = None
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


def _h264_encoder() -> Encoder:
    global _h264_encoder_cache
    with _h264_encoder_cache_lock:
        if _h264_encoder_cache is None:
            _h264_encoder_cache = (
                Encoder(_H264_NVENC_ARGS, "nvenc") if _nvenc_available()
                else Encoder(_H264_TRANSCODE_ARGS, "libx264")
            )
        return _h264_encoder_cache


_PRORES_ENCODER = Encoder(_PRORES_PROXY_ARGS, "prores")
_AAC_ACODEC_PREFIXES = ("mp4a", "aac")
_H264_VCODEC_PREFIXES = ("avc1", "h264")

PRE_MERGE_DEFAULT_ARGS = [
    "-c:v", "copy",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
]

TargetCodec = Literal["h264", "prores"]


def container_for(audio_only: bool, target_codec: TargetCodec = "h264") -> str:
    if audio_only:
        return "opus"
    if target_codec == "prores":
        return "mov"
    return "mp4" if TRANSCODE_TO_H264 else "mp4/mkv"


CodecCase = Literal["h264", "non_h264", "unknown"]


@dataclass(frozen=True)
class TranscodePlan:
    merge_args: list[str]
    needs_gate: bool
    codec_case: CodecCase
    log_message: str | None
    log_level: str = "info"


def _codec_case(vcodec: str) -> CodecCase:
    if not vcodec:
        return "unknown"
    return "h264" if vcodec.startswith(_H264_VCODEC_PREFIXES) else "non_h264"


def _audio_merge_args(acodec: str) -> list[str]:
    return (
        [] if acodec.startswith(_AAC_ACODEC_PREFIXES)
        else ["-c:a", "aac", "-b:a", "192k"]
    )


def plan_transcode(
    vcodec: str, acodec: str, target_codec: TargetCodec = "h264",
) -> TranscodePlan:
    vcodec = vcodec.strip().lower()
    acodec = acodec.strip().lower()
    codec_case = _codec_case(vcodec)

    if target_codec == "prores":
        encoder = _PRORES_ENCODER
        video_args = encoder.args
        will_transcode = True
        if codec_case == "unknown":
            log_message = (
                f"  Could not determine the source video codec — transcoding "
                f"to ProRes 422 Proxy ({encoder.name}) anyway; a ProRes merge "
                f"always re-encodes, so this doesn't change what happens next."
            )
            log_level = "warn"
        else:
            log_message = (
                f"  Transcoding {vcodec or 'source'} to ProRes 422 Proxy "
                f"({encoder.name}) for editing performance — this is slower "
                f"and much larger than a stream copy…"
            )
            log_level = "info"
    else:
        will_transcode = TRANSCODE_TO_H264 and codec_case != "h264"
        encoder = None
        if will_transcode:
            encoder = _h264_encoder()
            video_args = encoder.args
        else:
            video_args = ["-c:v", "copy"]

        log_message, log_level = None, "info"
        if codec_case != "h264" and not TRANSCODE_TO_H264:
            log_message = (
                f"  Keeping {vcodec or 'source'} video untouched (stream copy) — "
                f"Premiere 2023+ decodes it natively. Set TRANSCODE_TO_H264=True "
                f"for older Premiere."
            )
        elif will_transcode and codec_case == "unknown":
            log_message = (
                f"  Could not determine the source video codec — transcoding to "
                f"H.264 ({encoder.name}) so the mp4 container is guaranteed legal. "
                f"This is slower than a stream copy; if it keeps happening, "
                f"yt-dlp's callback payload has probably changed shape."
            )
            log_level = "warn"
        elif will_transcode:
            log_message = (
                f"  >1080p source is {vcodec} — transcoding to H.264 "
                f"({encoder.name}) for Premiere compatibility (this takes longer)…"
            )

    audio_args = _audio_merge_args(acodec)
    merge_args = [*video_args, *audio_args, "-movflags", "+faststart"]
    needs_gate = will_transcode and encoder.kind != "nvenc"

    return TranscodePlan(
        merge_args=merge_args,
        needs_gate=needs_gate,
        codec_case=codec_case,
        log_message=log_message,
        log_level=log_level,
    )


_TRANSCODE_GATE = threading.Lock()
_CONTAINER_COMMITMENTS = {"mp4": "h264", "mov": "prores"}


class _MergeSession:
    def __init__(self, log: LogFn, container: str):
        self._log = log
        self._holding_gate = False
        self._committed_codec = _CONTAINER_COMMITMENTS.get(container)
        self._merged: list[str] = []
        self._finished: list[str] = []

    def __enter__(self) -> _MergeSession:
        return self

    def __exit__(self, *exc_info) -> bool:
        self._free_gate()
        return False

    def merge_started(self, plan: TranscodePlan, filepath: str | None) -> None:
        if self._holding_gate:
            self._log("  Previous merge ended without reporting back — freeing "
                      "the transcode gate for this one.", "warn")
            self._free_gate()
        if filepath:
            self._merged.append(filepath)
        if plan.needs_gate:
            self._take_gate()

    def merge_finished(self, filepath: str | None) -> None:
        landed = filepath or (self._merged[-1] if self._merged else None)
        if landed:
            self._finished.append(landed)
        self._free_gate()

    def verify(self) -> bool:
        if self._committed_codec is None:
            return True
        verify_output = (
            verify_h264_output if self._committed_codec == "h264"
            else verify_prores_output
        )
        ok = True
        for path in self._finished:
            if not Path(path).exists():
                self._log(f"  Output verification failed: merged file is "
                          f"missing on disk ({Path(path).name}) — marking "
                          f"this download failed.", "error")
                ok = False
                continue
            if not verify_output(path, self._log):
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
    return _MergeSession(log, container)


_ffprobe_missing_reported = False


def _verify_output_codec(path: Path | str, log: LogFn, want_codec: str, want_label: str) -> bool:
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
    line = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
    codec = line.split(",")[0]
    if proc.returncode == 0 and codec == want_codec:
        log(f"  Verified: output is clean {want_label} — safe for any Premiere "
            f"version.", "info")
        return True
    log(f"  Output verification FAILED (codec={codec or 'unreadable'}, expected "
        f"{want_codec}) — {Path(path).name} is corrupt or was never transcoded. "
        f"Marking this download failed.", "error")
    return False


def verify_h264_output(path: Path | str, log: LogFn) -> bool:
    return _verify_output_codec(path, log, "h264", "H.264")


def verify_prores_output(path: Path | str, log: LogFn) -> bool:
    return _verify_output_codec(path, log, "prores", "ProRes")
