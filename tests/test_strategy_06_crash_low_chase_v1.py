# -*- coding: utf-8 -*-
"""새전략 06 급락 저점추격 — 진입 상태기계 단위 테스트 (주문 0·그림자).
2026-08-01 v2: 속도 역전 판정 + 관찰 60초 + 신저점 재무장 2회."""
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

RUN_DIR = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_06_crash_low_chase_v1 import (  # noqa: E402
    ChaseState,
    Config,
    Strategy06Engine,
)

KST = ZoneInfo("Asia/Seoul")
CODE = "123450"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ChaseMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.base = base
        self.now = datetime(2026, 8, 3, 9, 5, 0, tzinfo=KST)
        self.today = self.now.strftime("%Y%m%d")
        self.config = Config(
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
        self.engine = Strategy06Engine(self.config)

    def tearDown(self) -> None:
        import logging
        logger = logging.getLogger(self.config.strategy_slug)
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        self.temp.cleanup()

    def feed(self, *, price: float, hr_low: float, first: float = 20000.0,
             che: float = 60.0, advance_sec: float = 3.0, vol: float = 10000.0,
             buy_cum: float = 1000.0, sell_cum: float = 1000.0) -> None:
        """가짜 시세 한 틱을 밀어 넣고 상태기계를 한 번 돌린다."""
        self.now += timedelta(seconds=advance_sec)
        write_json(self.config.hr_state_path, {
            "codes": {CODE: {"first_price": first, "low": hr_low}},
        })
        write_json(self.config.snapshot_path, {
            "codes": {CODE: {
                "cur": price, "ts": self.now.isoformat(),
                "cum_vol": vol, "che_str": che,
                "buy_money_cum": buy_cum, "sell_money_cum": sell_cum,
            }},
        })
        self.engine._snapshot_cache = (0.0, {})
        self.engine._hr_cache = (0.0, {})
        self.engine._entry_wait_epoch = {}
        self.engine._chase_tick(CODE, self.now)

    def chase(self) -> dict:
        return self.engine.state.get("chase", {}).get(CODE, {})

    def pos(self, n: int = 1) -> dict:
        return self.engine._positions().get(f"{CODE}:{n}")

    def test_universe_covers_all_high_range_with_crown_first(self) -> None:
        """고저폭·crown은 전체 snapshot 안에서 우선순위로만 작동한다."""
        other = "654320"
        outside = "777770"
        write_json(self.config.watch_path, {
            "codes": [other, CODE], "crown_codes": [CODE],
            "for_date": self.today, "source_stale": False,
        })
        write_json(self.config.snapshot_path, {
            "codes": {outside: {}, other: {}, CODE: {}, "0155E0": {}},
        })
        self.engine._snapshot_cache = (0.0, {})
        codes, block = self.engine._universe(self.now)
        self.assertEqual(codes, [CODE, other, outside])
        self.assertEqual(block, "")

    def test_snapshot_empty_reuses_only_fresh_previous_payload(self) -> None:
        fresh = {"ts": self.now.isoformat(), "codes": {CODE: {}}}
        self.engine._snapshot_cache = (0.0, fresh)
        with (
            patch("strategy_06_crash_low_chase_v1.read_json", return_value={}),
            patch("strategy_06_crash_low_chase_v1.kst_now", return_value=self.now),
            patch("strategy_06_crash_low_chase_v1.time.sleep"),
        ):
            codes, block = self.engine._universe(self.now)
        self.assertEqual(codes, [CODE])
        self.assertEqual(block, "")

        stale = {
            "ts": (self.now - timedelta(seconds=30)).isoformat(),
            "codes": {CODE: {}},
        }
        self.engine._snapshot_cache = (0.0, stale)
        with (
            patch("strategy_06_crash_low_chase_v1.read_json", return_value={}),
            patch("strategy_06_crash_low_chase_v1.kst_now", return_value=self.now),
            patch("strategy_06_crash_low_chase_v1.time.sleep"),
        ):
            codes, block = self.engine._universe(self.now)
        self.assertEqual(codes, [])
        self.assertEqual(block, "SNAPSHOT_EMPTY")

    def test_universe_keeps_watching_when_crown_is_empty(self) -> None:
        """고저폭 정보가 비어도 snapshot 전체는 계속 본다."""
        other = "654320"
        write_json(self.config.watch_path, {
            "codes": [other, CODE], "crown_codes": [], "crown_priority_codes": [],
            "for_date": self.today, "source_stale": False,
        })
        write_json(self.config.snapshot_path, {"codes": {other: {}, CODE: {}}})
        self.engine._snapshot_cache = (0.0, {})
        codes, block = self.engine._universe(self.now)
        self.assertEqual(sorted(codes), sorted([CODE, other]))
        self.assertEqual(block, "")

    def test_common_quantity_and_slot_limit(self) -> None:
        # ★[QTY 2026-08-06 친구님 지시 "원래대로 1주"] 8/5 의 2주 전환을 되돌렸다.
        self.assertEqual(self.config.quantity, 1)
        self.assertEqual(self.config.max_slots, 6)

    def test_default_entry_band_is_half_to_one_point_five_percent(self) -> None:
        self.assertEqual(self.config.rebound_pct, 0.5)
        self.assertEqual(self.config.entry_floor_pct, 0.5)
        self.assertEqual(self.config.chase_cap_pct, 1.5)

    def test_default_take_profit_is_five_percent(self) -> None:
        self.assertEqual(self.config.tp_pct, 5.0)

    def test_under_10000_is_observed_but_order_is_blocked(self) -> None:
        write_json(self.config.snapshot_path, {
            "codes": {CODE: {"cur": 9999, "ts": self.now.isoformat()}},
        })
        self.engine._snapshot_cache = (0.0, {})
        codes, block = self.engine._universe(self.now)
        self.assertIn(CODE, codes)
        self.assertEqual(block, "")
        chase = ChaseState(low=9000.0)
        with patch.object(self.engine, "_event") as event:
            result = self.engine._try_entry(CODE, CODE, {"price": 9999.0}, chase, self.now)
        self.assertEqual(result, "STOP")
        self.assertEqual(event.call_args.kwargs["reason"], "PRICE_BELOW_MIN")

    def test_live_entry_acquires_and_releases_common_slot(self) -> None:
        class Broker:
            real_session = True
            buy_allowed = True
            mode = "LIVE"
            last_error = ""

            def __init__(self):
                self.submissions = []

            def holdings(self):
                return {}

            def open_orders(self, code, *, buy):
                return {}

            def submit(self, **kwargs):
                self.submissions.append(kwargs)
                return "OK"

        class Slots:
            def __init__(self):
                self.acquired = []
                self.released = []

            def acquire(self, code, owner, day):
                self.acquired.append((code, owner, day))
                return True

            def release(self, code, day):
                self.released.append((code, day))

        broker = Broker()
        slots = Slots()
        self.engine.broker = broker
        self.engine.slots = slots
        chase = ChaseState(low=19_700, low_at=self.now.isoformat())
        point = {
            "price": 20_000,
            "ts": self.now,
            "che_str": 100.0,
            "buy_money_cum": 1_000.0,
            "sell_money_cum": 500.0,
        }
        write_json(self.config.snapshot_path, {"codes": {CODE: {
            "cur": 20_000,
            "ts": self.now.isoformat(),
        }}})
        with patch(
            "strategy_06_crash_low_chase_v1.ma3_rows",
            return_value={"ma5": 1.0},
        ), patch(
            "strategy_06_crash_low_chase_v1.kst_now",
            return_value=self.now,
        ):
            result = self.engine._try_entry(
                CODE, "TEST", point, chase, self.now)

        self.assertEqual(result, "BOUGHT")
        state_day = str(self.engine.state["date"])
        self.assertEqual(slots.acquired, [(CODE, "S06_CRASH_LOW_CHASE", state_day)])
        position = self.pos()
        self.assertTrue(position["slot_reserved"])
        # ★[QTY 2026-08-06 친구님 지시 "원래대로 1주"] 8/5 의 2주 전환을 되돌렸다.
        self.assertEqual(position["pending"]["requested_qty"], 1)
        position["phase"] = "FAILED"
        self.engine._cleanup_terminal()
        self.assertEqual(slots.released, [(CODE, state_day)])

    def test_first_rebound_enters_one_share_inside_early_band(self) -> None:
        self.engine.config = replace(
            self.config,
            early_entry_cap_pct=1.8,
        )
        self.feed(price=20_000, hr_low=20_000)
        self.feed(price=18_200, hr_low=18_200)
        self.feed(price=18_480, hr_low=18_200)  # +1.538%: early entry

        position = self.pos(1)
        self.assertIsNotNone(position)
        self.assertEqual(position["phase"], "HOLD")
        self.assertEqual(position["qty"], 1)
        self.assertEqual(position["entry_reason"], "FIRST_REBOUND_EARLY_ENTRY")

    def test_first_rebound_above_early_band_keeps_legacy_observe(self) -> None:
        self.engine.config = replace(
            self.config,
            early_entry_cap_pct=1.8,
        )
        self.feed(price=20_000, hr_low=20_000)
        self.feed(price=18_200, hr_low=18_200)
        self.feed(price=18_530, hr_low=18_200)  # +1.813%, below absolute 2%

        self.assertEqual(self.chase()["phase"], "OBSERVE")
        self.assertEqual(self.engine._positions(), {})

    def test_universe_puts_min12_priority_core_first(self) -> None:
        core_b = "111110"
        core_a2 = "222220"
        write_json(self.config.watch_path, {
            "codes": [core_b, CODE, core_a2], "crown_codes": [core_b, CODE, core_a2],
            "crown_priority_codes": [CODE, core_a2], "for_date": self.today,
            "source_stale": False,
        })
        write_json(self.config.snapshot_path, {"codes": {core_b: {}, CODE: {}, core_a2: {}}})
        self.engine._snapshot_cache = (0.0, {})
        codes, block = self.engine._universe(self.now)
        self.assertEqual(codes, [CODE, core_a2, core_b])
        self.assertEqual(block, "")

    # ★[UNIVERSE-FIX 2026-08-06] 종전의 test_universe_blocks_entries_when_core_is_empty
    #   (crown 이 비면 감시를 통째로 멈춘다)는 새 동작과 정면으로 어긋나 제거했다.
    #   대체 시험은 위 test_universe_keeps_watching_when_crown_is_empty.

    def first_entry_setup(self) -> None:
        """-9% 저점까지 매도 우위 흐름을 만든다."""
        self.feed(price=20000, hr_low=20000, advance_sec=20,
                  buy_cum=1000, sell_cum=1000)
        self.feed(price=19600, hr_low=19600, advance_sec=20,
                  buy_cum=1100, sell_cum=2500)
        self.feed(price=18200, hr_low=18200, advance_sec=20,
                  buy_cum=1200, sell_cum=4000)

    def complete_retest(self, *, low: float, buy_base: float,
                        sell_base: float) -> None:
        """첫 반등·눌림·높은 2차 저점·10초 매수 재가속을 완성한다."""
        self.feed(price=low * 1.0154, hr_low=low, advance_sec=5,
                  buy_cum=buy_base + 150, sell_cum=sell_base + 50)
        self.feed(price=low * 1.0099, hr_low=low, advance_sec=20,
                  buy_cum=buy_base + 300, sell_cum=sell_base + 120)
        self.feed(price=low * 1.0104, hr_low=low, advance_sec=20,
                  buy_cum=buy_base + 500, sell_cum=sell_base + 210)
        self.feed(price=low * 1.0121, hr_low=low, advance_sec=10,
                  buy_cum=buy_base + 850, sell_cum=sell_base + 260)
        self.feed(price=low * 1.0154, hr_low=low, advance_sec=10,
                  buy_cum=buy_base + 1600, sell_cum=sell_base + 290)

    def buy_shadow(self) -> dict:
        self.first_entry_setup()
        self.complete_retest(low=18200, buy_base=1200, sell_base=4000)
        return self.pos(1)

    def test_trigger_observe_and_shadow_buy_then_rearm(self) -> None:
        self.feed(price=20000, hr_low=20000)
        self.assertEqual(self.chase().get("phase", "IDLE"), "IDLE")
        self.feed(price=18200, hr_low=18200)
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.feed(price=18300, hr_low=18200)          # +0.55%는 아직 추격
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.feed(price=18382, hr_low=18200)          # +1.0%도 아직 추격
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.feed(price=18480, hr_low=18200)          # +1.5% 첫 반등
        self.assertEqual(self.chase()["phase"], "OBSERVE")
        self.assertEqual(self.engine._positions(), {})
        self.feed(price=18380, hr_low=18200, advance_sec=20,
                  buy_cum=1300, sell_cum=1050)        # 높은 2차 저점
        self.assertTrue(self.chase()["pullback_seen"])
        self.assertGreater(float(self.chase()["pullback_low"]), 18200.0 * 1.003)
        # 수급 자료가 불충분하므로 가격 모양만으로는 매수하지 않는다.
        self.feed(price=18480, hr_low=18200, advance_sec=45,
                  buy_cum=1400, sell_cum=1100)
        self.assertEqual(self.engine._positions(), {})

    def test_valid_retest_and_flow_buys_then_rearms(self) -> None:
        self.buy_shadow()
        position = self.pos(1)
        self.assertIsNotNone(position)
        self.assertEqual(position["phase"], "HOLD")
        self.assertFalse(position["real"])
        # 1발 뒤 재무장 — DONE이 아니라 CHASE + "산 저점보다 1% 깊은" 문턱이 걸려야 한다
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.assertAlmostEqual(float(self.chase()["dead_low"]), 18200.0 * 0.99)

    def test_staircase_resets_low(self) -> None:
        self.feed(price=20000, hr_low=20000)
        self.feed(price=18200, hr_low=18200)
        self.feed(price=18480, hr_low=18200)
        self.assertEqual(self.chase()["phase"], "OBSERVE")
        self.feed(price=17800, hr_low=17800)          # 관찰 중 신저점 → 리셋
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.assertGreaterEqual(int(self.chase()["reset_steps"]), 1)
        self.assertFalse(self.chase()["pullback_seen"])
        self.feed(price=18080, hr_low=17800)
        self.assertEqual(self.chase()["phase"], "OBSERVE")
        self.assertAlmostEqual(float(self.chase()["low"]), 17800.0)

    def test_giveup_above_chase_cap(self) -> None:
        self.feed(price=20000, hr_low=20000)
        self.feed(price=18200, hr_low=18200)
        self.feed(price=18570, hr_low=18200)          # 저점+2% 초과 — 포기
        self.assertAlmostEqual(float(self.chase()["dead_low"]), 18200.0)
        self.assertEqual(self.engine._positions(), {})
        self.feed(price=18480, hr_low=18200)
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.feed(price=18000, hr_low=18000)          # 신저점 → 재무장
        self.assertAlmostEqual(float(self.chase()["dead_low"]), 0.0)

    def test_sell_speed_restrengthening_blocks_then_buy_acceleration_allows(self) -> None:
        """최근 10초 매도 재강화면 보류하고 매수 재가속 뒤에만 산다."""
        self.first_entry_setup()
        self.feed(price=18480, hr_low=18200, advance_sec=5,
                  buy_cum=1350, sell_cum=4050)
        self.feed(price=18380, hr_low=18200, advance_sec=20,
                  buy_cum=1500, sell_cum=4120)
        self.feed(price=18390, hr_low=18200, advance_sec=20,
                  buy_cum=1700, sell_cum=4210)
        self.feed(price=18420, hr_low=18200, advance_sec=10,
                  buy_cum=2050, sell_cum=4410)
        self.feed(price=18480, hr_low=18200, advance_sec=10,
                  buy_cum=2300, sell_cum=5000)        # 최근 10초 매도 재강화
        self.assertEqual(self.chase()["phase"], "OBSERVE")
        self.assertEqual(self.engine._positions(), {})
        self.feed(price=18470, hr_low=18200, advance_sec=10,
                  buy_cum=2450, sell_cum=5050)
        self.feed(price=18480, hr_low=18200, advance_sec=10,
                  buy_cum=2750, sell_cum=5080)
        self.feed(price=18490, hr_low=18200, advance_sec=10,
                  buy_cum=3450, sell_cum=5100)        # 매수속도 증가·매도속도 감소
        self.assertIsNotNone(self.pos(1))

    def test_pullback_below_higher_low_floor_requires_fresh_rebound(self) -> None:
        self.first_entry_setup()
        self.feed(price=18480, hr_low=18200, advance_sec=5,
                  buy_cum=1350, sell_cum=4050)
        self.feed(price=18240, hr_low=18200, advance_sec=20,
                  buy_cum=1500, sell_cum=4120)        # 원저점+0.22%: 높은 저점 실패
        self.assertEqual(self.chase()["phase"], "CHASE")
        self.assertFalse(self.chase()["pullback_seen"])
        self.assertEqual(self.engine._positions(), {})

    def test_missing_flow_data_is_fail_closed(self) -> None:
        self.feed(price=20000, hr_low=20000)
        self.feed(price=18200, hr_low=18200)
        self.feed(price=18480, hr_low=18200)
        self.feed(price=18380, hr_low=18200, advance_sec=20)
        self.feed(price=18480, hr_low=18200, advance_sec=45)
        self.assertEqual(self.chase()["phase"], "OBSERVE")
        self.assertEqual(self.engine._positions(), {})

    def test_rearm_second_entry_needs_lower_low(self) -> None:
        self.buy_shadow()                              # 1발째
        self.assertEqual(self.chase()["phase"], "CHASE")
        # 산 저점보다 1% 깊어지기 전에는 죽은 저점이 유지되고, 더 깊어지면 재무장한다.
        self.feed(price=18100, hr_low=18100, advance_sec=20,
                  buy_cum=2900, sell_cum=5000)
        self.assertGreater(float(self.chase()["dead_low"]), 0.0)
        self.feed(price=18050, hr_low=18050, advance_sec=20,
                  buy_cum=3000, sell_cum=6000)
        self.feed(price=17800, hr_low=17800, advance_sec=20,
                  buy_cum=3100, sell_cum=7500)
        self.assertAlmostEqual(float(self.chase()["dead_low"]), 0.0)
        self.complete_retest(low=17800, buy_base=3100, sell_base=7500)
        self.assertIsNotNone(self.pos(2))
        self.assertEqual(self.chase()["phase"], "DONE")     # 하루 2회 소진
        entered = [c for c in self.engine.state.get("entered_codes", [])]
        self.assertEqual(entered.count(CODE), 2)
        # 3발째는 없다
        self.feed(price=16000, hr_low=16000)
        self.assertEqual(self.chase()["phase"], "DONE")

    def snap(self, price: float, when: datetime, *,
             buy_cum: float = 1000.0, sell_cum: float = 1000.0) -> None:
        write_json(self.config.snapshot_path, {
            "codes": {CODE: {
                "cur": price, "ts": when.isoformat(),
                "cum_vol": 10000.0, "che_str": 60.0,
                "buy_money_cum": buy_cum, "sell_money_cum": sell_cum,
            }},
        })
        self.engine._snapshot_cache = (0.0, {})

    def set_rising_ma(self, reference: float) -> None:
        rows = ["date,code,close"]
        start = datetime(2026, 7, 1, tzinfo=KST)
        for index in range(21):
            day = start + timedelta(days=index)
            rows.append(
                f"{day:%Y%m%d},{CODE},{reference * (0.80 + index * 0.01):.4f}"
            )
        self.config.eod_bars_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        body = reference * 1.08
        write_json(self.config.bars_path, {
            "m": {CODE: {"prev": [
                [body, body, body, body],
                [body, body, body, body],
                [body, body, body, body],
            ]}},
        })
        self.engine._daily_ma_cache = ("", {})
        self.engine._bars_cache = (-1.0, {})

    def test_take_profit_5_same_day(self) -> None:
        position = self.buy_shadow()
        entry = float(position["entry_price"])
        self.now += timedelta(seconds=60)
        self.snap(entry * 1.051, self.now)
        self.engine._evaluate_exit(position, self.now)
        self.assertEqual(position["phase"], "CLOSED")
        self.assertIn("TAKE_PROFIT", position["exit_reason"])

    def test_no_intraday_sell_without_tp(self) -> None:
        position = self.buy_shadow()
        entry = float(position["entry_price"])
        self.now += timedelta(seconds=60)
        self.snap(entry * 0.90, self.now)
        self.engine._evaluate_exit(position, self.now)
        self.assertEqual(position["phase"], "HOLD")

    def test_next_morning_does_not_sell_immediately_at_0901(self) -> None:
        position = self.buy_shadow()
        entry = float(position["entry_price"])
        next_morning = datetime(2026, 8, 4, 9, 1, 0, tzinfo=KST)
        self.snap(entry * 0.97, next_morning)
        self.engine._evaluate_exit(position, next_morning)
        self.assertEqual(position["phase"], "HOLD")
        self.assertAlmostEqual(position["morning_peak_price"], entry * 0.97)

    def test_next_morning_rising_ma_holds_after_peak_pullback(self) -> None:
        position = self.buy_shadow()
        entry = float(position["entry_price"])
        peak_at = datetime(2026, 8, 4, 9, 2, 0, tzinfo=KST)
        pullback_at = datetime(2026, 8, 4, 9, 5, 0, tzinfo=KST)
        with patch(
            "strategy_06_crash_low_chase_v1.ma3_rider_permit",
            return_value=True,
        ):
            self.snap(entry * 1.10, peak_at, buy_cum=1000, sell_cum=1000)
            self.engine._evaluate_exit(position, peak_at)
            self.snap(entry * 1.0835, pullback_at, buy_cum=1100, sell_cum=1400)
            self.engine._evaluate_exit(position, pullback_at)
        self.assertEqual(position["phase"], "HOLD")
        self.assertTrue(position["morning_daily_ma_permit"])

    def test_next_morning_peak_trail_sells_on_seller_dominance(self) -> None:
        position = self.buy_shadow()
        entry = float(position["entry_price"])
        peak_at = datetime(2026, 8, 4, 9, 2, 0, tzinfo=KST)
        self.snap(entry * 1.10, peak_at, buy_cum=1000, sell_cum=1000)
        self.engine._evaluate_exit(position, peak_at)
        pullback_at = datetime(2026, 8, 4, 9, 5, 0, tzinfo=KST)
        self.snap(entry * 1.075, pullback_at, buy_cum=1100, sell_cum=1400)
        self.engine._evaluate_exit(position, pullback_at)
        self.assertEqual(position["phase"], "CLOSED")
        self.assertIn("NEXT_MORNING_PROFIT_TRAIL", position["exit_reason"])

    def test_no_unapproved_force_exit_at_0930(self) -> None:
        position = self.buy_shadow()
        observed_at = datetime(2026, 8, 4, 9, 30, 0, tzinfo=KST)
        self.engine._evaluate_exit(position, observed_at)
        self.assertEqual(position["phase"], "HOLD")

    def test_signal_record_has_flow_columns(self) -> None:
        self.buy_shadow()
        files = list((self.base / "events").glob("strategy_06_signals_*.csv"))
        self.assertTrue(files)
        header = files[0].read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertIn("dip_buy_sell_ratio", header)
        self.assertIn("flow_flip", header)
        self.assertIn("pullback_low", header)
        self.assertIn("recent_buy_rate_10s", header)
        self.assertIn("flow_accel", header)


if __name__ == "__main__":
    unittest.main()
