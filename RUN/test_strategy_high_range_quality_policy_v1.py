import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from strategy_high_range_quality_policy_v1 import (
    append_shadow_batch, enrich_candidates, rank_candidates, strategy_use,
)


class HighRangeQualityPolicyTest(unittest.TestCase):
    def setUp(self):
        self.status = {"static_fresh": True, "live_fresh": True}
        self.quality = {
            "000001": {"hr_rank": 20, "hr_money_speed_ratio": 2, "hr_quality_risks": []},
            "000002": {"hr_rank": 2, "hr_money_speed_ratio": 9, "hr_quality_risks": []},
        }
        self.candidates = [{"code": "1"}, {"code": "2"}]

    def test_momentum_reorders_but_never_becomes_live(self):
        rows = enrich_candidates("S01", self.candidates, self.quality, self.status)
        ranked = rank_candidates("S01", rows)
        self.assertEqual([r["code"] for r in ranked], ["000002", "000001"])
        self.assertTrue(all(r["order_qty"] == 0 and not r["live_eligible"] for r in ranked))

    def test_reversal_keeps_strategy_order(self):
        rows = enrich_candidates("S03", self.candidates, self.quality, self.status)
        ranked = rank_candidates("S03", rows)
        self.assertEqual(strategy_use("S03"), "RISK_CONTEXT_ONLY")
        self.assertEqual([r["code"] for r in ranked], ["000001", "000002"])

    def test_jsonl_is_durable_and_order_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.jsonl"
            rows = rank_candidates("S01", enrich_candidates(
                "S01", self.candidates, self.quality, self.status))
            append_shadow_batch(path, datetime(2026, 8, 21, 9, 1), "S01", rows)
            saved = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(saved), 2)
            self.assertTrue(all(r["mode"] == "SHADOW_ORDER_ZERO" for r in saved))


if __name__ == "__main__":
    unittest.main()
