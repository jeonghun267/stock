# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
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
    def test_s02_uses_open_before_0920_and_intraday_high_afterward(self) -> None:
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
            self.point(intraday_start + timedelta(seconds=30), price=10_670),
            open_price=10_000,
            session_high=11_000,
        )
        intraday_state = intraday.states["123456"]
        self.assertEqual(intraday_state.six_reference_mode, "INTRADAY_HIGH")
        self.assertEqual(intraday_state.six_episode_high, 11_000)
        self.assertEqual(intraday_state.six_phase, "CHASE")

    def test_open_drop_at_4pct_permanently_hands_off_to_s03_s06(self) -> None:
        monitor = LowBuySignalMonitor()
        observed_at = self.now.replace(hour=9, minute=10)
        row, fired = monitor.process_point(
            "123456", "TEST",
            self.point(observed_at, price=9_600),
            open_price=10_000,
            session_high=10_000,
        )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "OPEN_DROP_LE_4PCT_HANDOFF_S03_S06")
        state = monitor.states["123456"]
        self.assertTrue(state.handoff_to_s03_s06)
        self.assertEqual(state.six_phase, "DONE")
        recovered, recovered_fired = monitor.process_point(
            "123456", "TEST",
            self.point(observed_at + timedelta(seconds=30), price=9_800),
            open_price=10_000,
            session_high=10_000,
        )
        self.assertFalse(recovered_fired)
        self.assertEqual(
            recovered["reason"], "OPEN_DROP_LE_4PCT_HANDOFF_S03_S06")
    def test_s06_staircase_resets_new_low_during_observe(self) -> None:
        monitor = LowBuySignalMonitor()
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
                    self.now + timedelta(seconds=sec),
                    price=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                ),
            )
            self.assertFalse(fired)
        state = monitor.states["123456"]
        self.assertEqual(state.six_phase, "CHASE")
        self.assertEqual(state.six_low, 9_500)
        self.assertEqual(state.six_reset_steps, 2)
        self.assertIsNone(state.six_observe_since)

    def test_s06_staircase_full_retest_emits_only_after_flow_acceleration(self) -> None:
        monitor = LowBuySignalMonitor()
        sequence = [
            (0, 10_000, 1_000, 1_000),
            (20, 9_900, 1_100, 2_000),
            (40, 9_700, 1_200, 3_000),
            (50, 9_600, 1_300, 4_000),
            (60, 9_500, 1_400, 5_000),
            (65, 9_643, 1_600, 5_100),
            (85, 9_595, 1_900, 5_200),
            (105, 9_600, 2_200, 5_300),
            (115, 9_610, 2_400, 5_400),
            (125, 9_643, 3_000, 5_450),
        ]
        fired_rows = []
        for sec, price, buy_cum, sell_cum in sequence:
            row, fired = monitor.process_point(
                "123456", "TEST",
                self.point(
                    self.now + timedelta(seconds=sec),
                    price=price,
                    buy_money_cum=buy_cum,
                    sell_money_cum=sell_cum,
                ),
            )
            if fired:
                fired_rows.append(row)
        self.assertEqual(len(fired_rows), 1)
        row = fired_rows[0]
        self.assertEqual(row["action"], "BUY_READY")
        self.assertEqual(row["algorithm"], "S02_S06_STAIRCASE_RETEST_V1")
        self.assertEqual(row["anchor_low"], 9_500)
        self.assertEqual(row["dip_low_reset_steps"], 2)
        self.assertEqual(row["dip_flow_flip"], "O")
        self.assertEqual(row["flow_accel"], "O")
        self.assertGreaterEqual(row["observe_sec"], 60)
        self.assertGreaterEqual(row["entry_gap_pct"], 1.0)
        self.assertLessEqual(row["entry_gap_pct"], 2.0)

    def test_money_surge_onset_fires_at_first_bull_candle_start(self) -> None:
        monitor = LowBuySignalMonitor()
        sequence = [
            (0, 10_000, 0, 0, 1_000, 100),
            (5, 9_950, 500_000, 1_000_000, 1_100, 95),
            (10, 9_850, 1_000_000, 3_000_000, 1_200, 92),
            (15, 9_700, 1_500_000, 5_000_000, 1_300, 90),
            (20, 9_750, 16_500_000, 6_000_000, 2_300, 115),
            (21, 9_760, 20_000_000, 6_200_000, 2_500, 118),
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
        self.assertEqual(len(fired_rows), 1)
        row = fired_rows[0]
        self.assertEqual(row["algorithm"], "S02_MONEY_SURGE_ONSET_V1")
        self.assertEqual(row["anchor_low"], 9_700)
        self.assertEqual(row["surge_confirm_ticks"], 2)
        self.assertLessEqual(row["surge_turn_sec"], 10)
        self.assertGreaterEqual(row["surge_recent_buy_rate_5s"], 1_666_667)

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
            self.assertEqual(replace_mock.call_count, 3)

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

    def test_s02_flow_reversal_holds_when_ma10_and_ma20_support(self) -> None:
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
            ),
        )
        self.assertEqual(decision.action, HoldSellAction.HOLD)
        self.assertEqual(decision.reason, "S02_MA10_MA20_SUPPORT_HOLD")

    def test_s02_shadow_round_trip_exits_before_hard_stop_on_flow_reversal(self) -> None:
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
            ]
            for sec, price, buy_money, sell_money, buy_vol, sell_vol, strength in sequence:
                observed_at = write_market(
                    sec, price, buy_money, sell_money,
                    buy_vol, sell_vol, strength, sec >= 15)
                engine.tick(observed_at)

            self.assertEqual(engine._active_positions(), {})
            trade = engine.state["history"][-1]
            self.assertIn("S02_FLOW_REVERSAL_EXIT", trade["exit_reason"])
            self.assertGreater(trade["gross_return_pct"], -2.0)
            self.assertEqual(trade["exit_price"], 10_020)
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
            approval.write_text("APPROVED", encoding="utf-8")
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
        # ★[2026-08-01] 09:30 → 09:06 — 신호기 창과 불일치 수리(8/1 점검 발견 1)에 맞춰 갱신.
        self.assertEqual(config.entry_start.isoformat(), "09:06:00")
        self.assertEqual(config.entry_end.isoformat(), "14:20:00")
        self.assertEqual(config.max_daily_codes, 15)
        self.assertEqual(config.max_cycles_per_code, 2)
        self.assertEqual(config.rotation_capital_krw, 2_000_000)


if __name__ == "__main__":
    unittest.main()
