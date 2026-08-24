# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import regime_priority_judge_v1 as judge


class RegimePriorityJudgeTests(unittest.TestCase):
    def test_normal_market_records_but_does_not_disable_strategy01(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            top = root / "top.json"
            snap = root / "snap.json"
            flag = root / "strategy_01_off.flag"
            record = root / "record.json"
            now = datetime.now()
            today = now.strftime("%Y%m%d")
            candidates = [
                {"code": f"{index:06d}", "prev_close": 100}
                for index in range(1, 21)
            ]
            codes = {
                row["code"]: {"cur": 100, "ts": now.isoformat()}
                for row in candidates
            }
            top.write_text(json.dumps({
                "for_date": today,
                "candidates": candidates,
            }), encoding="utf-8")
            snap.write_text(json.dumps({"codes": codes}), encoding="utf-8")
            flag.write_text(f"REGIME_JUDGE {today}\n", encoding="utf-8")

            with patch.multiple(
                judge,
                TOP30=top,
                SNAP=snap,
                FLAG=flag,
                RECORD=record,
            ):
                self.assertEqual(judge.main(), 0)

            self.assertFalse(flag.exists())
            payload = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "NORMAL_OR_CRASH")
            self.assertTrue(payload["action"].startswith("ALL_STRATEGIES_OPEN"))


if __name__ == "__main__":
    unittest.main()
