from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_common_candidate_context_v1 import build_context


class CandidateContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 27, 9, 0, 5)
        self.profiles = {
            "111110": {"prev_close": 12000.0},
            "222220": {"prev_close": 13000.0},
            "333330": {"prev_close": 14000.0},
            "444440": {"prev_close": 15000.0},
        }
        self.shared = {
            "codes": ["111110"],
            "all_meta": {"111110": {"prev_close": 12000.0}},
            "qualified_codes": [],
        }
        self.valley = {"codes": ["111110", "222220"]}

    def test_current_sources_join_shared_without_expanding_valley(self) -> None:
        shared, valley, audit = build_context(
            now=self.now,
            shared_base=self.shared,
            valley_base=self.valley,
            profiles=self.profiles,
            money_rank={
                "date": "20260727",
                "ts": "2026-07-27 09:00:04",
                "top20": [{"code": "222220"}],
                "all_items": [
                    {"code": "333330", "money_start": True},
                ],
            },
            selector={
                "ts": "2026-07-27 09:00:04",
                "rows": [{"code": "444440"}, {"code": "999990"}],
            },
            money_watch={
                "ts": "2026-07-27T09:00:04",
                "codes": ["333330"],
            },
            high_range={
                "for_date": "20260727",
                "generated_at": "2026-07-27T08:40:00",
                "candidates": [
                    {"code": "444440", "rank": 2, "crown": False},
                    {"code": "222220", "rank": 1, "crown": True},
                ],
            },
        )

        self.assertEqual(
            shared["codes"], ["111110", "333330", "222220", "444440"])
        self.assertEqual(valley["codes"], ["111110", "222220"])
        self.assertNotIn("999990", shared["codes"])
        self.assertEqual(shared["source_tags"]["222220"],
                         ["captain_money_rank", "high_range_top30"])
        self.assertEqual(audit["order_capability"], 0)
        self.assertEqual(audit["shared_base_count"], 1)

    def test_stale_sources_are_ignored(self) -> None:
        shared, valley, audit = build_context(
            now=self.now,
            shared_base=self.shared,
            valley_base=self.valley,
            profiles=self.profiles,
            money_rank={"date": "20260724", "top20": [{"code": "222220"}]},
            selector={
                "ts": "2026-07-24 15:30:00",
                "rows": [{"code": "333330"}],
            },
            money_watch={
                "ts": "2026-07-24T15:30:00",
                "codes": ["444440"],
            },
            high_range={
                "for_date": "20260724",
                "candidates": [{"code": "222220"}],
            },
        )

        self.assertEqual(shared["codes"], ["111110"])
        self.assertEqual(valley["codes"], ["111110", "222220"])
        self.assertEqual(sum(audit["source_counts"].values()), 0)
        self.assertTrue(all(
            not row["fresh"] for row in audit["source_status"].values()))


if __name__ == "__main__":
    unittest.main()
