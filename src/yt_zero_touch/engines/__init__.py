"""
Download Engines: yt-dlp, gallery-dl, and Google Drive.
"""

from yt_zero_touch.engines.base import BaseEngine, LogFn
from yt_zero_touch.engines.gallery_engine import (
    GALLERY_DL_OK,
    GalleryEngine,
    download_gallery,
)
from yt_zero_touch.engines.gdrive_engine import (
    GDOWN_OK,
    GDriveEngine,
    download_gdrive,
    extract_gdrive_id,
)
from yt_zero_touch.engines.ytdlp_engine import (
    YT_DLP_API_OK,
    Downloader,
    YtdlpEngine,
    download_ytdlp,
)

__all__ = [
    "BaseEngine",
    "Downloader",
    "GALLERY_DL_OK",
    "GDOWN_OK",
    "GDriveEngine",
    "GalleryEngine",
    "LogFn",
    "YT_DLP_API_OK",
    "YtdlpEngine",
    "download_gallery",
    "download_gdrive",
    "download_ytdlp",
    "extract_gdrive_id",
]
