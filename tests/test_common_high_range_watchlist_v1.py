# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
sys.path.insert(0, str(RUN_DIR))

from common_high_range_watchlist_v1 import build_and_publish, select_candidates
from high_range_live_board_v1 import render_html, run_once, update_live_state


DATES = [f"202607{day:02d}" for day in range(20, 26)]


def _stock_rows(code, name, q_count, value_eok, close=20_000):
    rows = []
    for index, date in enumerate(DATES):
        qualified = index >= len(DATES) - q_count
        low = close * (0.98 if qualified else 1.0)
        high = low * (1.12 if qualified else 1.05)
        rows.append(
            {
                "date": date,
                "code": code,
                "name": name,
                "low": low,
                "high": high,
                "close": close,
                "value": value_eok * 100 if qualified else 5_000,
            }
        )
    return rows


class HighRangeWatchlistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        (self.base / "IPC").mkdir()
        rows = []
        rows += _stock_rows("000001", "핵심", 5, 600)
        rows += _stock_rows("000002", "확인", 5, 200)
        rows += _stock_rows("000003", "선발", 3, 300)
        rows += _stock_rows("000004", "신규", 1, 700)
        rows += _stock_rows("000005", "저가제외", 5, 900, close=9_000)
        self.eod = self.base / "data" / "eod_daily_bars.csv"
        pd.DataFrame(rows).to_csv(self.eod, index=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_stage_crown_and_price_filter(self):
        source_date, rows = select_candidates(self.eod)
        self.assertEqual(source_date, DATES[-1])
        self.assertEqual([row["code"] for row in rows], ["000001", "000002", "000003", "000004"])
        self.assertEqual(
            [row["stage"] for row in rows],
            ["핵심확인대", "확인대", "선발대", "신규대"],
        )
        self.assertEqual([row["crown"] for row in rows], [True, False, False, False])

    def test_publish_includes_transaction_values_and_watch_file(self):
        now = datetime(2026, 7, 27, 8, 40)
        payload = build_and_publish(self.base, self.eod, now)
        self.assertEqual(payload["candidate_count"], 4)
        self.assertEqual(payload["crown_count"], 1)
        self.assertEqual(payload["candidates"][0]["prev_value_eok"], 600.0)
        csv_text = (self.base / "data" / "common_high_range_top30.csv").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("전일거래대금_억원", csv_text)
        watch = json.loads(
            (self.base / "IPC" / "micro_watch_high_range.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(watch["codes"], ["000001", "000002", "000003", "000004"])
        self.assertEqual(watch["crown_codes"], ["000001"])
        self.assertEqual(watch["crown_priority_codes"], ["000001"])
        self.assertEqual(payload["filters"]["core_priority_min_5d_range_pct"], 12.0)

    def test_live_low_high_and_rebound_are_ordered(self):
        candidate = {
            "code": "000001",
            "name": "핵심",
            "rank": 1,
            "crown": True,
            "prev_close": 100.0,
        }
        state = {}
        for minute, current in [(1, 110), (2, 105), (3, 112)]:
            now = datetime(2026, 7, 27, 9, minute)
            snapshot = {
                "codes": {
                    "000001": {
                        "cur": current,
                        "ts": now.isoformat(),
                        "buy_money_cum": 600_000_000,
                        "sell_money_cum": 400_000_000,
                        "che_str": 120,
                    }
                }
            }
            state = update_live_state([candidate], snapshot, state, now)
        live = state["codes"]["000001"]
        self.assertEqual(live["low"], 105)
        self.assertEqual(live["low_time"], "09:02:00")
        self.assertEqual(live["high"], 112)
        self.assertEqual(live["later_high"], 112)
        self.assertEqual(live["live_value_eok"], 10.0)
        self.assertEqual(live["buy_ratio_pct"], 60.0)

    def test_stale_snapshot_does_not_create_false_extrema(self):
        now = datetime(2026, 7, 27, 9, 1)
        snapshot = {
            "codes": {
                "000001": {
                    "cur": 110,
                    "ts": (now - timedelta(minutes=1)).isoformat(),
                }
            }
        }
        state = update_live_state([{"code": "000001"}], snapshot, {}, now)
        self.assertEqual(state["codes"]["000001"]["status"], "STALE")
        self.assertNotIn("low", state["codes"]["000001"])

    def test_run_once_writes_large_desktop_board_without_orders(self):
        now = datetime(2026, 7, 27, 9, 1)
        build_and_publish(self.base, self.eod, now)
        (self.base / "IPC" / "live_micro_snapshot.json").write_text(
            json.dumps(
                {
                    "codes": {
                        "000001": {
                            "cur": 21_000,
                            "ts": now.isoformat(),
                            "buy_money_cum": 800_000_000,
                            "sell_money_cum": 200_000_000,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        desktop = self.base / "Desktop"
        payload, state, html_path = run_once(self.base, desktop, now)
        self.assertEqual(payload["candidate_count"], 4)
        self.assertEqual(state["codes"]["000001"]["status"], "LIVE")
        board = html_path.read_text(encoding="utf-8")
        self.assertIn("전일대금", board)
        self.assertIn("실시간대금", board)
        self.assertIn("주문 0 관찰모드", board)

    def test_html_identifies_crown_as_observation_not_buy_signal(self):
        payload = build_and_publish(
            self.base, self.eod, datetime(2026, 7, 27, 8, 40)
        )
        board = render_html(payload, {"codes": {}}, datetime(2026, 7, 27, 8, 40))
        self.assertIn("👑고저폭", board)
        self.assertIn("왕관은 매수신호가 아니며", board)


if __name__ == "__main__":
    unittest.main()
