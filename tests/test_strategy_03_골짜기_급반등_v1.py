# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))


from strategy_01_rotation_engine_v2 import kst_now
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
    _minute_opens,
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
        # ★[SPEED-GATE 2026-08-03] 새 규칙에 맞춰 시나리오 교체.
        #   옛 시나리오는 매수가 9,855 = 저점(9,700) 대비 +1.598% 로, 좁아진 매수구간
        #   (+1.0~+1.5%) 밖이라 더는 체결되지 않는다. 60초 관찰도 사라졌다.
        #   새 흐름: 저점 → 1차반등 +1.03% → 눌림(더 높은 저점) → 2차반등 +0.53%
        #            → 저점 +1.13% 에서 매수. 그 사이 매수속도가 매도속도를 앞선다.
        #   앞 3개(10,050/9,900/9,700)는 그대로 둔다 — [:3] 을 쓰는 다른 시험들이 있다.
        return [
            self.point(0, 10_050, 0, 0, ask_px=10_060, bid_px=10_050,
                       ask_qty=110, bid_qty=80),
            self.point(20, 9_900, 100, 500, ask_px=9_910, bid_px=9_900,
                       ask_qty=100, bid_qty=80),
            self.point(40, 9_700, 200, 1_500, ask_px=9_710, bid_px=9_700,
                       ask_qty=100, bid_qty=80),
            # 1차반등 +1.03% → OBSERVE 진입
            self.point(50, 9_800, 300, 1_520, ask_px=9_810, bid_px=9_800,
                       ask_qty=80, bid_qty=120),
            # 눌림 0.43% · 더 높은 저점(원저점 +0.60%)
            self.point(60, 9_758, 400, 1_540, ask_px=9_768, bid_px=9_758,
                       ask_qty=80, bid_qty=120),
            # 2차반등 +0.53% · 저점 후 매수속도가 매도속도를 크게 앞섬 → 매수
            self.point(70, 9_810, 900, 1_600, ask_px=9_820, bid_px=9_810,
                       ask_qty=40, bid_qty=200),
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

    def test_s06_staircase_retest_signals_on_buy_speed_lead(self) -> None:
        """★[SPEED-GATE 2026-08-03] 시간 관찰(60초) 대신 저점 후 매수속도 우위로 판정.

        계단 재테스트 4단계(1차반등·눌림·더높은저점·2차반등)는 그대로 지킨다 —
        신저점 찾기가 이 전략의 핵심이라 버리지 않았다.
        """
        row = self.make_signal()
        self.assertEqual(
            row["reason"],
            "S06_STAIRCASE+PULLBACK+HIGHER_LOW+SECOND_REBOUND+BUY_SPEED_LEAD")
        self.assertEqual(row["dip_low_reset_steps"], 2)
        # 1차 반등 문턱은 1.5 → 1.0 (좁아진 매수구간에 4단계를 넣기 위한 값)
        self.assertGreaterEqual(row["first_rebound_pct"], 1.0)
        # 계단 재테스트 3단계는 종전 그대로 유지된다
        self.assertGreaterEqual(row["pullback_depth_pct"], 0.4)
        self.assertGreaterEqual(row["higher_low_pct"], 0.3)
        self.assertGreaterEqual(row["second_rebound_pct"], 0.5)
        # 매수구간 저점 +1.0~+1.5%
        self.assertGreaterEqual(row["rebound_pct"], 1.0)
        self.assertLessEqual(row["rebound_pct"], 1.5)
        # 판정 근거는 저점 후 매수속도 > 매도속도
        self.assertGreater(row["post_buy_rate"], row["post_sell_rate"])

    def test_no_time_gate_buys_before_sixty_seconds(self) -> None:
        """60초를 채우지 않아도 산다 — 8/3 실전에서 관찰하다 가격이 달아난 문제."""
        row = self.make_signal()
        self.assertLess(row["observe_sec"], 60.0)

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
            43, 9_730, 230, 1_520,
            ask_px=9_740, bid_px=9_730, ask_qty=80, bid_qty=120)
        row = detector.feed(small, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "STAIRCASE_CHASING_LOW")

    def test_above_two_percent_chase_cap_waits_for_new_low(self) -> None:
        detector = RapidReboundDetector()
        for point in self.rapid_points()[:3]:
            detector.feed(point, self.profile, allow_signal=True)
        late = self.point(
            45, 9_900, 300, 1_550,
            ask_px=9_910, bid_px=9_900, ask_qty=80, bid_qty=120)
        row = detector.feed(late, self.profile, allow_signal=True)
        self.assertEqual(row["action"], "WAIT")
        self.assertEqual(row["reason"], "ABOVE_CHASE_CAP")

    def test_new_low_resets_entire_retest_and_counts_stair(self) -> None:
        detector = RapidReboundDetector()
        rows = []
        for point in self.rapid_points()[:3]:
            rows.append(detector.feed(point, self.profile, allow_signal=True))
        self.assertEqual([row["action"] for row in rows], ["ARMED", "RESET", "RESET"])
        self.assertEqual(rows[-1]["reason"], "NEW_LOW_STAIRCASE_RESET")
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
                         ["ARMED", "RESET", "RESET", "OBSERVE"])
        self.assertEqual(rows[-1]["action"], "BUY_READY")
        self.assertEqual(rows[-1]["anchor_low"], 9_700)
        self.assertGreater(rows[-1]["drop_from_open_pct"], -8.0)
        self.assertLessEqual(rows[-1]["drop_from_open_pct"], -4.0)

    def test_exact_minus_8_hands_off_to_s06_and_restore_keeps_it(self) -> None:
        detector = RapidReboundDetector()
        detector.feed(
            self.point(0, 10_050, 0, 0, ask_px=10_060, bid_px=10_050,
                       ask_qty=100, bid_qty=80),
            self.profile,
            allow_signal=True,
        )
        handoff = detector.feed(
            self.point(1, 9_660, 0, 100, ask_px=9_670, bid_px=9_660,
                       ask_qty=100, bid_qty=80),
            self.profile,
            allow_signal=False,
        )
        self.assertEqual(handoff["action"], "DONE")
        self.assertEqual(handoff["reason"], "OPEN_DROP_LE_8PCT_HANDOFF_S06")

        rebound = self.point(
            2, 9_700, 50, 120,
            ask_px=9_710, bid_px=9_700, ask_qty=80, bid_qty=100)
        still_handoff = detector.feed(
            rebound, self.profile, allow_signal=True)
        self.assertEqual(still_handoff["reason"], "OPEN_DROP_LE_8PCT_HANDOFF_S06")

        monitor = RapidReboundMonitor()
        monitor.restore({
            "schema": SIGNAL_SCHEMA,
            "date": self.now.strftime("%Y%m%d"),
            "signals": [],
            "candidates": [{
                "code": "123456",
                "entry_lane": "OPEN_CRASH",
                "reason": "OPEN_DROP_LE_8PCT_HANDOFF_S06",
            }],
        }, self.now.strftime("%Y%m%d"))
        restored, fired = monitor.process_point(
            "123456", "TEST", rebound, self.profile, allow_signal=True)
        self.assertFalse(fired)
        self.assertEqual(restored["reason"], "OPEN_DROP_LE_8PCT_HANDOFF_S06")

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
        self.assertEqual(row["action"], "BUY_READY")
        self.assertGreater(row["post_buy_rate"], row["post_sell_rate"])

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
            price=9_650,
            buy_money_cum=1_010,
            sell_money_cum=1_860,
        )
        handoff = detector.feed(not_deep, self.profile, allow_signal=True)
        self.assertEqual(handoff["reason"], "OPEN_DROP_LE_8PCT_HANDOFF_S06")

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
        handoff = self.signal_payload()
        handoff["signals"][0]["drop_from_open_pct"] = -8.0
        self.assertEqual(
            select_fresh_signals(handoff, now=decision_now, max_age_sec=5), [])

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
                "cur": 9_810,
                "cum_vol": 100_000,
                "buy_money_cum": 1_500,
                "sell_money_cum": 1_650,
                "best_ask_px": 9_820,
                "best_bid_px": 9_810,
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
            engine.tick(datetime.fromisoformat(stamp) + timedelta(seconds=1))
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
            approval.write_text("APPROVED", encoding="utf-8")
            self.assertTrue(broker.real_session)
            self.assertFalse(broker.buy_allowed)
            self.assertEqual(broker.submit(
                side="BUY", code="123456", quantity=1,
                idempotency_key="s03:off"), "BLOCKED")
            self.assertIsNone(broker.client)


if __name__ == "__main__":
    unittest.main()
