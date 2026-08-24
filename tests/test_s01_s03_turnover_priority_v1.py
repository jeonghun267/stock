from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from listed_turnover_common_v1 import listed_turnover_metrics, turnover_bonus
from strategy_01_signal_contract_v2 import (
    SIGNAL_MODE as S01_MODE,
    SIGNAL_SCHEMA as S01_SCHEMA,
    select_fresh_signals as select_s01,
)
from strategy_03_signal_contract_v1 import (
    EARLY_LOW_ALGORITHM,
    EARLY_LOW_LANE,
    SIGNAL_MODE as S03_MODE,
    SIGNAL_SCHEMA as S03_SCHEMA,
    select_fresh_signals as select_s03,
)


class TurnoverPriorityTests(unittest.TestCase):
    def test_shared_turnover_bands(self):
        self.assertEqual(
            [turnover_bonus(value) for value in (1.9, 2.0, 5.0, 10.0)],
            [0, 1, 2, 3],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shares.csv"
            path.write_text(
                "code,shares\n123456,1000000\n", encoding="utf-8")
            self.assertEqual(
                listed_turnover_metrics("123456", 50000, shares_path=path),
                {"listed_turnover_pct": 5.0, "listed_turnover_bonus": 2},
            )

    def test_s01_prefers_higher_turnover_band_after_theme(self):
        now = datetime(2026, 8, 14, 9, 1, 2)
        base = {
            "action": "BUY_READY", "mode": S01_MODE,
            "ts": now.isoformat(), "signal_sequence": 1,
            "theme_bonus": 0, "money_speed_5s": 100, "buy_ratio": 0.7,
        }
        payload = {
            "schema": S01_SCHEMA, "mode": S01_MODE, "date": "20260814",
            "updated_at": now.isoformat(), "signals": [
                {**base, "code": "111111", "listed_turnover_bonus": 1},
                {**base, "code": "222222", "listed_turnover_bonus": 3},
            ],
        }
        self.assertEqual(
            select_s01(payload, now=now, max_age_sec=5)[0]["code"],
            "222222",
        )

    def test_s03_prefers_higher_turnover_band(self):
        now = datetime(2026, 8, 14, 9, 1, 2)
        base = {
            "action": "BUY_READY", "mode": S03_MODE,
            "ts": now.isoformat(timespec="milliseconds"),
            "signal_sequence": 1, "entry_lane": EARLY_LOW_LANE,
            "algorithm": EARLY_LOW_ALGORITHM, "anchor_low": 100,
            "anchor_low_ts": "2026-08-14T09:00:30.000",
            "anchor_id": "2026-08-14T09:00:30.000:100.0000",
            "flow_turn_ready": True,
            "flow_recent_buy_rate": 10.0,
            "flow_recent_sell_rate": 1.0,
            "flow_price_responding": True,
            "rebound_pct": 1.2, "recent_buy_rate_10s": 10,
            "recent_sell_rate_10s": 1, "higher_low_pct": 0.3,
        }
        payload = {
            "schema": S03_SCHEMA, "mode": S03_MODE, "date": "20260814",
            "updated_at": now.isoformat(), "signals": [
                {**base, "code": "111111", "listed_turnover_bonus": 1},
                {**base, "code": "222222", "listed_turnover_bonus": 3},
            ],
        }
        self.assertEqual(
            select_s03(payload, now=now, max_age_sec=5)[0]["code"],
            "222222",
        )


if __name__ == "__main__":
    unittest.main()
