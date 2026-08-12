from datetime import datetime
from pathlib import Path
import sys
import unittest


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_high_range_top5_low_shadow_v1 import evaluate_once, select_shadow_universe


class HighRangeTop5LowShadowTests(unittest.TestCase):
    def test_selects_ranked_top5_with_four_of_latest_five_days(self):
        payload = {
            "schema_version": 2,
            "source_stale": False,
            "candidates": [
                {"rank": rank, "code": f"{rank:06d}", "qualified_5d_count": count}
                for rank, count in [(1, 5), (2, 3), (3, 4), (4, 5), (5, 4), (6, 4), (7, 5)]
            ],
        }
        selected = select_shadow_universe(payload)
        self.assertEqual(
            [row["code"] for row in selected],
            ["000001", "000003", "000004", "000005", "000006"],
        )

    def test_stale_source_fails_closed(self):
        self.assertEqual(
            select_shadow_universe(
                {"schema_version": 2, "source_stale": True, "candidates": []}
            ),
            [],
        )

    def test_old_payload_waits_and_retries_after_same_day_schema_upgrade(self):
        now = datetime(2026, 8, 11, 9, 1)
        waiting, emitted = evaluate_once(
            {"schema_version": 1, "source_stale": False, "candidates": []},
            {"codes": {}},
            {},
            now,
        )
        self.assertEqual(waiting["status"], "WAIT_SOURCE_SCHEMA")
        self.assertEqual(emitted, [])

        ready, emitted = evaluate_once(
            {
                "schema_version": 2,
                "source_stale": False,
                "candidates": [
                    {"rank": 1, "code": "000001", "qualified_5d_count": 4}
                ],
            },
            {"codes": {}},
            waiting,
            now,
        )
        self.assertEqual(ready["status"], "WATCH")
        self.assertEqual([row["code"] for row in ready["universe"]], ["000001"])
        self.assertEqual(emitted, [])


if __name__ == "__main__":
    unittest.main()
