# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from ma3_seed_v1 import build_opening_seed


class Ma3SeedV1Tests(unittest.TestCase):
    def test_builds_latest_regular_session_and_requires_21_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prices = root / "prices_1m.csv"
            seed = root / "seed.json"
            fields = ["code", "ts", "open", "high", "low", "close", "volume"]
            with prices.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for day, code, count in (
                    ("20260802", "000001", 63),
                    ("20260803", "000001", 63),
                    ("20260803", "000002", 20),
                ):
                    start = datetime.strptime(day + "140000", "%Y%m%d%H%M%S")
                    for index in range(count):
                        stamp = start + timedelta(minutes=index)
                        writer.writerow({
                            "code": code,
                            "ts": stamp.strftime("%Y%m%d%H%M%S"),
                            "open": 100 + index,
                            "high": 101 + index,
                            "low": 99 + index,
                            "close": 100 + index,
                            "volume": 1000 + index,
                        })

            stats = build_opening_seed(prices, seed, "20260803")
            payload = json.loads(seed.read_text(encoding="utf-8"))

            self.assertEqual(stats["session_date"], "20260803")
            self.assertEqual(stats["ready_codes"], 1)
            self.assertEqual(set(payload["m"]), {"000001"})
            self.assertEqual(len(payload["m"]["000001"]["prev"]), 63)
            self.assertTrue(payload["m"]["000001"]["pm"][0].startswith("20260803"))


if __name__ == "__main__":
    unittest.main()
