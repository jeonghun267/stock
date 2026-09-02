# -*- coding: utf-8 -*-
# ★[2026-08-26 이사] 8/25 MA10-3S 세션이 RUN\test_strategy_06_exit_policy_v2.py 로
#   남긴 작업 사본을 tests\ 정위치로 편입 — 마감 창(1510/1520)·밤샘 평탄화·
#   하드스톱 우선순위 검증 8건. RUN 에 있던 동안 tests\ 동명 모듈과 이름이
#   충돌해 다른 세션의 테스트 실행을 깨뜨렸다(19:55 Codex 사전점검 보고).
import unittest
from datetime import time
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_06_exit_policy_v2 import ExitObservation, decide_exit
import strategy_06_crash_low_chase_v1  # noqa: F401 - validates production wiring import


def observation(**overrides):
    values = dict(
        price=101.0,
        entry_price=100.0,
        anchor_low=97.0,
        peak_price=101.0,
        atr_3m_pct=0.5,
        ma5=100.5,
        ma5_prev=100.0,
        ma10=99.5,
        ma20=99.0,
        ma20_prev=98.8,
        buy_rate_10s=200.0,
        sell_rate_10s=100.0,
        buy_side_alive=True,
        buy_ratio_10s=0.67,
        observed_time=time(10, 0),
        same_day=True,
    )
    values.update(overrides)
    return ExitObservation(**values)


class Strategy06ExitPolicyTests(unittest.TestCase):
    def test_production_entry_band_matches_approved_contract(self):
        config = strategy_06_crash_low_chase_v1.Config()
        # ★[2026-08-26 현행화] chase_cap 2.0→2.5 는 8/26 10:15 친구님 실전 지시
        #   (이 사본이 8/25 작성이라 옛 값이었음).
        self.assertEqual(
            (config.rebound_pct, config.entry_floor_pct, config.chase_cap_pct),
            (1.5, 1.0, 2.5),
        )

    def test_five_percent_is_not_fixed_take_profit(self):
        decision = decide_exit(observation(price=105.0, peak_price=105.0))
        self.assertEqual((decision.action, decision.reason), ("HOLD", "NO_EXIT"))

    def test_rising_hold_can_pass_1510(self):
        decision = decide_exit(observation(observed_time=time(15, 10)))
        self.assertEqual((decision.action, decision.reason), ("HOLD", "NO_EXIT"))

    def test_1520_is_unconditional_flat(self):
        decision = decide_exit(observation(observed_time=time(15, 20)))
        self.assertEqual((decision.action, decision.reason), ("SELL", "HARD_FLAT_1520"))

    def test_legacy_overnight_is_flattened(self):
        decision = decide_exit(observation(same_day=False, observed_time=time(9, 0)))
        self.assertEqual(
            (decision.action, decision.reason),
            ("SELL", "LEGACY_OVERNIGHT_FLAT_0900"),
        )

    def test_1510_hold_requires_full_ma_stack(self):
        decision = decide_exit(observation(observed_time=time(15, 10), ma20=100.0))
        self.assertEqual(
            (decision.action, decision.reason),
            ("SELL", "CLOSE_PROTECT_1510"),
        )

    def test_hard_stop_has_priority(self):
        decision = decide_exit(observation(price=98.0, observed_time=time(9, 5)))
        self.assertEqual((decision.action, decision.reason), ("SELL", "HARD_STOP_2"))

    def test_production_engine_flattens_legacy_overnight_at_open(self):
        engine = object.__new__(strategy_06_crash_low_chase_v1.Strategy06Engine)
        engine.config = SimpleNamespace(morning_sell_start=time(9, 0))
        point = {
            "price": 99.0,
            "ts": datetime(2026, 8, 24, 9, 2, tzinfo=ZoneInfo("Asia/Seoul")),
        }
        engine._snapshot_point = lambda *_args: point
        engine._update_excursion = lambda *_args: None
        calls = []
        engine._start_sell = lambda _p, _n, reason, _point: calls.append(reason)
        position = {
            "code": "310210", "entry_price": 100.0, "entry_day": "20260820",
            "last_price": 100.0, "retry_after_epoch": 0,
        }
        engine._evaluate_exit(position, point["ts"])
        self.assertEqual(calls, ["LEGACY_OVERNIGHT_FLAT_0900"])


if __name__ == "__main__":
    unittest.main()
