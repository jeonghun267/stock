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
            replace(weak_observation, daily_ma_permit=True),
        )
        self.assertEqual(trend_decision.reason, "DAILY_MA_RIDER_HOLD")

        weak_decision = engine.evaluate(
            self._state("weak", code="654321"), weak_observation
        )
        self.assertTrue(weak_decision.should_sell)
        self.assertIn("EARLY_TREND_EXIT", weak_decision.reason)

    def test_open_risk_exits_override_daily_ma_hold(self) -> None:
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
            ),
        )
        self.assertTrue(ma5_break.should_sell)
        self.assertEqual(ma5_break.reason, "DAILY_MA5_BREAK")

    def test_open_daily_ma_hold_still_blocks_structure_exit(self) -> None:
        engine = Strategy03HoldSellEngine()
        decision = engine.evaluate(
            self._state("rider-blocks-structure"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=21),
                price=Decimal("10000"),
                daily_ma_permit=True,
                structure_broken=True,
                valley_exact_flow_valid=True,
                valley_exact_sell_dominant=True,
            ),
        )
        self.assertEqual(decision.reason, "DAILY_MA_RIDER_HOLD")

    def test_open_lane_forces_exit_at_0950(self) -> None:
        decision = Strategy03HoldSellEngine().evaluate(
            self._state("time-0950"),
            HoldSellObservation(
                observed_at=self.now.replace(hour=9, minute=50),
                price=Decimal("10000"),
                daily_ma_permit=True,
            ),
        )
        self.assertTrue(decision.should_sell)
        self.assertEqual(decision.reason, "TIME_EXIT_0950")

    def test_open_profit_trail_overrides_daily_ma_hold(self) -> None:
        engine = Strategy03HoldSellEngine()
        state = self._state("trail")
        peak = HoldSellObservation(
            observed_at=self.now + timedelta(minutes=3),
            price=Decimal("10300"),
            buy_ratio_recent=Decimal("0.80"),
            daily_ma_permit=True,
        )
        self.assertFalse(engine.evaluate(state, peak).should_sell)
        pullback = replace(
            peak,
            observed_at=self.now + timedelta(minutes=6),
            price=Decimal("10100"),
        )
        decision = engine.evaluate(state, pullback)
        self.assertTrue(decision.should_sell)
        self.assertIn("PROFIT_TRAIL", decision.reason)

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
        with tempfile.TemporaryDirectory() as folder:
            eod = Path(folder) / "eod.csv"
            bars = Path(folder) / "bars.json"
            rows = ["code,date,close"]
            for offset in range(21):
                day = f"202606{offset + 1:02d}"
                rows.append(f"111111,{day},{100 + offset}")
                rows.append(f"222222,{day},{120 - offset}")
            rows.append("111111,20260803,1")
            eod.write_text("\n".join(rows) + "\n", encoding="utf-8")
            bars.write_text(json.dumps({"m": {
                "111111": {"prev": [
                    [150, 151, 149, 150],
                    [150, 152, 149, 151],
                    [151, 153, 150, 152],
                ]},
                "222222": {"prev": [
                    [150, 151, 149, 150],
                    [150, 152, 149, 151],
                    [151, 153, 150, 152],
                ]},
            }}), encoding="utf-8")
            engine = Strategy03Engine.__new__(Strategy03Engine)
            engine.config = replace(
                build_config(), eod_bars_path=eod, bars_path=bars
            )
            engine.state = {"date": "20260802"}
            engine.log = logging.getLogger("s03-daily-trend-test")
            engine._s03_daily_trend = None
            self.assertTrue(engine._daily_ma_permit("111111", 120.0))
            self.assertFalse(engine._daily_ma_permit("222222", 120.0))

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
        self.assertEqual(
            engine._position_force_exit_at(open_position), day_time(9, 50)
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
            engine._s03_daily_trend = {"123456": {
                "ma5": 100.0, "ma10": 90.0,
                "ma20": 80.0, "ma20_prev": 79.0,
            }}
            position = {
                "code": "123456", "entry_at": entry_at.isoformat(),
                "s03_ma5_seen_above": True,
            }
            point = {"ts": observed_at, "price": 99.0}
            self.assertTrue(engine._completed_open_ma5_broken(position, point))

if __name__ == "__main__":
    unittest.main()
