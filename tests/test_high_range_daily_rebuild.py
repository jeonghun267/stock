# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
sys.path.insert(0, str(RUN_DIR))

from common_high_range_watchlist_v1 import build_and_publish
from high_range_live_board_v1 import run_once


class DailyRebuildTest(unittest.TestCase):
    def test_same_eod_is_republished_for_new_observation_date(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "data").mkdir()
            (base / "IPC").mkdir()
            rows = []
            for day in range(20, 25):
                rows.append(
                    {
                        "date": f"202607{day:02d}",
                        "code": "000001",
                        "name": "날짜검사",
                        "low": 10_000,
                        "high": 11_200,
                        "close": 11_000,
                        "value": 60_000,
                    }
                )
            eod = base / "data" / "eod_daily_bars.csv"
            pd.DataFrame(rows).to_csv(eod, index=False)
            build_and_publish(base, eod, datetime(2026, 7, 26, 12, 0))

            payload, _, _ = run_once(
                base,
                base / "Desktop",
                datetime(2026, 7, 27, 8, 40),
            )
            self.assertEqual(payload["for_date"], "20260727")
            watch = json.loads(
                (base / "IPC" / "micro_watch_high_range.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(watch["for_date"], "20260727")
            self.assertEqual(watch["source_date"], "20260724")


if __name__ == "__main__":
    unittest.main()
