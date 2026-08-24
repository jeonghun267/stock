# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_01_rotation_engine_v2 import kst_now
from strategy_03_rotation_engine_v1 import (
    Strategy03Engine,
    Strategy03HoldSellEngine,
    build_config,
)
from strategy_common_hold_sell_v1 import (
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    StrategyId,
)


class Strategy03ExitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = kst_now().replace(
            hour=9, minute=5, second=0, microsecond=0
        )

    def _state(self, suffix: str, code: str = "123456") -> HoldSellState:
        return HoldSellState(
            position_id=f"s03:open:{suffix}",
            strategy_id=StrategyId.VALLEY_MORNING_CRASH,
            code=code,
            quantity=1,
            entry_price=Decimal("10000"),
            entry_at=self.now,
            entry_lane="OPEN_CRASH",
        )

    def test_open_exit_uses_minus_two_stop_not_legacy_minus_one(self) -> None:
        engine = Strategy03HoldSellEngine()
        minus_one = HoldSellObservation(
            observed_at=self.now.replace(hour=9, minute=21),
            price=Decimal("9900"),
            buy_ratio_recent=Decimal("0.80"),
        )
        self.assertFalse(engine.evaluate(self._state("minus-one"), minus_one).should_sell)

        decision = engine.evaluate(
            self._state("minus-two", code="654321"),
            replace(minus_one, price=Decimal("9800")),
        )
        self.assertTrue(decision.should_sell)
        self.assertIn("-2.00%", decision.reason)

    def test_explicit_entry_lane_wins_over_fill_time(self) -> None:
        engine = Strategy03HoldSellEngine()
        late_open = self._state("late-open")
        late_open.entry_at = self.now.replace(hour=9, minute=21)
        open_decision = engine.evaluate(
            late_open,
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=22),
                price=Decimal("9900"),
                buy_ratio_recent=Decimal("0.80"),
            ),
        )
        self.assertFalse(open_decision.should_sell)

        early_intraday = self._state("early-intraday", code="654321")
        early_intraday.entry_lane = "INTRADAY_CRASH"
        intraday_decision = engine.evaluate(
            early_intraday,
            HoldSellObservation(
                observed_at=self.now + timedelta(minutes=1),
                price=Decimal("9900"),
                buy_ratio_recent=Decimal("0.80"),
            ),
        )
        self.assertTrue(intraday_decision.should_sell)
        self.assertIn("-1.00%", intraday_decision.reason)
    def test_open_daily_ma_trend_holds_but_weak_trend_exits(self) -> None:
        engine = Strategy03HoldSellEngine()
        weak_observation = HoldSellObservation(
            observed_at=self.now.replace(hour=9, minute=21),
            price=Decimal("10000"),
            vwap=Decimal("10100"),
            buy_ratio_recent=Decimal("0.40"),
        )
        trend_decision = engine.evaluate(
            self._state("trend"),
            replace(
                weak_observation,
                daily_ma_permit=True,
                price_above_ma5=True,
                ma5_rising=True,
            ),
        )
        self.assertEqual(trend_decision.reason, "DAILY_MA_RIDER_HOLD")

        weak_decision = engine.evaluate(
            self._state("weak", code="654321"),
            replace(
                weak_observation,
                price_above_ma5=True,
                ma5_rising=True,
            ),
        )
        self.assertTrue(weak_decision.should_sell)
        self.assertIn("EARLY_TREND_EXIT", weak_decision.reason)

    def test_hard_stop_overrides_rider_but_ma5_break_alone_does_not(self) -> None:
        engine = Strategy03HoldSellEngine()
        hard_stop = engine.evaluate(
            self._state("hard-stop-overrides-rider"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=21),
                price=Decimal("9700"),
                buy_ratio_recent=Decimal("0.20"),
                daily_ma_permit=True,
            ),
        )
        self.assertTrue(hard_stop.should_sell)
        self.assertIn("HARD_STOP", hard_stop.reason)

        ma5_break = engine.evaluate(
            self._state("ma5-break-overrides-rider", code="654321"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=21),
                price=Decimal("10000"),
                daily_ma_permit=True,
                daily_ma5_broken=True,
                price_above_ma5=True,
                ma5_rising=True,
            ),
        )
        self.assertFalse(ma5_break.should_sell)
        self.assertEqual(ma5_break.reason, "DAILY_MA_RIDER_HOLD")

    def test_open_daily_ma_hold_still_blocks_structure_exit(self) -> None:
        engine = Strategy03HoldSellEngine()
        decision = engine.evaluate(
            self._state("rider-blocks-structure"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=21),
                price=Decimal("10000"),
                daily_ma_permit=True,
                price_above_ma5=True,
                ma5_rising=True,
                structure_broken=True,
                valley_exact_flow_valid=True,
                valley_exact_sell_dominant=True,
            ),
        )
        self.assertEqual(decision.reason, "DAILY_MA_RIDER_HOLD")

    def test_open_lane_forces_exit_at_1030(self) -> None:
        """★[S03-EXPRESS 2026-08-06 친구님 지시 "매도 방법은 10:30까지"] 09:50 → 10:30.
        09:50 에는 더 이상 강제청산하지 않고, 10:30 에 판다."""
        engine = Strategy03HoldSellEngine()
        at_0950 = engine.evaluate(
            self._state("time-0950"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=50),
                price=Decimal("10000"),
                daily_ma_permit=True,
            ),
        )
        self.assertFalse(at_0950.should_sell)
        at_1030 = engine.evaluate(
            self._state("time-1030", code="654321"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=10, minute=30),
                price=Decimal("10000"),
                daily_ma_permit=True,
            ),
        )
        self.assertTrue(at_1030.should_sell)
        self.assertEqual(at_1030.reason, "TIME_EXIT_1030")

    def test_open_daily_ma_hold_precedes_profit_trail(self) -> None:
        engine = Strategy03HoldSellEngine()
        state = self._state("trail")
        peak = HoldSellObservation(
            observed_at=self.now + timedelta(minutes=3),
            price=Decimal("10300"),
            buy_ratio_recent=Decimal("0.80"),
            daily_ma_permit=True,
            price_above_ma5=True,
            ma5_rising=True,
        )
        self.assertFalse(engine.evaluate(state, peak).should_sell)
        pullback = replace(
            peak,
            observed_at=self.now + timedelta(minutes=6),
            price=Decimal("10100"),
        )
        decision = engine.evaluate(state, pullback)
        self.assertFalse(decision.should_sell)
        self.assertEqual(decision.reason, "DAILY_MA_RIDER_HOLD")

        support_lost = replace(
            pullback,
            observed_at=pullback.observed_at + timedelta(seconds=1),
            daily_ma_permit=False,
        )
        decision = engine.evaluate(state, support_lost)
        self.assertFalse(decision.should_sell)
        self.assertEqual(decision.reason, "TREND_REBOUND_HOLD")

        sell_confirmed = replace(
            support_lost,
            observed_at=support_lost.observed_at + timedelta(seconds=61),
            one_minute_bearish=True,
            buy_money_per_sec_10s=Decimal("10"),
            sell_money_per_sec_10s=Decimal("30"),
            buy_money_per_sec_30s=Decimal("20"),
            sell_money_per_sec_30s=Decimal("20"),
            sell_volume_per_sec_5s=Decimal("30"),
            sell_volume_per_sec_previous_10s=Decimal("10"),
        )
        decision = engine.evaluate(state, sell_confirmed)
        self.assertTrue(decision.should_sell)
        self.assertIn("PROFIT_TRAIL", decision.reason)

    def test_open_profit_trail_is_blocked_before_ma5_handoff(self) -> None:
        engine = Strategy03HoldSellEngine()
        state = self._state("pre-handoff-trail")
        peak = HoldSellObservation(
            observed_at=self.now + timedelta(minutes=2),
            price=Decimal("10300"),
        )
        self.assertFalse(engine.evaluate(state, peak).should_sell)
        pullback = replace(
            peak,
            observed_at=self.now + timedelta(minutes=4),
            price=Decimal("10100"),
            one_minute_bearish=True,
            buy_money_per_sec_10s=Decimal("10"),
            sell_money_per_sec_10s=Decimal("30"),
            buy_money_per_sec_30s=Decimal("20"),
            sell_money_per_sec_30s=Decimal("20"),
            sell_volume_per_sec_5s=Decimal("30"),
            sell_volume_per_sec_previous_10s=Decimal("10"),
        )
        decision = engine.evaluate(state, pullback)
        self.assertFalse(decision.should_sell)
        self.assertEqual(decision.reason, "S03_OPEN_PRE_MA5_HANDOFF_HOLD")

    def test_open_ma5_handoff_persists_after_pullback(self) -> None:
        engine = Strategy03HoldSellEngine()
        state = self._state("handoff-persistent")
        handoff = HoldSellObservation(
            observed_at=self.now + timedelta(minutes=1),
            price=Decimal("10100"),
            price_above_ma5=True,
            ma5_rising=True,
        )
        self.assertFalse(engine.evaluate(state, handoff).should_sell)
        self.assertTrue(state.s03_open_ma5_handoff)
        after_pullback = replace(
            handoff,
            observed_at=handoff.observed_at + timedelta(minutes=1),
            price_above_ma5=False,
            ma5_rising=False,
        )
        decision = engine.evaluate(state, after_pullback)
        self.assertTrue(state.s03_open_ma5_handoff)
        self.assertEqual(decision.reason, "TREND_REBOUND_HOLD")

    def test_open_structure_break_requires_ten_second_exact_sell_flow(self) -> None:
        engine = Strategy03HoldSellEngine()
        state = self._state("structure")
        first = HoldSellObservation(
            observed_at=self.now + timedelta(minutes=1),
            price=Decimal("10000"),
            structure_broken=True,
            valley_exact_flow_valid=True,
            valley_exact_sell_dominant=True,
        )
        self.assertEqual(engine.evaluate(state, first).action, HoldSellAction.WATCH)
        confirmed = replace(
            first, observed_at=first.observed_at + timedelta(seconds=10)
        )
        decision = engine.evaluate(state, confirmed)
        self.assertTrue(decision.should_sell)
        self.assertIn("STRUCTURE_BREAK+EXACT_SELL_DOMINANT", decision.reason)

    def test_open_observation_ignores_entry_minute_and_pre_entry_bars(self) -> None:
        class FlowStub:
            def add(self, *_args) -> None:
                return None

            def rates(self, _code: str, _seconds: int):
                return (100.0, 200.0)

        entry_at = self.now.replace(hour=9, minute=9, second=57)
        observed_at = self.now.replace(hour=9, minute=10, second=57)
        with tempfile.TemporaryDirectory() as folder:
            bars = Path(folder) / "bars.json"
            bars.write_text(json.dumps({
                "ts": observed_at.isoformat(),
                "hm": "0910",
                "m": {"123456": {"prev": [
                    [110, 111, 109, 110],
                    [108, 109, 107, 108],
                    [106, 107, 105, 106],
                    [104, 105, 100, 101],
                ]}},
            }), encoding="utf-8")
            engine = Strategy03Engine.__new__(Strategy03Engine)
            engine.config = replace(build_config(), bars_path=bars)
            engine.windows = FlowStub()
            engine._s03_daily_trend = {}
            point = {
                "ts": observed_at,
                "price": 100.0,
                "buy_money_cum": 10_000.0,
                "sell_money_cum": 20_000.0,
                "cum_vol": 1_000.0,
                "money_speed_5s": 300.0,
                "money_speed_10s": 250.0,
                "money_speed_30s": 200.0,
            }
            observation = engine._build_observation(
                {"code": "123456", "entry_at": entry_at.isoformat()}, point
            )
        self.assertFalse(observation.structure_broken)

    def test_open_observation_uses_post_entry_3m_support_and_1m_close(self) -> None:
        class FlowStub:
            def add(self, *_args) -> None:
                return None

            def rates(self, _code: str, _seconds: int):
                return (100.0, 200.0)

        entry_at = self.now.replace(hour=9, minute=9, second=57)
        observed_at = self.now.replace(hour=9, minute=14, second=10)
        with tempfile.TemporaryDirectory() as folder:
            bars = Path(folder) / "bars.json"
            bars.write_text(json.dumps({
                "ts": observed_at.isoformat(),
                "hm": "0914",
                "m": {"123456": {"prev": [
                    [110, 111, 109, 110],
                    [108, 109, 107, 108],
                    [100, 105, 100, 104],
                    [104, 106, 99, 103],
                    [103, 104, 98, 102],
                    [102, 103, 96, 97],
                ]}},
            }), encoding="utf-8")
            engine = Strategy03Engine.__new__(Strategy03Engine)
            engine.config = replace(build_config(), bars_path=bars)
            engine.windows = FlowStub()
            engine._s03_daily_trend = {}
            point = {
                "ts": observed_at,
                "price": 100.0,
                "buy_money_cum": 10_000.0,
                "sell_money_cum": 20_000.0,
                "cum_vol": 1_000.0,
                "money_speed_5s": 300.0,
                "money_speed_10s": 250.0,
                "money_speed_30s": 200.0,
            }
            position = {
                "code": "123456",
                "entry_at": entry_at.isoformat(),
                "hold_state": {"valley_morning_break_since": ""},
            }
            observation = engine._build_observation(position, point)
            position["hold_state"]["valley_morning_break_since"] = (
                observed_at.isoformat()
            )
            self.assertTrue(
                engine._open_structure_break_active(position, observed_at)
            )
            position["hold_state"]["valley_morning_break_since"] = ""
            self.assertFalse(
                engine._open_structure_break_active(
                    position, observed_at + timedelta(seconds=11)
                )
            )
        self.assertTrue(observation.structure_broken)
        self.assertTrue(observation.valley_exact_flow_valid)
        self.assertTrue(observation.valley_exact_sell_dominant)

    def test_open_daily_ma_matches_common_rider_and_ignores_future_day(self) -> None:
        # S03도 일봉이 아니라 전 전략 공통 3분봉 rider를 그대로 호출한다.
        engine = Strategy03Engine.__new__(Strategy03Engine)
        with patch(
            "strategy_03_rotation_engine_v1.ma3_rider_permit",
            side_effect=lambda code, _price, buy_side=None: code == "111111",
        ) as rider:
            self.assertTrue(engine._daily_ma_permit("111111", 120.0))
            self.assertFalse(engine._daily_ma_permit("222222", 120.0))
        self.assertEqual(rider.call_count, 2)

    def test_open_and_intraday_lanes_keep_separate_force_exit_times(self) -> None:
        engine = Strategy03Engine.__new__(Strategy03Engine)
        engine.config = build_config()
        open_position = {
            "code": "123456", "entry_at": self.now.isoformat(),
            "entry_lane": "OPEN_CRASH",
        }
        intraday_position = {
            **open_position, "entry_lane": "INTRADAY_CRASH",
        }
        # ★[S03-EXPRESS 2026-08-06] 아침 창구 강제청산 09:50 → 10:30 (친구님 지시).
        self.assertEqual(
            engine._position_force_exit_at(open_position), day_time(10, 30)
        )
        self.assertEqual(
            engine._position_force_exit_at(intraday_position), day_time(15, 10)
        )

    def test_completed_post_entry_one_minute_close_confirms_ma5_break(self) -> None:
        entry_at = self.now.replace(hour=9, minute=9, second=57)
        observed_at = self.now.replace(hour=9, minute=12, second=5)
        with tempfile.TemporaryDirectory() as folder:
            bars = Path(folder) / "bars.json"
            bars.write_text(json.dumps({
                "ts": observed_at.isoformat(),
                "hm": "0912",
                "m": {"123456": {"prev": [
                    [101, 102, 100, 101],
                    [101, 101, 98, 99],
                ]}},
            }), encoding="utf-8")
            engine = Strategy03Engine.__new__(Strategy03Engine)
            engine.config = replace(build_config(), bars_path=bars)
            position = {
                "code": "123456", "entry_at": entry_at.isoformat(),
                "s03_ma5_seen_above": True,
            }
            point = {"ts": observed_at, "price": 99.0}
            with patch(
                "strategy_03_rotation_engine_v1.ma3_rows",
                return_value={"ma5": 100.0},
            ):
                self.assertTrue(
                    engine._completed_open_ma5_broken(position, point)
                )

if __name__ == "__main__":
    unittest.main()
