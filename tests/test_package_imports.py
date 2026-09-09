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
            BaseEngine,
            Downloader,
            GalleryEngine,
            GDriveEngine,
            YtdlpEngine,
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
        self.assertTrue(issubclass(YtdlpEngine, BaseEngine))
        self.assertTrue(issubclass(GalleryEngine, BaseEngine))
        self.assertTrue(issubclass(GDriveEngine, BaseEngine))


if __name__ == "__main__":
    unittest.main()
