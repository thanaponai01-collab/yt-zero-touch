"""
Verification of package modular imports across yt_zero_touch.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestPackageImports(unittest.TestCase):
    def test_imports(self):
        import yt_zero_touch
        from yt_zero_touch.core import (
            AppSettings,
            BatchPolicy,
            FORMAT_SORT,
            HistoryStore,
            TRANSCODE_TO_H264,
            plan_transcode,
        )
        from yt_zero_touch.engines import (
            Downloader,
            download_gallery,
            download_gdrive,
            download_ytdlp,
        )
        from yt_zero_touch.services import (
            check_dependencies,
            check_disk_space,
            check_ffmpeg,
            resolve_url,
            run_batch,
            update_tools,
        )

        self.assertIsNotNone(yt_zero_touch.__version__)
        for adapter in (download_ytdlp, download_gallery, download_gdrive):
            self.assertTrue(callable(adapter))
        self.assertTrue(callable(Downloader))

    def test_every_source_dir_is_a_real_package(self):
        # pyproject.toml uses setuptools' find_packages, which only walks
        # directories containing __init__.py. A source dir missing one is
        # dropped from the built wheel with no error - and both [project.scripts]
        # entry points live under yt_zero_touch.ui, so the omission ships an
        # install whose console scripts ImportError. Assert the built package
        # list covers every directory that actually holds modules.
        from setuptools import find_packages

        src = Path(__file__).resolve().parent.parent / "src"
        with_modules = {
            str(d.relative_to(src)).replace("\\", "/").replace("/", ".")
            for d in src.rglob("*")
            if d.is_dir() and d.name != "__pycache__" and any(d.glob("*.py"))
        }
        self.assertEqual(with_modules - set(find_packages(where=str(src))), set())


if __name__ == "__main__":
    unittest.main()
