# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path


RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import trend_follow_start_ledger_v1 as ledger


class IntradayAuditTest(unittest.TestCase):
    def test_next_day_ohlc_metrics(self):
        event = ledger.intraday_audit_event(
            "CURRENT", "20260831", "20260901", "123456",
            {"name": "검증"}, 100.0,
            {"open": 110.0, "high": 121.0, "low": 99.0, "close": 115.5},
        )
        self.assertEqual(event["provenance"], "[HYPOTHETICAL]")
        self.assertAlmostEqual(event["gap_pct"], 10.0)
        self.assertAlmostEqual(event["open_to_close_pct"], 5.0)
        self.assertAlmostEqual(event["mfe_from_open_pct"], 10.0)
        self.assertAlmostEqual(event["mae_from_open_pct"], -10.0)


if __name__ == "__main__":
    unittest.main()
