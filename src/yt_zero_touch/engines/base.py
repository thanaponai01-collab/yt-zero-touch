"""
Base Engine Interface.
======================
Contract for all concrete download adapters (yt-dlp, gallery-dl, gdown).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

LogFn = Callable[[str, str], None]


class BaseEngine(ABC):
    """Abstract download engine."""

    @abstractmethod
    def can_handle(self, url: str, **kwargs: Any) -> bool:
        """Return True if this engine can process the given URL."""
        pass

    @abstractmethod
    def download(
        self,
        url: str,
        out_dir: Path,
        log: LogFn,
        **kwargs: Any,
    ) -> bool:
        """Download URL to out_dir. Returns True on success."""
        pass
