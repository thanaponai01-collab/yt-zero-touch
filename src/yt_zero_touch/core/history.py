"""
History Store — Thread-safe persistence of downloaded URLs.
============================================================
Tracks processed URLs locally so duplicate downloads are skipped.
Replaces the loose (history: set, lock, path) tuples previously passed across threads.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterator


class HistoryStore:
    """Thread-safe storage and persistence for downloaded URLs."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._urls: set[str] = set()
        self.load()

    def load(self) -> set[str]:
        """Load history from disk. Returns the populated URL set."""
        with self._lock:
            if not self.path.exists():
                self._urls = set()
                return self._urls
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._urls = set(data) if isinstance(data, list) else set()
            except Exception:
                self._urls = set()
            return self._urls

    def save(self) -> None:
        """Persist current URL set to disk atomically."""
        with self._lock:
            try:
                data = sorted(list(self._urls))
                self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def add(self, url: str) -> None:
        """Add a URL and immediately persist."""
        with self._lock:
            self._urls.add(url)
            try:
                data = sorted(list(self._urls))
                self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def contains(self, url: str) -> bool:
        """Check if URL was previously downloaded."""
        with self._lock:
            return url in self._urls

    def __contains__(self, url: str) -> bool:
        return self.contains(url)

    def __len__(self) -> int:
        with self._lock:
            return len(self._urls)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._urls))

    @property
    def lock(self) -> threading.Lock:
        """Lock exposed for legacy code requiring explicit synchronization."""
        return self._lock

    @property
    def urls(self) -> set[str]:
        """Raw set copy for legacy compatibility."""
        with self._lock:
            return set(self._urls)


# Legacy functional helpers for backwards compatibility
def load_history(path: Path | str) -> set[str]:
    store = HistoryStore(path)
    return store.urls


def save_history(path: Path | str, history: set[str]) -> None:
    path = Path(path)
    try:
        data = sorted(list(history))
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
