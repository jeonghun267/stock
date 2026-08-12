# -*- coding: utf-8 -*-
"""새전략 02 독립 회전엔진: 매수만 S02, 보유·매도·주문복구는 공통."""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict, deque
from dataclasses import replace
from datetime import time as day_time, timedelta
from pathlib import Path

# ★[MA3-COMMON 2026-08-03] 상승보유 = 3분봉 5/10/20선 + 매수세 우위(전 전략 공통).
from ma3_common_v1 import (
    buy_side_alive as ma3_buy_side_alive,
    ma3_rows,
    ma5_broken as ma3_ma5_broken,
    rider_permit as ma3_rider_permit,
)
from strategy_01_rotation_engine_v2 import (
    Config,
    ProcessLock,
    Strategy01Engine,
    number,
    read_json,
)
from strategy_02_signal_contract_v1 import select_fresh_signals
from strategy_common_hold_sell_v1 import StrategyId


class Strategy02Engine(Strategy01Engine):
    """S02-only market telemetry adapter for the shared hold/sell engine."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._s02_micro = defaultdict(lambda: deque(maxlen=80))

    def _load_daily_ma(self) -> None:
        if self._daily_ma is not None:
            return
        self._daily_ma = {}
        by_code = {}
        try:
            with self.config.eod_bars_path.open(
                encoding="utf-8-sig", newline="",
            ) as fh:
                for raw in csv.DictReader(fh):
                    code = str(raw.get("code") or "").zfill(6)
                    day = str(raw.get("date") or "").replace("-", "")
                    close = number(raw.get("close"))
                    if len(code) == 6 and code.isdigit() and day and close > 0:
                        by_code.setdefault(code, {})[day] = close
        except OSError:
            self.log.warning("일봉 파일 없음 — S02 상승보유 허가 비활성")
            return
        for code, series in by_code.items():
            days = sorted(series)
            if len(days) < 21:
                continue
            closes = [series[day] for day in days]
            self._daily_ma[code] = {
                "ma5": sum(closes[-5:]) / 5,
                "ma5_prev": sum(closes[-6:-1]) / 5,
                "ma10": sum(closes[-10:]) / 10,
                "ma10_prev": sum(closes[-11:-1]) / 10,
                "ma20": sum(closes[-20:]) / 20,
                "ma20_prev": sum(closes[-21:-1]) / 20,
            }

    def _bar_row(self, code: str):
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        return (source or {}).get(str(code).zfill(6)) or {}

    def _one_minute_bull_to_bear(self, code: str) -> bool:
        row = self._bar_row(code)
        previous = row.get("prev") or []
        if not previous or len(previous[-1]) < 4:
            return False
        previous_bull = number(previous[-1][3]) > number(previous[-1][0])
        current_open = number(row.get("o"))
        current_close = number(row.get("c"))
        return previous_bull and current_open > 0 and current_close < current_open

    def _one_minute_bearish(self, code: str) -> bool:
        """★[TRAIL-FLOW 2026-08-03] 진행 중 1분봉이 음봉인가(종가 < 시가).

        _one_minute_bull_to_bear 는 직전봉이 양봉이어야 해서 연속 음봉을 놓친다.
        꼭지 판정에는 전환이 아니라 '지금 음봉인가'가 필요하다.
        """
        row = self._bar_row(code)
        current_open = number(row.get("o"))
        current_close = number(row.get("c"))
        return bool(current_open > 0 and current_close > 0
                    and current_close < current_open)

    def _daily_ma_permit(self, code: str, price: float,
                         buy_side=None) -> bool:
        """★[MA3-COMMON 2026-08-03] 3분봉 5/10/20선 + 매수세 우위로 통일(공용코어와 동일).

        종전 S02 판정은 일봉 5선↑·10선↑·20선↑·5선>10선 + (완성봉≥5선 또는 현재가≥10선)
        이었다. 일봉이라 장중에 안 깨져서 상승보유가 사실상 영구 참이었다.
        되돌리기: backup\\strategy_02_rotation_engine_v1_20260803_ma3wire.py
        """
        return ma3_rider_permit(code, price, buy_side=buy_side)

    def _daily_ma_permit_legacy(self, code: str, price: float) -> bool:
        self._load_daily_ma()
        row = (self._daily_ma or {}).get(str(code).zfill(6))
        if not row:
            return False
        rising = (
            row["ma5"] > row["ma5_prev"]
            and row["ma10"] >= row["ma10_prev"]
            and row["ma20"] > row["ma20_prev"]
            and row["ma5"] > row["ma10"]
        )
        if not rising:
            return False
        bars = self._bar_row(code)
        previous = bars.get("prev") or []
        completed_close = (
            number(previous[-1][3])
            if previous and len(previous[-1]) >= 4 else price
        )
        rides_ma5 = completed_close >= row["ma5"]
        ma10_support = price >= row["ma10"]
        return rides_ma5 or ma10_support

    def _snapshot_point(self, code, now):
        point = super()._snapshot_point(code, now)
        if point is None:
            return None
        snapshot = read_json(self.config.snapshot_path, {})
        raw = (snapshot.get("codes") or {}).get(str(code).zfill(6)) or {}
        point["che_str"] = max(0.0, number(raw.get("che_str")))
        point["buy_vol_cum"] = number(raw.get("buy_vol_cum"), -1.0)
        point["sell_vol_cum"] = number(raw.get("sell_vol_cum"), -1.0)
        return point

    def _micro_rates(self, code: str, point):
        rows = self._s02_micro[str(code).zfill(6)]
        current = (
            point["ts"],
            number(point.get("buy_vol_cum"), -1.0),
            number(point.get("sell_vol_cum"), -1.0),
            number(point.get("che_str")),
        )
        if min(current[1], current[2]) < 0 or current[3] <= 0:
            rows.clear()
            return 0.0, 0.0, 0.0, 0.0, 0.0
        if rows and (
            current[0] <= rows[-1][0]
            or current[1] < rows[-1][1]
            or current[2] < rows[-1][2]
        ):
            rows.clear()
        rows.append(current)
        while rows and (current[0] - rows[0][0]).total_seconds() > 20:
            rows.popleft()

        def at_or_before(target):
            for item in reversed(rows):
                if item[0] <= target:
                    return item
            return None

        recent_target = current[0] - timedelta(seconds=5)
        previous_target = current[0] - timedelta(seconds=15)
        recent_start = at_or_before(recent_target)
        previous_start = at_or_before(previous_target)
        if recent_start is None or previous_start is None:
            return 0.0, 0.0, 0.0, current[3], 0.0
        if (
            (recent_target - recent_start[0]).total_seconds() > 2
            or (previous_target - previous_start[0]).total_seconds() > 3
        ):
            return 0.0, 0.0, 0.0, current[3], 0.0
        recent_span = (current[0] - recent_start[0]).total_seconds()
        previous_span = (recent_start[0] - previous_start[0]).total_seconds()
        deltas = (
            current[1] - recent_start[1],
            current[2] - recent_start[2],
            recent_start[2] - previous_start[2],
        )
        if recent_span <= 0 or previous_span <= 0 or min(deltas) < 0:
            return 0.0, 0.0, 0.0, current[3], 0.0
        return (
            deltas[0] / recent_span,
            deltas[1] / recent_span,
            deltas[2] / previous_span,
            current[3],
            current[3] - recent_start[3],
        )

    def _build_observation(self, position, point):
        observation = super()._build_observation(position, point)
        (
            buy_volume_5s,
            sell_volume_5s,
            previous_sell_volume_10s,
            che_str,
            che_change_5s,
        ) = self._micro_rates(position["code"], point)
        # ★[MA3-COMMON 2026-08-03] 종전 일봉 5/10/20선 → 3분봉으로 교체.
        #   ma10_support·ma20_rising 은 S05(베이스 붕괴 방어)도 그대로 읽는다.
        code = str(position["code"]).zfill(6)
        price = point["price"]
        ma3 = ma3_rows(code) or {}
        # 상승보유는 부모(_build_observation)가 거래대금 속도만으로 이미 한 번 판정했다.
        # S02·S05 는 체결량 속도까지 있으니 그 3종으로 다시 정확히 판정해 덮어쓴다.
        buy_side = ma3_buy_side_alive(
            float(observation.buy_money_per_sec_10s),
            float(observation.buy_money_per_sec_30s),
            float(observation.sell_money_per_sec_10s),
            float(observation.sell_money_per_sec_30s),
            sell_volume_5s,
            previous_sell_volume_10s,
        )
        return replace(
            observation,
            buy_volume_per_sec_5s=buy_volume_5s,
            sell_volume_per_sec_5s=sell_volume_5s,
            sell_volume_per_sec_previous_10s=previous_sell_volume_10s,
            che_str=che_str,
            che_str_change_5s=che_change_5s,
            one_minute_bull_to_bear=self._one_minute_bull_to_bear(
                position["code"]),
            one_minute_bearish=self._one_minute_bearish(position["code"]),
            daily_ma_permit=self._daily_ma_permit(code, price, buy_side=buy_side),
            daily_ma5_broken=ma3_ma5_broken(code, price),
            ma10_support=bool(
                ma3.get("ma10", 0.0) > 0 and price >= ma3["ma10"]
            ),
            ma20_rising=bool(
                ma3.get("ma20", 0.0) > ma3.get("ma20_prev", 0.0) > 0
            ),
        )


def build_config() -> Config:
    return Config(
        signal_path=Path(r"C:\stock_bot\data\strategy_02_low_buy_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(r"C:\stock_bot\data\strategy_02_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_02_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_02_rotation_v1.log"),
        approval_path=Path(r"C:\stock_bot\config\strategy_02_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_02_off.flag"),
        manual_buy_block_path=Path(r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_02_rotation_v1.lock"),
        live_requested=os.environ.get("S02_LIVE", "NO").strip().upper() == "YES",
        quantity=int(os.environ.get("S02_QTY", "1")),
        max_slots=int(os.environ.get("S02_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S02_MAX_DAILY_CODES", "15")),
        max_cycles_per_code=int(os.environ.get("S02_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=int(os.environ.get("S02_ROTATION_CAPITAL_KRW", "2000000")),
        max_sell_retries=int(os.environ.get("S02_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get("S02_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get("S02_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get("S02_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S02_FILL_WAIT_SEC", "8")),
        loop_sec=float(os.environ.get("S02_LOOP_SEC", "1")),
        # ★[2026-08-01 친구님 승인 "3건 다 고쳐줘"] 09:30 → 09:06 — 신호기 창(ENTRY_START
        #   09:06)과의 불일치 수리. 신호 신선도 5초라 09:30 시작이면 09:06~09:29 딥모드
        #   신호가 전량 소멸했다(8/1 점검 발견 1). 저점은 25/30개가 09:10 이전 형성.
        #   롤백: backup\strategy_02_rotation_engine_v1_20260801_secfix.py 복원.
        entry_start=day_time(9, 6),
        entry_end=day_time(14, 20),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_02_rotation_engine_v1",
        strategy_id=StrategyId.S02_LOW_BUY_SELL_EXHAUSTION,
        strategy_slug="strategy02",
        strategy_label="Strategy 02 Low Buy Sell Exhaustion",
        slot_owner="STRATEGY02",
        broker_order_prefix="STRATEGY02",
        event_prefix="strategy_02",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 02 is already running.", flush=True)
        return 0
    try:
        return Strategy02Engine(
            config,
            signal_selector=select_fresh_signals,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())