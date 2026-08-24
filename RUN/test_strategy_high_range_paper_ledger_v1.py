import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from strategy_high_range_paper_ledger_v1 import PaperLedger


class PaperLedgerTest(unittest.TestCase):
    def test_opens_order_zero_virtual_position(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            (root / "IPC").mkdir()
            (root / "data" / "common_high_range_top30.json").write_text(
                json.dumps({"for_date": "20260821", "candidates": [{"code": "1", "rank": 1}]}), encoding="utf-8")
            (root / "data" / "common_high_range_live_state.json").write_text(
                json.dumps({"date": "20260821", "codes": {"000001": {"status": "LIVE"}}}), encoding="utf-8")
            (root / "data" / "strategy_01_open_surge_signal_v2.json").write_text(
                json.dumps({"signals": [{"ts": "2026-08-21T09:01:00", "code": "1", "price": 1000, "action": "BUY_READY"}]}), encoding="utf-8")
            (root / "IPC" / "live_micro_snapshot.json").write_text(
                json.dumps({"codes": {"000001": {"cur": 1000, "best_ask_px": 1001, "best_bid_px": 1000}}}), encoding="utf-8")
            ledger = PaperLedger(root)
            events = ledger.process_once(datetime(2026, 8, 21, 9, 1, 1))
            buys = [row for row in events if row["event"] == "VIRTUAL_BUY"]
            self.assertEqual(len(buys), 1)
            self.assertEqual(buys[0]["order_qty"], 0)
            self.assertFalse(buys[0]["live_eligible"])


if __name__ == "__main__":
    unittest.main()
