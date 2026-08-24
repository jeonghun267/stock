# -*- coding: utf-8 -*-
"""Focused tests for the EOD_GAP closing-auction persistence gate."""
import importlib.util
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


def _load_module():
    path = Path(__file__).with_name("eod_gap_live_executor_v1.py")
    spec = importlib.util.spec_from_file_location("eod_gap_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch("logging.handlers.RotatingFileHandler",
               lambda *args, **kwargs: logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


class EodGapAuctionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def _record(self, tmp, prices, quantities, locked=False, reference_px=0):
        m = self.mod
        now = datetime.now().replace(hour=15, minute=27, second=5, microsecond=0)
        m.AUCTION_AUDIT_DIR = Path(tmp)
        m.AUCTION_DECISION_HHMM = 1527
        m.AUCTION_MIN_SAMPLES = 3
        m.AUCTION_MIN_SPAN_SEC = 60
        rows = []
        for idx, (px, qty) in enumerate(zip(prices, quantities)):
            observed = now - timedelta(seconds=120 - idx * 60)
            rows.append({
                "observed_at": observed.isoformat(timespec="milliseconds"),
                "code": "005930",
                "is_locked": locked,
                "reference_px": reference_px,
                "fid": {"21": observed.strftime("%H%M%S"), "23": px,
                        "24": qty, "121": 100, "125": 120},
            })
        path = m.AUCTION_AUDIT_DIR / f"auction_{datetime.now():%Y%m%d}.jsonl"
        path.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
        current = dict(rows[-1])
        current["fid"] = dict(current["fid"], **{"21": now.strftime("%H%M%S")})
        return current, now

    def test_three_persistent_samples_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, now = self._record(tmp, [100, 101, 102], [1000, 1100, 1200])
            ok, reason = self.mod._auction_gate_decision(record, now=now)
            self.assertTrue(ok, reason)

    def test_falling_expected_price_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, now = self._record(tmp, [102, 101, 100], [1000, 1100, 1200])
            ok, reason = self.mod._auction_gate_decision(record, now=now)
            self.assertFalse(ok)
            self.assertIn("예상체결가 하락", reason)

    def test_before_final_decision_minute_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, now = self._record(tmp, [100, 101, 102], [1000, 1100, 1200])
            now = now.replace(hour=15, minute=26)
            record["fid"]["21"] = now.strftime("%H%M%S")
            ok, reason = self.mod._auction_gate_decision(record, now=now)
            self.assertFalse(ok)
            self.assertIn("지속관측 중", reason)

    @staticmethod
    def _cand(code, score, locked=False, strat_a=False, strat_b=False, value=100):
        return (score, code, code, value, 10000, 0, 0, 0, locked,
                0, True, 0.10, 3.0, 1, True, 0.8, 5.0, strat_a, strat_b)

    def test_portfolio_caps_locked_and_theme_and_keeps_general_lane(self):
        m = self.mod
        cands = [
            self._cand("000001", 90, locked=True),
            self._cand("000002", 100, locked=True),
            self._cand("000003", 95, strat_a=True),
            self._cand("000004", 90, strat_b=True),
            self._cand("000005", 85),
            self._cand("000006", 80),
        ]
        themes = {"000001": "L1", "000002": "L2", "000003": "X",
                  "000004": "X", "000005": "Y", "000006": "Z"}
        picks, tags = m._portfolio_v2_select(cands, themes, {}, set(), 3)
        codes = [c[1] for c in picks]
        self.assertEqual(codes, ["000002", "000003", "000005"])
        self.assertEqual(sum(bool(c[8]) for c in picks), 1)
        self.assertIn("GENERAL", tags["000005"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
