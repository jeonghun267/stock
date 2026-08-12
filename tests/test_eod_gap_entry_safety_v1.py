import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import eod_gap_fill_check_v1 as fill_check
import eod_gap_live_executor_v1 as executor


class FakeBroker:
    def send_order_real(self, **kwargs):
        return {"status": "TIMEOUT", "request_id": "test-timeout"}


class EodGapEntrySafetyTests(unittest.TestCase):
    def test_pick_window_closes_at_1520(self):
        self.assertTrue(executor._pick_window_open(datetime(2026, 8, 11, 15, 19, 59)))
        self.assertFalse(executor._pick_window_open(datetime(2026, 8, 11, 15, 20, 0)))

    def test_final_score_gate_blocks_low_score_before_any_order_work(self):
        pick = (69.9, "000001", "LOW", 100.0, 10000.0, 0, 0, 0,
                False, 0, 0, 0, 0, 0)
        old_min = executor.MIN_SCORE
        try:
            executor.MIN_SCORE = 70.0
            self.assertFalse(executor._buy_one(object(), pick, "20260811", {}))
        finally:
            executor.MIN_SCORE = old_min

    def test_timeout_is_not_order_success(self):
        old_live = executor.LIVE
        old_account = executor.ACCOUNT
        try:
            executor.LIVE = True
            executor.ACCOUNT = "12345678"
            with patch.dict("os.environ", {"EODGAP_LEADER_BOARD": "NO"}), \
                    patch.object(executor, "_log"):
                self.assertFalse(executor._order(FakeBroker(), "000001", 1, "BUY", "TEST"))
            self.assertEqual(executor.LAST_ORDER_STATUS, "TIMEOUT")
        finally:
            executor.LIVE = old_live
            executor.ACCOUNT = old_account

    def test_empty_live_board_never_calls_stale_fallback(self):
        with patch.object(executor, "_pick_window_open", return_value=True), \
                patch.object(executor, "_jload", return_value={}), \
                patch.object(executor, "_broker", return_value=object()), \
                patch.object(executor, "_opt10032_top", return_value=[]), \
                patch.object(executor, "_board_fallback_top") as fallback, \
                patch.object(executor, "_log"):
            executor.mode_pick()
        fallback.assert_not_called()

    def test_live_board_cache_accepts_only_same_day_two_minutes(self):
        now = datetime(2026, 8, 12, 15, 18, 0)
        fresh = {
            "date": "20260812",
            "captured_at": (now - timedelta(seconds=119)).isoformat(),
            "rows": [["000001", "TEST", 123.0]],
        }
        stale = dict(fresh, captured_at=(now - timedelta(seconds=121)).isoformat())
        wrong_day = dict(fresh, date="20260811")
        with patch.object(executor, "_jload", return_value=fresh):
            self.assertEqual(executor._load_fresh_live_board_cache(now), [("000001", "TEST", 123.0)])
        with patch.object(executor, "_jload", return_value=stale):
            self.assertEqual(executor._load_fresh_live_board_cache(now), [])
        with patch.object(executor, "_jload", return_value=wrong_day):
            self.assertEqual(executor._load_fresh_live_board_cache(now), [])

    def test_live_board_cache_fallback_defaults_to_disabled(self):
        self.assertFalse(executor.LIVE_BOARD_CACHE_FALLBACK)

    def test_balance_confirmation_promotes_pending_to_open(self):
        base = Path(r"C:\stock_bot\tests") / f"_tmp_eod_gap_{uuid.uuid4().hex}"
        try:
            pos_path = base / "DATA" / "eod_gap_positions.json"
            pos_path.parent.mkdir(parents=True)
            pos_path.write_text(json.dumps({
                "000001": {
                    "code": "000001", "name": "TEST", "qty": 1,
                    "buy_price": 10000, "status": "PENDING", "live": True,
                }
            }), encoding="utf-8")
            with patch.object(fill_check, "_fetch_balance", return_value={"000001": 1}), \
                    patch.object(fill_check, "_log"):
                fill_check.run_check(base, apply=True)
            saved = json.loads(pos_path.read_text(encoding="utf-8"))
            rt = json.loads((base / "DATA" / "rt_open_positions.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["000001"]["status"], "OPEN")
            self.assertEqual(rt["000001"]["strategy"], "EOD_GAP")
        finally:
            for path in (base / "DATA" / "rt_open_positions.json",
                         base / "DATA" / "eod_gap_positions.json"):
                path.unlink(missing_ok=True)
            if (base / "DATA").exists():
                (base / "DATA").rmdir()
            if base.exists():
                base.rmdir()


if __name__ == "__main__":
    unittest.main()
