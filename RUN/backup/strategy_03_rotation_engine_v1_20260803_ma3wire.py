# -*- coding: utf-8 -*-
"""전략 03 골짜기 급반등 주문0 회전 배선.

매수신호는 S03 독립 계약을 사용한다. 체결 이후 주문복구·슬롯·보유·매도는
기존 공통 엔진을 사용한다. 기존 VALLEY_MORNING_CRASH 매도 수치와 우선순위는
유지하되, 사용자 지시에 따라 이 S03 프로세스에서만 09:30 강제청산을 15:10
최종청산으로 바꾼다. 기존 골짜기 프로필 전역값은 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass, replace
from datetime import datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from strategy_01_rotation_engine_v2 import (
    Config,
    ProcessLock,
    Strategy01Engine,
    number,
    parse_dt,
    read_json,
)
from strategy_03_signal_contract_v1 import (
    OPEN_ARM_DROP_PCT,
    OPEN_HANDOFF_DROP_PCT,
    OPEN_CRASH_LANE,
    OPEN_MAX_REBOUND_PCT,
    OPEN_MIN_REBOUND_PCT,
    select_fresh_signals,
)
from strategy_common_hold_sell_v1 import (
    ExitPolicy,
    HoldSellObservation,
    HoldSellState,
    STRATEGY_PROFILES,
    StrategyId,
    UnifiedHoldSellEngine,
)


class Strategy03HoldSellEngine(UnifiedHoldSellEngine):
    """공통 장초반 골짜기 매도에서 S03의 시간청산만 15:10으로 분리."""

    def __init__(self) -> None:
        super().__init__()
        self.open_profile = replace(
            STRATEGY_PROFILES[StrategyId.VALLEY_MORNING_CRASH],
            hard_stop_pct=Decimal("-2.0"),
            strong_flow_hard_stop_pct=Decimal("-2.0"),
            force_exit_at=day_time(9, 50),
            early_decision_at=day_time(9, 20),
            exit_policy=ExitPolicy.TREND_REBOUND,
        )
        self.profile = replace(
            STRATEGY_PROFILES[StrategyId.VALLEY_MORNING_CRASH],
            force_exit_at=day_time(15, 10),
        )

    def evaluate(
        self,
        state: HoldSellState,
        observation: HoldSellObservation,
    ):
        if state.strategy_id is not StrategyId.VALLEY_MORNING_CRASH:
            return super().evaluate(state, observation)
        self._validate_sequence(state, observation)
        if state.sell_latched:
            return self._latched_decision(state)
        self._update_state_metrics(state, observation)
        entry_time = state.entry_at.timetz().replace(tzinfo=None)
        is_open_lane = (
            state.entry_lane == OPEN_CRASH_LANE
            or (not state.entry_lane and entry_time < day_time(9, 20))
        )
        profile = self.open_profile if is_open_lane else self.profile
        return self._evaluate_valley(state, observation, profile)



def make_strategy03_signal_selector(
    snapshot_path: Path,
    snapshot_max_age_sec: float,
):
    """Recheck the S06-style staircase price band and live flow before ordering."""

    def selector(
        payload,
        *,
        now: datetime,
        max_age_sec: float,
        consumed=(),
    ):
        rows = select_fresh_signals(
            payload,
            now=now,
            max_age_sec=max_age_sec,
            consumed=consumed,
        )
        snapshot = read_json(snapshot_path, {})
        codes = snapshot.get("codes") or {}
        decision_at = parse_dt(now.isoformat(), now)
        validated = []
        for row in rows:
            raw = codes.get(str(row.get("code") or "").zfill(6))
            if not isinstance(raw, dict):
                continue
            point_at = parse_dt(raw.get("ts"), decision_at)
            if abs((decision_at - point_at).total_seconds()) > snapshot_max_age_sec:
                continue

            price = abs(number(raw.get("cur")))
            anchor_low = number(row.get("anchor_low"))
            open_price = number(row.get("open_price"))
            if price <= 0 or anchor_low <= 0 or open_price <= 0:
                continue
            lower_price = open_price * (1.0 + OPEN_HANDOFF_DROP_PCT / 100.0)
            upper_price = open_price * (1.0 + OPEN_ARM_DROP_PCT / 100.0)
            if not lower_price < price <= upper_price:
                continue
            rebound = (price / anchor_low - 1.0) * 100.0
            if not OPEN_MIN_REBOUND_PCT <= rebound <= OPEN_MAX_REBOUND_PCT:
                continue

            current_buy = number(raw.get("buy_money_cum"), -1.0)
            current_sell = number(raw.get("sell_money_cum"), -1.0)
            signal_buy = number(row.get("current_buy_money_cum"), -1.0)
            signal_sell = number(row.get("current_sell_money_cum"), -1.0)
            if min(current_buy, current_sell, signal_buy, signal_sell) < 0:
                continue
            if current_buy < signal_buy or current_sell < signal_sell:
                continue
            signal_at = parse_dt(row.get("ts"), decision_at)
            if point_at > signal_at:
                delta_buy = current_buy - signal_buy
                delta_sell = current_sell - signal_sell
                if delta_buy <= delta_sell:
                    continue
            validated.append(row)
        return validated

    return selector


class Strategy03Engine(Strategy01Engine):
    def __init__(self, config: Config, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)
        self.exit_engine = Strategy03HoldSellEngine()
        self._s03_daily_trend: dict[str, dict[str, float]] | None = None

    def _load_s03_daily_trend(self) -> None:
        if self._s03_daily_trend is not None:
            return
        self._s03_daily_trend = {}
        session_day = str(self.state.get("date") or "")
        if len(session_day) != 8 or not session_day.isdigit():
            self.log.warning("S03 daily trend disabled: invalid session date")
            return
        by_code: dict[str, dict[str, float]] = {}
        try:
            with self.config.eod_bars_path.open(
                encoding="utf-8-sig", newline=""
            ) as fh:
                for raw in csv.DictReader(fh):
                    code = str(raw.get("code") or "").zfill(6)
                    day = str(raw.get("date") or "").replace("-", "")
                    close = number(raw.get("close"))
                    if (
                        len(code) == 6
                        and code.isdigit()
                        and day < session_day
                        and len(day) == 8
                        and day.isdigit()
                        and close > 0
                    ):
                        by_code.setdefault(code, {})[day] = close
        except OSError:
            self.log.warning("S03 daily trend disabled: EOD bars unavailable")
            return

        for code, series in by_code.items():
            days = sorted(series)
            if len(days) < 21:
                continue
            closes = [series[day] for day in days]
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma20_prev = sum(closes[-21:-1]) / 20
            self._s03_daily_trend[code] = {
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "ma20_prev": ma20_prev,
            }

    def _daily_ma_permit(self, code: str, price: float) -> bool:
        self._load_s03_daily_trend()
        row = (self._s03_daily_trend or {}).get(code)
        if not row:
            return False
        ma5, ma10, ma20, ma20_prev = (
            row["ma5"], row["ma10"], row["ma20"], row["ma20_prev"]
        )
        if not (ma5 > ma10 and ma20 > ma20_prev):
            return False
        high3 = self._recent_3min_high(code)
        reference = high3 if high3 > 0 else price
        return bool(reference >= ma5)

    def _position_force_exit_at(
        self,
        position: dict[str, Any],
    ) -> day_time:
        entry_at = parse_dt(position.get("entry_at"))
        entry_lane = str(position.get("entry_lane") or "")
        is_open_lane = (
            entry_lane == OPEN_CRASH_LANE
            or (not entry_lane and entry_at.time() < day_time(9, 20))
        )
        return day_time(9, 50) if is_open_lane else self.config.force_exit

    def _completed_open_ma5_broken(
        self,
        position: dict[str, Any],
        point: dict[str, Any],
    ) -> bool:
        self._load_s03_daily_trend()
        row = (self._s03_daily_trend or {}).get(position["code"])
        if not row:
            return False
        ma5 = row["ma5"]
        if number(point.get("price")) >= ma5:
            position["s03_ma5_seen_above"] = True

        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        previous = ((source or {}).get(position["code"]) or {}).get("prev") or []
        hm = str(payload.get("hm") or "")
        if len(hm) != 4 or not hm.isdigit() or not previous:
            return False
        observed_at = point["ts"]
        bars_at = parse_dt(payload.get("ts"), observed_at)
        if abs((observed_at - bars_at).total_seconds()) > 90:
            return False
        try:
            current_minute = observed_at.replace(
                hour=int(hm[:2]), minute=int(hm[2:]), second=0, microsecond=0
            )
        except ValueError:
            return False
        entry_at = parse_dt(position.get("entry_at"), observed_at)
        first_post_entry_minute = (
            entry_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        )
        latest_completed_minute = current_minute - timedelta(minutes=1)
        if latest_completed_minute < first_post_entry_minute:
            return False
        latest = previous[-1]
        latest_close = number(latest[3]) if len(latest) >= 4 else 0.0
        return bool(
            position.get("s03_ma5_seen_above")
            and latest_close > 0
            and latest_close < ma5
            and number(point.get("price")) < ma5
        )

    def _completed_open_structure(
        self,
        position: dict[str, Any],
        observed_at: datetime,
    ) -> tuple[bool, str]:
        """Return a new post-entry 3m-support/1m-close break.

        The entry minute is deliberately excluded. The three completed
        one-minute bars immediately before the latest completed one-minute
        bar form the post-entry three-minute support. The latest completed
        one-minute close must finish below that support.
        """
        payload = read_json(self.config.bars_path, {})
        source = payload.get("m") if isinstance(payload.get("m"), dict) else payload
        code = str(position.get("code") or "").zfill(6)
        previous = ((source or {}).get(code) or {}).get("prev") or []
        hm = str(payload.get("hm") or "")
        if len(hm) != 4 or not hm.isdigit() or not previous:
            return False, ""

        bars_at = parse_dt(payload.get("ts"), observed_at)
        if abs((observed_at - bars_at).total_seconds()) > 90:
            return False, ""
        try:
            current_minute = observed_at.replace(
                hour=int(hm[:2]),
                minute=int(hm[2:]),
                second=0,
                microsecond=0,
            )
        except ValueError:
            return False, ""
        if abs((observed_at - current_minute).total_seconds()) > 90:
            return False, ""

        entry_at = parse_dt(position.get("entry_at"), observed_at)
        first_post_entry_minute = (
            entry_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        )
        full_post_entry_count = int(
            (current_minute - first_post_entry_minute).total_seconds() // 60
        )
        latest_key = (current_minute - timedelta(minutes=1)).strftime("%Y%m%d%H%M")
        if full_post_entry_count < 4:
            return False, latest_key

        post_entry = previous[-min(full_post_entry_count, len(previous)):]
        if len(post_entry) < 4:
            return False, latest_key
        baseline_lows = [
            number(bar[2]) for bar in post_entry[-4:-1]
            if len(bar) >= 4 and number(bar[2]) > 0
        ]
        latest = post_entry[-1]
        latest_close = number(latest[3]) if len(latest) >= 4 else 0.0
        return bool(
            len(baseline_lows) == 3
            and latest_close > 0
            and latest_close < min(baseline_lows)
        ), latest_key

    def _open_structure_break_active(
        self,
        position: dict[str, Any],
        observed_at: datetime,
    ) -> bool:
        broken, break_key = self._completed_open_structure(position, observed_at)
        if not break_key:
            return False

        tracked_key = str(position.get("s03_structure_bar_key") or "")
        hold_payload = position.get("hold_state")
        if break_key != tracked_key:
            position["s03_structure_bar_key"] = break_key
            position["s03_structure_watch_started"] = bool(broken)
            if isinstance(hold_payload, dict):
                hold_payload["valley_morning_break_since"] = ""
            return broken

        if not broken:
            position["s03_structure_watch_started"] = False
            return False
        if not position.get("s03_structure_watch_started"):
            return False
        if isinstance(hold_payload, dict) and hold_payload.get(
            "valley_morning_break_since"
        ):
            return True

        # This completed one-minute break already received its single 10s
        # exact-flow confirmation and was cancelled. A new completed bar is
        # required before another structure-break watch may start.
        position["s03_structure_watch_started"] = False
        return False

    def _build_observation(
        self,
        position: dict[str, Any],
        point: dict[str, Any],
    ) -> HoldSellObservation:
        observation = super()._build_observation(position, point)
        entry_at = parse_dt(position.get("entry_at"), point["ts"])
        entry_lane = str(position.get("entry_lane") or "")
        is_open_lane = (
            entry_lane == OPEN_CRASH_LANE
            or (not entry_lane and entry_at.time() < day_time(9, 20))
        )
        if not is_open_lane:
            return observation

        exact = point["buy_money_cum"] >= 0 and point["sell_money_cum"] >= 0
        rate10 = self.windows.rates(position["code"], 10) if exact else None
        exact_valid = bool(rate10 and rate10[0] + rate10[1] > 0)
        return replace(
            observation,
            daily_ma5_broken=self._completed_open_ma5_broken(position, point),
            structure_broken=self._open_structure_break_active(
                position, point["ts"]
            ),
            valley_exact_flow_valid=exact_valid,
            valley_exact_sell_dominant=bool(
                exact_valid and rate10 and rate10[1] > rate10[0]
            ),
        )


@dataclass(frozen=True)
class Strategy03Config(Config):
    max_cycles_per_code: int = 2

    def __post_init__(self) -> None:
        if self.quantity != 1:
            raise ValueError("Strategy 03 requires exactly one share")
        if self.max_slots != 6:
            raise ValueError("Strategy 03 requires exactly six concurrent slots")
        if self.max_daily_codes != 6:
            raise ValueError("Strategy 03 requires exactly six distinct codes per day")
        if self.max_cycles_per_code != 2:
            raise ValueError("Strategy 03 permits exactly two entries per code")
        if self.rotation_capital_krw <= 0:
            raise ValueError("rotation_capital_krw must be positive")
        if self.max_sell_retries < 1:
            raise ValueError("max_sell_retries must be positive")
        if not all((
            self.state_schema,
            self.strategy_slug,
            self.strategy_label,
            self.slot_owner,
            self.broker_order_prefix,
            self.event_prefix,
        )):
            raise ValueError("strategy identity fields must not be empty")


def build_config() -> Strategy03Config:
    return Strategy03Config(
        signal_path=Path(
            r"C:\stock_bot\data\strategy_03_골짜기_급반등_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(
            r"C:\stock_bot\data\strategy_03_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_03_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_03_rotation_v1.log"),
        approval_path=Path(
            r"C:\stock_bot\config\strategy_03_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_03_off.flag"),
        manual_buy_block_path=Path(
            r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_03_rotation_v1.lock"),
        live_requested=(
            os.environ.get("S03_LIVE", "NO").strip().upper() == "YES"),
        quantity=int(os.environ.get("S03_QTY", "1")),
        max_slots=int(os.environ.get("S03_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S03_MAX_DAILY_CODES", "6")),
        max_cycles_per_code=int(os.environ.get("S03_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=int(os.environ.get(
            "S03_ROTATION_CAPITAL_KRW", "2000000")),
        max_sell_retries=int(os.environ.get("S03_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get(
            "S03_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get(
            "S03_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get(
            "S03_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S03_FILL_WAIT_SEC", "8")),
        loop_sec=float(os.environ.get("S03_LOOP_SEC", "1")),
        entry_start=day_time(9, 0),
        entry_end=day_time(14, 30),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_03_rotation_engine_v1",
        strategy_id=StrategyId.VALLEY_MORNING_CRASH,
        strategy_slug="strategy03",
        strategy_label="Strategy 03 Valley Rapid Rebound",
        slot_owner="STRATEGY03",
        broker_order_prefix="STRATEGY03",
        event_prefix="strategy_03",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 03 is already running.", flush=True)
        return 0
    try:
        selector = make_strategy03_signal_selector(
            config.snapshot_path, config.snapshot_max_age_sec)
        return Strategy03Engine(
            config,
            signal_selector=selector,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
