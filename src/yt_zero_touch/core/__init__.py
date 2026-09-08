"""
Core domain models, transcode policies, failure classification, and stores.
"""

from yt_zero_touch.core.config import AppSettings
from yt_zero_touch.core.failures import (
    FailureClass,
    classify_failure,
    is_permanent_error,
)
from yt_zero_touch.core.format_policy import (
    DONT_CAP_RESOLUTION,
    FORMAT_SORT,
    PREFER_H264_WITHIN_TIER,
    PREFER_ORIGINAL_AUDIO_TRACK,
)
from yt_zero_touch.core.history import HistoryStore, load_history, save_history
from yt_zero_touch.core.models import (
    FORMAT_AUDIO,
    FORMAT_VIDEO,
    IMAGE_HOSTS,
    QUALITY_PRESETS,
    URL_RE,
    BatchPolicy,
    BatchResult,
    DownloadOutcome,
    build_output_template,
    is_image_host,
    parse_sections,
)
from yt_zero_touch.core.transcode import (
    PRE_MERGE_DEFAULT_ARGS,
    TRANSCODE_TO_H264,
    Encoder,
    TargetCodec,
    TranscodePlan,
    container_for,
    merge_session,
    plan_transcode,
    verify_h264_output,
    verify_prores_output,
)

__all__ = [
    "AppSettings",
    "BatchPolicy",
    "BatchResult",
    "DownloadOutcome",
    "Encoder",
    "FailureClass",
    "FORMAT_AUDIO",
    "FORMAT_SORT",
    "FORMAT_VIDEO",
    "HistoryStore",
    "IMAGE_HOSTS",
    "PRE_MERGE_DEFAULT_ARGS",
    "QUALITY_PRESETS",
    "TRANSCODE_TO_H264",
    "TargetCodec",
    "TranscodePlan",
    "URL_RE",
    "build_output_template",
    "classify_failure",
    "container_for",
    "is_image_host",
    "is_permanent_error",
    "load_history",
    "merge_session",
    "parse_sections",
    "plan_transcode",
    "save_history",
    "verify_h264_output",
    "verify_prores_output",
]
