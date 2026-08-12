# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from strategy_01_open_surge_signal_v2 import (
    BuyAction,
    OpenSurgeShadowMonitor,
    ShadowPoint,
    _book_telemetry,
)


class SequenceStrategy:
    def __init__(self, actions):
        self.actions = iter(actions)

    def evaluate(self, _observation):
        action = next(self.actions)
        return SimpleNamespace(
            action=action,
            reason=action.value,
            gap_pct=0,
            priority_bonus=0,
        )


class Strategy01SignalV2Tests(unittest.TestCase):
    def point(self, second: int) -> ShadowPoint:
        # ★[2026-07-31] 매수규칙이 "급상승 추격"→"되돌림 진입"으로 바뀌어, 계속 오르기만
        #   하는 시세로는 가격조건(시가 대비 밀림)을 통과하지 못한다.
        #   ★[2026-08-03 밀림 문턱 -1.5% → -3.0%] 저점도 그만큼 깊게 잡았다.
        #   시가 50,000 → 저점 48,250(-3.5%) → 초당 +100원씩 되돌아오는 시세.
        #   second 4 에서 저점 +0.62%(반등 확인) · second 5 에서 관측 5초 충족 → 발사.
        price = 50_000 if second == 0 else 48_250 + max(0, second - 1) * 100
        return ShadowPoint(
            ts=datetime(2026, 7, 27, 9, 0, second),
            code="123450",
            name="TEST",
            previous_close=50_000,
            price=price,
            money_speed_5s=2_000_000,
            money_speed_30s=1_500_000,
            buy_money_cum=1_000_000 + second * 750_000,
            sell_money_cum=1_000_000 + second * 250_000,
            exact_flow=True,
        )

    def staged_point(self, second: int) -> ShadowPoint:
        if second == 0:
            price = 50_000
        elif second <= 10:
            # S01 구간 안의 얕은 눌림: 시가 50,000 -> 저점 49,000(-2%).
            price = 50_000 - second * 100
        elif second < 15:
            price = 49_000 + (second - 10) * 80
        elif second == 15:
            price = 49_500
        elif second == 16:
            # EARLY_FLOW는 연속 2틱 확인이 필요하다.
            price = 49_650
        elif second == 17:
            price = 49_760
        else:
            price = 49_800
        if second <= 10:
            buy_cum = 1_000_000 + second * 100_000
            sell_cum = 1_000_000 + second * 100_000
            cum_vol = 1_000 + second * 10
            che_str = 100
        else:
            buy_cum = 2_000_000 + (second - 10) * 2_000_000
            sell_cum = 2_000_000 + (second - 10) * 400_000
            cum_vol = 1_100 + (second - 10) * 100
            che_str = 100 + second - 10
        return ShadowPoint(
            ts=datetime(2026, 7, 27, 9, 0, second),
            code="123450",
            name="TEST",
            previous_close=50_000,
            price=price,
            money_speed_5s=2_000_000,
            money_speed_30s=1_500_000,
            buy_money_cum=buy_cum,
            sell_money_cum=sell_cum,
            exact_flow=True,
            che_str=che_str,
            cum_vol=cum_vol,
            order_book_fresh=True,
        )

    def straight_rise_point(self, second: int) -> ShadowPoint:
        """강한 수급이어도 시가 아래 눌림이 전혀 없는 직선 상승."""
        return ShadowPoint(
            ts=datetime(2026, 7, 27, 9, 0, second),
            code="654321",
            name="NO_PULLBACK",
            previous_close=50_000,
            price=50_000 + second * 75,
            money_speed_5s=2_000_000,
            money_speed_30s=1_500_000,
            buy_money_cum=1_000_000 + second * 2_000_000,
            sell_money_cum=1_000_000 + second * 400_000,
            exact_flow=True,
            che_str=100 + second,
            cum_vol=1_000 + second * 100,
            order_book_fresh=True,
        )

    def above_open_rebreak_point(self, second: int) -> ShadowPoint:
        """시가 위 상승 뒤 실제 되밀림과 강한 재돌파가 나오는 그림자 시나리오."""
        if second <= 10:
            price = 50_000 + second * 60
            buy_cum = 1_000_000 + second * 100_000
            sell_cum = 1_000_000 + second * 100_000
            cum_vol = 1_000 + second * 10
            che_str = 100
        else:
            prices = {
                11: 50_500, 12: 50_450, 13: 50_500,
                14: 50_550, 15: 50_600, 16: 50_650,
            }
            price = prices.get(second, 50_700)
            buy_cum = 2_000_000 + (second - 10) * 2_000_000
            sell_cum = 2_000_000 + (second - 10) * 400_000
            cum_vol = 1_100 + (second - 10) * 100
            che_str = 100 + second - 10
        return ShadowPoint(
            ts=datetime(2026, 7, 27, 9, 0, second),
            code="777777",
            name="ABOVE_REBREAK",
            previous_close=50_000,
            price=price,
            money_speed_5s=2_000_000,
            money_speed_30s=1_500_000,
            buy_money_cum=buy_cum,
            sell_money_cum=sell_cum,
            exact_flow=True,
            che_str=che_str,
            cum_vol=cum_vol,
            order_book_fresh=True,
        )

    def test_reformed_opportunity_emits_at_most_two_times(self) -> None:
        actions = []
        for _ in range(7):
            actions.extend([BuyAction.BUY_READY, BuyAction.WAIT])
        monitor = OpenSurgeShadowMonitor(
            SequenceStrategy(actions),
            max_signals_per_code=2,
        )

        emitted = []
        for second in range(14):
            emitted.extend(monitor.process_points([self.point(second)]))

        self.assertEqual(len(emitted), 2)
        self.assertEqual(
            [row["signal_sequence"] for row in emitted],
            [1, 2],
        )

    def test_restart_does_not_refire_still_latched_condition(self) -> None:
        monitor = OpenSurgeShadowMonitor(
            SequenceStrategy([
                BuyAction.BUY_READY,
                BuyAction.WAIT,
                BuyAction.BUY_READY,
            ]),
            max_signals_per_code=2,
        )
        monitor.restore_emitted({
            "date": "20260727",
            "signals": [{
                "code": "123450",
                "action": "BUY_READY",
                "signal_sequence": 1,
            }],
            "candidates": [{
                "code": "123450",
                "action": "BUY_READY",
            }],
        }, "20260727")

        self.assertEqual(monitor.process_points([self.point(0)]), [])
        self.assertEqual(monitor.process_points([self.point(1)]), [])
        emitted = monitor.process_points([self.point(2)])

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["signal_sequence"], 2)

    def test_real_strategy_emits_early_then_strong_one_share_stages(self) -> None:
        monitor = OpenSurgeShadowMonitor()
        emitted = []
        for second in range(19):
            emitted.extend(monitor.process_points([self.staged_point(second)]))

        self.assertEqual(
            [row["entry_stage"] for row in emitted],
            ["EARLY_FLOW", "STRONG_FLOW"],
        )
        self.assertEqual(
            [row["requested_quantity"] for row in emitted],
            [1, 1],
        )
        self.assertTrue(1.0 <= emitted[0]["rebound_pct"] <= 1.5)
        self.assertTrue(1.5 <= emitted[1]["rebound_pct"] <= 2.5)

    def test_straight_rise_cannot_emit_early_or_strong_stage(self) -> None:
        monitor = OpenSurgeShadowMonitor()
        emitted = []
        for second in range(20):
            emitted.extend(monitor.process_points([self.straight_rise_point(second)]))
        self.assertEqual(emitted, [])
        self.assertEqual(monitor.shadow_signals, [])

    def test_above_open_pullback_rebreak_is_shadow_only(self) -> None:
        monitor = OpenSurgeShadowMonitor()
        live_emitted = []
        for second in range(18):
            live_emitted.extend(
                monitor.process_points([self.above_open_rebreak_point(second)])
            )
        self.assertEqual(live_emitted, [])
        self.assertEqual(len(monitor.shadow_signals), 1)
        row = monitor.shadow_signals[0]
        self.assertEqual(row["reason"], "ABOVE_OPEN_REBREAK_CONFIRMED")
        self.assertEqual(row["requested_quantity"], 0)
        self.assertEqual(row["mode"], "SHADOW_ORDER_ZERO")

    def test_fresh_order_book_is_exposed_as_shadow_telemetry(self) -> None:
        now = datetime(2026, 7, 27, 9, 0, 5)
        fresh, bid_share, spread_bps, edge_bps = _book_telemetry(
            {
                "ob_ts": now.isoformat(),
                "ask_tot": 40_000,
                "bid_tot": 60_000,
                "best_ask_px": 10_060,
                "best_bid_px": 10_050,
                "best_ask_qty": 400,
                "best_bid_qty": 600,
            },
            now,
            5.0,
        )

        self.assertTrue(fresh)
        self.assertAlmostEqual(bid_share, 0.6)
        self.assertGreater(spread_bps, 0)
        self.assertGreater(edge_bps, 0)



if __name__ == "__main__":
    unittest.main()
