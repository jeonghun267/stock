# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from strategy_05_base_breakout_signal_v1 import (
    Bar,
    BaseBreakoutSignalMonitor,
    CodeState,
    MicroPoint,
    SignalConfig,
    detect_base_breakout,
)
from strategy_01_rotation_engine_v2 import kst_now
from strategy_05_rotation_engine_v1 import Strategy05Engine, build_config
from strategy_05_signal_contract_v1 import select_fresh_signals
from strategy_common_hold_sell_v1 import STRATEGY_PROFILES, StrategyId


def point(
    ts: datetime,
    price: float,
    bv: float,
    sv: float,
    bm: float,
    sm: float,
    *,
    spread_bps: float = 5,
    microprice_edge_bps: float = 1,
) -> MicroPoint:
    return MicroPoint(
        ts=ts,
        price=price,
        buy_volume_cum=bv,
        sell_volume_cum=sv,
        buy_money_cum=bm,
        sell_money_cum=sm,
        ask_price=price + 10,
        bid_price=price,
        spread_bps=spread_bps,
        microprice_edge_bps=microprice_edge_bps,
    )


class FakeSlots:
    def __init__(self) -> None:
        self.owned: set[str] = set()

    def acquire(self, code: str, _owner: str, _day: str) -> bool:
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

class Strategy05Tests(unittest.TestCase):
    def test_valid_30_bar_base_breakout(self) -> None:
        start = datetime(2026, 7, 27, 12, 44)
        bars = [
            Bar(start + timedelta(minutes=i), 19000, 19100, 18950, 19020, 100)
            for i in range(30)
        ]
        bars.append(Bar(start + timedelta(minutes=30), 19020, 19700, 19020, 19600, 700))
        found = detect_base_breakout(bars)
        self.assertIsNotNone(found)
        self.assertEqual(found["base_high"], 19100)
        self.assertGreaterEqual(found["breakout_volx"], 6)
        self.assertIsNone(detect_base_breakout(bars, min_volx=10))

    def test_minute_gap_clears_stale_base(self) -> None:
        monitor = BaseBreakoutSignalMonitor(SignalConfig())
        state = monitor.states.setdefault("445090", CodeState())
        start = datetime(2026, 7, 27, 10, 0)
        state.bars.extend([
            Bar(start - timedelta(minutes=30 - i), 19000, 19100, 18950, 19020, 100)
            for i in range(30)
        ])
        state.building = Bar(start, 19020, 19100, 19000, 19050, 100)
        state.phase = "WAIT_RETEST"
        state.breakout_line = 19100
        updated = monitor.update_minute(
            "445090",
            start + timedelta(minutes=2),
            {"o": 19050, "h": 19120, "l": 19040, "c": 19100, "v": 100},
        )
        self.assertFalse(updated)
        self.assertEqual(len(state.bars), 0)
        self.assertEqual(state.phase, "SCAN")


    def test_no_chase_and_retest_flow_confirmation(self) -> None:
        config = SignalConfig()
        monitor = BaseBreakoutSignalMonitor(config)
        state = monitor.states.setdefault("445090", CodeState())
        base_ts = datetime(2026, 7, 27, 13, 15)
        state.phase = "WAIT_RETEST"
        state.breakout_line = 19200
        state.breakout_ts = base_ts
        state.base_range_pct = 1.5
        state.breakout_volx = 7.0
        state.wait_left = 10

        row, fired = monitor.process_micro(
            "445090", "test",
            point(base_ts, 19600, 0, 0, 0, 0),
            allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "BREAKOUT_RETEST_WAIT")

        sequence = [
            (1, 19200, 15, 12, 1_200_000, 1_100_000),
            (4, 19210, 18, 14, 1_600_000, 1_300_000),
            (11, 19210, 50, 30, 2_500_000, 1_500_000),
            (19, 19210, 100, 60, 4_000_000, 2_000_000),
            (29, 19260, 300, 120, 8_000_000, 3_000_000),
            (31, 19260, 500, 150, 12_000_000, 3_500_000),
            (34, 19260, 750, 190, 17_000_000, 4_200_000),
            (37, 19260, 1100, 230, 24_000_000, 5_000_000),
        ]
        fired_row = None
        for sec, price_value, bv, sv, bm, sm in sequence:
            row, fired = monitor.process_micro(
                "445090", "test",
                point(base_ts + timedelta(seconds=sec), price_value, bv, sv, bm, sm),
                allow_signal=True,
            )
            if fired:
                fired_row = row
                break
        self.assertIsNotNone(fired_row, row)
        self.assertEqual(fired_row["action"], "BUY_READY")
        self.assertTrue(fired_row["line_reclaimed"])
        self.assertTrue(fired_row["chase_ok"])
        self.assertTrue(fired_row["fast_flow_ok"])
        self.assertEqual(fired_row["entry_lane"], "S05_BASE:19200.0000:19200.0000")
        self.assertGreaterEqual(fired_row["rebound_pct"], 0.3)
        self.assertLessEqual(fired_row["rebound_pct"], 1.0)
    def test_persistence_uses_buy_money_not_total_money(self) -> None:
        monitor = BaseBreakoutSignalMonitor(SignalConfig())
        state = CodeState()
        start = datetime(2026, 7, 27, 13, 0)
        state.micro.extend([
            point(start, 19200, 0, 0, 0, 0),
            point(start + timedelta(seconds=10), 19200, 10, 10, 20_000_000, 5_000_000),
            point(start + timedelta(seconds=30), 19200, 20, 20, 100_000_000, 80_000_000),
            point(start + timedelta(seconds=40), 19200, 30, 30, 101_000_000, 140_000_000),
        ])
        buy10 = monitor._money_rate(state, 10, side="buy")
        buy30 = monitor._money_rate(state, 30, side="buy")
        sell10 = monitor._money_rate(state, 10, side="sell")
        sell30 = monitor._money_rate(state, 30, side="sell")
        self.assertLess(buy10, 0.5 * buy30)
        self.assertGreater(sell10, sell30)


    def test_book_quality_is_an_actual_buy_gate(self) -> None:
        config = SignalConfig()
        base_ts = datetime(2026, 7, 27, 13, 15)
        reset = point(base_ts, 19200, 0, 0, 0, 0)
        history = [
            reset,
            point(base_ts + timedelta(seconds=16), 19210, 100, 60, 2_000_000, 1_000_000),
            point(base_ts + timedelta(seconds=20), 19210, 150, 75, 3_000_000, 1_300_000),
            point(base_ts + timedelta(seconds=26), 19220, 300, 100, 6_000_000, 2_000_000),
            point(base_ts + timedelta(seconds=29), 19240, 450, 130, 9_000_000, 2_500_000),
        ]

        monitor = BaseBreakoutSignalMonitor(config)
        state = monitor.states.setdefault("445090", CodeState())
        state.phase = "BUY_CONFIRM"
        state.reset_point = reset
        state.breakout_line = 19200
        state.breakout_ts = base_ts
        state.micro.extend(history)
        row, fired = monitor.process_micro(
            "445090", "test",
            point(
                base_ts + timedelta(seconds=31),
                19260, 700, 160, 14_000_000, 3_000_000,
                microprice_edge_bps=-1,
            ),
            allow_signal=True,
        )
        self.assertFalse(fired)
        row, fired = monitor.process_micro(
            "445090", "test",
            point(
                base_ts + timedelta(seconds=34),
                19260, 1100, 210, 22_000_000, 4_300_000,
                microprice_edge_bps=-1,
            ),
            allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "MICROPRICE_CONFIRM_WAIT")
        row, fired = monitor.process_micro(
            "445090", "test",
            point(
                base_ts + timedelta(seconds=35),
                19260, 1250, 230, 25_000_000, 4_700_000,
            ),
            allow_signal=True,
        )
        self.assertTrue(fired)

        monitor = BaseBreakoutSignalMonitor(config)
        state = monitor.states.setdefault("445090", CodeState())
        state.phase = "BUY_CONFIRM"
        state.reset_point = reset
        state.breakout_line = 19200
        state.breakout_ts = base_ts
        state.micro.extend(history)
        row, fired = monitor.process_micro(
            "445090", "test",
            point(
                base_ts + timedelta(seconds=31),
                19260, 700, 160, 14_000_000, 3_000_000,
                spread_bps=40,
            ),
            allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertTrue(row["fast_flow_ok"])
        self.assertFalse(row["spread_ok"])

    def test_retest_location_guards_block_failed_breakout_and_chase(self) -> None:
        config = SignalConfig()
        base_ts = datetime(2026, 7, 27, 13, 15)

        monitor = BaseBreakoutSignalMonitor(config)
        state = monitor.states.setdefault("445090", CodeState())
        state.phase = "WAIT_RETEST"
        state.breakout_line = 19200
        state.breakout_ts = base_ts
        row, fired = monitor.process_micro(
            "445090", "test",
            point(base_ts, 18500, 0, 0, 0, 0),
            allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertEqual(row["reason"], "RETEST_TOO_DEEP")
        self.assertEqual(state.phase, "SCAN")

        monitor = BaseBreakoutSignalMonitor(config)
        state = monitor.states.setdefault("445090", CodeState())
        reset = point(base_ts, 19200, 0, 0, 0, 0)
        state.phase = "BUY_CONFIRM"
        state.reset_point = reset
        state.breakout_line = 19200
        state.breakout_ts = base_ts
        state.micro.extend([
            reset,
            point(base_ts + timedelta(seconds=16), 19210, 100, 60, 2_000_000, 1_000_000),
            point(base_ts + timedelta(seconds=26), 19220, 300, 100, 6_000_000, 2_000_000),
            point(base_ts + timedelta(seconds=29), 19240, 450, 130, 9_000_000, 2_500_000),
        ])
        row, fired = monitor.process_micro(
            "445090", "test",
            point(
                base_ts + timedelta(seconds=31),
                20000, 700, 160, 14_000_000, 3_000_000,
            ),
            allow_signal=True,
        )
        self.assertFalse(fired)
        self.assertTrue(row["fast_flow_ok"])
        self.assertFalse(row["chase_ok"])
        self.assertGreater(row["rebound_pct"], 1.0)
    def test_s05_shadow_combines_common_exit_base_failure_and_ma_rider(self) -> None:
        now = kst_now().replace(hour=13, minute=20, second=0, microsecond=0)

        def run_case(*, rising_support: bool):
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
                stamp = now.replace(tzinfo=None).isoformat(timespec="seconds")
                signal = {
                    "schema": "strategy_05_base_breakout_signal_v1",
                    "mode": "SIGNAL_ONLY_ORDER_ZERO",
                    "date": now.strftime("%Y%m%d"),
                    "updated_at": stamp,
                    "signals": [{
                        "ts": stamp,
                        "code": "123456",
                        "name": "TEST",
                        "action": "BUY_READY",
                        "reason": "BASE_RETEST+REAL_LOW+EXACT_BUY_DOMINANCE+BOOK_CONFIRM",
                        "mode": "SIGNAL_ONLY_ORDER_ZERO",
                        "anchor_id": "base:retest",
                        "entry_lane": "S05_BASE:10000.0000:9950.0000",
                        "signal_sequence": 1,
                        "breakout_volx": 7.0,
                        "buy_ratio": 0.7,
                    }],
                }
                config.signal_path.write_text(json.dumps(signal), encoding="utf-8")
                config.names_path.write_text("{}", encoding="utf-8")
                daily = ["code,date,close"]
                for day in range(1, 22):
                    close = (
                        9700 + 5 * (day - 1)
                        if rising_support else 11000 - 5 * (day - 1)
                    )
                    daily.append(f"123456,202607{day:02d},{close}")
                config.eod_bars_path.write_text(
                    "\n".join(daily) + "\n", encoding="utf-8")

                broker = FakeBroker()
                logger = logging.getLogger(
                    f"strategy05-combined-{int(rising_support)}")
                logger.handlers.clear()
                logger.addHandler(logging.NullHandler())
                engine = Strategy05Engine(
                    config,
                    broker=broker,
                    slots=FakeSlots(),
                    logger=logger,
                    signal_selector=select_fresh_signals,
                )

                def write_market(
                    sec, price_value, buy_money, sell_money,
                    buy_volume, sell_volume, bearish,
                ):
                    observed_at = now + timedelta(seconds=sec)
                    market_stamp = observed_at.replace(tzinfo=None).isoformat(
                        timespec="seconds")
                    config.snapshot_path.write_text(json.dumps({"codes": {
                        "123456": {
                            "ts": market_stamp,
                            "cur": price_value,
                            "cum_vol": buy_volume + sell_volume,
                            "buy_vol_cum": buy_volume,
                            "sell_vol_cum": sell_volume,
                            "buy_money_cum": buy_money,
                            "sell_money_cum": sell_money,
                            "che_str": 90,
                        },
                    }}), encoding="utf-8")
                    config.board_path.write_text(json.dumps({
                        "ts": market_stamp,
                        "all_items": [{
                            "code": "123456",
                            "money_speed_5s": 2_000_000,
                            "money_speed_10s": 1_800_000,
                            "money_speed_30s": 1_500_000,
                        }],
                    }), encoding="utf-8")
                    current_close = price_value if bearish else 10_080
                    config.bars_path.write_text(json.dumps({"m": {
                        "123456": {
                            "o": 10_050,
                            "h": 10_100,
                            "l": min(price_value, 10_040),
                            "c": current_close,
                            "prev": [[10_000, 10_100, 9_990, 10_080]],
                        },
                    }}), encoding="utf-8")
                    return observed_at

                entry_at = write_market(
                    0, 10_100, 20_000_000, 10_000_000,
                    1_000, 1_000, False)
                engine.tick(entry_at)
                self.assertEqual(
                    engine._active_positions()["123456"]["phase"], "HOLD")
                sequence = [
                    (5, 10_080, 25_000_000, 15_000_000, 1_500, 1_500),
                    (10, 10_060, 30_000_000, 20_000_000, 2_000, 2_000),
                    (13, 10_040, 33_000_000, 23_000_000, 2_300, 2_300),
                    (15, 9_900, 34_000_000, 27_000_000, 2_400, 2_600),
                    (18, 9_900, 35_000_000, 35_000_000, 2_550, 3_000),
                    (20, 9_900, 36_000_000, 42_000_000, 2_650, 3_500),
                    (21, 9_900, 36_500_000, 46_000_000, 2_700, 3_800),
                    (22, 9_900, 37_000_000, 50_000_000, 2_750, 4_100),
                    (23, 9_900, 37_500_000, 54_000_000, 2_800, 4_400),
                ]
                for sec, price_value, bm, sm, bv, sv in sequence:
                    engine.tick(write_market(
                        sec, price_value, bm, sm, bv, sv, sec >= 15))
                return engine, broker

        engine, broker = run_case(rising_support=False)
        self.assertEqual(engine._active_positions(), {})
        trade = engine.state["history"][-1]
        self.assertIn("S05_BASE_FAILURE_EXIT", trade["exit_reason"])
        self.assertGreater(trade["gross_return_pct"], -2.0)
        self.assertTrue(all(
            row.get("side") == "BUY" for row in broker.submissions))
        self.assertFalse(broker.real_session)

        # ★[RISING-HOLD 단일화 2026-08-05] 잠금 시험 — 지우기 전에 읽을 것.
        #   종전에는 여기서 phase=="HOLD" 와 history==[] 를 기대했다. rising_support
        #   는 '일봉' 21일치 상승 종가만 넣는 스위치이고, S05 만 남아 있던
        #   _daily_ma_permit_legacy(일봉 5/10/20선)가 그걸 읽어 상승보유를 켰다.
        #   일봉 5일선은 장중에 안 움직이는 고정값이라, 일봉 정배열 종목을 잡으면
        #   매도세가 압도해도(아래 대본 끝: 매수 3,750만 vs 매도 5,400만) 하루 종일
        #   안 팔았다 — 8/3 에스피지 사고가 그것이다.
        #   지금은 상승보유 판정이 3분봉(ma3_common_v1) 하나로 통일됐고, 이 대본은
        #   3분봉 완성봉이 1개뿐이라 상승보유가 애초에 안 켜진다 → 정상 매도된다.
        #   일봉 경로가 되살아나면 아래가 터진다.
        engine, broker = run_case(rising_support=True)
        self.assertEqual(
            engine._active_positions(), {},
            "일봉 상승만으로 매도가 다시 막혔다 — legacy 일봉 경로가 되살아났다",
        )
        self.assertTrue(engine.state["history"])
        self.assertFalse(broker.real_session)
    def test_contract_and_common_rotation_identity(self) -> None:
        now = datetime(2026, 7, 27, 13, 20)
        payload = {
            "schema": "strategy_05_base_breakout_signal_v1",
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "date": "20260727",
            "updated_at": now.isoformat(),
            "signals": [{
                "ts": now.isoformat(),
                "code": "445090",
                "action": "BUY_READY",
                "mode": "SIGNAL_ONLY_ORDER_ZERO",
                "anchor_id": "base:retest",
                "signal_sequence": 1,
                "breakout_volx": 7.0,
                "buy_ratio": 0.7,
            }],
        }
        selected = select_fresh_signals(payload, now=now, max_age_sec=5)
        self.assertEqual(selected[0]["strategy_id"], "S05_BASE_BREAKOUT")
        config = build_config()
        # ★[2026-08-06 친구님 지시 "QTY 2주 원래대로 1주로 돌려줘"] 2 -> 1.
        self.assertEqual(config.quantity, 1)
        self.assertEqual(config.max_daily_codes, 6)
        self.assertEqual(config.max_cycles_per_code, 2)
        self.assertEqual(config.strategy_id, StrategyId.S05_BASE_BREAKOUT)
        self.assertIn(StrategyId.S05_BASE_BREAKOUT, STRATEGY_PROFILES)

    def test_ten_multiple_is_priority_not_a_hard_cut(self) -> None:
        now = datetime(2026, 7, 27, 13, 20)
        base = {
            "ts": now.isoformat(),
            "action": "BUY_READY",
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "signal_sequence": 1,
            "buy_ratio": 0.7,
        }
        payload = {
            "schema": "strategy_05_base_breakout_signal_v1",
            "mode": "SIGNAL_ONLY_ORDER_ZERO",
            "date": "20260727",
            "updated_at": now.isoformat(),
            "signals": [
                dict(base, code="111111", anchor_id="six", breakout_volx=7.0),
                dict(base, code="222222", anchor_id="ten", breakout_volx=11.0),
            ],
        }
        selected = select_fresh_signals(payload, now=now, max_age_sec=5)
        self.assertEqual([row["code"] for row in selected], ["222222", "111111"])

if __name__ == "__main__":
    unittest.main()
