# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# ★[2026-08-01] 이 파일의 확정대기·호가관문 검증은 롤백 경로(S02_SIX_STYLE=NO) 기준.
#   실전 기본값(YES·6번식)은 해당 관문을 의도적으로 우회한다.
# ★[2026-08-03 보안점검] 전역 NO 고정을 걷어냈다. 이 파일에는 두 경로의 검증이
#   섞여 있어(옛 호가관문 3건 / 6번식 계단·자금분출 4건) 전역 고정으로는 어느
#   쪽이든 반드시 실패했다. 기본은 실전값(YES)으로 두고, 옛 경로를 검증하는
#   3건만 SIX_STYLE 을 국소적으로 끈다.
os.environ["S02_SIX_STYLE"] = "YES"

from strategy_01_rotation_engine_v2 import kst_now
from strategy_02_low_buy_signal_v1 import LowBuySignalMonitor, _write_json_atomic
from strategy_02_rotation_engine_v1 import Strategy02Engine, build_config
from strategy_02_signal_contract_v1 import (
    SIGNAL_MODE,
    SIGNAL_SCHEMA,
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
from 저점매수_매도소진 import BottomSignal, MarketPoint


class FakeSlots:
    def __init__(self) -> None:
        self.owned: set[str] = set()
        self.owner = ""

    def acquire(self, code: str, owner: str, _day: str) -> bool:
        self.owner = owner
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


class Strategy02Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = kst_now().replace(hour=9, minute=31, second=0, microsecond=0)

    @staticmethod
    def point(
        ts,
        *,
        price: float = 10_100,
        best_ask_px: float = 10_110,
        best_bid_px: float = 10_100,
        best_ask_qty: float = 100,
        best_bid_qty: float = 300,
        buy_money_cum: float = 700_000_000,
        sell_money_cum: float = 300_000_000,
        cum_vol: float = 1_000,
        che_str: float = 110,
        buy_vol_cum: float = 700_000,
        sell_vol_cum: float = 300_000,
    ) -> MarketPoint:
        return MarketPoint(
            ts=ts.replace(tzinfo=None),
            price=price,
            cum_vol=cum_vol,
            che_str=che_str,
            ask_tot=1_000,
            bid_tot=2_000,
            buy_money_cum=buy_money_cum,
            sell_money_cum=sell_money_cum,
            buy_vol_cum=buy_vol_cum,
            sell_vol_cum=sell_vol_cum,
            best_ask_px=best_ask_px,
            best_bid_px=best_bid_px,
            best_ask_qty=best_ask_qty,
            best_bid_qty=best_bid_qty,
        )
    def signal_payload(self) -> dict:
        stamp = self.now.replace(tzinfo=None).isoformat(timespec="seconds")
        return {
            "schema": SIGNAL_SCHEMA,
            "date": self.now.strftime("%Y%m%d"),
            "updated_at": stamp,
            "mode": SIGNAL_MODE,
            "signals": [{
                "ts": stamp,
                "code": "123456",
                "name": "TEST",
                "action": "BUY_READY",
                "reason": "PRO_FLOW_BOOK_EXHAUSTION",
                "price": 10_100,
                "entry_gap_pct": 0.8,
                "book_imbalance": 0.3,
                "wave_count": 2,
                "signal_sequence": 1,
                "mode": SIGNAL_MODE,
            }],
        }

    def test_contract_accepts_fresh_s02_only(self) -> None:
        rows = select_fresh_signals(
            self.signal_payload(), now=self.now, max_age_sec=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_id"], StrategyId.S02_LOW_BUY_SELL_EXHAUSTION.value)
        stale = self.signal_payload()
        stale["updated_at"] = (self.now - timedelta(seconds=20)).isoformat()
        self.assertEqual(
            select_fresh_signals(stale, now=self.now, max_age_sec=5), [])

    def test_flow_book_shadow_never_enters_live_signal_list(self) -> None:
        monitor = LowBuySignalMonitor()
        anchor_ts = self.now.replace(tzinfo=None) - timedelta(seconds=10)

        def detected(points):
            point = points[-1]
            return BottomSignal(
                algorithm="PRO_FLOW_BOOK_EXHAUSTION",
                signal_ts=point.ts,
                signal_price=point.price,
                anchor_low_ts=anchor_ts,
                anchor_low_price=10_000,
                wave_count=2,
                reason="FLOW_BOOK_RECOVERED",
            )

        with patch(
            "strategy_02_low_buy_signal_v1.detect_flow_book_exhaustion",
            side_effect=detected,
        ), patch.object(
            LowBuySignalMonitor, "_detect_dip_rebound", return_value=None,
        ):
            shadow_rows = []
            for sec in range(3):
                _, fired = monitor.process_point(
                    "123456",
                    "TEST",
                    self.point(self.now + timedelta(seconds=sec)),
                    open_price=10_500,
                    session_high=10_500,
                )
                self.assertFalse(fired)
                shadow_rows.extend(monitor.drain_flow_book_shadow_signals())

        self.assertEqual(monitor.signals, [])
        self.assertEqual(len(shadow_rows), 1)
        self.assertEqual(shadow_rows[0]["action"], "SHADOW_READY")
        self.assertEqual(shadow_rows[0]["mode"], "SHADOW_ORDER_ZERO")
        self.assertEqual(shadow_rows[0]["provenance"], "[HYPOTHETICAL]")

    @patch("strategy_02_low_buy_signal_v1.SIX_STYLE", False)
    def test_signal_monitor_latches_same_anchor(self) -> None:
        monitor = LowBuySignalMonitor()

        def detected(points):
            point = points[-1]
            return BottomSignal(
                algorithm="PRO_FLOW_BOOK_EXHAUSTION",
                signal_ts=point.ts,
                signal_price=point.price,
                anchor_low_ts=self.now.replace(tzinfo=None) - timedelta(seconds=10),
                anchor_low_price=10_000,
                wave_count=2,
                reason="FLOW_BOOK_RECOVERED",
            )

        with patch.object(          # ★[2026-07-31] 되돌림 판정으로 교체(위 주석 참조)
            LowBuySignalMonitor, "_detect_dip_rebound",
            side_effect=detected,
        ):
            first, first_fired = monitor.process_point(
                "123456", "TEST", self.point(self.now))
            second, second_fired = monitor.process_point(
                "123456", "TEST", self.point(self.now + timedelta(seconds=1)))
            point = self.point(self.now + timedelta(seconds=2))
            row, fired = monitor.process_point("123456", "TEST", point)
            duplicate, fired_again = monitor.process_point("123456", "TEST", point)
        self.assertFalse(first_fired)
        self.assertFalse(second_fired)
        self.assertEqual(first["reason"], "ENTRY_CONFIRM_WAIT")
        self.assertEqual(second["reason"], "ENTRY_CONFIRM_WAIT")
        self.assertTrue(fired)
        self.assertEqual(row["action"], "BUY_READY")
        self.assertEqual(row["confirm_points"], 3)
        self.assertGreaterEqual(row["confirm_age_sec"], 2)
        self.assertLessEqual(row["spread_bps"], 30)
        self.assertGreaterEqual(row["microprice_edge_bps"], 0)
        self.assertFalse(fired_again)
        self.assertEqual(duplicate["reason"], "DUPLICATE_SNAPSHOT")

    @patch("strategy_02_low_buy_signal_v1.SIX_STYLE", False)
    def test_signal_rejects_wide_exact_spread(self) -> None:
        point = self.point(
            self.now, best_ask_px=10_200, best_bid_px=10_100)
        detected = BottomSignal(
            algorithm="PRO_FLOW_BOOK_EXHAUSTION",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=point.ts - timedelta(seconds=10),
            anchor_low_price=10_000,
            wave_count=2,
            reason="FLOW_BOOK_RECOVERED",
        )
        monitor = LowBuySignalMonitor()
        # ★[2026-07-31] 매수 판정이 detect_flow_book_exhaustion → _detect_dip_rebound
        #   (되돌림)으로 교체됐다. 이 테스트들이 검사하는 건 판정 이후 흐름
        #   (호가 확인·anchor 중복 방지)이므로 가짜로 바꿀 대상만 옮긴다.
        with patch.object(
            LowBuySignalMonitor, "_detect_dip_rebound",
            return_value=detected,
        ):
            row, fired = monitor.process_point("123456", "TEST", point)
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "SPREAD_TOO_WIDE")

    @patch("strategy_02_low_buy_signal_v1.SIX_STYLE", False)
    def test_signal_requires_exact_topbook(self) -> None:
        point = self.point(
            self.now,
            best_ask_px=0,
            best_bid_px=0,
            best_ask_qty=0,
            best_bid_qty=0,
        )
        detected = BottomSignal(
            algorithm="PRO_FLOW_BOOK_EXHAUSTION",
            signal_ts=point.ts,
            signal_price=point.price,
            anchor_low_ts=point.ts - timedelta(seconds=10),
            anchor_low_price=10_000,
            wave_count=2,
            reason="FLOW_BOOK_RECOVERED",
        )
        monitor = LowBuySignalMonitor()
        # ★[2026-07-31] 매수 판정이 detect_flow_book_exhaustion → _detect_dip_rebound
        #   (되돌림)으로 교체됐다. 이 테스트들이 검사하는 건 판정 이후 흐름
        #   (호가 확인·anchor 중복 방지)이므로 가짜로 바꿀 대상만 옮긴다.
        with patch.object(
            LowBuySignalMonitor, "_detect_dip_rebound",
            return_value=detected,
        ):
            row, fired = monitor.process_point("123456", "TEST", point)
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "EXACT_TOPBOOK_REQUIRED")
    def test_s02_uses_open_before_0930_and_intraday_high_afterward(self) -> None:
        morning = LowBuySignalMonitor()
        morning_start = self.now.replace(hour=9, minute=10)
        morning.process_point(
            "123456", "TEST",
            self.point(morning_start, price=9_900),
            open_price=10_000,
            session_high=11_000,
        )
        morning.process_point(
            "123456", "TEST",
            self.point(morning_start + timedelta(seconds=30), price=9_700),
            open_price=10_000,
            session_high=11_000,
        )
        morning_state = morning.states["123456"]
        self.assertEqual(morning_state.six_reference_mode, "OPEN")
        self.assertEqual(morning_state.six_episode_high, 10_000)
        self.assertEqual(morning_state.six_phase, "CHASE")

        intraday = LowBuySignalMonitor()
        intraday_start = self.now.replace(hour=10, minute=0)
        intraday.process_point(
            "123456", "TEST",
            self.point(intraday_start, price=10_800),
            open_price=10_000,
            session_high=11_000,
        )
        intraday.process_point(
            "123456", "TEST",
            self.point(intraday_start + timedelta(seconds=30), price=10_450),
            open_price=10_000,
            session_high=11_000,
        )
        intraday_state = intraday.states["123456"]
        self.assertEqual(intraday_state.six_reference_mode, "INTRADAY_HIGH")
        self.assertEqual(intraday_state.six_episode_high, 11_000)
        self.assertEqual(intraday_state.six_phase, "CHASE")

    def test_morning_open_drop_at_4pct_stays_in_strategy_02(self) -> None:
        monitor = LowBuySignalMonitor()
        observed_at = self.now.replace(hour=9, minute=10)
        row, fired = monitor.process_point(
            "123456", "TEST",
            self.point(observed_at, price=9_600),
            open_price=10_000,
            session_high=10_000,
        )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "S02_MONEY_SURGE_OR_STAIRCASE_WAIT")
        state = monitor.states["123456"]
        self.assertFalse(state.handoff_to_s03_s06)
        self.assertEqual(state.six_phase, "CHASE")
        recovered, recovered_fired = monitor.process_point(
            "123456", "TEST",
            self.point(observed_at + timedelta(seconds=30), price=9_800),
            open_price=10_000,
            session_high=10_000,
        )
        self.assertFalse(recovered_fired)
        self.assertEqual(
            recovered["reason"], "S02_MONEY_SURGE_OR_STAIRCASE_WAIT")
    def test_s06_staircase_resets_new_low_during_observe(self) -> None:
        monitor = LowBuySignalMonitor()
        # 09:30 이후에는 확정된 강화값(-5%)이 적용되므로, 이 시험은
        # 아침 -3% 계단 경로에서 "관찰 중 새 저점 리셋"만 검증한다.
        base = self.now.replace(hour=9, minute=0)
        sequence = [
            (0, 10_000, 1_000, 1_000),
            (20, 9_900, 1_100, 2_000),
            (40, 9_700, 1_200, 3_000),
            (50, 9_600, 1_300, 4_000),
            (55, 9_750, 1_500, 4_100),
            (60, 9_500, 1_600, 5_000),
        ]
        for sec, price, buy_cum, sell_cum in sequence:
            _, fired = monitor.process_point(
                "123456", "TEST",
                self.point(
                    base + timedelta(seconds=sec),
                    price=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                ),
                open_price=10_000,
            )
            self.assertFalse(fired)
        state = monitor.states["123456"]
        self.assertEqual(state.six_phase, "CHASE")
        self.assertEqual(state.six_low, 9_500)
        self.assertEqual(state.six_reset_steps, 2)
        self.assertIsNone(state.six_observe_since)

    # ★[2026-08-07] 이 시험이 잠그는 것은 '흐름 가속이 있어야 신호가 나간다' 하나다.
    #   여기 표본은 저점을 한 번도 갈아치우지 않아(dip_low_reset_steps=0) 8/7 에 생긴
    #   저점리셋 관문에 걸린다. 시험의 뜻을 지키려고 그 관문만 국소로 끈다.
    #   저점리셋 관문 자체는 바로 아래 test_low_reset_gate_* 두 건이 잠근다.
    @patch("strategy_02_low_buy_signal_v1.MIN_LOW_RESET_STEPS", 0)
    def test_s06_staircase_full_retest_emits_only_after_flow_acceleration(self) -> None:
        monitor = LowBuySignalMonitor()
        sequence = [
            (0, 10_000, 0, 0, 1_000, 90, 0, 0),
            (20, 9_900, 100_000, 1_000_000, 1_100, 85, 100, 1_000),
            (40, 9_700, 200_000, 3_000_000, 1_200, 80, 200, 3_000),
            (50, 9_600, 300_000, 4_500_000, 1_300, 75, 300, 4_500),
            (60, 9_500, 400_000, 6_000_000, 1_400, 70, 400, 6_000),
            (65, 9_643, 600_000, 6_100_000, 1_450, 72, 600, 6_100),
            (85, 9_595, 800_000, 6_300_000, 1_470, 73, 800, 6_300),
            (105, 9_600, 1_000_000, 8_000_000, 1_500, 74, 1_000, 8_000),
            (110, 9_610, 1_500_000, 8_500_000, 1_550, 75, 1_200, 8_500),
            (115, 9_615, 2_000_000, 9_000_000, 1_600, 76, 1_500, 9_000),
            (120, 9_620, 3_000_000, 9_400_000, 1_700, 78, 2_500, 9_400),
            (125, 9_643, 13_000_000, 9_800_000, 2_200, 80, 5_000, 9_800),
            (126, 9_644, 16_000_000, 9_900_000, 2_400, 82, 5_500, 9_900),
        ]
        fired_rows = []
        for sec, price, buy_cum, sell_cum, cum_vol, che_str, buy_vol, sell_vol in sequence:
            row, fired = monitor.process_point(
                "123456", "TEST",
                self.point(
                    self.now + timedelta(seconds=sec),
                    price=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                    cum_vol=cum_vol,
                    che_str=che_str,
                    buy_vol_cum=buy_vol,
                    sell_vol_cum=sell_vol,
                ),
            )
            if fired:
                fired_rows.append(row)
        self.assertEqual(len(fired_rows), 1)
        row = fired_rows[0]
        self.assertEqual(row["action"], "BUY_READY")
        self.assertEqual(row["algorithm"], "S02_S06_STAIRCASE_RETEST_V1")
        self.assertEqual(row["anchor_low"], 9_500)
        self.assertEqual(row["dip_low_reset_steps"], 0)
        self.assertEqual(row["dip_flow_flip"], "O")
        self.assertEqual(row["flow_accel"], "O")
        self.assertEqual(row["low_confirm_ticks"], 2)
        self.assertLess(row["low_confirm_che_str"], 105)
        self.assertGreater(
            row["low_confirm_che_str"], row["low_confirm_low_che_str"])
        self.assertEqual(row["low_confirm_flow_turn"], "O")
        self.assertGreaterEqual(row["dip_drop_pct"], 5.0)
        self.assertGreaterEqual(row["observe_sec"], 60)
        self.assertGreaterEqual(row["entry_gap_pct"], 1.0)
        self.assertLessEqual(row["entry_gap_pct"], 2.0)

    # ★[저점리셋 관문 잠금 2026-08-07 친구님 지시 "하락할 때 양봉 튀어나오는 거 걸러내기"]
    #   저점이 한두 번밖에 안 깨졌는데 튀어 오른 양봉은 사지 않는다.
    #   위 시험과 완전히 같은 표본(리셋 0회)을 쓴다 — 관문만 켜면 신호가 사라져야 한다.
    #   이 두 건이 함께 있어야 '관문이 실제로 일한다'가 증명된다(하나는 켬/하나는 끔).
    def _staircase_retest_sequence(self):
        return [
            (0, 10_000, 0, 0, 1_000, 90, 0, 0),
            (20, 9_900, 100_000, 1_000_000, 1_100, 85, 100, 1_000),
            (40, 9_700, 200_000, 3_000_000, 1_200, 80, 200, 3_000),
            (50, 9_600, 300_000, 4_500_000, 1_300, 75, 300, 4_500),
            (60, 9_500, 400_000, 6_000_000, 1_400, 70, 400, 6_000),
            (65, 9_643, 600_000, 6_100_000, 1_450, 72, 600, 6_100),
            (85, 9_595, 800_000, 6_300_000, 1_470, 73, 800, 6_300),
            (105, 9_600, 1_000_000, 8_000_000, 1_500, 74, 1_000, 8_000),
            (110, 9_610, 1_500_000, 8_500_000, 1_550, 75, 1_200, 8_500),
            (115, 9_615, 2_000_000, 9_000_000, 1_600, 76, 1_500, 9_000),
            (120, 9_620, 3_000_000, 9_400_000, 1_700, 78, 2_500, 9_400),
            (125, 9_643, 13_000_000, 9_800_000, 2_200, 80, 5_000, 9_800),
            (126, 9_644, 16_000_000, 9_900_000, 2_400, 82, 5_500, 9_900),
        ]

    def _run_staircase(self):
        monitor = LowBuySignalMonitor()
        fired = []
        for sec, price, buy_cum, sell_cum, cum_vol, che, buy_v, sell_v in (
                self._staircase_retest_sequence()):
            row, hit = monitor.process_point(
                "123456", "TEST",
                self.point(self.now + timedelta(seconds=sec), price=price,
                           buy_money_cum=buy_cum, sell_money_cum=sell_cum,
                           cum_vol=cum_vol, che_str=che,
                           buy_vol_cum=buy_v, sell_vol_cum=sell_v))
            if hit:
                fired.append(row)
        return fired

    @patch("strategy_02_low_buy_signal_v1.MIN_LOW_RESET_STEPS", 4)
    def test_low_reset_gate_blocks_shallow_reset_bounce(self) -> None:
        """리셋 0회짜리 반등은 관문이 막는다 = 하락 중 튀어 오른 양봉을 안 산다."""
        self.assertEqual(self._run_staircase(), [])

    @patch("strategy_02_low_buy_signal_v1.MIN_LOW_RESET_STEPS", 0)
    def test_low_reset_gate_off_restores_signal(self) -> None:
        """관문을 끄면(롤백 경로) 같은 표본이 다시 신호를 낸다 = 막은 주체가 이 관문이다."""
        fired = self._run_staircase()
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["dip_low_reset_steps"], 0)

    def test_money_surge_onset_fires_at_first_bull_candle_start(self) -> None:
        monitor = LowBuySignalMonitor()
        sequence = [
            (0, 10_000, 0, 0, 1_000, 90, 0, 0),
            (5, 9_900, 500_000, 1_000_000, 1_100, 85, 100, 500),
            (10, 9_700, 1_000_000, 3_000_000, 1_200, 78, 200, 1_200),
            (15, 9_500, 1_500_000, 5_000_000, 1_300, 70, 300, 2_200),
            (20, 9_550, 16_500_000, 6_000_000, 2_300, 80, 2_300, 2_300),
            (21, 9_560, 20_000_000, 6_200_000, 2_500, 82, 2_600, 2_320),
        ]
        fired_rows = []
        for sec, price, buy_cum, sell_cum, cum_vol, che_str, buy_vol, sell_vol in sequence:
            row, fired = monitor.process_point(
                "123456", "TEST",
                self.point(
                    self.now + timedelta(seconds=sec),
                    price=price,
                    best_ask_px=price + 1,
                    best_bid_px=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                    cum_vol=cum_vol,
                    che_str=che_str,
                    buy_vol_cum=buy_vol,
                    sell_vol_cum=sell_vol,
                ),
            )
            if fired:
                fired_rows.append(row)
        self.assertEqual(len(fired_rows), 1)
        row = fired_rows[0]
        self.assertEqual(row["algorithm"], "S02_MONEY_SURGE_ONSET_V1")
        self.assertEqual(row["anchor_low"], 9_500)
        self.assertGreaterEqual(row["dip_drop_pct"], 5.0)
        self.assertEqual(row["surge_confirm_ticks"], 2)
        self.assertLess(row["surge_che_str"], 105)
        self.assertEqual(row["surge_flow_turn"], "O")
        self.assertLessEqual(row["surge_turn_sec"], 10)
        self.assertGreaterEqual(row["surge_recent_buy_rate_5s"], 1_666_667)

    def test_entry_does_not_arm_above_minus_five_percent(self) -> None:
        monitor = LowBuySignalMonitor()
        sequence = [
            (0, 10_000, 0, 0, 1_000, 100),
            (5, 9_900, 500_000, 1_000_000, 1_100, 95),
            (10, 9_700, 1_000_000, 3_000_000, 1_200, 92),
            (15, 9_510, 1_500_000, 5_000_000, 1_300, 90),
            (20, 9_560, 16_500_000, 6_000_000, 2_300, 115),
            (21, 9_570, 20_000_000, 6_200_000, 2_500, 118),
        ]
        fired_rows = []
        for sec, price, buy_cum, sell_cum, cum_vol, che_str in sequence:
            row, fired = monitor.process_point(
                "123456", "TEST",
                self.point(
                    self.now + timedelta(seconds=sec),
                    price=price,
                    best_ask_px=price + 1,
                    best_bid_px=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                    cum_vol=cum_vol,
                    che_str=che_str,
                ),
            )
            if fired:
                fired_rows.append(row)
        self.assertEqual(fired_rows, [])
        self.assertEqual(monitor.states["123456"].surge_phase, "IDLE")

    def test_money_surge_onset_rejects_slow_drop(self) -> None:
        monitor = LowBuySignalMonitor()
        sequence = [
            (0, 10_000, 0, 0, 1_000, 100),
            (20, 9_900, 500_000, 1_000_000, 1_100, 95),
            (40, 9_800, 1_000_000, 3_000_000, 1_200, 92),
            (60, 9_700, 1_500_000, 5_000_000, 1_300, 90),
            (65, 9_750, 16_500_000, 6_000_000, 2_300, 115),
            (66, 9_760, 20_000_000, 6_200_000, 2_500, 118),
        ]
        fired_rows = []
        for sec, price, buy_cum, sell_cum, cum_vol, che_str in sequence:
            row, fired = monitor.process_point(
                "123456", "TEST",
                self.point(
                    self.now + timedelta(seconds=sec),
                    price=price,
                    best_ask_px=price + 1,
                    best_bid_px=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                    cum_vol=cum_vol,
                    che_str=che_str,
                ),
            )
            if fired:
                fired_rows.append(row)
        self.assertEqual(fired_rows, [])
        self.assertEqual(monitor.states["123456"].surge_phase, "IDLE")

    def test_atomic_write_retries_permission_error_then_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "signal.json"
            real_replace = os.replace
            attempts = 0

            def replace_after_one_lock(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError(5, "locked")
                return real_replace(source, destination)

            with patch(
                "strategy_02_low_buy_signal_v1.os.replace",
                side_effect=replace_after_one_lock,
            ), patch("strategy_02_low_buy_signal_v1.time_module.sleep"):
                written = _write_json_atomic(path, {"status": "LIVE"})

            self.assertTrue(written)
            self.assertEqual(attempts, 2)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["status"],
                "LIVE",
            )

    def test_atomic_write_exhaustion_returns_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "signal.json"
            with patch(
                "strategy_02_low_buy_signal_v1.os.replace",
                side_effect=PermissionError(5, "locked"),
            ) as replace_mock, patch(
                "strategy_02_low_buy_signal_v1.time_module.sleep",
            ):
                written = _write_json_atomic(path, {"status": "LIVE"})

            self.assertFalse(written)
            self.assertEqual(replace_mock.call_count, 6)

    def test_s02_signal_routes_to_common_rotation_engine(self) -> None:
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
            stamp = self.now.replace(tzinfo=None).isoformat(timespec="seconds")
            config.signal_path.write_text(
                json.dumps(self.signal_payload()), encoding="utf-8")
            config.snapshot_path.write_text(json.dumps({"codes": {"123456": {
                "ts": stamp,
                "cur": 10_100,
                "cum_vol": 100_000,
                "buy_money_cum": 700_000_000,
                "sell_money_cum": 300_000_000,
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
            logger = logging.getLogger("strategy02-test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            engine = Strategy02Engine(
                config,
                broker=broker,
                slots=slots,
                logger=logger,
                signal_selector=select_fresh_signals,
            )
            engine.tick(self.now)
            self.assertEqual(len(broker.submissions), 1)
            self.assertEqual(config.slot_owner, "STRATEGY02")
            position = engine._active_positions()["123456"]
            self.assertEqual(
                position["hold_state"]["strategy_id"],
                StrategyId.S02_LOW_BUY_SELL_EXHAUSTION.value,
            )
            self.assertTrue(
                broker.submissions[0]["idempotency_key"].startswith("strategy02:"))

    def test_s02_ma10_ma20_alone_no_longer_blocks_exit(self) -> None:
        """★[RISING-HOLD 단일화 2026-08-05] 잠금 시험 — 지우기 전에 읽을 것.

        종전 이름: test_s02_flow_reversal_holds_when_ma10_and_ma20_support.
        그때는 `ma10_support and ma20_rising` 만으로 상승보유(HOLD)를 줬고 이
        시험이 그 동작을 시험했다. 그 가지는 매수세를 안 봐서, 8/3 에 만든
        2단 판정(선 지지 AND 매수세 우위 = daily_ma_permit)을 우회했다.
        8/5 실전 감사기록 — S02 상승보유 434회 중 196회(45.2%)가 그 가지였고
        그중 192회(98.0%)가 매도세>매수세인 순간이었다.
        지금은 daily_ma_permit 하나만 상승보유를 준다.

        아래 대본은 매도세 우위(매수 100 / 매도 180)에 흐름역전 신호까지 켜진
        상태다. 이때 COMMON_RISING_HOLD 가 다시 나오면 그 가지가 되살아난
        것이므로 이 시험이 터진다.
        """
        engine = UnifiedHoldSellEngine()
        state = HoldSellState(
            position_id="s02-support",
            strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
            code="123456",
            quantity=1,
            entry_price="100",
            entry_at=self.now,
        )
        decision = engine.evaluate(
            state,
            HoldSellObservation(
                observed_at=self.now + timedelta(seconds=20),
                price="99.2",
                buy_money_per_sec_10s="100",
                sell_money_per_sec_10s="180",
                buy_volume_per_sec_5s="100",
                sell_volume_per_sec_5s="200",
                sell_volume_per_sec_previous_10s="100",
                che_str="90",
                che_str_change_5s="-10",
                one_minute_bull_to_bear=True,
                daily_ma5_broken=True,
                ma10_support=True,
                ma20_rising=True,
                common_peak_flow_ready=True,
            ),
        )
        self.assertNotEqual(
            decision.reason, "COMMON_RISING_HOLD",
            "ma10/ma20 만으로 상승보유가 다시 켜졌다 — 우회 가지가 되살아났다",
        )

        # 반대쪽도 함께 잠근다: 매수세 우위까지 확인된 daily_ma_permit 이면
        # 상승보유는 종전대로 나와야 한다(①을 실수로 같이 없애지 않았는지).
        permitted = engine.evaluate(
            HoldSellState(
                position_id="s02-support-permit",
                strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
                code="123456",
                quantity=1,
                entry_price="100",
                entry_at=self.now,
            ),
            HoldSellObservation(
                observed_at=self.now + timedelta(seconds=20),
                price="99.2",
                buy_money_per_sec_10s="100",
                sell_money_per_sec_10s="180",
                buy_volume_per_sec_5s="100",
                sell_volume_per_sec_5s="200",
                sell_volume_per_sec_previous_10s="100",
                che_str="90",
                che_str_change_5s="-10",
                one_minute_bull_to_bear=True,
                daily_ma5_broken=True,
                ma10_support=True,
                ma20_rising=True,
                common_peak_flow_ready=True,
                daily_ma_permit=True,
            ),
        )
        self.assertEqual(permitted.action, HoldSellAction.HOLD)
        self.assertEqual(
            permitted.reason, "COMMON_RISING_HOLD",
            "daily_ma_permit(선 지지 AND 매수세 우위) 상승보유까지 사라졌다",
        )

    def test_s02_ma20_defense_holds_shallow_loss_but_not_hard_stop(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = build_config()
            config = replace(
                base,
                signal_path=root / "signal.json",
                snapshot_path=root / "snapshot.json",
                board_path=root / "board.json",
                bars_path=root / "bars.json",
                eod_bars_path=root / "eod.csv",
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
            config.signal_path.write_text(
                json.dumps(self.signal_payload()), encoding="utf-8")
            config.names_path.write_text("{}", encoding="utf-8")
            daily = ["code,date,close"]
            daily.extend(
                f"123456,202607{day:02d},{10000 + 5 * (day - 1)}"
                for day in range(1, 22)
            )
            config.eod_bars_path.write_text(
                "\n".join(daily) + "\n", encoding="utf-8")

            broker = FakeBroker()
            logger = logging.getLogger("strategy02-flow-roundtrip")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            engine = Strategy02Engine(
                config,
                broker=broker,
                slots=FakeSlots(),
                logger=logger,
                signal_selector=select_fresh_signals,
            )

            def write_market(
                sec, price, buy_money, sell_money,
                buy_volume, sell_volume, che_str, bearish,
            ):
                observed_at = self.now + timedelta(seconds=sec)
                stamp = observed_at.replace(tzinfo=None).isoformat(
                    timespec="seconds")
                config.snapshot_path.write_text(json.dumps({"codes": {
                    "123456": {
                        "ts": stamp,
                        "cur": price,
                        "cum_vol": buy_volume + sell_volume,
                        "buy_vol_cum": buy_volume,
                        "sell_vol_cum": sell_volume,
                        "buy_money_cum": buy_money,
                        "sell_money_cum": sell_money,
                        "che_str": che_str,
                    },
                }}), encoding="utf-8")
                config.board_path.write_text(json.dumps({
                    "ts": stamp,
                    "all_items": [{
                        "code": "123456",
                        "money_speed_5s": 2_000_000,
                        "money_speed_10s": 1_800_000,
                        "money_speed_30s": 1_500_000,
                    }],
                }), encoding="utf-8")
                current_close = price if bearish else 10_080
                config.bars_path.write_text(json.dumps({"m": {
                    "123456": {
                        "o": 10_050,
                        "h": 10_100,
                        "l": min(price, 10_040),
                        "c": current_close,
                        "bull": 0 if bearish else 1,
                        "prev": [[10_000, 10_050, 9_990, 10_040]],
                    },
                }}), encoding="utf-8")
                return observed_at

            entry_at = write_market(
                0, 10_100, 20_000_000, 10_000_000,
                1_000, 1_000, 110, False)
            engine.tick(entry_at)
            self.assertEqual(
                engine._active_positions()["123456"]["phase"], "HOLD")

            sequence = [
                (5, 10_080, 25_000_000, 15_000_000, 1_500, 1_500, 108),
                (10, 10_060, 30_000_000, 20_000_000, 2_000, 2_000, 105),
                (13, 10_040, 33_000_000, 23_000_000, 2_300, 2_300, 102),
                (15, 10_020, 34_000_000, 27_000_000, 2_400, 2_600, 100),
                (18, 10_020, 35_000_000, 35_000_000, 2_550, 3_000, 98),
                (20, 10_020, 36_000_000, 42_000_000, 2_650, 3_500, 93),
                (21, 10_020, 36_500_000, 46_000_000, 2_700, 3_800, 92),
                (22, 10_020, 37_000_000, 50_000_000, 2_750, 4_100, 91),
                (23, 10_020, 37_500_000, 54_000_000, 2_800, 4_400, 90),
                # MA10 지지 중 약한 역전은 확정값 6초를 채운 뒤 매도한다.
                (24, 10_020, 38_000_000, 58_000_000, 2_850, 4_700, 89),
            ]
            for sec, price, buy_money, sell_money, buy_vol, sell_vol, strength in sequence:
                observed_at = write_market(
                    sec, price, buy_money, sell_money,
                    buy_vol, sell_vol, strength, sec >= 15)
                engine.tick(observed_at)

            active = engine._active_positions()
            self.assertIn("123456", active)
            self.assertFalse(active["123456"]["hold_state"]["sell_latched"])

            # 20선 방어는 얕은 손실만 보유한다. -2% 보험선은 항상 우선한다.
            hard_stop_at = write_market(
                25, 9_890, 38_500_000, 62_000_000,
                2_900, 5_000, 88, True,
            )
            engine.tick(hard_stop_at)
            self.assertEqual(engine._active_positions(), {})
            trade = engine.state["history"][-1]
            self.assertIn("HARD_STOP", trade["exit_reason"])
            self.assertLessEqual(trade["gross_return_pct"], -2.0)
            self.assertEqual(trade["exit_price"], 9_890)
            self.assertTrue(all(
                row.get("side") == "BUY" for row in broker.submissions))
            self.assertFalse(broker.real_session)

    def test_live_buy_requires_approval_and_off_removed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            off = root / "off.flag"
            approval = root / "approval.flag"
            off.write_text("OFF", encoding="utf-8")
            logger = logging.getLogger("strategy02-safety-test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            broker = StrategyBroker(
                live_requested=True,
                approval_path=approval,
                off_flag_path=off,
                manual_buy_block_path=root / "manual.flag",
                logger=logger,
                order_prefix="STRATEGY02",
            )
            self.assertFalse(broker.real_session)
            self.assertEqual(broker.submit(
                side="BUY", code="123456", quantity=1,
                idempotency_key="test:no-approval"), "SHADOW")
            approval.write_text(
                f"APPROVED_BY_OWNER {datetime.now():%Y%m%d %H:%M:%S}\n",
                encoding="ascii")
            self.assertTrue(broker.real_session)
            self.assertFalse(broker.buy_allowed)
            self.assertEqual(broker.submit(
                side="BUY", code="123456", quantity=1,
                idempotency_key="test:off"), "BLOCKED")
            self.assertIsNone(broker.client)

    def test_production_identity_and_time_window(self) -> None:
        config = build_config()
        self.assertEqual(config.strategy_id, StrategyId.S02_LOW_BUY_SELL_EXHAUSTION)
        self.assertEqual(config.strategy_slug, "strategy02")
        # 아침 시가 -3% 조건과 동일하게 주문기도 09:00부터 연다.
        self.assertEqual(config.entry_start.isoformat(), "09:00:00")
        self.assertEqual(config.entry_end.isoformat(), "14:20:00")
        # ★[2026-08-06 친구님 지시 "QTY 2주 원래대로 1주로 돌려줘"] 2 -> 1.
        self.assertEqual(config.quantity, 1)
        self.assertEqual(config.max_daily_codes, 15)
        self.assertEqual(config.max_cycles_per_code, 2)
        self.assertEqual(config.rotation_capital_krw, 2_000_000)


if __name__ == "__main__":
    unittest.main()
