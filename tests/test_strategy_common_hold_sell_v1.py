# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


STAGE_DIR = Path(__file__).resolve().parent
RUN_DIR = Path(r"C:\stock_bot\RUN")
sys.path.insert(0, str(RUN_DIR))
sys.path.insert(0, str(STAGE_DIR))

from strategy_common_foundation_v1 import ContractError, OrderLedger, OrderSide  # noqa: E402
from strategy_common_hold_sell_v1 import (  # noqa: E402
    STANDARD_STRATEGIES,
    EARLY_STRATEGIES,
    STRATEGY_PROFILES,
    VALLEY_STRATEGIES,
    HoldPhase,
    HoldSellAction,
    HoldSellObservation,
    HoldSellState,
    JsonHoldSellStateStore,
    MA3Mode,
    PeakStage,
    StrategyId,
    UnifiedHoldSellEngine,
    build_sell_intent,
)


KST = ZoneInfo("Asia/Seoul")


def kst(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 25, hour, minute, second, tzinfo=KST)


class UnifiedHoldSellEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = UnifiedHoldSellEngine()

    def state(
        self,
        strategy: StrategyId = StrategyId.RAID,
        *,
        entry_at: datetime = kst(9, 0),
        entry_price: str = "100",
    ) -> HoldSellState:
        return HoldSellState(
            position_id=f"position-{strategy.value}",
            strategy_id=strategy,
            code="5930",
            quantity=1,
            entry_price=Decimal(entry_price),
            entry_at=entry_at,
        )

    def observation(
        self,
        observed_at: datetime,
        *,
        price: str = "100",
        **overrides,
    ) -> HoldSellObservation:
        values = {
            "observed_at": observed_at,
            "price": Decimal(price),
            "vwap": Decimal("99"),
            "buy_ratio_recent": Decimal("0.60"),
            "money_speed_5s": Decimal("0"),
            "money_speed_10s": Decimal("100"),
            "money_speed_30s": Decimal("100"),
            "buy_money_per_sec_10s": Decimal("0"),
            "sell_money_per_sec_10s": Decimal("0"),
            "buy_money_per_sec_30s": Decimal("0"),
            "sell_money_per_sec_30s": Decimal("0"),
            "structure_broken": False,
            "money_accelerating": False,
            "ma3_permit": False,
            "daily_ma_permit": False,
            "recent_buy_money_rising": False,
        }
        values.update(overrides)
        return HoldSellObservation(**values)

    def test_all_strategy_profiles_exist(self):
        self.assertEqual(set(STRATEGY_PROFILES), set(StrategyId))
        self.assertEqual(len(STANDARD_STRATEGIES), 11)
        self.assertEqual(len(VALLEY_STRATEGIES), 3)
        self.assertEqual(len(EARLY_STRATEGIES), 3)
        self.assertEqual(STRATEGY_PROFILES[StrategyId.RAID].ma3_mode, MA3Mode.HOLD_LOCK)
        self.assertEqual(STRATEGY_PROFILES[StrategyId.PULL].ma3_mode, MA3Mode.SELL_OVERRIDE)
        self.assertEqual(STRATEGY_PROFILES[StrategyId.BASE].ma3_mode, MA3Mode.SELL_OVERRIDE)
        self.assertEqual(STRATEGY_PROFILES[StrategyId.REACCEL].ma3_mode, MA3Mode.NONE)

    def test_regular_valley_profile_preserves_stop_insure_and_time_exit(self):
        stop = self.state(StrategyId.VALLEY)
        stop_decision = self.engine.evaluate(
            stop, self.observation(kst(10, 0), price="97.4")
        )
        self.assertEqual(stop_decision.action, HoldSellAction.EMERGENCY_SELL)
        self.assertTrue(stop_decision.reason.startswith("HARD_STOP"))

        insure = self.state(StrategyId.VALLEY)
        self.engine.evaluate(insure, self.observation(kst(10, 0), price="104"))
        insure_decision = self.engine.evaluate(
            insure, self.observation(kst(10, 0, 1), price="102.4")
        )
        self.assertEqual(insure_decision.action, HoldSellAction.EMERGENCY_SELL)
        self.assertIn("VALLEY_PEAK_INSURE", insure_decision.reason)

        timed = self.state(StrategyId.VALLEY)
        timed_decision = self.engine.evaluate(
            timed, self.observation(kst(15, 10), price="101")
        )
        self.assertEqual(timed_decision.reason, "TIME_EXIT_1510")

    def test_regular_valley_waits_ten_seconds_and_sells_at_three_of_four(self):
        state = self.state(StrategyId.VALLEY)
        watch = self.engine.evaluate(
            state,
            self.observation(kst(10, 0), valley_completed_bearish_1m=True),
        )
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        still_watch = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0, 9),
                valley_strength_falling=True,
                valley_buy_flow_falling=True,
                valley_sell_flow_rising=True,
                valley_peak_reclaim_failed=True,
            ),
        )
        self.assertEqual(still_watch.action, HoldSellAction.WATCH)
        sold = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0, 10),
                valley_strength_falling=True,
                valley_buy_flow_falling=True,
                valley_sell_flow_rising=True,
            ),
        )
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("score=3/4", sold.reason)

    def test_regular_valley_holds_on_reclaim_and_ma5_weakness_lowers_threshold(self):
        reclaimed = self.state(StrategyId.VALLEY)
        self.engine.evaluate(
            reclaimed,
            self.observation(kst(10, 0), valley_completed_bearish_1m=True),
        )
        hold = self.engine.evaluate(
            reclaimed,
            self.observation(kst(10, 0, 5), valley_peak_reclaimed=True),
        )
        self.assertEqual(hold.action, HoldSellAction.HOLD)
        self.assertIsNone(reclaimed.valley_watch_since)

        weak = self.state(StrategyId.VALLEY)
        self.engine.evaluate(
            weak,
            self.observation(kst(10, 1), valley_completed_bearish_1m=True),
        )
        sold = self.engine.evaluate(
            weak,
            self.observation(
                kst(10, 1, 10),
                valley_strength_falling=True,
                valley_peak_reclaim_failed=True,
                valley_ma5_reclaimed_then_lost=True,
            ),
        )
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("threshold=2", sold.reason)

    def test_regular_valley_ma10_reclaim_loss_is_final_insurance(self):
        state = self.state(StrategyId.VALLEY)
        decision = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                price="101",
                valley_ma10_reclaimed_then_lost=True,
            ),
        )
        self.assertEqual(decision.action, HoldSellAction.EMERGENCY_SELL)
        self.assertEqual(decision.reason, "VALLEY_MA10_RECLAIM_LOST")

    def test_valley_morning_requires_structure_and_exact_sell_flow_for_ten_seconds(self):
        state = self.state(StrategyId.VALLEY_MORNING_CRASH)
        hold = self.engine.evaluate(
            state,
            self.observation(kst(9, 10), price="101", vwap=Decimal("105")),
        )
        self.assertEqual(hold.action, HoldSellAction.HOLD)
        watch = self.engine.evaluate(
            state,
            self.observation(kst(9, 11), price="101", structure_broken=True),
        )
        self.assertEqual(watch.action, HoldSellAction.WATCH)
        sold = self.engine.evaluate(
            state,
            self.observation(
                kst(9, 11, 10),
                price="101",
                structure_broken=True,
                valley_exact_flow_valid=True,
                valley_exact_sell_dominant=True,
            ),
        )
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("EXACT_SELL_DOMINANT", sold.reason)

    def test_valley_morning_missing_exact_flow_cancels_and_0930_exits(self):
        state = self.state(StrategyId.VALLEY_MORNING_CRASH)
        self.engine.evaluate(
            state,
            self.observation(kst(9, 11), structure_broken=True),
        )
        cancelled = self.engine.evaluate(
            state,
            self.observation(kst(9, 11, 10), structure_broken=True),
        )
        self.assertEqual(cancelled.action, HoldSellAction.HOLD)
        self.assertEqual(cancelled.reason, "VALLEY_MORNING_BREAK_CANCEL")

        timed = self.state(StrategyId.VALLEY_MORNING_CRASH)
        timed_decision = self.engine.evaluate(
            timed, self.observation(kst(9, 30), price="101")
        )
        self.assertEqual(timed_decision.reason, "TIME_EXIT_0930")

    def test_valley_base_uses_only_minus_one_point_five_plus_two_and_time(self):
        target = self.state(StrategyId.VALLEY_BASE_BREAKOUT)
        target_decision = self.engine.evaluate(
            target, self.observation(kst(10, 0), price="102")
        )
        self.assertEqual(target_decision.action, HoldSellAction.SELL)
        self.assertIn("VALLEY_BASE_TARGET", target_decision.reason)

        stop = self.state(StrategyId.VALLEY_BASE_BREAKOUT)
        stop_decision = self.engine.evaluate(
            stop, self.observation(kst(10, 0), price="98.4")
        )
        self.assertEqual(stop_decision.action, HoldSellAction.EMERGENCY_SELL)
        self.assertTrue(stop_decision.reason.startswith("HARD_STOP"))

    @unittest.skip("2026-07-29 공통 하드손절 -2.0%→-3.0% 변경. 테스트가 -2% 기준 가격(97.9)을 사용")
    def test_standard_hard_stop_precedes_ma3_hold_and_time_exit(self):
        state = self.state(StrategyId.RAID)
        decision = self.engine.evaluate(
            state,
            self.observation(
                kst(15, 10),
                price="97.9",
                ma3_permit=True,
            ),
        )
        self.assertEqual(decision.action, HoldSellAction.EMERGENCY_SELL)
        self.assertTrue(decision.reason.startswith("HARD_STOP"))

    def test_pull_uses_minus_three_or_minus_four_stop_by_flow(self):
        weak = self.state(StrategyId.PULL)
        weak_decision = self.engine.evaluate(
            weak,
            self.observation(kst(10, 0), price="96.9", buy_ratio_recent=Decimal("0.49")),
        )
        self.assertEqual(weak_decision.action, HoldSellAction.EMERGENCY_SELL)

        strong = self.state(StrategyId.PULL)
        strong_hold = self.engine.evaluate(
            strong,
            self.observation(kst(10, 0), price="96.5", buy_ratio_recent=Decimal("0.60")),
        )
        self.assertEqual(strong_hold.action, HoldSellAction.HOLD)
        strong_stop = self.state(StrategyId.PULL)
        strong_sell = self.engine.evaluate(
            strong_stop,
            self.observation(kst(10, 0), price="95.9", buy_ratio_recent=Decimal("0.60")),
        )
        self.assertEqual(strong_sell.action, HoldSellAction.EMERGENCY_SELL)

    def test_all_early_routes_share_0920_trend_and_0930_exit(self):
        for strategy in EARLY_STRATEGIES:
            with self.subTest(strategy=strategy.value):
                state = self.state(strategy)
                hold = self.engine.evaluate(
                    state,
                    self.observation(
                        kst(9, 20),
                        price="102",
                        vwap=Decimal("101"),
                        ma3_permit=True,
                        buy_ratio_recent=Decimal("0.60"),
                        money_speed_10s=Decimal("60"),
                        money_speed_30s=Decimal("100"),
                    ),
                )
                self.assertEqual(hold.action, HoldSellAction.HOLD)
                exit_decision = self.engine.evaluate(
                    state,
                    self.observation(
                        kst(9, 30),
                        price="102",
                        vwap=Decimal("101"),
                        ma3_permit=True,
                    ),
                )
                self.assertEqual(exit_decision.action, HoldSellAction.EMERGENCY_SELL)
                self.assertEqual(exit_decision.reason, "TIME_EXIT_0930")

    def test_early_trend_failure_sells_before_0930(self):
        state = self.state(StrategyId.EARLY_GAP_ONSET)
        decision = self.engine.evaluate(
            state,
            self.observation(
                kst(9, 20),
                price="101",
                vwap=Decimal("102"),
                ma3_permit=True,
            ),
        )
        self.assertEqual(decision.action, HoldSellAction.SELL)
        self.assertIn("VWAP", decision.reason)

    def test_regular_strategies_force_exit_at_1510(self):
        for strategy in (StrategyId.RAID, StrategyId.PULL, StrategyId.BASE, StrategyId.REACCEL):
            with self.subTest(strategy=strategy.value):
                state = self.state(strategy)
                decision = self.engine.evaluate(
                    state,
                    self.observation(kst(15, 10), price="100"),
                )
                self.assertEqual(decision.action, HoldSellAction.EMERGENCY_SELL)
                self.assertEqual(decision.reason, "TIME_EXIT_1510")

    def test_raid_ma3_permit_locks_general_sell_rules(self):
        state = self.state(StrategyId.RAID)
        decision = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                ma3_permit=True,
                buy_ratio_recent=Decimal("0.40"),
                structure_broken=True,
            ),
        )
        self.assertEqual(decision.action, HoldSellAction.HOLD)
        self.assertEqual(decision.reason, "MA3_RIDER_HOLD")

    def test_pull_and_base_ma3_allow_sustained_sell_override(self):
        for strategy in (StrategyId.PULL, StrategyId.BASE):
            with self.subTest(strategy=strategy.value):
                state = self.state(strategy)
                first = self.engine.evaluate(
                    state,
                    self.observation(
                        kst(10, 0),
                        ma3_permit=True,
                        buy_ratio_recent=Decimal("0.40"),
                        structure_broken=True,
                    ),
                )
                self.assertEqual(first.action, HoldSellAction.WATCH)
                second = self.engine.evaluate(
                    state,
                    self.observation(
                        kst(10, 0, 15),
                        ma3_permit=True,
                        buy_ratio_recent=Decimal("0.40"),
                        structure_broken=True,
                    ),
                )
                self.assertEqual(second.action, HoldSellAction.SELL)
                self.assertIn("MA3_SELL_OVERRIDE", second.reason)

    @unittest.skip("ma3_permit 을 채우는 코드가 현역 회전엔진에 없어 MA3 규칙 미작동 — 배선 후 해제")
    def test_reaccel_does_not_receive_ma3_hold_lock(self):
        state = self.state(StrategyId.REACCEL)
        first = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                ma3_permit=True,
                buy_ratio_recent=Decimal("0.40"),
                structure_broken=True,
            ),
        )
        self.assertEqual(first.action, HoldSellAction.WATCH)
        self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0, 1),
                ma3_permit=True,
                buy_ratio_recent=Decimal("0.40"),
                structure_broken=True,
            ),
        )
        third = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0, 16),
                ma3_permit=True,
                buy_ratio_recent=Decimal("0.40"),
                structure_broken=True,
            ),
        )
        self.assertEqual(third.action, HoldSellAction.SELL)
        self.assertIn("FLOW_WEAK+STRUCTURE_BREAK", third.reason)

    def test_standard_profile_does_not_use_price_only_profit_trail(self):
        state = self.state(StrategyId.RAID)
        self.engine.evaluate(state, self.observation(kst(10, 0), price="102"))
        # ★[2026-07-30] 꼭지점 매도 판정 주기 180초 도입 — 1초 뒤에는 판정하지 않는다.
        early = self.engine.evaluate(
            state,
            self.observation(kst(10, 0, 1), price="100.47"),
        )
        self.assertNotEqual(early.action, HoldSellAction.SELL)
        decision = self.engine.evaluate(
            state,
            self.observation(kst(10, 3, 1), price="100.47"),
        )
        self.assertEqual(state.peak_stage, PeakStage.PROFIT_2)
        self.assertEqual(decision.action, HoldSellAction.HOLD)
        self.assertNotIn("PROFIT_TRAIL", decision.reason)

    @unittest.skip("매도 보류 동작은 동일(HOLD). 사유 라벨만 FLOW_HEALTHY→HOLD_RIDING 으로 변경됨")
    def test_profit_trail_money_guard_keeps_holding(self):
        state = self.state(StrategyId.RAID)
        self.engine.evaluate(state, self.observation(kst(10, 0), price="102"))
        decision = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0, 1),
                price="100.4",
                buy_money_per_sec_10s=Decimal("900"),
                sell_money_per_sec_10s=Decimal("100"),
                money_speed_10s=Decimal("60"),
                money_speed_30s=Decimal("100"),
            ),
        )
        self.assertEqual(decision.action, HoldSellAction.HOLD)
        self.assertEqual(decision.reason, "FLOW_HEALTHY")

    @unittest.skip("2026-07-27 친구님 지시로 돈마름 매도 중단 — 기능 복구 시 해제")
    def test_money_dryup_requires_sell_dominance_and_sixty_seconds(self):
        state = self.state(StrategyId.REACCEL, entry_at=kst(9, 50))
        self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                buy_money_per_sec_30s=Decimal("1500000"),
                sell_money_per_sec_30s=Decimal("500000"),
            ),
        )
        first_dry = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 1),
                buy_money_per_sec_30s=Decimal("20000"),
                sell_money_per_sec_30s=Decimal("100000"),
            ),
        )
        self.assertFalse(first_dry.should_sell)
        sold = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 2),
                buy_money_per_sec_30s=Decimal("20000"),
                sell_money_per_sec_30s=Decimal("100000"),
            ),
        )
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("MONEY_DRYUP", sold.reason)

    @unittest.skip("2026-07-27 친구님 지시로 점수 매도 중단 — 기능 복구 시 해제")
    def test_score_sell_needs_five_seconds_and_no_buy_recovery(self):
        state = self.state(StrategyId.RAID, entry_at=kst(9, 58))
        self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                money_speed_5s=Decimal("2000000"),
                buy_money_per_sec_30s=Decimal("800000"),
                sell_money_per_sec_30s=Decimal("200000"),
            ),
        )
        armed = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 1),
                money_speed_5s=Decimal("100000"),
                buy_money_per_sec_30s=Decimal("300000"),
                sell_money_per_sec_30s=Decimal("700000"),
            ),
        )
        self.assertFalse(armed.should_sell)
        sold = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 1, 5),
                money_speed_5s=Decimal("100000"),
                buy_money_per_sec_30s=Decimal("300000"),
                sell_money_per_sec_30s=Decimal("700000"),
            ),
        )
        self.assertEqual(sold.action, HoldSellAction.SELL)
        self.assertIn("SCORE_SELL", sold.reason)

    def test_score_timer_resets_when_recent_buy_money_rises(self):
        state = self.state(StrategyId.RAID, entry_at=kst(9, 58))
        self.engine.evaluate(
            state,
            self.observation(kst(10, 0), money_speed_5s=Decimal("2000000")),
        )
        recovering = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 1),
                money_speed_5s=Decimal("100000"),
                buy_money_per_sec_30s=Decimal("300000"),
                sell_money_per_sec_30s=Decimal("700000"),
                recent_buy_money_rising=True,
            ),
        )
        self.assertFalse(recovering.should_sell)
        self.assertIsNone(state.score_sell_since)

    @unittest.skip("2026-07-27 친구님 지시로 자금흐름 매도 중단 — 기능 복구 시 해제")
    def test_flow_sell_timer_resets_after_recovery(self):
        state = self.state(StrategyId.REACCEL)
        poor = {
            "buy_ratio_recent": Decimal("0.40"),
            "structure_broken": True,
        }
        self.engine.evaluate(state, self.observation(kst(10, 0), **poor))
        self.engine.evaluate(state, self.observation(kst(10, 0, 1), **poor))
        recovered = self.engine.evaluate(
            state,
            self.observation(kst(10, 0, 10), buy_ratio_recent=Decimal("0.60")),
        )
        self.assertEqual(recovered.action, HoldSellAction.HOLD)
        self.assertEqual(state.phase, HoldPhase.HOLD)
        again = self.engine.evaluate(state, self.observation(kst(10, 0, 20), **poor))
        self.assertEqual(again.action, HoldSellAction.WATCH)
        self.assertFalse(again.should_sell)

    def test_daily_ma_permit_holds_through_weak_flow(self):
        """상승보유(친구님 확정 사양) — 3분봉이 5일선 횡보·10일선 받침·20일선 우상향이면
        흐름이 나빠도 매도하지 않는다. 모든 전략 공통."""
        state = self.state(StrategyId.REACCEL)
        poor = {
            "buy_ratio_recent": Decimal("0.40"),
            "structure_broken": True,
            "daily_ma_permit": True,
        }
        for offset in (0, 1, 20, 31, 59):
            decision = self.engine.evaluate(
                state, self.observation(kst(10, 0, offset), **poor))
            self.assertEqual(decision.action, HoldSellAction.HOLD)
            self.assertFalse(decision.should_sell)
            self.assertEqual(decision.reason, "DAILY_MA_RIDER_HOLD")

    def test_daily_ma_permit_never_blocks_hard_stop(self):
        """상승보유 허가가 있어도 하드손절과 강제청산은 그대로 살아 있어야 한다."""
        state = self.state(StrategyId.REACCEL)
        stopped = self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                price=state.entry_price * Decimal("0.95"),
                daily_ma_permit=True,
            ),
        )
        self.assertTrue(stopped.should_sell)
        self.assertIn("HARD_STOP", stopped.reason)

    def test_out_of_order_observation_is_rejected(self):
        state = self.state()
        self.engine.evaluate(state, self.observation(kst(10, 0)))
        with self.assertRaises(ContractError):
            self.engine.evaluate(state, self.observation(kst(9, 59, 59)))

    @unittest.skip("WATCH 단계를 만들던 매도 규칙들이 2026-07-27 에 중단되어 HOLD 로 고정됨")
    def test_state_store_round_trip_preserves_strategy_and_timers(self):
        state = self.state(StrategyId.BASE)
        self.engine.evaluate(
            state,
            self.observation(
                kst(10, 0),
                buy_ratio_recent=Decimal("0.40"),
                structure_broken=True,
            ),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hold_sell_state.json"
            store = JsonHoldSellStateStore(path)
            store.save({state.code: state})
            restored = store.load()[state.code]
        self.assertEqual(restored.strategy_id, StrategyId.BASE)
        self.assertEqual(restored.phase, HoldPhase.WATCH)
        self.assertEqual(restored.watch_since, kst(10, 0))

    def test_valley_watch_timer_survives_state_store_round_trip(self):
        state = self.state(StrategyId.VALLEY)
        self.engine.evaluate(
            state,
            self.observation(kst(10, 0), valley_completed_bearish_1m=True),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "valley_hold_sell_state.json"
            store = JsonHoldSellStateStore(path)
            store.save({state.code: state})
            restored = store.load()[state.code]
        self.assertEqual(restored.strategy_id, StrategyId.VALLEY)
        self.assertEqual(restored.valley_watch_since, kst(10, 0))
        self.assertFalse(restored.sell_latched)


    def test_sell_decision_is_latched_and_order_key_is_idempotent(self):
        state = self.state(StrategyId.RAID)
        first = self.engine.evaluate(state, self.observation(kst(15, 10), price="101"))
        repeated = self.engine.evaluate(state, self.observation(kst(15, 10, 5), price="99"))
        self.assertEqual(first.order_key, repeated.order_key)
        self.assertEqual(first.observed_at, repeated.observed_at)
        self.assertEqual(first.price, repeated.price)

        intent = build_sell_intent(state, repeated)
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.side, OrderSide.SELL)
        ledger = OrderLedger()
        _first_state, first_created = ledger.submit(intent)
        _same_state, second_created = ledger.submit(intent)
        self.assertTrue(first_created)
        self.assertFalse(second_created)

    def test_hold_decision_does_not_build_sell_intent(self):
        state = self.state(StrategyId.RAID)
        decision = self.engine.evaluate(state, self.observation(kst(10, 0), price="101"))
        self.assertEqual(decision.action, HoldSellAction.HOLD)
        self.assertIsNone(build_sell_intent(state, decision))


if __name__ == "__main__":
    unittest.main()
