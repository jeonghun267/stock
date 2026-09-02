# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
import unittest.mock
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))


from strategy_01_rotation_engine_v2 import kst_now
import strategy_03_rotation_engine_v1 as s03_rotation
from strategy_03_rotation_engine_v1 import (
    Strategy03Engine,
    Strategy03HoldSellEngine,
    build_config,
    make_strategy03_signal_selector,
)
from strategy_03_signal_contract_v1 import (
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
    STRATEGY_ID,
    select_fresh_signals,
)
from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
    UnifiedHoldSellEngine,
)
from strategy_common_order_v1 import StrategyBroker
from 골짜기_급반등 import (
    MicroPoint,
    PriorProfile,
    RapidReboundDetector,
    RapidReboundMonitor,
    SignalConfig,
    load_live_points,
    load_prior_profile_universe,
    _minute_opens,
    _strategy03_board_codes,
)


class FakeSlots:
    def __init__(self) -> None:
        self.owned: set[str] = set()

    def acquire(self, code: str, _owner: str, _day: str) -> bool:
        if code in self.owned:
            return False
        self.owned.add(code)
        return True

    def release(self, code: str, _day: str) -> None:
        self.owned.discard(code)


class FakeBroker:
    real_session = False
    buy_allowed = False
    mode = "SHADOW"
    last_error = ""

    def __init__(self) -> None:
        self.submissions: list[dict] = []

    def holdings(self):
        return {}

    def open_orders(self, _code: str, *, buy: bool):
        return {}

    def submit(self, **kwargs):
        self.submissions.append(dict(kwargs))
        return "SHADOW"

    def cancel(self, **_kwargs):
        return "SHADOW"


class Strategy03RapidReboundTests(unittest.TestCase):
    def setUp(self) -> None:
        # ★[2026-07-31] 장초 급락 레인 진입창이 09:00 → 09:02 로 바뀌어(친구님 지시
        #   "3번 급락이 9시 2분부터") 기준 시각을 창 안으로 옮긴다. 09:00 이면 창 밖이라
        #   계약 검사가 모든 신호를 걸러 테스트가 통째로 실패한다.
        self.now = kst_now().replace(
            hour=9, minute=5, second=0, microsecond=0)
        self.profile = PriorProfile(
            previous_close=10_500,
            previous_value=20_000,
            previous_range_pct=8.0,
            previous_close_position=0.7,
        )

    def test_prior_profile_universe_loads_multiple_dates_in_one_scan(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "eod.csv"
            path.write_text(
                "date,code,open,high,low,close,value\n"
                "20260809,123456,100,120,90,110,1000\n"
                "20260810,123456,110,130,100,120,2000\n"
                "20260810,654321,200,230,180,220,3000\n",
                encoding="utf-8",
            )

            universe = load_prior_profile_universe(
                path,
                source_dates={"20260809", "20260810"},
            )

        self.assertEqual(len(universe), 3)
        self.assertEqual(universe[("20260810", "123456")].previous_close, 120)
        self.assertEqual(universe[("20260810", "654321")].previous_value, 3000)

    def point(
        self,
        second: int,
        price: float,
        buy: float,
        sell: float,
        *,
        ask_px: float,
        bid_px: float,
        ask_qty: float,
        bid_qty: float,
    ) -> MicroPoint:
        return MicroPoint(
            ts=(self.now + timedelta(seconds=second)).replace(tzinfo=None),
            price=price,
            open_price=10_500,
            buy_money_cum=buy,
            sell_money_cum=sell,
            che_str=100,
            best_ask_px=ask_px,
            best_bid_px=bid_px,
            best_ask_qty=ask_qty,
            best_bid_qty=bid_qty,
        )

    def rapid_points(self) -> list[MicroPoint]:
        # -4%~-8% 미만에서 신저점을 계속 갱신한 뒤 매도속도 2단 감속,
        # 연속 2틱 상승, 매도호가 2회 감소를 확인해 +1~2%에서 진입한다.
        return [
            self.point(0, 10_050, 0, 0, ask_px=10_060, bid_px=10_050,
                       ask_qty=500, bid_qty=1_000),
            self.point(20, 9_950, 100, 500, ask_px=9_960, bid_px=9_950,
                       ask_qty=400, bid_qty=1_000),
            self.point(40, 9_900, 200, 1_500, ask_px=9_910, bid_px=9_900,
                       ask_qty=300, bid_qty=1_000),
            self.point(50, 9_950, 205, 1_700, ask_px=9_960, bid_px=9_950,
                       ask_qty=200, bid_qty=1_000),
            self.point(60, 10_020, 210, 1_800, ask_px=10_030, bid_px=10_020,
                       ask_qty=100, bid_qty=1_000),
        ]

    def make_signal(self) -> dict:
        detector = RapidReboundDetector()
        row = {}
        for point in self.rapid_points():
            row = detector.feed(point, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "BUY_READY")
        row.update({
            "code": "123456",
            "name": "TEST",
            "signal_sequence": 1,
            "anchor_id": (
                f"{row['anchor_low_ts']}:{float(row['anchor_low']):.4f}"),
        })
        return row

    def signal_payload(self) -> dict:
        row = self.make_signal()
        return {
            "schema": SIGNAL_SCHEMA,
            "date": self.now.strftime("%Y%m%d"),
            "updated_at": row["ts"],
            "mode": SIGNAL_MODE,
            "signals": [row],
        }

    def test_open_seller_exhaustion_direct_enters_without_buy_dominance(self) -> None:
        row = self.make_signal()
        self.assertEqual(row["reason"], "S03_OPEN_SELLER_EXHAUSTION_DIRECT")
        self.assertEqual(row["dip_low_reset_steps"], 2)
        self.assertGreaterEqual(row["rebound_pct"], 1.0)
        self.assertLessEqual(row["rebound_pct"], 2.0)
        self.assertTrue(row["seller_exhaustion_fast"]["ready"])
        self.assertLess(row["post_buy_rate"], row["post_sell_rate"])

    def test_no_time_gate_buys_before_sixty_seconds(self) -> None:
        """60초를 채우지 않아도 산다 — 8/3 실전에서 관찰하다 가격이 달아난 문제."""
        row = self.make_signal()
        self.assertLess(row["dip_flow_obs_sec"], 60.0)

    def test_flow_flip_and_accel_are_recorded_not_gates(self) -> None:
        """흐름 자료가 비어도 매수가 막히지 않는다(8/3 fail-closed 로 하루 0건).

        pre_rate·flow_accel 은 저점 '전' 자료나 10초 구간 2개가 필요해 실전에서
        99% 가 빈 값이었다. 기록은 남기되 관문에서는 뺐다.
        """
        row = self.make_signal()
        self.assertEqual(row["action"], "BUY_READY")
        self.assertIn("flow_flip", row)
        self.assertIn("flow_accel", row)

    def test_no_minimum_money_condition(self) -> None:
        row = self.make_signal()
        self.assertLess(row["buy_money_since_low"] + row["sell_money_since_low"], 10_000_000)
        self.assertEqual(row["action"], "BUY_READY")

    def test_old_three_second_small_rebound_never_buys(self) -> None:
        detector = RapidReboundDetector()
        for point in self.rapid_points()[:3]:
            detector.feed(point, self.profile, allow_signal=True)
        small = self.point(
            43, 9_940, 230, 1_520,
            ask_px=9_950, bid_px=9_940, ask_qty=80, bid_qty=120)
        row = detector.feed(small, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "OPEN_DIRECT_REBOUND_ENTRY_RANGE_WAIT")

    def test_above_two_percent_chase_cap_waits_for_new_low(self) -> None:
        detector = RapidReboundDetector()
        for point in self.rapid_points()[:3]:
            detector.feed(point, self.profile, allow_signal=True)
        late = self.point(
            45, 10_110, 300, 1_550,
            ask_px=10_120, bid_px=10_110, ask_qty=80, bid_qty=120)
        row = detector.feed(late, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "ABOVE_CHASE_CAP")

    def test_new_low_resets_entire_retest_and_counts_stair(self) -> None:
        detector = RapidReboundDetector()
        rows = []
        for point in self.rapid_points()[:3]:
            rows.append(detector.feed(point, self.profile, allow_signal=True))
        self.assertEqual([row["action"] for row in rows], ["ARMED", "RESET", "RESET"])
        self.assertEqual(rows[-1]["reason"], "OPEN_NEW_LOW_RESET")
        self.assertEqual(rows[-1]["dip_low_reset_steps"], 2)

    def test_open_drop_uses_open_price_and_missing_open_fails_closed(self) -> None:
        different_close = replace(self.profile, previous_close=11_000)
        detector = RapidReboundDetector()
        above_band = self.point(
            0, 10_100, 0, 0,
            ask_px=10_110, bid_px=10_100, ask_qty=100, bid_qty=80)
        row = detector.feed(above_band, different_close, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "OPEN_DROP_GT_4PCT")

        armed = self.point(
            1, 10_000, 0, 100,
            ask_px=10_010, bid_px=10_000, ask_qty=100, bid_qty=80)
        row = detector.feed(armed, different_close, allow_signal=True)
        self.assertEqual(row["action"], "ARMED")
        self.assertAlmostEqual(row["drop_from_open_pct"], -4.7619, places=4)

        missing_open = replace(above_band, open_price=0)
        row = RapidReboundDetector().feed(
            missing_open, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "OPEN_PRICE_MISSING")

    def test_stair_step_decline_uses_final_low_then_signals(self) -> None:
        detector = RapidReboundDetector()
        rows = [detector.feed(point, self.profile, allow_signal=True)
                for point in self.rapid_points()]
        self.assertEqual([row["action"] for row in rows[:4]],
                         ["ARMED", "RESET", "RESET", "WAIT"])
        self.assertEqual(rows[-1]["action"], "BUY_READY")
        self.assertEqual(rows[-1]["anchor_low"], 9_900)
        self.assertTrue(rows[-1]["s03_first_seen_ts"])
        self.assertTrue(rows[-1]["stable_pass_ts"])
        self.assertTrue(rows[-1]["signal_ts"])
        self.assertLessEqual(
            datetime.fromisoformat(rows[-1]["stable_pass_ts"]),
            datetime.fromisoformat(rows[-1]["signal_ts"]),
        )
        self.assertGreater(rows[-1]["drop_from_open_pct"], -8.0)
        self.assertLessEqual(rows[-1]["drop_from_open_pct"], -4.0)

    def test_minus_8_or_deeper_remains_in_s03_open_crash(self) -> None:
        detector = RapidReboundDetector()
        detector.feed(
            self.point(0, 10_050, 0, 0, ask_px=10_060, bid_px=10_050,
                       ask_qty=100, bid_qty=80),
            self.profile,
            allow_signal=True,
        )
        deep = detector.feed(
            self.point(1, 9_660, 0, 100, ask_px=9_670, bid_px=9_660,
                       ask_qty=100, bid_qty=80),
            self.profile,
            allow_signal=True,
        )
        self.assertEqual(deep["action"], "RESET")
        self.assertEqual(deep["reason"], "OPEN_NEW_LOW_RESET")
        self.assertLessEqual(deep["anchor_drop_from_open_pct"], -8.0)

    def test_buy_ready_fails_closed_when_priority_claim_is_not_held(self) -> None:
        monitor = RapidReboundMonitor()
        row = {}
        fired = False
        with (
            unittest.mock.patch(
                "골짜기_급반등.crash_claim.enabled", return_value=True),
            unittest.mock.patch(
                "골짜기_급반등.crash_claim.try_claim_s03",
                return_value="ERROR",
            ),
        ):
            for point in self.rapid_points():
                row, fired = monitor.process_point(
                    "123456", "TEST", point, self.profile, allow_signal=True)

        self.assertFalse(fired)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "S03_CRASH_CLAIM_NOT_HELD")

    def test_two_tick_sell_reacceleration_discards_low(self) -> None:
        detector = RapidReboundDetector()
        rows = [
            self.point(0, 10_050, 0, 0, ask_px=10_060, bid_px=10_050,
                       ask_qty=500, bid_qty=1_000),
            self.point(20, 9_950, 100, 500, ask_px=9_960, bid_px=9_950,
                       ask_qty=400, bid_qty=1_000),
            self.point(40, 9_900, 200, 1_500, ask_px=9_910, bid_px=9_900,
                       ask_qty=300, bid_qty=1_000),
            self.point(50, 10_000, 220, 1_600, ask_px=10_010, bid_px=10_000,
                       ask_qty=250, bid_qty=1_000),
            self.point(60, 10_050, 230, 1_800, ask_px=10_060, bid_px=10_050,
                       ask_qty=200, bid_qty=1_000),
            self.point(70, 10_080, 235, 2_200, ask_px=10_090, bid_px=10_080,
                       ask_qty=150, bid_qty=1_000),
        ]
        row = {}
        for point in rows:
            row = detector.feed(point, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(
            row["reason"], "SELL_REACCEL_BUY_WEAK_2TICKS_WAIT_NEW_LOW")

    def test_minute_open_requires_today_and_positive_price(self) -> None:
        today = self.now.strftime("%Y%m%d")
        payload = {
            "ts": self.now.isoformat(),
            "m": {
                "123456": {"op": "10,500"},
                "654321": {"op": 0},
            },
        }
        self.assertEqual(_minute_opens(payload, today), {"123456": 10_500.0})
        self.assertEqual(_minute_opens(payload, "19990101"), {})

    def test_board_universe_is_high_range_plus_moneyflow_dump(self) -> None:
        day = self.now.strftime("%Y%m%d")
        high_range = {
            "schema_version": 2,
            "for_date": day,
            "source_stale": False,
            "candidates": [
                {"rank": 1, "code": "123456"},
                {"rank": 2, "code": "234567"},
            ],
        }
        moneyflow = {
            "ts": self.now.isoformat(),
            "rows": [
                {"code": "345678", "grade": "🔴던짐"},
                {"code": "456789", "grade": "🔵매도세"},
                {"code": "567890", "grade": "🟢매수세"},
            ],
        }
        self.assertEqual(
            _strategy03_board_codes(high_range, moneyflow, day),
            {"123456", "234567", "345678", "456789"},
        )
        self.assertNotIn(
            "567890",
            _strategy03_board_codes(high_range, moneyflow, day),
        )

    def test_open_lane_keeps_tracking_below_absolute_min_price(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot_path = root / "snapshot.json"
            names_path = root / "names.json"
            now = self.now.replace(tzinfo=None)
            stamp = now.isoformat()
            snapshot_path.write_text(json.dumps({"codes": {"123456": {
                "ts": stamp,
                "ob_ts": stamp,
                "cur": 9_700,
                "buy_money_cum": 100,
                "sell_money_cum": 200,
            }}}), encoding="utf-8")
            names_path.write_text("{}", encoding="utf-8")
            config = replace(
                SignalConfig(),
                snapshot_path=snapshot_path,
                names_path=names_path,
                min_price=10_000,
            )
            kwargs = {
                "now": now,
                "watch": {
                    "for_date": now.strftime("%Y%m%d"),
                    "codes": ["123456"],
                },
                "profiles": {"123456": self.profile},
                "opens": {"123456": 10_500},
            }
            points, status = load_live_points(
                config, open_codes={"123456"}, **kwargs)
            self.assertEqual(status, "LIVE")
            self.assertEqual(len(points), 1)
            self.assertEqual(points[0][2].price, 9_700)

            intraday_points, intraday_status = load_live_points(
                config, open_codes=set(), **kwargs)
            self.assertEqual(intraday_points, [])
            self.assertEqual(intraday_status, "DATA_WAIT")

    def test_missing_top_book_still_buys_on_buy_speed_lead(self) -> None:
        """호가가 통째로 없어도 매수 판정은 저점 후 속도로 이뤄진다.

        ★[SPEED-GATE 2026-08-03] 종전에는 flow_flip·flow_accel 이 "O" 여야 했으나
        그 둘은 관문에서 빠졌다(8/3 실전에서 99% 가 빈 값이라 하루 0건). 이 시험의
        요지는 "호가 부재가 매수를 막지 않는다" 이고, 그 요지는 그대로다.
        """
        detector = RapidReboundDetector()
        row = {}
        for point in self.rapid_points():
            row = detector.feed(replace(
                point, best_ask_px=0, best_bid_px=0,
                best_ask_qty=0, best_bid_qty=0),
                self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "OPEN_SELLER_EXHAUSTION_WAIT")

    def test_cumulative_reverse_resets(self) -> None:
        detector = RapidReboundDetector()
        for point in self.rapid_points()[:2]:
            detector.feed(point, self.profile, allow_signal=True)
        reversed_point = self.point(
            30, 9_850, 0, 490,
            ask_px=9_860, bid_px=9_850, ask_qty=90, bid_qty=100)
        row = detector.feed(reversed_point, self.profile, allow_signal=True)
        self.assertEqual(row["reason"], "CUMULATIVE_REVERSE_RESET")

    def test_time_gate_and_second_chance_require_one_percent_deeper_low(self) -> None:
        detector = RapidReboundDetector()
        late = replace(
            self.rapid_points()[1],
            ts=self.now.replace(hour=14, minute=30, second=0, tzinfo=None),
        )
        row = detector.feed(late, self.profile, allow_signal=False)
        self.assertEqual(row["reason"], "ENTRY_TIME_CLOSED")

        detector = RapidReboundDetector()
        for point in self.rapid_points():
            row = detector.feed(point, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "BUY_READY")
        not_deep = replace(
            self.rapid_points()[-1],
            ts=self.rapid_points()[-1].ts + timedelta(seconds=1),
            price=9_850,
            buy_money_cum=1_010,
            sell_money_cum=1_860,
        )
        # ★[S03-EXPRESS 2026-08-06] 종전엔 이 지점(-8.1%)이 인계로 끝났지만,
        #   인계 폐지 후엔 재무장 규칙이 직접 판정한다 — 1% 더 깊어야 두 번째 기회.
        second_chance = detector.feed(not_deep, self.profile, allow_signal=True)
        self.assertEqual(
            second_chance["reason"], "SECOND_CHANCE_REQUIRES_1PCT_DEEPER_LOW")

    def test_contract_accepts_only_one_fresh_s03_signal(self) -> None:
        payload = self.signal_payload()
        payload["signals"].append(dict(payload["signals"][0]))
        decision_now = (
            datetime.fromisoformat(payload["updated_at"]) + timedelta(seconds=2))
        rows = select_fresh_signals(
            payload, now=decision_now, max_age_sec=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_id"], STRATEGY_ID)
        stale = self.signal_payload()
        stale["updated_at"] = (
            self.now - timedelta(seconds=20)).replace(
                tzinfo=None).isoformat()
        self.assertEqual(
            select_fresh_signals(stale, now=decision_now, max_age_sec=5), [])
        # -8% 이상도 이제 OPEN_CRASH 소유이므로 계약이 통과시킨다.
        deep = self.signal_payload()
        deep["signals"][0]["anchor_drop_from_open_pct"] = -8.0
        self.assertEqual(len(select_fresh_signals(
            deep, now=decision_now, max_age_sec=5)), 1)
        deeper = self.signal_payload()
        deeper["signals"][0]["anchor_drop_from_open_pct"] = -12.5
        self.assertEqual(len(select_fresh_signals(
            deeper, now=decision_now, max_age_sec=5)), 1)

    def test_only_open_and_intraday_lanes_survive_contract_and_restore(self) -> None:
        payload = self.signal_payload()
        early = dict(payload["signals"][0])
        early.update({
            "code": "654321",
            "entry_lane": "EARLY_LOW",
            "algorithm": "S03_EARLY_60S_REBOUND_V1",
        })
        payload["signals"].insert(0, early)
        decision_now = (
            datetime.fromisoformat(payload["updated_at"]) + timedelta(seconds=1)
        )

        selected = select_fresh_signals(
            payload, now=decision_now, max_age_sec=5
        )
        self.assertEqual(
            {row["entry_lane"] for row in selected}, {"OPEN_CRASH"}
        )

        monitor = RapidReboundMonitor()
        monitor.restore(payload, self.now.strftime("%Y%m%d"))
        self.assertEqual(
            {row["entry_lane"] for row in monitor.signals}, {"OPEN_CRASH"}
        )

    def test_order_recheck_blocks_chase_and_fresh_sell_dominance(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            snapshot_path = Path(folder) / "snapshot.json"
            payload = self.signal_payload()
            stamp = payload["updated_at"]
            decision_now = datetime.fromisoformat(stamp) + timedelta(seconds=1)
            selector = make_strategy03_signal_selector(snapshot_path, 4.0)

            snapshot_path.write_text(json.dumps({"codes": {"123456": {
                "ts": stamp,
                "ob_ts": stamp,
                "cur": 10_090,
                "buy_money_cum": 270,
                "sell_money_cum": 460,
                "best_ask_px": 10_100,
                "best_bid_px": 10_090,
                "best_ask_qty": 40,
                "best_bid_qty": 200,
            }}}), encoding="utf-8")
            self.assertEqual(
                selector(payload, now=decision_now, max_age_sec=5), [])

            later_stamp = decision_now.isoformat()
            snapshot_path.write_text(json.dumps({"codes": {"123456": {
                "ts": later_stamp,
                "ob_ts": later_stamp,
                "cur": 10_040,
                "buy_money_cum": 280,
                "sell_money_cum": 480,
                "best_ask_px": 10_050,
                "best_bid_px": 10_040,
                "best_ask_qty": 40,
                "best_bid_qty": 200,
            }}}), encoding="utf-8")
            self.assertEqual(
                selector(payload, now=decision_now, max_age_sec=5), [])

    def test_signal_routes_to_common_shadow_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = build_config()
            config = replace(
                base,
                signal_path=root / "signal.json",
                snapshot_path=root / "snapshot.json",
                board_path=root / "board.json",
                bars_path=root / "bars.json",
                names_path=root / "names.json",
                state_path=root / "state.json",
                fills_dir=root / "fills",
                event_dir=root / "events",
                log_path=root / "engine.log",
                approval_path=root / "approved.flag",
                off_flag_path=root / "off.flag",
                manual_buy_block_path=root / "manual.flag",
                lock_path=root / "engine.lock",
                live_requested=False,
            )
            payload = self.signal_payload()
            stamp = payload["updated_at"]
            config.signal_path.write_text(
                json.dumps(payload), encoding="utf-8")
            # ★[SPEED-GATE 2026-08-03] 주문 시점 스냅샷도 새 규칙에 맞춘다.
            #   cur 9,855 는 저점(9,700) 대비 +1.598% 로 좁아진 매수구간(+1.0~1.5%) 밖이라
            #   매매엔진이 거른다. 그리고 엔진은 신호 이후 매수증가 > 매도증가도 요구하는데
            #   옛 값은 매수 +100 vs 매도 +250 으로 매도가 더 컸다.
            config.snapshot_path.write_text(json.dumps({"codes": {"123456": {
                "ts": stamp,
                "ob_ts": stamp,
                "cur": 10_020,
                "cum_vol": 100_000,
                "buy_money_cum": 220,
                "sell_money_cum": 1_805,
                "best_ask_px": 10_030,
                "best_bid_px": 10_020,
                "best_ask_qty": 40,
                "best_bid_qty": 200,
            }}}), encoding="utf-8")
            config.board_path.write_text(json.dumps({
                "ts": stamp,
                "all_items": [{
                    "code": "123456",
                    "money_speed_5s": 2_000_000,
                    "money_speed_10s": 1_800_000,
                    "money_speed_30s": 1_500_000,
                }],
            }), encoding="utf-8")
            config.bars_path.write_text("{}", encoding="utf-8")
            config.names_path.write_text("{}", encoding="utf-8")
            broker = FakeBroker()
            slots = FakeSlots()
            logger = logging.getLogger("strategy03-test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            engine = Strategy03Engine(
                config,
                broker=broker,
                slots=slots,
                logger=logger,
                signal_selector=make_strategy03_signal_selector(
                    config.snapshot_path, config.snapshot_max_age_sec),
            )
            # ★[PRICE-FLOOR-FIXTURE 2026-08-26] 이 테스트의 목적은 신호→회전
            #   라우팅이다. 공유 픽스처가 9,700원대라 나중에 생긴 실전 하한
            #   S03_ORDER_MIN_PRICE(1만원)에 걸려 0건이 되므로, 여기서만 하한을
            #   픽스처 아래로 내려 라우팅만 검증한다(하한 게이트 동작 자체는
            #   실전 드롭로그 S03_PRICE_BELOW_10000 으로 별도 확인).
            with unittest.mock.patch.object(
                    s03_rotation, "S03_ORDER_MIN_PRICE", 9_000.0):
                engine.tick(
                    datetime.fromisoformat(stamp) + timedelta(seconds=1))
            self.assertEqual(len(broker.submissions), 1)
            self.assertEqual(config.slot_owner, "STRATEGY03")
            self.assertEqual(config.max_daily_codes, 6)
            self.assertEqual(config.max_cycles_per_code, 2)
            position = engine._active_positions()["123456"]
            self.assertEqual(
                position["hold_state"]["strategy_id"],
                StrategyId.VALLEY_MORNING_CRASH.value,
            )
            self.assertTrue(
                broker.submissions[0]["idempotency_key"].startswith(
                    "strategy03:"))

    def test_0930_exit_cancel_is_local_to_s03(self) -> None:
        state = HoldSellState(
            position_id="s03:test",
            strategy_id=StrategyId.VALLEY_MORNING_CRASH,
            code="123456",
            quantity=1,
            entry_price=Decimal("10000"),
            entry_at=self.now + timedelta(minutes=5),
        )
        observation = HoldSellObservation(
            observed_at=self.now.replace(
                hour=9, minute=31, second=0),
            price=Decimal("10100"),
            buy_ratio_recent=Decimal("0.80"),
            structure_broken=False,
        )
        s03_decision = Strategy03HoldSellEngine().evaluate(
            state, observation)
        self.assertEqual(s03_decision.action, HoldSellAction.HOLD)

        original_state = HoldSellState(
            position_id="old-valley:test",
            strategy_id=StrategyId.VALLEY_MORNING_CRASH,
            code="654321",
            quantity=1,
            entry_price=Decimal("10000"),
            entry_at=self.now + timedelta(minutes=5),
        )
        original = UnifiedHoldSellEngine().evaluate(
            original_state, observation)
        self.assertTrue(original.should_sell)

    def test_live_buy_requires_approval_and_off_removed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off = root / "off.flag"
            approval = root / "approval.flag"
            off.write_text("OFF", encoding="utf-8")
            logger = logging.getLogger("strategy03-safety")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            broker = StrategyBroker(
                live_requested=True,
                approval_path=approval,
                off_flag_path=off,
                manual_buy_block_path=root / "manual.flag",
                logger=logger,
                order_prefix="STRATEGY03",
            )
            self.assertFalse(broker.real_session)
            self.assertEqual(broker.submit(
                side="BUY", code="123456", quantity=1,
                idempotency_key="s03:no-approval"), "SHADOW")
            approval.write_text(
                f"APPROVED_BY_OWNER {datetime.now():%Y%m%d %H:%M:%S}\n",
                encoding="ascii")
            self.assertTrue(broker.real_session)
            self.assertFalse(broker.buy_allowed)
            self.assertEqual(broker.submit(
                side="BUY", code="123456", quantity=1,
                idempotency_key="s03:off"), "BLOCKED")
            self.assertIsNone(broker.client)


if __name__ == "__main__":
    unittest.main()
