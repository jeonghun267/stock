import tempfile
import unittest
from pathlib import Path
import sys

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from rotate_runtime_file_v1 import rotate
import pipeline_runner  # noqa: F401 - validates shutdown wiring import
import pipeline_watchdog  # noqa: F401
import micro_rank_engine_v1  # noqa: F401
import integrated_candidate_engine_v1  # noqa: F401
import moneyflow_watch_v1  # noqa: F401


class RuntimeFileRotationTests(unittest.TestCase):
    def test_large_file_is_moved_and_small_file_is_kept(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            large, small = root / "large.log", root / "small.log"
            large.write_bytes(b"x" * 20)
            small.write_bytes(b"x" * 2)
            moved = rotate([large, small], 10, "20260821_230000")
            self.assertFalse(large.exists())
            self.assertTrue(small.exists())
            self.assertEqual(len(moved), 1)
            self.assertTrue(moved[0].exists())


if __name__ == "__main__":
    unittest.main()
