"""
Presentation State & View Model.
=================================
Decoupled UI state tracking queue items, active download metrics, and flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class QueueItemState:
    idx: int
    url: str
    status: str = "queued"
    percent: float | None = None


@dataclass
class AppState:
    downloading: bool = False
    updating: bool = False
    status_text: str = "Idle"
    items: dict[int, QueueItemState] = field(default_factory=dict)
    listeners: list[Callable[[], None]] = field(default_factory=list)

    def subscribe(self, callback: Callable[[], None]) -> None:
        self.listeners.append(callback)

    def notify(self) -> None:
        for listener in self.listeners:
            try:
                listener()
            except Exception:
                pass

    def reset_queue(self, urls: list[str]) -> None:
        self.items = {
            idx: QueueItemState(idx=idx, url=url, status="queued")
            for idx, url in enumerate(urls, 1)
        }
        self.notify()

    def update_item(self, idx: int, status: str, percent: float | None = None) -> None:
        if idx in self.items:
            self.items[idx].status = status
            if percent is not None:
                self.items[idx].percent = percent
            self.notify()
