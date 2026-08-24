# -*- coding: utf-8 -*-
"""공통 직접반등 판정(low_rebound_common_v1) 집중 테스트."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

import low_rebound_common_v1 as lrc
from low_rebound_common_v1 import (
    DIRECT_LANE,
    RETEST_LANE,
    DirectReboundConfig,
    judge_direct_rebound,
)

T0 = datetime(2026, 8, 13, 9, 30, 0)


def base_kwargs(**overrides):
    values = dict(
        confirm_hits=0,
        last_confirm_ts=None,
        cfg=DirectReboundConfig(first_rebound_pct=1.0, chase_cap_pct=2.0,
                                confirm_ticks=2),
        ts=T0,
        price=101.2,          # 저점 100 대비 +1.2% (문턱 1.0~상한 2.0 사이)
        low_price=100.0,
        no_new_low_sec=20.0,
        drop_ok=True,
        flow_flip=True,
        flow_accel=True,
        money_buy_turn=True,
        volume_buy_turn=True,
        sell_restrength=False,
        che_rising=True,
    )
    values.update(overrides)
    return values


class DirectReboundTests(unittest.TestCase):
    def test_direct_rebound_without_pullback_passes_after_confirm_ticks(self):
        with patch.object(lrc, "DIRECT_ENABLED", True):
            first = judge_direct_rebound(**base_kwargs())
            self.assertFalse(first["ready"])
            self.assertIn("CONFIRM_TICKS_PENDING", first["fail"])
            second = judge_direct_rebound(**base_kwargs(
                confirm_hits=first["confirm_ticks"],
                last_confirm_ts=first["last_confirm_ts"],
                ts=T0 + timedelta(seconds=2),
            ))
            self.assertTrue(second["ready"])
            self.assertTrue(second["allow"])
            self.assertEqual(second["lane"], DIRECT_LANE)

    def test_sell_dominance_blocks(self):
        verdict = judge_direct_rebound(**base_kwargs(money_buy_turn=False))
        self.assertFalse(verdict["ready"])
        self.assertIn("MONEY_BUY_TURN_ABSENT", verdict["fail"])
        self.assertEqual(verdict["confirm_ticks"], 0)

    def test_sell_restrength_blocks(self):
        verdict = judge_direct_rebound(**base_kwargs(sell_restrength=True))
        self.assertIn("SELL_RESTRENGTH_PRESENT", verdict["fail"])
        self.assertFalse(verdict["ready"])

    def test_fresh_new_low_blocks_and_resets_confirm(self):
        # 신저점 직후(경과 2초) = 갱신 중단으로 인정 불가 → 차단 + 확인 초기화.
        verdict = judge_direct_rebound(**base_kwargs(
            confirm_hits=1, last_confirm_ts=T0 - timedelta(seconds=2),
            no_new_low_sec=2.0,
        ))
        self.assertIn("LOW_TOO_FRESH", verdict["fail"])
        self.assertEqual(verdict["confirm_ticks"], 0)

    def test_chase_cap_blocks(self):
        verdict = judge_direct_rebound(**base_kwargs(price=102.5))
        self.assertIn("ABOVE_CHASE_CAP", verdict["fail"])
        self.assertFalse(verdict["chase_cap_pass"])
        self.assertFalse(verdict["ready"])

    def test_exact_half_percent_boundary_passes_and_over_cap_blocks(self):
        cfg = DirectReboundConfig(
            first_rebound_pct=0.5, chase_cap_pct=1.5, confirm_ticks=1,
            volume_turn_required=False,
        )
        lower = judge_direct_rebound(**base_kwargs(
            cfg=cfg, price=100.5, volume_buy_turn=None,
        ))
        upper = judge_direct_rebound(**base_kwargs(
            cfg=cfg, price=101.5, volume_buy_turn=None,
        ))
        over = judge_direct_rebound(**base_kwargs(
            cfg=cfg, price=101.501, volume_buy_turn=None,
        ))
        self.assertTrue(lower["ready"])
        self.assertTrue(upper["ready"])
        self.assertIn("ABOVE_CHASE_CAP", over["fail"])

    def test_missing_data_fails_closed(self):
        verdict = judge_direct_rebound(**base_kwargs(flow_flip=None))
        self.assertIn("DATA_MISSING:flow_flip", verdict["fail"])
        self.assertFalse(verdict["ready"])

    def test_env_off_keeps_ready_but_blocks_allow(self):
        with patch.object(lrc, "DIRECT_ENABLED", False):
            first = judge_direct_rebound(**base_kwargs())
            second = judge_direct_rebound(**base_kwargs(
                confirm_hits=first["confirm_ticks"],
                last_confirm_ts=first["last_confirm_ts"],
                ts=T0 + timedelta(seconds=2),
            ))
            self.assertTrue(second["ready"])
            self.assertFalse(second["allow"])

    def test_same_inputs_same_policy_for_s02_and_s06_configs(self):
        # S06 은 체결량 분리 원천이 없어 volume_turn_required=False 만 다르다.
        s02_cfg = DirectReboundConfig(1.0, 2.0, confirm_ticks=1)
        s06_cfg = DirectReboundConfig(1.0, 2.0, confirm_ticks=1,
                                      volume_turn_required=False)
        v_s02 = judge_direct_rebound(**base_kwargs(cfg=s02_cfg))
        v_s06 = judge_direct_rebound(**base_kwargs(cfg=s06_cfg,
                                                   volume_buy_turn=None))
        self.assertEqual(v_s02["ready"], v_s06["ready"])
        self.assertEqual(v_s02["rebound_pct"], v_s06["rebound_pct"])
        self.assertEqual(v_s02["fail"], v_s06["fail"])

    def test_lane_constants(self):
        self.assertEqual(DIRECT_LANE, "DIRECT_REBOUND")
        self.assertEqual(RETEST_LANE, "RETEST_REBOUND")


class WiringSourceTests(unittest.TestCase):
    """전략 파일이 공통 모듈을 호출하고, 판정 코드를 복사하지 않았는지 소스 검사."""

    S02 = RUN / "strategy_02_low_buy_signal_v1.py"
    S06 = RUN / "strategy_06_crash_low_chase_v1.py"

    def test_both_strategies_call_shared_judge(self):
        for path in (self.S02, self.S06):
            text = path.read_text(encoding="utf-8")
            self.assertIn("judge_direct_rebound(", text, path.name)
            self.assertIn("from low_rebound_common_v1 import", text, path.name)
            self.assertNotIn("def judge_direct_rebound", text, path.name)

    def test_strategy_specific_thresholds_preserved(self):
        s02 = self.S02.read_text(encoding="utf-8")
        self.assertIn("first_rebound_pct=SIX_FIRST_REBOUND_PCT", s02)
        self.assertIn("chase_cap_pct=SIX_CHASE_CAP_PCT", s02)
        s06 = self.S06.read_text(encoding="utf-8")
        self.assertIn("first_rebound_pct=self.config.rebound_pct", s06)
        self.assertIn("chase_cap_pct=self.config.chase_cap_pct", s06)
        self.assertIn("volume_turn_required=False", s06)


if __name__ == "__main__":
    unittest.main()
