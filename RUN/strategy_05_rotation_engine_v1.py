# -*- coding: utf-8 -*-
"""Strategy 05 rotation: S05 entry, shared hold/sell/order/recovery."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, time as day_time
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from strategy_01_rotation_engine_v2 import (
    Config,
    ProcessLock,
    as_kst,
    number,
)
from strategy_02_rotation_engine_v1 import Strategy02Engine
from strategy_05_signal_contract_v1 import select_fresh_signals
from strategy_common_hold_sell_v1 import StrategyId


class Strategy05Engine(Strategy02Engine):
    """S05 common exit plus confirmed base-failure protection."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._s05_last_observation = {}
        self._s05_last_point = {}

    def _build_observation(self, position, point):
        observation = super()._build_observation(position, point)
        code = str(position["code"]).zfill(6)
        self._s05_last_observation[code] = observation
        self._s05_last_point[code] = dict(point)
        return observation

    @staticmethod
    def _entry_levels(position):
        parts = str(position.get("entry_lane") or "").split(":")
        if len(parts) != 3 or parts[0] != "S05_BASE":
            return 0.0, 0.0
        return number(parts[1]), number(parts[2])

    def _evaluate_exit(self, position, now: datetime) -> None:
        code = str(position.get("code") or "").zfill(6)
        self._s05_last_observation.pop(code, None)
        self._s05_last_point.pop(code, None)

        # Common priority stays intact: -2% insurance, time exit, and profit trail.
        super()._evaluate_exit(position, now)
        if position.get("phase") != "HOLD":
            position.pop("s05_failure_since", None)
            return

        observation = self._s05_last_observation.pop(code, None)
        point = self._s05_last_point.pop(code, None)
        if observation is None or point is None:
            return

        # Friend-approved rider: MA10 support plus rising MA20 blocks a noise exit.
        if observation.ma10_support and observation.ma20_rising:
            position.pop("s05_failure_since", None)
            return

        breakout_line, retest_low = self._entry_levels(position)
        if breakout_line <= 0 or retest_low <= 0:
            position.pop("s05_failure_since", None)
            return

        price = number(point.get("price"))
        structure_broken = (
            price <= breakout_line * 0.995 or price < retest_low
        )
        config = self.exit_engine.config
        exact_flow = (
            observation.buy_money_per_sec_10s > 0
            and observation.sell_money_per_sec_10s > 0
            and observation.buy_volume_per_sec_5s > 0
            and observation.sell_volume_per_sec_5s > 0
            and observation.sell_volume_per_sec_previous_10s > 0
        )
        failure = (
            structure_broken
            and exact_flow
            and observation.one_minute_bull_to_bear
            and observation.sell_money_per_sec_10s
            >= observation.buy_money_per_sec_10s
            * config.flow_reversal_sell_money_mult
            and observation.sell_volume_per_sec_5s
            >= observation.buy_volume_per_sec_5s
            * config.flow_reversal_sell_volume_mult
            and observation.sell_volume_per_sec_5s
            >= observation.sell_volume_per_sec_previous_10s
            * config.flow_reversal_volume_accel_mult
        )
        if not failure:
            position.pop("s05_failure_since", None)
            return

        since_text = str(position.get("s05_failure_since") or "")
        if since_text:
            try:
                since = as_kst(datetime.fromisoformat(since_text))
            except ValueError:
                since = observation.observed_at
        else:
            since = observation.observed_at
            position["s05_failure_since"] = since.isoformat()
        age = (observation.observed_at - since).total_seconds()
        if age < config.flow_reversal_confirm_sec:
            return

        reason = (
            "S05_BASE_FAILURE_EXIT "
            f"line={breakout_line:.0f} low={retest_low:.0f} "
            f"money={observation.sell_money_per_sec_10s / observation.buy_money_per_sec_10s:.2f}x "
            f"volume={observation.sell_volume_per_sec_5s / observation.buy_volume_per_sec_5s:.2f}x "
            f"age={age:.0f}s"
        )
        self._start_sell(position, now, reason, point)

def build_config() -> Config:
    return Config(
        signal_path=Path(r"C:\stock_bot\data\strategy_05_base_breakout_signal_v1.json"),
        snapshot_path=Path(r"C:\stock_bot\IPC\live_micro_snapshot.json"),
        board_path=Path(r"C:\stock_bot\data\micro_rank_board.json"),
        bars_path=Path(r"C:\stock_bot\data\돈맥_1분봉.json"),
        names_path=Path(r"C:\stock_bot\data\_code_name_cache.json"),
        state_path=Path(r"C:\stock_bot\data\strategy_05_rotation_state_v1.json"),
        fills_dir=Path(r"C:\stock_bot\LOG"),
        event_dir=Path(r"C:\stock_bot\data\strategy_05_rotation_v1"),
        log_path=Path(r"C:\stock_bot\LOG\strategy_05_rotation_v1.log"),
        approval_path=Path(r"C:\stock_bot\config\strategy_05_live_approved.flag"),
        off_flag_path=Path(r"C:\stock_bot\config\strategy_05_off.flag"),
        manual_buy_block_path=Path(r"C:\stock_bot\config\manual_buy_block.flag"),
        lock_path=Path(r"C:\stock_bot\data\strategy_05_rotation_v1.lock"),
        live_requested=os.environ.get("S05_LIVE", "NO").strip().upper() == "YES",
        quantity=int(os.environ.get("S05_QTY", "1")),
        max_slots=int(os.environ.get("S05_MAX_SLOTS", "6")),
        max_daily_codes=int(os.environ.get("S05_MAX_DAILY_CODES", "6")),
        max_cycles_per_code=int(os.environ.get("S05_MAX_CYCLES_PER_CODE", "2")),
        rotation_capital_krw=int(os.environ.get(
            "S05_ROTATION_CAPITAL_KRW", "2000000")),
        max_sell_retries=int(os.environ.get("S05_MAX_SELL_RETRIES", "3")),
        signal_max_age_sec=float(os.environ.get(
            "S05_SIGNAL_MAX_AGE_SEC", "5")),
        snapshot_max_age_sec=float(os.environ.get(
            "S05_SNAPSHOT_MAX_AGE_SEC", "4")),
        board_max_age_sec=float(os.environ.get(
            "S05_BOARD_MAX_AGE_SEC", "8")),
        fill_wait_sec=float(os.environ.get("S05_FILL_WAIT_SEC", "8")),
        loop_sec=float(os.environ.get("S05_LOOP_SEC", "1")),
        entry_start=day_time(9, 30),
        entry_end=day_time(14, 30),
        force_exit=day_time(15, 10),
        process_end=day_time(15, 25),
        state_schema="strategy_05_rotation_engine_v1",
        strategy_id=StrategyId.S05_BASE_BREAKOUT,
        strategy_slug="strategy05",
        strategy_label="Strategy 05 Base Breakout",
        slot_owner="STRATEGY05",
        broker_order_prefix="STRATEGY05",
        event_prefix="strategy_05",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = build_config()
    lock = ProcessLock(config.lock_path)
    if not lock.acquire():
        print("Strategy 05 is already running.", flush=True)
        return 0
    try:
        return Strategy05Engine(
            config,
            signal_selector=select_fresh_signals,
        ).run(once=args.once)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
