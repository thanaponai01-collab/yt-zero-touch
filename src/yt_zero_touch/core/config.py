"""
App Configuration & Settings Management.
=========================================
Type-safe application settings with automatic JSON persistence and fallback defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    out_dir: str = ""
    quality: str = "Best"
    cookie_file: str = ""
    browser_cookies: str = "none"
    sub_en: bool = False
    sub_th: bool = False
    sections: str = ""
    watch_clip: bool = False
    prores_proxy: bool = False

    @classmethod
    def load(cls, path: Path | str, default_out_dir: Path | str | None = None) -> AppSettings:
        path = Path(path)
        settings = cls()
        if default_out_dir and not settings.out_dir:
            settings.out_dir = str(default_out_dir)

        if not path.exists():
            return settings

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if hasattr(settings, k) and v is not None:
                        setattr(settings, k, v)
        except Exception:
            pass

        return settings

    def save(self, path: Path | str) -> None:
        path = Path(path)
        try:
            data = asdict(self)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
