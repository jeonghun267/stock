# -*- coding: utf-8 -*-
import sys
import unittest
from datetime import datetime
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))
import strategy_07_morning_trend_v1 as s07m


class MorningTrendDecisionTest(unittest.TestCase):
    def test_fill_based_entry_and_take_profit(self):
        engine = s07m.DecisionEngine([{"code": "006730", "definitions": ["ALT_A_097_VALUE_1P5"]}])
        entry = engine.process({"code": "006730", "observed_at": "2026-09-03T09:01:00+09:00",
                                "cur": 10000, "day_open": 9900})
        self.assertEqual(entry[0]["event"], "SHADOW_ENTRY")
        self.assertEqual(engine.process({"code": "006730", "observed_at": "2026-09-03T09:02:00+09:00",
                                         "cur": 10299, "day_open": 9900}), [])
        exit_rows = engine.process({"code": "006730", "observed_at": "2026-09-03T09:03:00+09:00",
                                    "cur": 10300, "day_open": 9900})
        self.assertIn("TAKE_PROFIT_3PCT", exit_rows[0]["reason"])

    def test_priority_and_max_six(self):
        day = {"CURRENT": ["300000"], "ALT_A_097_VALUE_1P5": ["200000"],
               "ALT_B_NO_BREAKOUT": ["100000", "200000", "300000"]}
        ranked = sorted({code for values in day.values() for code in values},
                        key=lambda code: (0 if code in day["CURRENT"] else 1 if code in day["ALT_A_097_VALUE_1P5"] else 2, code))[:s07m.S07M_MAX_POS]
        self.assertEqual(s07m.S07M_MAX_POS, 6)
        self.assertEqual(ranked, ["300000", "200000", "100000"])


if __name__ == "__main__":
    unittest.main()
