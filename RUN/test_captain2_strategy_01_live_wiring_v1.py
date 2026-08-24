# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, time as day_time
from pathlib import Path
from types import SimpleNamespace

import CAPTAIN2_MONEYFLOW_ENGINE_V1 as M
from captain2_common_hold_sell_v1 import (
    STRATEGY_PROFILES,
    StrategyId,
    UnifiedHoldSellEngine,
)
from valley_common_exit_shadow_v1 import SideWindows


def point(now: datetime, code: str = "123456", price: float = 10_000) -> M.MarketPoint:
    return M.MarketPoint(
        ts=now,
        code=code,
        price=price,
        cum_vol=100_000,
        che_str=120,
        money_speed_5s=2_000_000,
        money_speed_10s=1_800_000,
        money_speed_30s=1_500_000,
        buy_vol_cum=70_000,
        sell_vol_cum=30_000,
        buy_money_cum=700_000_000,
        sell_money_cum=300_000_000,
    )


class FakeExecution:
    last_error_detail = ""

    def __init__(self) -> None:
        self.buys: list[tuple[str, int]] = []

    def buy(self, code: str, qty: int) -> str:
        self.buys.append((code, qty))
        return "SHADOW"


class C201LiveWiringTests(unittest.TestCase):
    def test_fresh_signal_is_consumed_once(self) -> None:
        now = datetime.now().replace(microsecond=0)
        with tempfile.TemporaryDirectory() as folder:
            signal_path = Path(folder) / "signal.json"
            signal_path.write_text(json.dumps({
                "schema": "captain2_c2_01_shadow_v1",
                "date": now.strftime("%Y%m%d"),
                "updated_at": now.isoformat(timespec="seconds"),
                "mode": "SHADOW_ORDER_ZERO",
                "signals": [{
                    "ts": now.isoformat(timespec="seconds"),
                    "code": "123456",
                    "action": "BUY_READY",
                    "reason": "TEST",
                    "mode": "SHADOW_ORDER_ZERO",
                    "buy_ratio": 0.72,
                    "money_speed_5s": 2_000_000,
                    "theme_bonus": 0,
                }],
            }), encoding="utf-8")

            engine = object.__new__(M.Captain2Engine)
            engine.cfg = SimpleNamespace(
                c2_01_signal_path=signal_path,
                c2_01_signal_max_age_sec=5,
                c2_01_max_order_attempts=1,
            )
            engine.states = {}
            engine.feed = SimpleNamespace(names={"123456": "테스트"})
            engine.c2_01_consumed_signals = set()
            engine.c2_01_order_attempts = 0
            events: list[str] = []
            opened: list[tuple[str, int]] = []
            engine._event = lambda _p, _s, event, _reason: events.append(event)

            def open_once(p: M.MarketPoint, state: M.FlowState, _reason: str) -> None:
                opened.append((p.code, 1))
                state.phase = M.Phase.BUY_PENDING

            engine._open = open_once
            points = {"123456": point(now)}
            M.Captain2Engine._c2_01_signal_step(engine, points)
            M.Captain2Engine._c2_01_signal_step(engine, points)

            self.assertEqual(opened, [("123456", 1)])
            self.assertEqual(engine.c2_01_order_attempts, 1)
            self.assertEqual(engine.states["123456"].lane, "C2_01_OPEN_SURGE")
            self.assertEqual(events.count("C2_01_SIGNAL"), 1)

    def test_existing_order_path_receives_exactly_one_share_in_shadow(self) -> None:
        now = datetime.now().replace(microsecond=0)
        engine = object.__new__(M.Captain2Engine)
        engine.cfg = SimpleNamespace(
            qty_fixed=1,
            max_active_capital_krw=2_000_000,
            live=False,
        )
        engine.execution = FakeExecution()
        engine._capital_in_use_krw = lambda: 0
        engine._can_open = lambda _code: (True, "OK")
        engine._reentry_ok = lambda _p, _state: (True, "")
        engine._event = lambda *_args: None
        confirmed: list[tuple[int, bool]] = []
        engine._confirm_entry = (
            lambda _p, _state, qty, _price, _reason, shadow=False:
            confirmed.append((qty, shadow))
        )
        state = M.FlowState(
            code="123456",
            phase=M.Phase.BUY_READY,
            lane="C2_01_OPEN_SURGE",
        )
        M.Captain2Engine._open(engine, point(now), state, "TEST")
        self.assertEqual(engine.execution.buys, [("123456", 1)])
        self.assertEqual(confirmed, [(1, True)])

    def test_c2_lane_routes_to_common_exit_and_not_legacy_exit(self) -> None:
        now = datetime.now().replace(microsecond=0)
        engine = object.__new__(M.Captain2Engine)
        engine._vi_track = lambda *_args: None
        engine._c2_01_common_exit = lambda *_args: ("HARD_STOP -2.00% <= -2.00%", "FLOW_WARMUP")
        events: list[str] = []
        closed: list[str] = []
        engine._event = lambda _p, _s, event, _reason: events.append(event)
        engine._close = lambda _p, _s, reason: closed.append(reason)
        state = M.FlowState(
            code="123456",
            phase=M.Phase.HOLD,
            lane="C2_01_OPEN_SURGE",
            entry_price=10_000,
            qty=1,
        )
        M.Captain2Engine._hold_or_sell(engine, point(now, price=9_800), state)
        self.assertEqual(closed, ["HARD_STOP -2.00% <= -2.00%"])
        self.assertEqual(events, ["C2_01_COMMON_EXIT"])

    def test_common_engine_actual_hard_stop_and_1510_profile(self) -> None:
        now = datetime.now().replace(microsecond=0)
        engine = object.__new__(M.Captain2Engine)
        engine._c2_01_common_engine = UnifiedHoldSellEngine()
        engine._c2_01_common_windows = SideWindows()
        engine._c2_01_exit_error = ""
        engine._c2_01_bars_payload = lambda: {}
        engine.log = SimpleNamespace(warning=lambda *_args: None)
        state = M.FlowState(
            code="123456",
            phase=M.Phase.HOLD,
            lane="C2_01_OPEN_SURGE",
            entry_ts=now,
            entry_price=10_000,
            qty=1,
        )
        reason, _quality = M.Captain2Engine._c2_01_common_exit(
            engine, point(now, price=9_800), state)
        self.assertTrue(reason and reason.startswith("HARD_STOP"))
        self.assertEqual(
            STRATEGY_PROFILES[StrategyId.C2_01_OPEN_SURGE].force_exit_at,
            day_time(15, 10),
        )


if __name__ == "__main__":
    unittest.main()
