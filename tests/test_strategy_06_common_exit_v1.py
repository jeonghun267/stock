# -*- coding: utf-8 -*-
"""S06 매도 = S02 동일 엔진·동일 정책 배선 집중 단위테스트 (주문 0·그림자).

[2026-08-25 친구님 지시] "S06 매도를 규칙 복사가 아니라 S02가 쓰는
strategy_common_hold_sell_v1.py 의 동일 엔진·동일 정책으로 연결하라."

이 테스트가 지키는 것:
  ① S06 프로필이 S02 와 글자 그대로 같은가 (드리프트 방지)
  ② 체결 -> 매도상태 생성 -> 저장 -> 재기동 복구가 이어지는가
  ③ 매도 판정이 공통 엔진에서 나오는가 (종전 exit_policy_v2 경로 사용 중지)
  ④ 부분매도가 S02 와 같은 모양인가
  ⑤ 진입·수량·강제청산(15:20)이 종전 그대로인가
"""
import json
import sys
import tempfile
import unittest
from dataclasses import fields
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

import strategy_06_crash_low_chase_v1 as s06  # noqa: E402
from hold_sell_audit_v1 import HoldSellAuditRecorder  # noqa: E402
from strategy_06_common_exit_adapter_v1 import (  # noqa: E402
    HOLD_STATES_KEY,
    Strategy06CommonExitAdapter,
)
from strategy_common_hold_sell_v1 import (  # noqa: E402
    S02_POLICY_STRATEGIES,
    STRATEGY_PROFILES,
    HoldSellState,
    StrategyId,
)

KST = ZoneInfo("Asia/Seoul")
CODE = "477850"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ProfileMappingTest(unittest.TestCase):
    """① 공통 파일에 더한 것이 'S06 등록 + S02 동일 정책 매핑' 뿐인가."""

    def test_s06_profile_is_identical_to_s02(self) -> None:
        s02 = STRATEGY_PROFILES[StrategyId.S02_LOW_BUY_SELL_EXHAUSTION]
        s06 = STRATEGY_PROFILES[StrategyId.S06_CRASH_LOW_CHASE]
        for field in fields(s02):
            if field.name == "strategy_id":
                continue
            self.assertEqual(
                getattr(s02, field.name), getattr(s06, field.name),
                f"S06 프로필 {field.name} 이 S02 와 다르다 = 규칙 복사가 시작된 것",
            )

    def test_s02_policy_set_is_exactly_s02_and_s06(self) -> None:
        """id 로 걸린 S02 전용 규칙 3곳이 S02·S06 에만 열려 있어야 한다."""
        self.assertEqual(
            S02_POLICY_STRATEGIES,
            frozenset({
                StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
                StrategyId.S06_CRASH_LOW_CHASE,
            }),
        )
        for other in (
            StrategyId.S01_OPEN_SURGE,
            StrategyId.S04_PULLBACK,
            StrategyId.S05_BASE_BREAKOUT,
        ):
            self.assertNotIn(other, S02_POLICY_STRATEGIES)

    def test_every_strategy_still_has_a_profile(self) -> None:
        self.assertEqual(set(STRATEGY_PROFILES), set(StrategyId))


class Strategy06ExitWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.base = base
        self.now = datetime(2026, 8, 25, 10, 0, 0, tzinfo=KST)
        self.today = self.now.strftime("%Y%m%d")
        self.config = s06.Config(
            watch_path=base / "watch.json",
            hr_state_path=base / "hr_state.json",
            snapshot_path=base / "snapshot.json",
            bars_path=base / "bars.json",
            eod_bars_path=base / "eod.csv",
            names_path=base / "names.json",
            state_path=base / "state.json",
            fills_dir=base / "LOG",
            event_dir=base / "events",
            log_path=base / "engine.log",
            approval_path=base / "approve.flag",
            off_flag_path=base / "off.flag",
            manual_buy_block_path=base / "block.flag",
            lock_path=base / "engine.lock",
            live_requested=False,
            early_entry_cap_pct=0.0,
        )
        write_json(self.config.watch_path, {
            "codes": [CODE], "crown_codes": [CODE],
            "for_date": self.today, "source_stale": False,
        })
        self.engine = self._engine()

    def _engine(self) -> "s06.Strategy06Engine":
        engine = s06.Strategy06Engine(self.config)
        # 감사기록은 실전 폴더로 나간다. 시험에서는 끈다(판정에는 영향 없음).
        engine.exit_engine.audit_recorder = HoldSellAuditRecorder.disabled()
        return engine

    def tearDown(self) -> None:
        import logging
        logger = logging.getLogger(self.config.strategy_slug)
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        self.temp.cleanup()

    # ── 도우미 ──────────────────────────────────────────────────────────
    def make_position(self, *, qty: int = 1, entry: float = 23000.0) -> dict:
        position = {
            "code": CODE,
            "name": "시험종목",
            "entry_no": 1,
            "phase": "BUY_PENDING",
            "qty": 0,
            "real": False,
            "dip_low": entry * 0.99,
            "last_price": entry,
            "pending": {"side": "BUY", "requested_qty": qty, "order_no": ""},
        }
        self.engine._positions()[f"{CODE}:1"] = position
        return position

    def snapshot(self, price: float, *, seconds: float = 0.0,
                 buy_cum: float = 1000.0, sell_cum: float = 1000.0,
                 at: "datetime | None" = None) -> dict:
        ts = at if at is not None else self.now + timedelta(seconds=seconds)
        write_json(self.config.snapshot_path, {
            "codes": {CODE: {
                "cur": price, "ts": ts.isoformat(), "cum_vol": 10000.0,
                "che_str": 60.0, "buy_money_cum": buy_cum,
                "sell_money_cum": sell_cum,
                "buy_vol_cum": 500.0, "sell_vol_cum": 500.0,
            }},
        })
        self.engine._snapshot_cache = (0.0, {})
        return {"ts": ts}

    def hold_states(self) -> dict:
        return self.engine.state.get(HOLD_STATES_KEY) or {}

    # ── ② 체결 -> 생성 -> 저장 -> 복구 ──────────────────────────────────
    def test_fill_creates_hold_state(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        saved = self.hold_states().get(f"{CODE}:1")
        self.assertIsNotNone(saved, "체결했는데 매도상태가 안 생겼다")
        state = HoldSellState.from_dict(saved)
        self.assertIs(state.strategy_id, StrategyId.S06_CRASH_LOW_CHASE)
        self.assertEqual(state.code, CODE)
        self.assertEqual(state.quantity, 1)
        self.assertEqual(state.entry_price, Decimal("23000"))

    def test_hold_state_is_saved_and_restored_after_restart(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.engine._save()
        restarted = self._engine()
        try:
            restored = restarted.exit_adapter.load({"code": CODE, "entry_no": 1})
            self.assertIsNotNone(restored, "재기동 후 매도상태가 사라졌다")
            self.assertEqual(restored.entry_price, Decimal("23000"))
        finally:
            for handler in list(restarted.log.handlers):
                handler.close()
                restarted.log.removeHandler(handler)

    def test_ensure_rebuilds_missing_hold_state_from_ledger(self) -> None:
        """이 배선 이전에 만들어진 보유 포지션도 매도판정을 받는다."""
        position = {
            "code": CODE, "name": "구포지션", "entry_no": 1, "phase": "HOLD",
            "qty": 1, "real": False, "entry_price": 23000.0,
            "entry_at": self.now.isoformat(), "peak_price": 24000.0,
        }
        self.engine._positions()[f"{CODE}:1"] = position
        state = self.engine.exit_adapter.ensure(position)
        self.assertIsNotNone(state)
        self.assertEqual(state.peak_price, Decimal("24000.0"))
        self.assertIn(f"{CODE}:1", self.hold_states())

    def test_ensure_follows_ledger_quantity(self) -> None:
        position = self.make_position(qty=2)
        self.engine._confirm_entry(position, 2, 23000.0, self.now, shadow=True)
        position["qty"] = 1                      # 잔량 재배분(_startup_reconcile)
        state = self.engine.exit_adapter.ensure(position)
        self.assertEqual(state.quantity, 1)

    def test_exit_confirm_drops_hold_state(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.engine._confirm_exit(position, 23100.0, "TEST", shadow=True)
        self.assertNotIn(f"{CODE}:1", self.hold_states())

    # ── ③ 판정이 공통 엔진에서 나오는가 ────────────────────────────────
    def test_old_exit_policy_is_not_wired_anymore(self) -> None:
        self.assertFalse(hasattr(s06, "decide_s06_exit"))
        self.assertFalse(hasattr(s06, "S06ExitObservation"))
        self.assertFalse(hasattr(s06.Strategy06Engine, "_same_day_exit_observation"))

    def test_hard_stop_comes_from_common_engine(self) -> None:
        """-2% 하드손절(S02 동일 프로필)이 공통 엔진 사유로 나온다."""
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.snapshot(22000.0, seconds=5)        # -4.35%
        self.engine._evaluate_exit(position, self.now + timedelta(seconds=5))
        self.assertEqual(position["phase"], "CLOSED")
        self.assertTrue(
            position["exit_reason"].startswith("HARD_STOP"),
            position["exit_reason"],
        )

    def test_flat_price_does_not_sell(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.snapshot(23010.0, seconds=5)
        self.engine._evaluate_exit(position, self.now + timedelta(seconds=5))
        self.assertEqual(position["phase"], "HOLD")

    def test_same_tick_is_not_judged_twice(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.snapshot(23010.0, seconds=5)
        moment = self.now + timedelta(seconds=5)
        self.engine._evaluate_exit(position, moment)
        first = HoldSellState.from_dict(self.hold_states()[f"{CODE}:1"])
        self.engine._evaluate_exit(position, moment)
        second = HoldSellState.from_dict(self.hold_states()[f"{CODE}:1"])
        self.assertEqual(first.last_observed_at, second.last_observed_at)

    def test_pre_entry_snapshot_is_skipped(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.snapshot(22000.0, at=self.now - timedelta(seconds=1))

        self.engine._evaluate_exit(position, self.now)

        state = HoldSellState.from_dict(self.hold_states()[f"{CODE}:1"])
        self.assertEqual(position["phase"], "HOLD")
        self.assertIsNone(state.last_observed_at)

    def test_incomplete_input_holds_instead_of_selling(self) -> None:
        """진입가가 없는 손상 포지션은 판정 보류 — 주문을 내지 않는다."""
        position = {
            "code": CODE, "name": "손상", "entry_no": 1, "phase": "HOLD",
            "qty": 1, "real": False, "entry_price": 0.0,
            "entry_at": self.now.isoformat(),
        }
        self.engine._positions()[f"{CODE}:1"] = position
        self.snapshot(22000.0, seconds=5)
        self.engine._evaluate_exit(position, self.now + timedelta(seconds=5))
        self.assertEqual(position["phase"], "HOLD")

    # ── ④ 부분매도 ─────────────────────────────────────────────────────
    def test_partial_sell_keeps_remaining_and_updates_hold_state(self) -> None:
        position = self.make_position(qty=2)
        self.engine._confirm_entry(position, 2, 23000.0, self.now, shadow=True)
        self.engine._start_sell(
            position, self.now, "PEAK_PARTIAL", {"price": 23500.0},
            quantity_override=1, partial=True,
        )
        self.assertEqual(position["phase"], "HOLD")
        self.assertEqual(position["qty"], 1)
        self.assertEqual(len(position["partial_exits"]), 1)
        state = HoldSellState.from_dict(self.hold_states()[f"{CODE}:1"])
        self.assertEqual(state.quantity, 1)
        self.assertTrue(state.peak_partial_taken)
        self.assertFalse(state.sell_latched)

    def test_partial_on_single_share_sells_everything(self) -> None:
        """S06 기본 1주에서는 부분매도가 성립하지 않는다(전량매도)."""
        position = self.make_position(qty=1)
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.engine._start_sell(
            position, self.now, "PEAK_PARTIAL", {"price": 23500.0},
            quantity_override=1, partial=True,
        )
        self.assertEqual(position["phase"], "CLOSED")
        self.assertEqual(position["qty"], 0)

    # ── ⑤ 손대지 않기로 한 것 ──────────────────────────────────────────
    def test_forced_flat_1520_still_bypasses_the_common_engine(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        late = datetime(2026, 8, 25, 15, 20, 0, tzinfo=KST)
        self.snapshot(23000.0, seconds=0)
        self.engine._evaluate_exit(position, late)
        self.assertEqual(position["phase"], "CLOSED")
        self.assertEqual(position["exit_reason"], "HARD_FLAT_1520")

    def test_1510_time_exit_now_comes_from_the_s02_profile(self) -> None:
        """⚠️행동 변화 1건 — S02 동일 프로필을 쓴 결과 15:10 시간청산이 붙는다.

        종전 S06 은 15:10 에 CLOSE_PROTECT_1510(수익>=0·정배열·매수세면 보유 허용)
        이었고, 무조건 청산은 15:20 뿐이었다. S02 프로필의 force_exit_at=15:10 은
        예외 없이 판다. 15:20 HARD_FLAT 안전망은 그대로다.
        되돌리기: 공통 파일 S06 프로필에 force=time(15, 20) 을 준다.
        """
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        late = datetime(2026, 8, 25, 15, 12, 0, tzinfo=KST)
        self.snapshot(23500.0, at=late)          # 수익 중이어도 판다
        self.engine._evaluate_exit(position, late)
        self.assertEqual(position["phase"], "CLOSED")
        self.assertEqual(position["exit_reason"], "TIME_EXIT_1510")

    def test_entry_quantity_contract_unchanged(self) -> None:
        self.assertEqual(self.config.quantity, 1)
        self.assertEqual(self.config.max_slots, 6)
        self.assertEqual(self.config.max_entries_per_code, 2)

    def test_hold_states_do_not_leak_into_positions(self) -> None:
        """보존입력 재생기가 대조하는 positions 를 오염시키지 않는다."""
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        self.assertNotIn("hold_state", position)
        self.assertIn(HOLD_STATES_KEY, self.engine.state)

    def test_cleanup_prunes_orphan_hold_states(self) -> None:
        position = self.make_position()
        self.engine._confirm_entry(position, 1, 23000.0, self.now, shadow=True)
        position["phase"] = "CLOSED"
        self.engine._cleanup_terminal()
        self.assertEqual(self.hold_states(), {})


class AdapterObservationTest(unittest.TestCase):
    """관측값 변환이 값을 지어내지 않는가(자료 부족 = fail-closed)."""

    class _Stub:
        class config:
            bars_path = Path("nonexistent_bars.json")
            strategy_slug = "strategy06"

        def __init__(self) -> None:
            self.state = {"date": "20260825"}
            self.flows = {}

        def _snapshot(self):
            return {}

        def _append_exit_flow(self, code, point):
            return None

    def test_missing_flow_marks_peak_rule_not_ready(self) -> None:
        adapter = Strategy06CommonExitAdapter(self._Stub())
        observation = adapter.build_observation(
            {"code": CODE, "real": False},
            {
                "ts": datetime(2026, 8, 25, 10, 0, tzinfo=KST),
                "price": 23000.0, "cum_vol": 0.0,
                "buy_money_cum": -1.0, "sell_money_cum": -1.0,
            },
        )
        self.assertFalse(observation.common_peak_flow_ready)
        self.assertEqual(observation.buy_money_per_sec_10s, Decimal("0"))
        self.assertFalse(observation.daily_ma_permit)

    def test_zero_price_is_refused(self) -> None:
        adapter = Strategy06CommonExitAdapter(self._Stub())
        self.assertIsNone(adapter.build_observation(
            {"code": CODE, "real": False},
            {"ts": datetime(2026, 8, 25, 10, 0, tzinfo=KST), "price": 0.0},
        ))


if __name__ == "__main__":
    unittest.main()
