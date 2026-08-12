# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ma3_backfill_v1 import read_cached_bars, request_backfill


class Ma3BackfillV1Tests(unittest.TestCase):
    def test_request_is_deduplicated_and_ready_cache_suppresses_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests = root / "requests"
            cache = root / "cache"
            now = datetime(2026, 8, 4, 9, 0)

            self.assertTrue(request_backfill(
                "123", "S01:ENTRY", requests, cache, now,
            ))
            self.assertFalse(request_backfill(
                "000123", "S02:ENTRY", requests, cache, now,
            ))

            requests.joinpath("000123.json").unlink()
            cache.mkdir(parents=True)
            start = datetime(2026, 8, 3, 14, 0)
            bars = [
                [(start + timedelta(minutes=3 * index)).strftime("%Y%m%d%H%M%S"),
                 100.0 + index]
                for index in range(21)
            ]
            cache.joinpath("000123.json").write_text(json.dumps({
                "status": "OK",
                "fetched_at": now.isoformat(timespec="seconds"),
                "bars": bars,
            }), encoding="utf-8")

            self.assertEqual(len(read_cached_bars("000123", now.date(), cache)), 21)
            self.assertFalse(request_backfill(
                "000123", "S03:ENTRY", requests, cache, now,
            ))
            self.assertFalse(requests.joinpath("000123.json").exists())


if __name__ == "__main__":
    unittest.main()
