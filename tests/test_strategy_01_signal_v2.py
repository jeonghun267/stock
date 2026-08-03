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
        #   하는 시세로는 가격조건(시가 대비 -1.5% 밀림)을 통과하지 못한다.
        #   시가 50,000 → 저점 49,000(-2.0%) → 초당 +100원씩 되돌아오는 시세로 교체.
        #   second 4 에서 저점 +0.61%(반등 확인) · second 5 에서 관측 5초 충족 → 발사.
        price = 50_000 if second == 0 else 49_000 + max(0, second - 1) * 100
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

    def test_real_strategy_waits_for_complete_five_second_flow_window(self) -> None:
        monitor = OpenSurgeShadowMonitor()

        for second in range(5):
            monitor.process_points([self.point(second)])
        self.assertEqual(
            monitor.latest["123450"]["reason"],
            "FLOW_WINDOW_WARMING_UP",
        )

        emitted = monitor.process_points([self.point(5)])

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["flow_observation_sec"], 5.0)

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
